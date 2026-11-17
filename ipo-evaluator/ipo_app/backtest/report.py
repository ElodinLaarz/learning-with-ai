"""Applies the pre-registered verdict rule to the recorded runs and writes
results/verdict.json, results/VALIDATION_REPORT.md and results/validation_dashboard.html.

Every number in the report is read from run outputs; nothing is typed by hand.

    python -m ipo_app.backtest.report
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from ..engine import recommend as R

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"
RUNS = RESULTS / "runs"
PROC = ROOT / "data" / "processed"
PRIMARY = "A_retail"
H = ["1m", "3m", "6m", "12m"]
MODE_NAMES = {"A_retail": "Retail access — decide after the first-day close, buy at the 2nd-day open (PRIMARY)",
              "A_offer": "Offer-price access — hypothetical allocation at the offer price",
              "B_post_report": "Retail access — decide after the first 10-Q/10-K, buy at the next open"}


def _j(p, default=None):
    try:
        return json.loads(Path(p).read_text())
    except (OSError, json.JSONDecodeError):
        return default


def pct(x, d=1):
    return "–" if x is None else f"{x * 100:.{d}f}%"


def num(x):
    return "–" if x is None else f"{x:,.0f}"


def ci(c):
    if not c or c.get("ci_lo") is None:
        return "–"
    return f"{pct(c.get('estimate'))} [{pct(c['ci_lo'])}, {pct(c['ci_hi'])}]"


def find_runs(rule_hash: str) -> dict:
    out = {}
    led = _j(RESULTS / "freeze_ledger.json", {"unsealings": []})
    for d in sorted(RUNS.iterdir()) if RUNS.exists() else []:
        m = _j(d / "manifest.json")
        if not m:
            continue
        if m["name"] == "test" and m["rule_hash"] == rule_hash:
            out["test"] = (m, _j(d / "summary.json"))
        if m["name"] == "pretest" and m["rule_hash"] == rule_hash:
            out["pretest"] = (m, _j(d / "summary.json"))
        if m["name"] == "validation":
            if "validation" not in out or m["created_at"] > out["validation"][0]["created_at"]:
                out["validation"] = (m, _j(d / "summary.json"))
    out["ledger"] = led
    return out


def compute_verdict(test_manifest: dict, t: dict) -> dict:
    p = t["modes"][PRIMARY]
    s12 = p["strategy"].get("12m", {})
    c = s12.get("excess_ci") or {}
    d12 = (p.get("diff_vs_buy_all") or {}).get("12m") or {}
    b = p.get("brier") or {}
    w = p.get("winner_dependence_12m") or {}
    s50 = next((r for r in t.get("sensitivity", []) if r["mode"] == PRIMARY and r["variant"] == "50 bps per side"), {})
    cov = t["coverage"]["price_coverage"]
    integ = t.get("held_out_integrity", {})
    h1 = c.get("ci_lo") is not None and c["ci_lo"] > 0
    h2 = d12.get("ci_lo") is not None and d12["ci_lo"] > 0
    h1_neg = c.get("ci_hi") is not None and c["ci_hi"] < 0
    h2_neg = d12.get("ci_hi") is not None and d12["ci_hi"] < 0
    h3 = b.get("skill_vs_base_rate") is not None and b["skill_vs_base_rate"] > 0
    g1 = (s12.get("n") or 0) >= 30 and (c.get("n_clusters") or 0) >= 8
    g2 = w.get("mean_excess_drop_top5pct") is not None and w["mean_excess_drop_top5pct"] > 0
    g3 = s50.get("buy_mean_excess_12m") is not None and s50["buy_mean_excess_12m"] > 0
    g4 = cov is not None and cov >= 0.90
    held_out = not integ.get("unsealed_before_with_other_rules", False)
    if h1 and h2 and g1 and g2 and g3 and g4 and held_out:
        verdict = "SUPPORTED"
    elif h1_neg or h2_neg:
        verdict = "NOT SUPPORTED"
    else:
        verdict = "INCONCLUSIVE"
    label = ("HISTORICALLY VALIDATED — advantage supported on held-out data" if verdict == "SUPPORTED"
             else "NOT HISTORICALLY VALIDATED")
    crit = [
        {"name": "H1 — BUY trades beat SPY over 12 months (95% interval above zero)", "result": f"mean excess {ci(c)}, n = {s12.get('n', 0)}", "met": h1},
        {"name": "H2 — BUY trades beat buying every eligible IPO (95% interval above zero)", "result": f"difference {ci(d12)}", "met": h2},
        {"name": "H3 — Brier score better than the base rate", "result": (f"Brier {b['brier']:.4f} vs reference {b['brier_base_rate_reference']:.4f} (skill {b['skill_vs_base_rate']:+.3f})" if b.get("brier") is not None else "no scored forecasts"), "met": h3},
        {"name": "Guardrail 1 — at least 30 BUY trades over at least 8 entry quarters", "result": f"{s12.get('n', 0)} trades, {c.get('n_clusters', 0)} quarters", "met": g1},
        {"name": "Guardrail 2 — still positive without the best 5% of BUY trades", "result": pct(w.get("mean_excess_drop_top5pct")), "met": g2},
        {"name": "Guardrail 3 — still positive at 50 bps per side", "result": pct(s50.get("buy_mean_excess_12m")), "met": g3},
        {"name": "Guardrail 4 — price history for at least 90% of eligible test-period IPOs", "result": f"{pct(cov)} ({t['coverage']['n_with_price_history']} of {t['coverage']['n_eligible']})", "met": g4},
        {"name": "Test period was held out (never unsealed with other rules)", "result": "yes" if held_out else "no", "met": held_out},
    ]
    if verdict == "SUPPORTED":
        summary = "The frozen rules met every pre-registered criterion on the held-out period."
    else:
        bits = []
        if not g4:
            bits.append(f"price history exists for only {pct(cov, 0)} of eligible test-period IPOs, so results describe survivors of the price vendor's database, not all IPOs")
        if not h1:
            bits.append(f"the 12-month excess return of BUY recommendations over SPY is {ci(c)}, which does not exclude zero" if not h1_neg else f"BUY recommendations underperformed SPY over 12 months: {ci(c)}")
        if not h2:
            bits.append(f"the difference versus buying every eligible IPO is {ci(d12)}" + (" (reliably worse)" if h2_neg else ", not distinguishable from zero"))
        summary = ("The evidence does not support an advantage over the benchmarks: " + "; ".join(bits) + "."
                   if bits else "Not every pre-registered guardrail was met.")
        if h2 and not h1:
            wf = (((t.get("walk_forward") or {}).get("modes") or {}).get(PRIMARY) or {}).get("diff_vs_buy_all", {}).get("12m") or {}
            summary += (f" BUY recommendations did lose less than buying every eligible IPO (difference {ci(d12)}), "
                        "but a smaller loss is not an advantage over the market"
                        + (f", and the walk-forward difference is {ci(wf)}" if wf.get("estimate") is not None else "") + ".")
    return {"label": label, "verdict": verdict, "summary": summary, "criteria": crit,
            "rule_version": test_manifest["rule_version"], "rule_hash": test_manifest["rule_hash"],
            "run_id": test_manifest["run_id"], "primary_endpoint": "A_retail, 12-month horizon, held-out test period"}


# ----------------------------------------------------------------------------- markdown helpers
def horizon_table(s: dict) -> str:
    rows = ["| Horizon | Group | n | incomplete | delisted before horizon | mean net return | median | SPY same dates | mean excess vs SPY [95%] | vs sector ETF | vs IWM | vs IPO ETF | % beating SPY | volatility | worst | 5th pct |",
            "|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for h in H:
        for key, name in (("strategy", "Strategy BUYs"), ("buy_all", "Buy every eligible IPO"), ("screen", "Simple screen")):
            r = s[key].get(h, {})
            if not r.get("n"):
                rows.append(f"| {h} | {name} | 0 | {num(r.get('n_incomplete'))} | – | – | – | – | – | – | – | – | – | – | – | – |")
                continue
            rows.append(f"| {h} | {name} | {r['n']} | {num(r.get('n_incomplete'))} | {num(r.get('n_delisted_before_horizon'))} | {pct(r['mean_ret'])} | {pct(r['median_ret'])} | {pct(r['mean_bench'])} | {ci(r.get('excess_ci'))} | {pct(r.get('mean_excess_vs_sector'))} | {pct(r.get('mean_excess_vs_iwm'))} | {pct(r.get('mean_excess_vs_ipoetf'))} | {pct(r['pct_outperform'])} | {pct(r.get('std_ret'))} | {pct(r['worst'])} | {pct(r['p05'])} |")
        d = (s.get("diff_vs_buy_all") or {}).get(h)
        if d and d.get("estimate") is not None:
            rows.append(f"| {h} | *Strategy minus buy-all* | {d['n_a']} vs {d['n_b']} | | | | | | {ci(d)} | | | | | | | |")
        d = (s.get("diff_vs_screen") or {}).get(h)
        if d and d.get("estimate") is not None:
            rows.append(f"| {h} | *Strategy minus simple screen* | {d['n_a']} vs {d['n_b']} | | | | | | {ci(d)} | | | | | | | |")
    return "\n".join(rows)


def class_block(s: dict) -> str:
    c = s.get("classification_12m") or {}
    rec = ", ".join(f"{k} {v}" for k, v in (s.get("recommendations") or {}).items())
    act = ", ".join(f"{k} {v}" for k, v in (s.get("actions") or {}).items())
    gates = ", ".join(f"{k} {v}" for k, v in (s.get("gates_triggered") or {}).items()) or "none"
    nd = ", ".join(f"{k} {v}" for k, v in (s.get("no_decision_reasons") or {}).items()) or "none"
    return (f"- Eligible IPOs: **{s['n_eligible']}**. Initial recommendations: {rec}. Final actions: {act}.\n"
            f"- BUY trades: **{s['n_buy']}** ({s.get('n_buy_after_wait', 0)} after a watchlist wait). **Abstention rate: {pct(s.get('abstention_rate'))}**.\n"
            f"- Hard gates triggered: {gates}. No decision possible: {nd}.\n"
            f"- Of {num(c.get('n_buys_with_outcome'))} BUYs with a complete 12-month outcome, **{num(c.get('buys_outperform'))} beat SPY ({pct(c.get('precision'))})** and "
            f"**{num(c.get('false_positives'))} were false positives ({pct(c.get('false_positive_rate_of_buys'))})**.\n"
            f"- Base rate: {pct(c.get('base_rate_winners'))} of {num(c.get('n_labelled'))} eligible IPOs beat SPY when bought at the same entry. "
            f"**Missed winners: {num(c.get('missed_winners'))} of {num(c.get('winners_total'))} ({pct(c.get('missed_winner_rate'))})**; "
            f"losers avoided: {num(c.get('losers_avoided'))} ({pct(c.get('loser_avoidance_rate'))}).")


def portfolio_table(s: dict) -> str:
    P = s.get("portfolio") or {}
    rows = ["| Account | total return | CAGR | annualised volatility | max drawdown | worst day | trades taken / offered | average invested |", "|---|--:|--:|--:|--:|--:|--:|--:|"]

    def r(name, st):
        if st and st.get("total_return") is not None:
            tk = f"{st['n_trades_taken']} / {st['n_trades_offered']}" if st.get("n_trades_taken") is not None else ""
            inv = pct(st.get("avg_invested_share"), 0) if st.get("avg_invested_share") is not None else ""
            rows.append(f"| {name} | {pct(st['total_return'])} | {pct(st.get('cagr'))} | {pct(st['ann_vol'])} | {pct(st['max_drawdown'])} | {pct(st['worst_day'])} | {tk} | {inv} |")

    alpha = []
    for key, name in (("strategy", "Strategy"), ("buy_all", "Buy every eligible IPO"), ("screen", "Simple screen")):
        p = P.get(key)
        if not p:
            continue
        r(name, p["stats"])
        r(f"{name} — same trades in SPY", p.get("matched_spy_stats"))
        r(f"{name} — SPY buy & hold, same window", p.get("spy_buy_hold_stats"))
        a = p.get("calendar_time_alpha") or {}
        if a.get("alpha_annualized") is not None:
            alpha.append(f"- {name}: calendar-time alpha vs SPY **{pct(a['alpha_annualized'])}/yr** (Newey–West t = {a['alpha_t']:.2f}, beta {a['beta']:.2f}, {a['n_months']} months, {a.get('avg_positions', 0):.0f} positions on average)")
    return "\n".join(rows) + ("\n\n" + "\n".join(alpha) if alpha else "")


def brk_table(s: dict, key: str, field: str, title: str) -> str:
    A = {r[field]: r for r in (s.get(key) or {}).get("strategy", [])}
    Bm = {r[field]: r for r in (s.get(key) or {}).get("buy_all", [])}
    keys = sorted(set(A) | set(Bm), key=str)
    rows = [f"| {title} | BUY n | BUY mean excess | BUY % beating SPY | all-IPO n | all-IPO mean excess | all-IPO % beating SPY |", "|---|--:|--:|--:|--:|--:|--:|"]
    for k in keys:
        a, b = A.get(k), Bm.get(k)
        rows.append(f"| {k} | {a['n'] if a else 0} | {pct(a['mean_excess']) if a else '–'} | {pct(a['pct_outperform']) if a else '–'} | {b['n'] if b else 0} | {pct(b['mean_excess']) if b else '–'} | {pct(b['pct_outperform']) if b else '–'} |")
    return "\n".join(rows)


def calib_block(s: dict) -> str:
    b = s.get("brier") or {}
    if not b.get("n"):
        return "No forecasts with completed outcomes."
    out = (f"Brier score **{b['brier']:.4f}** on {b['n']} forecasts; base-rate reference {b['brier_base_rate_reference']:.4f}; "
           f"always-50% reference {b['brier_coinflip_reference']:.4f}; **skill vs base rate {b['skill_vs_base_rate']:+.3f}** "
           f"(positive = better than always forecasting the base rate). Mean forecast {pct(b['mean_forecast'])}, observed rate {pct(b['base_rate'])}.\n\n"
           "| Probability bin | n | mean forecast | observed share beating SPY |\n|---|--:|--:|--:|\n")
    for r in s.get("calibration") or []:
        out += f"| {r['bin']} ({pct(r['p_lo'], 0)}–{pct(r['p_hi'], 0)}) | {r['n']} | {pct(r['mean_forecast'])} | {pct(r['observed_rate'])} |\n"
    return out


def sens_table(rows: list, mode: str) -> str:
    out = ["| Assumption | Variant | BUY n | BUY mean excess 12m | BUY median excess | BUY % beating SPY | buy-all mean excess | difference |", "|---|---|--:|--:|--:|--:|--:|--:|"]
    for r in rows:
        if r["mode"] == mode:
            out.append(f"| {r['family']} | {r['variant']} | {r['n_buy']} | {pct(r['buy_mean_excess_12m'])} | {pct(r['buy_median_excess_12m'])} | {pct(r['buy_pct_outperform'])} | {pct(r['all_mean_excess_12m'])} | {pct(r['diff_mean_excess'])} |")
    return "\n".join(out)


def winner_block(s: dict) -> str:
    w = s.get("winner_dependence_12m") or {}
    if not w.get("n") or w.get("mean_excess") is None:
        return "Too few BUY trades to analyse."
    share = w.get("share_of_total_excess_from_top5pct")
    return (f"| BUY trades, 12-month excess vs SPY | value |\n|---|--:|\n| all {w['n']} trades — mean | {pct(w['mean_excess'])} |\n| median | {pct(w['median_excess'])} |\n"
            f"| without the single best trade | {pct(w['mean_excess_drop_top1'])} |\n| without the best 5 trades | {pct(w.get('mean_excess_drop_top5'))} |\n"
            f"| without the best 5% ({w['top5pct_count']} trades) | {pct(w['mean_excess_drop_top5pct'])} |\n| winsorised at the 95th percentile | {pct(w['mean_excess_winsor_95'])} |\n"
            + (f"| share of total excess contributed by the best 5% | {pct(share, 0)} |\n" if share is not None else ""))


def worst_table(s: dict) -> str:
    rows = ["| Symbol | Company | IPO priced | Entered | 12-month net return | SPY same dates | Status |", "|---|---|---|---|--:|--:|---|"]
    for r in s.get("worst_buys_12m") or []:
        rows.append(f"| {r['symbol']} | {str(r['name'])[:40]} | {r['priced_date']} | {r['strat_entry_date']} | {pct(r['strat_ret_12m'])} | {pct(r['strat_spy_12m'])} | {r['strat_status_12m']} |")
    return "\n".join(rows)


def mode_section(s: dict, title: str, level="###") -> str:
    return (f"{level} {title}\n\n{class_block(s)}\n\n{horizon_table(s)}\n\n"
            f"**Capital-constrained account** ($100k, 5% per position, max 20 positions, 12-month holds, idle cash in T-bills)\n\n{portfolio_table(s)}\n")


def write_report():
    rules = R.load_rules("v1.0.0")
    runs = find_runs(rules["hash"])
    cov = _j(PROC / "coverage.json", {})
    prov = _j(PROC / "provenance.json", {})
    L = []
    if "test" not in runs:
        verdict = {"label": "NOT HISTORICALLY VALIDATED", "verdict": "NO TEST RUN",
                   "summary": "The held-out test period has not been evaluated with the current frozen rules.", "criteria": [],
                   "rule_version": rules["version"], "rule_hash": rules["hash"]}
        (RESULTS / "verdict.json").write_text(json.dumps(verdict, indent=1))
        return verdict
    tm, t = runs["test"]
    verdict = compute_verdict(tm, t)
    (RESULTS / "verdict.json").write_text(json.dumps(verdict, indent=1))
    P = t["modes"][PRIMARY]
    tc = t["coverage"]

    L.append("# Historical Validation Report — IPO Evaluator\n")
    L.append(f"*Generated from run `{tm['run_id']}` · rules `{tm['rule_version']}` (hash `{tm['rule_hash'][:16]}…`) · data snapshot `{(tm.get('data_hash') or '')[:16]}…`, last market date {tm['snapshot_last_market_date']}. Every figure below is read from the run outputs in `results/runs/`.*\n")
    L.append(f"## 1. Verdict\n\n> **{verdict['label']}**\n>\n> Pre-registered verdict: **{verdict['verdict']}**. {verdict['summary']}\n")
    L.append("| Pre-registered criterion (primary endpoint: retail access, 12 months, held-out period) | Result | Met |\n|---|---|:-:|")
    for c in verdict["criteria"]:
        L.append(f"| {c['name']} | {c['result']} | {'yes' if c['met'] else 'no'} |")
    L.append("\nThe criteria were written to `PREREGISTRATION.md` and committed together with the frozen rule file before the test period was opened "
             f"(freeze commit `{(tm.get('freeze_commit') or '')[:12]}`; the code refuses to unseal otherwise).\n")

    L.append("## 2. What was tested\n")
    L.append("- **Application**: `ipo_app/engine` — deterministic calculations (dilution, proceeds, enterprise value, runway), hard gates, a logistic probability model, and BUY / WAIT / AVOID / ABSTAIN output. The backtest calls the same `evaluate()` function the web app uses.\n"
             "- **No LLM in the loop**: each historical decision is assembled by code from filings and quotes dated on or before the decision. Model weights were fitted by an algorithm on pre-2020 outcomes; no weight or threshold was set by the author.\n"
             f"- **Rule version**: `{rules['version']}`, frozen at {rules.get('frozen_at')}. Models trained on outcomes known before {rules.get('trained_through')}.\n")
    sel = (rules.get("meta") or {}).get("selection") or {}
    if sel:
        L.append("| Model | training IPOs | L2 λ (chosen on validation Brier) | buy threshold quantile (chosen on validation excess return) | buy threshold | avoid threshold |\n|---|--:|--:|--:|--:|--:|")
        for m, mdl in rules["models"].items():
            L.append(f"| {m} | {mdl['n_train']} | {mdl['l2_lambda']:g} | {mdl['thresholds']['buy_quantile']} | p ≥ {mdl['thresholds']['buy']:.3f} | p < {mdl['thresholds']['avoid']:.3f} |")
        L.append("")

    L.append("## 3. Dataset: coverage, exclusions, sources\n")
    L.append(f"Universe: every deal marked *priced* in the Nasdaq IPO calendar from 2012-01 to the snapshot ({cov.get('calendar_priced_deals')} deals including SPACs). "
             f"**{cov.get('eligible')} are eligible** operating-company IPOs after the exclusions below. The list is taken as published; no company was added or removed by hand.\n")
    names = {"spac_name_and_10usd_unit": "SPAC by name with a $10 unit price", "unit_offering_10usd": "$10 unit offering (SPAC-style)", "foreign_private_issuer": "Foreign private issuer (files F-1/20-F/6-K; no quarterly XBRL)",
             "offer_price_below_5": "Offer price below $5", "before_universe_start": "Priced before 2012 (calendar lead-in only)", "no_price": "No final offer price in the calendar record",
             "non_major_exchange": "Not NYSE / Nasdaq / NYSE American", "spac_sic_6770": "Blank-check company (SIC 6770)", "prior_trading_history": "Already traded before the deal (uplisting, not an IPO)",
             "fund_or_commodity_pool": "Fund or commodity pool", "no_cik_in_deal_record": "No SEC CIK in the deal record", "no_sec_submissions": "No SEC filing index", "not_first_offering_for_cik": "Later offering by a company already in the universe", "no_date": "No pricing date"}
    L.append("| Exclusion | deals |\n|---|--:|")
    for k, v in sorted((cov.get("exclusions") or {}).items(), key=lambda kv: -kv[1]):
        L.append(f"| {names.get(k, k)} | {v} |")
    L.append("\n| IPO year | " + " | ".join(cov.get("eligible_by_year", {}).keys()) + " |\n|---|" + "--:|" * len(cov.get("eligible_by_year", {})))
    L.append("| eligible | " + " | ".join(str(v) for v in cov.get("eligible_by_year", {}).values()) + " |")
    L.append("| with price history | " + " | ".join(str(cov.get("price_ok_by_year", {}).get(y, 0)) for y in cov.get("eligible_by_year", {})) + " |")
    L.append("| coverage | " + " | ".join(pct(cov.get("price_ok_by_year", {}).get(y, 0) / v, 0) for y, v in cov.get("eligible_by_year", {}).items()) + " |\n")
    so, sm, sk = cov.get("sec_outcome_all_eligible", {}), cov.get("sec_outcome_when_price_missing", {}), cov.get("sec_outcome_when_price_ok", {})
    L.append("**Unsuccessful IPOs are in the universe, but mostly not in the price data.** Later fate of each eligible IPO, classified mechanically from SEC filings (bankruptcy = an 8-K with item 1.03; still filing = a 10-K/10-Q within about 18 months of the snapshot; acquired = stopped reporting with merger or tender-offer documents on file; other = stopped reporting for any other reason):\n")
    L.append("| Fate per SEC filings (as of snapshot) | eligible IPOs | with price history | without price history | coverage |\n|---|--:|--:|--:|--:|")
    for k, lab in (("active", "Still filing"), ("acquired", "Acquired / merged"), ("delisted_other", "Delisted or deregistered, other"), ("bankruptcy", "Bankruptcy")):
        n = so.get(k, 0)
        L.append(f"| {lab} | {n} | {sk.get(k, 0)} | {sm.get(k, 0)} | {pct(sk.get(k, 0) / n, 0) if n else '–'} |")
    ps = cov.get("price_status", {})
    L.append(f"\nPrice-history status of eligible IPOs: " + ", ".join(f"{k} {v}" for k, v in ps.items()) + ".\n")
    L.append("**Sources** (public, no API key; raw responses cached under `data/raw/`, hashes in `data/processed/provenance.json`):\n")
    L.append("| Source | Endpoint | Used for |\n|---|---|---|")
    for s in prov.get("sources", []):
        L.append(f"| {s['name']} | `{s['url']}` | {s['fields']} |")
    L.append(f"\nFirst periodic report located for {cov.get('first_report_found')} eligible IPOs, of which {cov.get('first_report_with_xbrl')} carry machine-readable (XBRL) facts. "
             f"Shares outstanding after the offering are missing for {cov.get('shares_outstanding_missing')} deals (the engine abstains on those). "
             f"Eligible IPOs with any XBRL fact filed on or before the pricing date: {cov.get('pre_ipo_xbrl_available', 'n/a')}.\n")

    L.append("## 4. Point-in-time reconstruction\n")
    L.append("| Decision | Information used | Executable entry |\n|---|---|---|\n"
             "| Offer-price access | Deal terms from the IPO calendar record, SIC code, VIX / S&P 500 trend / IPO count as of the close before the first trade | Offer price (no spread) on the first trading day |\n"
             "| Retail, at IPO (primary) | The above plus the first-day closing price | Open of the 2nd trading day, +25 bps |\n"
             "| Retail, post-report | The above plus facts tagged with the accession number of the first 10-Q/10-K filed after pricing, and that day's close | Open of the trading day after the filing date, +25 bps |\n")
    L.append("Later filings, restated figures and anything dated after the decision are excluded by construction and by tests (`tests/test_backtest.py`: decisions are unchanged when future prices and index data are rewritten; a later restatement of the same period is ignored). "
             "Known departures from strict point-in-time are listed in §11.\n")

    L.append("## 5. Protocol\n")
    L.append("Development 2012–2016 → validation 2017–2018 → embargo 2019 → **held-out test 2020 onward**. Training labels need a 12-month outcome fully realised before the period being evaluated. "
             "Walk-forward refits each January on outcomes known by then and decides that year's IPOs. Horizons are 21 / 63 / 126 / 252 trading days from entry; a horizon that ends after the snapshot is *incomplete* and is counted, not scored.\n")
    led = runs["ledger"]
    L.append("| Ledger event | UTC | rule hash | git commit |\n|---|---|---|---|")
    for f in led.get("freezes", []):
        L.append(f"| rules frozen | {f['frozen_at']} | `{f['rule_hash'][:16]}` | `{(f.get('git_commit_at_freeze') or '')[:12]}` |")
    for u in led.get("unsealings", []):
        L.append(f"| test period unsealed → `{u['run_id']}` | {u['at']} | `{u['rule_hash'][:16]}` | `{(u.get('git_commit') or '')[:12]}` |")
    L.append("")

    L.append(f"## 6. Held-out test results (IPOs priced 2020-01-01 → snapshot)\n")
    L.append(f"Eligible test-period IPOs: {tc['n_eligible']}; with price history: {tc['n_with_price_history']} ({pct(tc['price_coverage'])}). "
             "Without price history: " + ", ".join(f"{k} {v}" for k, v in tc.get("missing_price_by_sec_outcome", {}).items()) + ".\n")
    for m in ("A_retail", "A_offer", "B_post_report"):
        L.append(mode_section(t["modes"][m], MODE_NAMES[m]))
    L.append("### Worst BUY outcomes (primary endpoint)\n\n" + worst_table(P) + "\n")
    L.append("### Probability calibration (primary endpoint)\n\n" + calib_block(P) + "\n")
    for m in ("A_offer", "B_post_report"):
        b = t["modes"][m].get("brier") or {}
        if b.get("n"):
            L.append(f"- {m}: Brier {b['brier']:.4f} vs base-rate reference {b['brier_base_rate_reference']:.4f} (skill {b['skill_vs_base_rate']:+.3f}, n = {b['n']})")
    L.append("\n### By IPO year, sector and market conditions (primary endpoint, 12-month excess vs SPY)\n")
    L.append(brk_table(P, "by_ipo_year", "ipo_year", "IPO year") + "\n")
    L.append(brk_table(P, "by_sector", "sector", "Sector") + "\n")
    L.append(brk_table(P, "by_regime", "regime", "Market conditions at decision") + "\n")
    L.append("Sub-group figures are descriptive; several rest on very few trades.\n")

    L.append("## 7. Sensitivity and dependence on a few winners\n")
    L.append("These variants re-run the frozen rules under changed assumptions. They are robustness checks on the test period, not candidates for adoption.\n")
    L.append("**Primary endpoint**\n\n" + sens_table(t.get("sensitivity", []), "A_retail") + "\n")
    L.append("**Offer-price access**\n\n" + sens_table(t.get("sensitivity", []), "A_offer") + "\n")
    L.append("**Post-report**\n\n" + sens_table(t.get("sensitivity", []), "B_post_report") + "\n")
    L.append("**Concentration of results in the best trades (primary endpoint)**\n\n" + winner_block(P) + "\n")
    wa = P.get("winner_dependence_buy_all_12m") or {}
    if wa.get("n"):
        L.append(f"For comparison, buying every eligible IPO: mean {pct(wa['mean_excess'])}, median {pct(wa['median_excess'])}, without the best 5% {pct(wa['mean_excess_drop_top5pct'])}.\n")

    L.append("## 8. What the missing IPOs could do to the results\n")
    b = t.get("missing_price_bounds") or {}
    if b:
        L.append("The offer-stage decision needs no price data, so it was made for every eligible IPO, including those with no surviving price history. The table shows the 12-month mean excess return under explicit assumptions about those unobserved IPOs. These are bounds, not results.\n")
        L.append("| Group | observed | missing | observed only | missing = total loss | missing = market return | missing = +50% excess | bankrupt −100%, acquired +25%, others = observed mean |\n|---|--:|--:|--:|--:|--:|--:|--:|")
        for k, lab in (("strategy_buys", "Strategy BUYs (offer access)"), ("buy_all", "Every eligible IPO (offer access)")):
            v = b.get(k)
            if v:
                L.append(f"| {lab} | {v['n_observed']} | {v['n_missing_price']} | {pct(v['mean_excess_observed_only'])} | {pct(v['mean_excess_if_missing_total_loss'])} | {pct(v['mean_excess_if_missing_match_market'])} | {pct(v['mean_excess_if_missing_plus50pct'])} | {pct(v['mean_excess_by_outcome_assumption'])} |")
        L.append("")

    wf = t.get("walk_forward") or {}
    L.append("## 9. Walk-forward evaluation (2016–2025)\n")
    if wf.get("modes"):
        L.append("Each year's IPOs are decided by models fitted only on outcomes known before 1 January of that year (λ = 10, buy threshold at the 70th percentile of training probabilities, no per-fold tuning).\n")
        L.append("| Year | Mode | training IPOs | training base rate | buy threshold |\n|---|---|--:|--:|--:|")
        for f in wf.get("folds", []):
            L.append(f"| {f['year']} | {f['mode']} | {f['n_train']} | {pct(f['train_base_rate'])} | {f['buy_threshold']:.3f} |")
        L.append("")
        for m in ("A_retail", "A_offer", "B_post_report"):
            if m in wf["modes"]:
                s = wf["modes"][m]
                L.append(f"### {MODE_NAMES[m]}\n\n{class_block(s)}\n\n{horizon_table(s)}\n")
                by = (wf.get("by_year") or {}).get(m) or {}
                A = {r["wf_year"]: r for r in by.get("strategy", [])}
                Bm = {r["wf_year"]: r for r in by.get("buy_all", [])}
                L.append("| Year | BUY n | BUY mean excess 12m | BUY % beating SPY | all-IPO n | all-IPO mean excess |\n|---|--:|--:|--:|--:|--:|")
                for y in sorted(set(A) | set(Bm)):
                    a, bb = A.get(y), Bm.get(y)
                    L.append(f"| {y} | {a['n'] if a else 0} | {pct(a['mean_excess']) if a else '–'} | {pct(a['pct_outperform']) if a else '–'} | {bb['n'] if bb else 0} | {pct(bb['mean_excess']) if bb else '–'} |")
                bs = s.get("brier") or {}
                if bs.get("n"):
                    L.append(f"\nWalk-forward Brier {bs['brier']:.4f} vs base-rate reference {bs['brier_base_rate_reference']:.4f} (skill {bs['skill_vs_base_rate']:+.3f}, n = {bs['n']}).\n")
    else:
        L.append("Not enough training data for any fold.\n")

    L.append("## 10. Development-stage results (seen before the freeze)\n")
    if "validation" in runs:
        vm, v = runs["validation"]
        L.append(f"**Validation period 2017–2018, models fitted on 2012–2016 only** (run `{vm['run_id']}`). This is where λ and the buy threshold were chosen, so it flatters the chosen settings.\n")
        for m in ("A_retail", "A_offer", "B_post_report"):
            s = v["modes"][m]
            r, c = s["strategy"].get("12m", {}), s["buy_all"].get("12m", {})
            L.append(f"- {m}: BUY n = {r.get('n', 0)}, mean 12-month excess {ci(r.get('excess_ci'))}; buy-all n = {c.get('n', 0)}, mean excess {ci(c.get('excess_ci'))}; Brier skill {((s.get('brier') or {}).get('skill_vs_base_rate') or 0):+.3f}")
        L.append("")
    if "pretest" in runs:
        pm, pt = runs["pretest"]
        emb = pt["by_period"].get("embargo", {})
        L.append(f"**Embargo year 2019 with the final rules** (out-of-sample, but seen before the freeze; run `{pm['run_id']}`):\n")
        for m in ("A_retail", "A_offer", "B_post_report"):
            if m in emb:
                r, c = emb[m]["strategy"].get("12m", {}), emb[m]["buy_all"].get("12m", {})
                L.append(f"- {m}: BUY n = {r.get('n', 0)}, mean 12-month excess {ci(r.get('excess_ci'))}; buy-all n = {c.get('n', 0)}, mean excess {ci(c.get('excess_ci'))}")
        L.append("")

    n_del = sum((t["modes"][m][g].get(h) or {}).get("n_delisted_before_horizon") or 0
                for m in t["modes"] for g in ("strategy", "buy_all", "screen") for h in H)
    L.append("## 11. Limitations\n")
    L.append(LIMITATIONS.format(n_del=n_del, cov_all=pct(ps.get("ok", 0) / max(cov.get("eligible", 1), 1), 0), cov_test=pct(tc["price_coverage"], 0),
                                acq=so.get("acquired", 0), acq_ok=sk.get("acquired", 0), bk=so.get("bankruptcy", 0), bk_ok=sk.get("bankruptcy", 0),
                                pre_xbrl=cov.get("pre_ipo_xbrl_available", "n/a"), elig=cov.get("eligible")))
    L.append("## 12. Reproduce\n")
    L.append("```bash\ncd ipo-evaluator\npip install -r requirements.txt\npython -m pytest tests -q                    # calculation, dilution, missing-data, gate, price-sensitivity and backtest-integrity tests\n"
             "python -m ipo_app.data.fetch all             # re-download raw data (about an hour; hosts listed in README)\npython -m ipo_app.data.build                 # processed dataset + provenance hashes\n"
             "python -m ipo_app.backtest.run develop       # fit on dev, select on validation (test stays sealed)\npython -m ipo_app.backtest.run test          # frozen rules on the held-out period, sensitivity, walk-forward\n"
             "python -m ipo_app.backtest.report            # this report, verdict.json, static dashboard\npython -m ipo_app.server                     # dashboard at http://127.0.0.1:8765\n```\n\n"
             "A run id is a hash of the rule hash, data hash and configuration; the same three inputs reproduce the same run id and the same numbers (the bootstrap is seeded). "
             "Vendor price data is not redistributed in the repository, so a rebuild uses a fresh download and its data hash will differ from the one recorded here; prices for symbols delisted in the meantime will be gone.\n")
    (RESULTS / "VALIDATION_REPORT.md").write_text("\n".join(L))
    write_static_dashboard(runs)
    return verdict


LIMITATIONS = """**These limit what the numbers above can be taken to mean. The first is disqualifying on its own.**

1. **Survivorship in the price data.** Yahoo Finance removes price history for delisted symbols. Price history exists for {cov_all} of all eligible IPOs and {cov_test} of test-period IPOs. Of {acq} IPOs later acquired only {acq_ok} have prices; of {bk} that went bankrupt only {bk_ok} do. Every return in this report is therefore conditional on the company's symbol still existing at the snapshot. The direction of the bias is not known (acquisitions usually carry premiums; bankruptcies are near-total losses), and it need not be the same for the strategy as for the baselines. Other free sources were tried and failed at a named point: Stooq serves a browser-verification challenge to automated clients (not circumvented); stockanalysis.com redirects delisted symbols to the acquirer's page; Nasdaq's quote API answers "Symbol not exists" for delisted symbols. **Cheapest fix:** a survivorship-free daily price file (CRSP, Norgate, Sharadar, EODHD, or Tiingo's free tier at ~50 symbols/hour) keyed by the CIK/ticker/date columns already in `data/processed/universe.csv`, then re-run `build`, `test` and `report` with the same frozen rules.
2. **No prospectus financials at the IPO date.** SEC's XBRL API carries no facts filed before pricing for most IPOs ({pre_xbrl} of {elig} eligible IPOs have any), and requests to `www.sec.gov` were refused (HTTP 403) for a client that sends no contact address, so prospectus documents in the EDGAR archives were not retrieved. The at-IPO models therefore see deal terms and market conditions only. The web app accepts hand-typed prospectus financials at the IPO stage, and its calculations and gates on them are unit-tested, but their effect on recommendations at the IPO stage has **no historical test** here.
3. **Gates that could not be exercised historically.** Going-concern doubt is not available as a machine-readable historical field, and option/warrant strike prices are not either (the backtest uses the count of anti-dilutive securities reported in the first 10-Q/10-K as a strike-zero upper bound on dilution). These paths are covered by unit tests only.
4. **Author hindsight.** The code was written by a language model whose training data covers this period. Weights and thresholds were fitted mechanically on pre-2020 outcomes and the gates follow listing conventions, but the choice of features, exclusions and model family cannot be proven free of hindsight.
5. **Mild point-in-time approximations.** SIC codes and the Nasdaq deal record (shares outstanding, employees, expenses) are read as they stand today and are assumed unchanged since the IPO; the first-report decision uses the filing date and assumes the report was public by that day's close; the watchlist re-evaluates with new prices but keeps fundamentals and market conditions fixed at the decision date.
6. **Execution realism.** Entries use the official open of a daily bar; opening auctions of newly listed stocks can be thin, and 25 bps per side may understate costs for small floats (see the 50 and 100 bps rows). Offer-price access assumes a full allocation in every IPO, which retail investors do not receive, least of all in the deals that open strongly; the offer-price results are an upper bound on what allocation access could have delivered.
7. **Delisting outcomes are implemented but were not exercised by real data.** When a price series ends before a horizon, the position is closed at the last price less a haircut that depends on the SEC-derived reason. In the test period this happened {n_del} times across all groups and horizons: a company that delists loses its entire price history at the vendor, so it drops out of the sample instead of appearing as a delisting. The logic is covered by synthetic-data tests only, which is why the delisting sensitivity rows do not move.
8. **Sample size and overlap.** Twelve-month windows overlap heavily and IPOs cluster in hot markets (2020–2021 dominate the test period), so the effective number of independent observations is far below the trade count. Intervals are clustered by entry quarter; sub-group tables are descriptive only. Secondary analyses are not adjusted for multiple comparisons.
9. **Universe.** US-listed operating-company IPOs with an offer price of at least $5. Foreign private issuers, SPACs, units, funds, sub-$5 offerings and uplistings are excluded; conclusions do not extend to them. Sector benchmarks are broad SPDR sector ETFs chosen by SIC code, an approximation (biotechnology IPOs are compared with XLV, for example).
"""


def write_static_dashboard(runs: dict):
    """Self-contained copy of the dashboard with run data inlined (no server needed)."""
    html = (ROOT / "ipo_app" / "web" / "index.html").read_text()
    manifests, summaries, decisions = [], {}, {}
    keep = ["symbol", "name", "priced_date", "sector", "mode", "recommendation", "probability", "action", "wait_bars", "gates",
            "no_decision_reason", "strat_entry_date", "strat_ret_1m", "strat_ret_3m", "strat_ret_6m", "strat_ret_12m",
            "strat_spy_12m", "strat_status_12m", "base_ret_12m", "price_status", "sec_outcome"]
    for key in ("test", "validation", "pretest"):
        if key not in runs:
            continue
        m, s = runs[key]
        manifests.append(m)
        summaries[m["run_id"]] = s
        decisions[m["run_id"]] = {}
        for name, fn in (("main", "decisions.csv"), ("walkforward", "walkforward_decisions.csv")):
            p = RUNS / m["run_id"] / fn
            if p.exists():
                with p.open(newline="") as f:
                    decisions[m["run_id"]][name] = [{k: r.get(k, "") for k in keep} for r in csv.DictReader(f)]
    status = {"validation": _j(RESULTS / "verdict.json", {}), "rule_versions": R.list_rule_versions(),
              "ledger": runs.get("ledger"), "coverage": _j(PROC / "coverage.json")}
    blob = json.dumps({"status": status, "runs": manifests, "summaries": summaries, "decisions": decisions}).replace("</", "<\\/")
    html = html.replace("<script>\nconst STATIC", f"<script>window.__STATIC__ = {blob};</script>\n<script>\nconst STATIC", 1)
    html = html.replace("<title>IPO Evaluator</title>", "<title>IPO Validation Dashboard</title>", 1)
    (RESULTS / "validation_dashboard.html").write_text(html)


if __name__ == "__main__":
    v = write_report()
    print(v["label"], "|", v["verdict"], "|", v["summary"])
