"""Backtest orchestration.

    python -m ipo_app.backtest.run develop   # fit on dev, select on validation, write rules (test stays sealed)
    python -m ipo_app.backtest.run freeze    # mark the rule version frozen and record it in the ledger
    python -m ipo_app.backtest.run test      # unseal the held-out period with the frozen rules; walk-forward; sensitivity

Every run writes results/runs/<run_id>/ with manifest.json, decisions.csv, summary.json.
The run id is a hash of (command, rule hash, data hash, config) so identical inputs give the same run.
"""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ..engine import recommend as R
from . import core as C
from . import metrics as M
from . import train as T

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"
RUNS = RESULTS / "runs"
LEDGER = RESULTS / "freeze_ledger.json"
RULE_VERSION = "v1.0.0"
PRIMARY_MODE = "A_retail"
H = list(C.HORIZONS)


# ----------------------------------------------------------------------------- helpers
def _git(*args) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception:
        return ""


def _json_default(o):
    if isinstance(o, (np.floating,)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


def _clean(o):
    """NaN/inf -> None so the JSON is strict and the dashboard can parse it."""
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, float) and not np.isfinite(o):
        return None
    if isinstance(o, (np.floating, np.integer, np.bool_, np.ndarray)):
        return _clean(_json_default(o))
    return o


def load_ledger() -> dict:
    if LEDGER.exists():
        return json.loads(LEDGER.read_text())
    return {"freezes": [], "unsealings": []}


def save_ledger(l: dict):
    RESULTS.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(l, indent=1))


def quarter(d: str) -> str:
    return f"{d[:4]}Q{(int(d[5:7]) - 1) // 3 + 1}"


def regime(vix, spy6) -> str:
    if vix is None or not np.isfinite(vix):
        return "unknown"
    v = "calm (VIX<15)" if vix < 15 else ("normal (VIX 15-25)" if vix < 25 else "stressed (VIX>=25)")
    return v


# ----------------------------------------------------------------------------- evaluation
def evaluate_deals(data: C.Data, rules: dict, cfg: C.Config, deal_ids, modes=C.MODES) -> pd.DataFrame:
    """One row per (IPO, mode): the decision, the strategy's own trade, and the immediate-entry
    baseline trade used for 'buy every eligible IPO', the simple screen and outcome labels."""
    rows = []
    for did in deal_ids:
        u = data.uni.loc[did]
        meta = {"deal_id": did, "symbol": u["symbol"], "name": u["name"], "priced_date": u["priced_date"],
                "ipo_year": int(u["priced_date"][:4]), "period": C.period_of(u["priced_date"]),
                "sector": R.sector_of(u.get("sic")), "exchange": u["exchange"],
                "offer_price": u["offer_price"], "deal_size": u["deal_size"],
                "price_status": u.get("price_status"), "sec_outcome": u.get("sec_outcome")}
        for mode in modes:
            rec = C.decide(data, did, mode, rules, cfg)
            inp = rec.pop("_input", None)
            rec.update(meta)
            rec.update(C.baseline_flags(data, did, mode, inp))
            if inp is not None:
                rec.update({"vix": inp.vix, "spy_ret_6m": inp.spy_ret_6m, "ipo_count_90d": inp.ipo_count_90d,
                            "regime": regime(inp.vix, inp.spy_ret_6m)})
            base = None
            if inp is not None and data.usable_bars(did) is not None:
                ep = data.entry_point(did, mode, rec["decision_bar"], cfg)
                if ep is not None:
                    base = data.outcome(did, ep[0], ep[1], ep[2], cfg)
                    rec.update({f"base_{k}": v for k, v in base.items()})
                    rec["base_entry_px_adj"], rec["base_entry_bar"] = ep[1], ep[0]
            if rec["action"] == "BUY":
                if rec.get("wait_bars", 0) == 0 and base is not None:
                    rec.update({f"strat_{k}": v for k, v in base.items()})
                    rec["strat_entry_px_adj"], rec["strat_entry_bar"] = rec["base_entry_px_adj"], rec["base_entry_bar"]
                else:
                    ep = data.entry_point(did, mode, rec["entry_decision_bar"], cfg)
                    if ep is None:
                        rec["action"] = "NO_TRADE"
                    else:
                        o = data.outcome(did, ep[0], ep[1], ep[2], cfg)
                        rec.update({f"strat_{k}": v for k, v in o.items()})
                        rec["strat_entry_px_adj"], rec["strat_entry_bar"] = ep[1], ep[0]
            rows.append(rec)
    return pd.DataFrame(rows)


def _col(df, name):
    return df[name].values.astype(float) if name in df else np.full(len(df), np.nan)


def group_summary(df: pd.DataFrame, prefix: str) -> dict:
    """Fixed-horizon table for one group of trades. prefix: 'strat' or 'base'."""
    out = {}
    ent = df.get(f"{prefix}_entry_date")
    clusters = np.array([quarter(d) if isinstance(d, str) else "NA" for d in (ent if ent is not None else [])])
    for h in H:
        ret, spy = _col(df, f"{prefix}_ret_{h}"), _col(df, f"{prefix}_spy_{h}")
        st = df[f"{prefix}_status_{h}"] if f"{prefix}_status_{h}" in df else pd.Series([None] * len(df))
        s = M.summarize(ret, spy)
        s["n_incomplete"] = int((st == "incomplete").sum())
        s["n_delisted_before_horizon"] = int((st == "delisted").sum())
        for b in ("iwm", "sector", "ipoetf"):
            bb = _col(df, f"{prefix}_{b}_{h}")
            ok = np.isfinite(ret) & np.isfinite(bb)
            s[f"mean_excess_vs_{b}"] = float((ret[ok] - bb[ok]).mean()) if ok.sum() else None
            s[f"pct_outperform_{b}"] = float((ret[ok] > bb[ok]).mean()) if ok.sum() else None
            s[f"n_vs_{b}"] = int(ok.sum())
        if len(clusters) == len(ret):
            s["excess_ci"] = M.cluster_bootstrap(ret - spy, clusters)
        out[h] = s
    return out


def breakdown(df: pd.DataFrame, prefix: str, by: str, h: str = "12m") -> list[dict]:
    rows = []
    if by not in df:
        return rows
    for key, g in df.groupby(by, dropna=False):
        s = M.summarize(_col(g, f"{prefix}_ret_{h}"), _col(g, f"{prefix}_spy_{h}"))
        if s["n"]:
            rows.append({by: key, "n": s["n"], "mean_ret": s["mean_ret"], "mean_excess": s["mean_excess"],
                         "median_excess": s["median_excess"], "pct_outperform": s["pct_outperform"]})
    return rows


# ----------------------------------------------------------------------------- portfolio simulation
def _paths(data: C.Data, trades: pd.DataFrame, prefix: str, cfg: C.Config, bench: str | None = None):
    """Daily value multipliers (relative to the entry price) for each trade over the holding period."""
    cal = data.cal
    out = []
    for _, t in trades.iterrows():
        bars = data.px[t["deal_id"]]
        eb = int(t[f"{prefix}_entry_bar"])
        ci = int(np.searchsorted(cal, bars.d[eb]))
        days = cal[ci: ci + cfg.hold_days + 1]
        if len(days) < 2:
            continue
        if bench:
            b = data.bench[bench]
            a = int(np.searchsorted(b["d"], bars.d[eb]))
            idx = np.clip(np.searchsorted(b["d"], days, side="right") - 1, a, len(b["d"]) - 1)
            path = b["adj"][idx] / b["open_adj"][a]
            cost_in = cost_out = cfg.cost_bps_etf / 1e4
            final_mult = 1.0 - cost_out
        else:
            idx = np.clip(np.searchsorted(bars.d, days, side="right") - 1, eb, len(bars.d) - 1)
            path = bars.adj[idx] / float(t[f"{prefix}_entry_px_adj"])
            cost_in = 0.0 if t["mode"] == "A_offer" else cfg.cost_bps_stock / 1e4
            delisted = t.get(f"{prefix}_status_12m") == "delisted"
            hc = cfg.delist_haircut.get(str(t.get("sec_outcome") or "active"), cfg.delist_haircut["active"])
            if delisted:   # after the last quote the position is cash at the haircut value
                gone = days > bars.d[-1]
                path = np.where(gone, bars.adj[-1] * (1 - hc) / float(t[f"{prefix}_entry_px_adj"]), path)
                final_mult = 1.0
            else:
                final_mult = 1.0 - cfg.cost_bps_stock / 1e4
        out.append({"ci": ci, "path": path, "cost_in": cost_in, "final_mult": final_mult,
                    "complete": len(days) == cfg.hold_days + 1})
    return sorted(out, key=lambda p: p["ci"])


def simulate(data: C.Data, paths: list, cfg: C.Config) -> dict:
    """Capital-constrained account: each new position gets `position_frac` of current equity (if
    cash allows and fewer than `max_positions` are open); idle cash earns the T-bill ETF (BIL);
    positions are sold after `hold_days` trading days or at delisting."""
    if not paths:
        return {"n_trades_taken": 0}
    cal = data.cal
    bil = data.bench["BIL"]
    start, end = paths[0]["ci"], min(max(p["ci"] + len(p["path"]) - 1 for p in paths), len(cal) - 1)
    bi = np.clip(np.searchsorted(bil["d"], cal[start - 1: end + 1], side="right") - 1, 0, len(bil["d"]) - 1)
    bil_ret = bil["adj"][bi][1:] / bil["adj"][bi][:-1] - 1.0
    cash, open_pos, equity, dates = cfg.start_capital, [], [], []
    by_day: dict[int, list] = {}
    for p in paths:
        by_day.setdefault(p["ci"], []).append(p)
    taken = skipped = 0
    invested_share = []
    prev_equity = cash
    for k, c in enumerate(range(start, end + 1)):
        cash *= 1.0 + bil_ret[k]
        for p in by_day.get(c, []):                       # entries at the open
            size = min(cfg.position_frac * prev_equity, cash)
            if len(open_pos) >= cfg.max_positions or size < 0.01 * cfg.start_capital * cfg.position_frac * 10:
                skipped += 1
                continue
            cash -= size + cfg.commission
            open_pos.append({"p": p, "base": size / (1.0 + p["cost_in"])})
            taken += 1
        val, still = 0.0, []
        for pos in open_pos:                               # mark at the close; exit at the horizon
            t = c - pos["p"]["ci"]
            v = pos["base"] * pos["p"]["path"][min(t, len(pos["p"]["path"]) - 1)]
            if t >= len(pos["p"]["path"]) - 1 and pos["p"]["complete"]:
                cash += v * pos["p"]["final_mult"] - cfg.commission
            else:
                val += v
                still.append(pos)
        open_pos = still
        prev_equity = cash + val
        equity.append(prev_equity)
        dates.append(str(cal[c]))
        invested_share.append(val / prev_equity if prev_equity > 0 else 0.0)
    st = M.equity_stats(equity, dates)
    st.update({"n_trades_offered": len(paths), "n_trades_taken": taken, "n_trades_skipped_capacity": skipped,
               "avg_invested_share": float(np.mean(invested_share)), "start": dates[0], "end": dates[-1]})
    return {"stats": st, "equity": equity, "dates": dates}


def spy_buy_hold(data: C.Data, start: str, end: str, cfg: C.Config) -> dict:
    b = data.bench["SPY"]
    a = int(np.searchsorted(b["d"], np.datetime64(start, "D")))
    e = int(np.searchsorted(b["d"], np.datetime64(end, "D"), side="right") - 1)
    eq = cfg.start_capital * b["adj"][a: e + 1] / b["adj"][a]
    return {"stats": M.equity_stats(eq, [str(d) for d in b["d"][a: e + 1]]), "equity": eq.tolist(),
            "dates": [str(d) for d in b["d"][a: e + 1]]}


def calendar_time_alpha(data: C.Data, paths: list) -> dict:
    """Equal-weight portfolio of every open position (no capital constraint), compounded to months and
    regressed on the market: alpha with Newey–West errors. Overlapping holding periods are handled by
    construction because each month appears once."""
    if not paths:
        return {}
    cal = data.cal
    n = len(cal)
    s, cnt = np.zeros(n), np.zeros(n)
    for p in paths:
        r = p["path"][1:] / p["path"][:-1] - 1.0
        idx = np.arange(p["ci"] + 1, p["ci"] + 1 + len(r))
        s[idx] += r
        cnt[idx] += 1
    daily = pd.Series(np.where(cnt > 0, s / np.maximum(cnt, 1), np.nan), index=pd.to_datetime(cal))

    def bench_daily(sym):
        b = data.bench[sym]
        ser = pd.Series(b["adj"], index=pd.to_datetime(b["d"])).reindex(daily.index).ffill()
        return ser.pct_change()

    df = pd.DataFrame({"p": daily, "m": bench_daily("SPY"), "f": bench_daily("BIL")}).dropna()
    if df.empty:
        return {}
    mon = (1 + df).groupby(df.index.to_period("M")).prod() - 1
    days = df.groupby(df.index.to_period("M")).size()
    mon = mon[days >= 15]
    out = M.newey_west_alpha(mon["p"] - mon["f"], mon["m"] - mon["f"])
    out["avg_positions"] = float(cnt[cnt > 0].mean())
    return out


# ----------------------------------------------------------------------------- summaries
def summarize_mode(data: C.Data, df: pd.DataFrame, mode: str, cfg: C.Config, with_portfolio=True) -> dict:
    d = df[df["mode"] == mode]
    buys = d[d["action"] == "BUY"]
    has_base = d[d.get("base_entry_date").notna()] if "base_entry_date" in d else d.iloc[0:0]
    screen = has_base[has_base["screen"]]
    out = {"n_eligible": int(len(d)),
           "recommendations": d["recommendation"].value_counts().to_dict(),
           "actions": d["action"].value_counts().to_dict(),
           "no_decision_reasons": d["no_decision_reason"].value_counts().to_dict() if "no_decision_reason" in d else {},
           "gates_triggered": pd.Series([g for s in d.get("gates", pd.Series(dtype=str)).dropna() for g in str(s).split("|") if g]).value_counts().to_dict(),
           "n_buy": int(len(buys)), "n_buy_after_wait": int((buys.get("wait_bars", 0) > 0).sum()) if len(buys) else 0,
           "abstention_rate": float(1 - len(buys) / len(d)) if len(d) else None,
           "strategy": group_summary(buys, "strat"), "buy_all": group_summary(has_base, "base"),
           "screen": group_summary(screen, "base")}
    # paired differences with shared-quarter resampling
    out["diff_vs_buy_all"], out["diff_vs_screen"] = {}, {}
    for h in H:
        if len(buys) and f"strat_ret_{h}" in buys and f"base_ret_{h}" in has_base:
            a = _col(buys, f"strat_ret_{h}") - _col(buys, f"strat_spy_{h}")
            ac = np.array([quarter(x) for x in buys["strat_entry_date"]])
            b = _col(has_base, f"base_ret_{h}") - _col(has_base, f"base_spy_{h}")
            bc = np.array([quarter(x) for x in has_base["base_entry_date"]])
            out["diff_vs_buy_all"][h] = M.cluster_bootstrap_diff(a, ac, b, bc)
            if len(screen):
                s_ = _col(screen, f"base_ret_{h}") - _col(screen, f"base_spy_{h}")
                sc = np.array([quarter(x) for x in screen["base_entry_date"]])
                out["diff_vs_screen"][h] = M.cluster_bootstrap_diff(a, ac, s_, sc)
    # classification at 12 months (winner = an immediate entry beat SPY over the same dates)
    if "base_ret_12m" in has_base:
        lab = has_base[np.isfinite(_col(has_base, "base_ret_12m")) & np.isfinite(_col(has_base, "base_spy_12m"))].copy()
        lab["winner"] = lab["base_ret_12m"] > lab["base_spy_12m"]
        bought = lab["action"] == "BUY"
        sb = buys[np.isfinite(_col(buys, "strat_ret_12m")) & np.isfinite(_col(buys, "strat_spy_12m"))] if len(buys) and "strat_ret_12m" in buys else buys.iloc[0:0]
        own_win = (sb["strat_ret_12m"] > sb["strat_spy_12m"]) if len(sb) else pd.Series(dtype=bool)
        out["classification_12m"] = {
            "n_labelled": int(len(lab)), "base_rate_winners": float(lab["winner"].mean()) if len(lab) else None,
            "n_buys_with_outcome": int(len(sb)),
            "buys_outperform": int(own_win.sum()), "false_positives": int((~own_win).sum()) if len(sb) else 0,
            "precision": float(own_win.mean()) if len(sb) else None,
            "false_positive_rate_of_buys": float((~own_win).mean()) if len(sb) else None,
            "winners_total": int(lab["winner"].sum()),
            "missed_winners": int((lab["winner"] & ~bought).sum()),
            "missed_winner_rate": float((lab["winner"] & ~bought).sum() / max(lab["winner"].sum(), 1)),
            "losers_avoided": int((~lab["winner"] & ~bought).sum()),
            "loser_avoidance_rate": float((~lab["winner"] & ~bought).sum() / max((~lab["winner"]).sum(), 1))}
        pm = lab[lab["probability"].notna()] if "probability" in lab else lab.iloc[0:0]
        out["brier"] = M.brier(pm["probability"], pm["winner"].astype(float)) if len(pm) else {"n": 0}
        out["calibration"] = M.calibration_table(pm["probability"], pm["winner"].astype(float)) if len(pm) else []
    out["winner_dependence_12m"] = M.winner_dependence(_col(buys, "strat_ret_12m"), _col(buys, "strat_spy_12m")) if len(buys) else {}
    out["winner_dependence_buy_all_12m"] = M.winner_dependence(_col(has_base, "base_ret_12m"), _col(has_base, "base_spy_12m")) if len(has_base) else {}
    out["by_sector"] = {"strategy": breakdown(buys, "strat", "sector"), "buy_all": breakdown(has_base, "base", "sector")}
    out["by_ipo_year"] = {"strategy": breakdown(buys, "strat", "ipo_year"), "buy_all": breakdown(has_base, "base", "ipo_year")}
    out["by_regime"] = {"strategy": breakdown(buys, "strat", "regime"), "buy_all": breakdown(has_base, "base", "regime")}
    worst = buys.dropna(subset=["strat_ret_12m"]).nsmallest(10, "strat_ret_12m") if len(buys) and "strat_ret_12m" in buys else buys.iloc[0:0]
    out["worst_buys_12m"] = worst[["symbol", "name", "priced_date", "strat_entry_date", "strat_ret_12m", "strat_spy_12m", "strat_status_12m"]].to_dict("records")
    if with_portfolio:
        port = {}
        for label, trades, prefix in (("strategy", buys, "strat"), ("buy_all", has_base, "base"), ("screen", screen, "base")):
            if not len(trades):
                continue
            paths = _paths(data, trades, prefix, cfg)
            sim = simulate(data, paths, cfg)
            if "stats" not in sim:
                continue
            sm = simulate(data, _paths(data, trades, prefix, cfg, bench="SPY"), cfg)
            bh = spy_buy_hold(data, sim["dates"][0], sim["dates"][-1], cfg)
            port[label] = {"stats": sim["stats"], "matched_spy_stats": sm.get("stats"), "spy_buy_hold_stats": bh["stats"],
                           "calendar_time_alpha": calendar_time_alpha(data, paths),
                           "curve": {"dates": sim["dates"][::5], "equity": [round(x, 2) for x in sim["equity"][::5]],
                                     "matched_spy": [round(x, 2) for x in sm.get("equity", [])[::5]],
                                     "spy_buy_hold": [round(x, 2) for x in bh["equity"][::5]]}}
        out["portfolio"] = port
    return out


def coverage_summary(data: C.Data, deal_ids) -> dict:
    u = data.uni.loc[list(deal_ids)]
    ok = u["price_status"] == "ok"
    return {"n_eligible": int(len(u)), "n_with_price_history": int(ok.sum()),
            "price_coverage": float(ok.mean()) if len(u) else None,
            "missing_price_by_sec_outcome": u.loc[~ok, "sec_outcome"].value_counts().to_dict(),
            "with_price_by_sec_outcome": u.loc[ok, "sec_outcome"].value_counts().to_dict(),
            "coverage_by_year": {y: {"eligible": int(len(g)), "with_price": int((g["price_status"] == "ok").sum())}
                                 for y, g in u.groupby(u["priced_date"].str[:4])}}


def missing_price_bounds(df: pd.DataFrame, h: str = "12m") -> dict:
    """A_offer decisions exist even for IPOs whose price history is gone. Bound the 12-month mean excess
    return of each group under explicit assumptions about those unobserved names."""
    d = df[df["mode"] == "A_offer"]
    out = {}
    for label, g in (("strategy_buys", d[d["recommendation"] == R.BUY]), ("buy_all", d[d["recommendation"].isin([R.BUY, R.WAIT, R.AVOID])])):
        col_r, col_b = ("strat_ret_" + h, "strat_spy_" + h) if label == "strategy_buys" else ("base_ret_" + h, "base_spy_" + h)
        ex = (_col(g, col_r) - _col(g, col_b))
        obs = ex[np.isfinite(ex)]
        miss = g[g["price_status"] != "ok"]
        if len(obs) == 0:
            continue
        mean_spy = float(np.nanmean(_col(g, col_b)))
        n_m, n_o = len(miss), len(obs)

        def mix(val_per_missing):
            return float((obs.sum() + np.sum(val_per_missing)) / (n_o + n_m)) if (n_o + n_m) else None

        by = miss["sec_outcome"].fillna("active").values
        out[label] = {
            "n_observed": int(n_o), "n_missing_price": int(n_m), "missing_by_sec_outcome": pd.Series(by).value_counts().to_dict(),
            "mean_excess_observed_only": float(obs.mean()),
            "mean_excess_if_missing_total_loss": mix(np.full(n_m, -1.0 - mean_spy)),
            "mean_excess_if_missing_match_market": mix(np.zeros(n_m)),
            "mean_excess_if_missing_plus50pct": mix(np.full(n_m, 0.5)),
            "mean_excess_by_outcome_assumption": mix(np.where(by == "bankruptcy", -1.0 - mean_spy, np.where(by == "acquired", 0.25, obs.mean())))}
    return out


# ----------------------------------------------------------------------------- sensitivity
def sensitivity(data: C.Data, rules: dict, cfg: C.Config, deal_ids, modes=C.MODES) -> list[dict]:
    def point(label, family, r=rules, c=cfg, m=modes):
        df = evaluate_deals(data, r, c, deal_ids, modes=m)
        rows = []
        for mode in m:
            d = df[df["mode"] == mode]
            b = d[d["action"] == "BUY"]
            hb = d[d["base_entry_date"].notna()] if "base_entry_date" in d else d.iloc[0:0]
            sb = M.summarize(_col(b, "strat_ret_12m"), _col(b, "strat_spy_12m"))
            sa = M.summarize(_col(hb, "base_ret_12m"), _col(hb, "base_spy_12m"))
            rows.append({"family": family, "variant": label, "mode": mode, "n_buy": sb.get("n", 0),
                         "buy_mean_excess_12m": sb.get("mean_excess"), "buy_median_excess_12m": sb.get("median_excess"),
                         "buy_pct_outperform": sb.get("pct_outperform"), "n_all": sa.get("n", 0),
                         "all_mean_excess_12m": sa.get("mean_excess"),
                         "diff_mean_excess": (sb["mean_excess"] - sa["mean_excess"]) if sb.get("n") and sa.get("n") else None})
        return rows

    out = point("baseline (frozen settings)", "baseline")
    for bps in (0, 10, 50, 100):
        out += point(f"{bps} bps per side", "costs", c=C.Config(**{**cfg.to_dict(), "cost_bps_stock": float(bps)}))
    for q in ("-10", "+10"):
        r2 = copy.deepcopy(rules)
        for mk, mdl in r2["models"].items():
            bq = int(round(mdl["thresholds"]["buy_quantile"] * 100)) + int(q)
            if str(bq) in mdl["train_prob_quantiles"]:
                mdl["thresholds"]["buy"] = mdl["train_prob_quantiles"][str(bq)]
        out += point(f"buy threshold at train quantile {q} pts", "thresholds", r=r2)
    r3 = copy.deepcopy(rules)
    for mdl in r3["models"].values():
        mdl["thresholds"]["avoid"] = -1.0
    out += point("no AVOID band (everything below BUY waits)", "thresholds", r=r3)
    for wd in (0, 120):
        out += point(f"watchlist window {wd} days", "waiting", c=C.Config(**{**cfg.to_dict(), "wait_days": wd}))
    out += point("retail entry at 2nd-day CLOSE", "execution", c=C.Config(**{**cfg.to_dict(), "entry_at": "close"}), m=("A_retail", "B_post_report"))
    out += point("retail entry at 6th-day open", "execution", c=C.Config(**{**cfg.to_dict(), "entry_lag": 5}), m=("A_retail",))
    out += point("delisting: no haircut", "delisting", c=C.Config(**{**cfg.to_dict(), "delist_haircut": {"bankruptcy": 0.0, "acquired": 0.0, "delisted_other": 0.0, "active": 0.0}}))
    out += point("delisting: total loss unless acquired", "delisting", c=C.Config(**{**cfg.to_dict(), "delist_haircut": {"bankruptcy": 1.0, "acquired": 0.0, "delisted_other": 1.0, "active": 1.0}}))
    out += point("valuation on basic shares (no dilutive securities)", "valuation", c=C.Config(**{**cfg.to_dict(), "use_diluted": False}), m=("B_post_report",))
    r4 = copy.deepcopy(rules)
    r4["gates"] = {**r4.get("gates", {}), "min_deal_size": 0.0, "min_runway_months": 0.0, "min_price": 0.0}
    out += point("hard gates relaxed (price/deal-size/runway off)", "gates", r=r4)
    r5 = copy.deepcopy(rules)
    r5["gates"] = {**r5.get("gates", {}), "min_deal_size": 50e6, "min_runway_months": 12.0}
    out += point("hard gates stricter ($50M deal, 12-month runway)", "gates", r=r5)
    return out


# ----------------------------------------------------------------------------- walk-forward
def walk_forward(data: C.Data, cfg: C.Config, years, modes=C.MODES) -> tuple[pd.DataFrame, list]:
    """For each year Y: fit on IPOs whose 12-month outcome was known before 1 Jan Y (pre-declared
    default hyper-parameters, no per-fold tuning), then decide every IPO priced in Y."""
    ids = list(data.uni.index)
    priced = data.uni["priced_date"]
    full = {m: T.feature_frame(data, ids, m, cfg, label_before=None) for m in modes}
    exit_dates = {}
    frames, folds = [], []
    for m in modes:
        # exit date of the 12m label, recomputed cheaply from the frame's deal ids
        ex = {}
        for did in full[m]["deal_id"]:
            inp, ctx = data.reconstruct(did, m, cfg)
            ep = data.entry_point(did, m, ctx["decision_bar"], cfg)
            ex[did] = data.outcome(did, ep[0], ep[1], ep[2], cfg, horizons={"12m": 252}).get("exit_date_12m")
        exit_dates[m] = ex
    for y in years:
        cut = f"{y}-01-01"
        test_ids = [d for d in ids if cut <= priced[d] <= f"{y}-12-31"]
        if not test_ids:
            continue
        models = {}
        for m in modes:
            f = full[m]
            tr = f[[(exit_dates[m].get(d) or "9999") < cut for d in f["deal_id"]]]
            if len(tr) >= T.MIN_TRAIN and 0 < tr["y"].mean() < 1:
                models[m] = T.fit_model(tr, m, T.DEFAULT_LAMBDA, T.DEFAULT_BUY_Q)
                folds.append({"year": y, "mode": m, "n_train": int(len(tr)), "train_base_rate": float(tr["y"].mean()),
                              "buy_threshold": models[m]["thresholds"]["buy"]})
        if not models:
            continue
        rules_y = {"version": f"walkforward-{y}", "gates": dict(R.DEFAULT_GATES), "models": models}
        df = evaluate_deals(data, rules_y, cfg, test_ids, modes=tuple(models))
        df["wf_year"] = y
        frames.append(df)
    return (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()), folds


# ----------------------------------------------------------------------------- run plumbing
DECISION_COLS = ["deal_id", "symbol", "name", "priced_date", "ipo_year", "period", "sector", "exchange", "offer_price",
                 "deal_size", "mode", "recommendation", "probability", "action", "wait_bars", "gates", "no_decision_reason",
                 "asof", "decision_price", "screen", "vix", "spy_ret_6m", "ipo_count_90d", "regime", "price_status", "sec_outcome"]


def write_run(name: str, command: str, rules: dict, data: C.Data, cfg: C.Config, df: pd.DataFrame, summary: dict,
              extra: dict | None = None) -> str:
    ident = {"command": command, "rule_hash": rules.get("hash"), "data_hash": data.provenance.get("data_hash"),
             "config": cfg.to_dict(), "name": name}
    run_id = f"{name}-{hashlib.sha256(json.dumps(ident, sort_keys=True).encode()).hexdigest()[:10]}"
    out = RUNS / run_id
    out.mkdir(parents=True, exist_ok=True)
    cols = [c for c in DECISION_COLS if c in df] + sorted(c for c in df if c.startswith(("strat_", "base_")) and "entry_bar" not in c and "px_adj" not in c)
    extra_cols = [c for c in ("wf_year",) if c in df]
    df[cols + extra_cols].to_csv(out / "decisions.csv", index=False, float_format="%.6g")
    manifest = {"run_id": run_id, "name": name, "command": command,
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "git_commit": _git("rev-parse", "HEAD"), "git_dirty": bool(_git("status", "--porcelain", "--", "ipo_app", "rules")),
                "rule_version": rules.get("version"), "rule_hash": rules.get("hash"), "rules_frozen": rules.get("frozen", False),
                "data_hash": data.provenance.get("data_hash"), "data_built_at": data.provenance.get("built_at"),
                "snapshot_last_market_date": str(data.snapshot), "config": cfg.to_dict(), "periods": C.PERIODS,
                "horizons_trading_days": C.HORIZONS, "bootstrap_seed": M.SEED,
                "test_period_unsealed": bool(data.unsealed), "n_decision_rows": int(len(df))}
    if extra:
        manifest.update(extra)
    (out / "manifest.json").write_text(json.dumps(_clean(manifest), indent=1, default=_json_default))
    (out / "summary.json").write_text(json.dumps(_clean(summary), indent=1, default=_json_default))
    print("wrote", out.relative_to(ROOT), flush=True)
    return run_id


def ids_in(data: C.Data, a: str, b: str):
    p = data.uni["priced_date"]
    return list(p[(p >= a) & (p <= b)].index)


# ----------------------------------------------------------------------------- commands
def cmd_develop():
    data, cfg = C.Data(), C.Config()
    dev_ids = ids_in(data, *C.PERIODS["dev"])
    val_ids = ids_in(data, *C.PERIODS["val"])
    pre_ids = ids_in(data, "2012-01-01", C.PERIODS["embargo"][1])
    models, devfit, selection = {}, {}, {}
    for mode in C.MODES:
        dev = T.feature_frame(data, dev_ids, mode, cfg, label_before=C.PERIODS["val"][0])
        val = T.feature_frame(data, val_ids, mode, cfg, label_before=C.TEST_START)
        sel = T.select_hyper(dev, val, mode)
        selection[mode] = sel
        devfit[mode] = T.fit_model(dev, mode, sel["lambda"], sel["buy_quantile"])
        allpre = T.feature_frame(data, pre_ids, mode, cfg, label_before=C.TEST_START)
        models[mode] = T.fit_model(allpre, mode, sel["lambda"], sel["buy_quantile"])
        print(mode, "dev", len(dev), "val", len(val), "final-train", len(allpre), "lambda", sel["lambda"], "buy_q", sel["buy_quantile"], flush=True)
    rules = {"version": RULE_VERSION,
             "description": "Gates fixed a priori; logistic models fitted on IPOs whose 12-month outcome was known before "
                            f"{C.TEST_START}; hyper-parameters selected on the 2017-2018 validation period.",
             "gates": dict(R.DEFAULT_GATES), "models": models, "trained_through": C.TEST_START,
             "label": "12-month net return after an immediate entry beats SPY over the same dates",
             "frozen": False, "frozen_at": None, "meta": {"selection": selection}}
    rules["hash"] = R.canonical_hash(rules)
    R.RULES_DIR.mkdir(exist_ok=True)
    (R.RULES_DIR / f"{RULE_VERSION}.json").write_text(json.dumps(_clean(rules), indent=1))
    rules = R.load_rules(RULE_VERSION)

    # (a) honest validation: models fitted on dev only, applied to the validation years
    val_rules = {"version": f"{RULE_VERSION}-devfit", "gates": dict(R.DEFAULT_GATES), "models": devfit}
    val_rules["hash"] = R.canonical_hash(val_rules)
    dfv = evaluate_deals(data, val_rules, cfg, val_ids)
    summ_v = {"scope": "validation period 2017-2018, models fitted on the development period only (out-of-sample)",
              "coverage": coverage_summary(data, val_ids), "selection": selection,
              "modes": {m: summarize_mode(data, dfv, m, cfg) for m in C.MODES}}
    write_run("validation", "develop", val_rules, data, cfg, dfv, summ_v)
    # (b) frozen-candidate rules on everything before the test period (dev+val are IN-SAMPLE; 2019 is not)
    dfp = evaluate_deals(data, rules, cfg, pre_ids)
    summ_p = {"scope": "pre-test periods with the final rule file: dev and val are in-sample, the 2019 embargo year is out-of-sample",
              "coverage": coverage_summary(data, pre_ids),
              "by_period": {p: {m: summarize_mode(data, dfp[dfp["period"] == p], m, cfg, with_portfolio=False) for m in C.MODES}
                            for p in ("dev", "val", "embargo")}}
    write_run("pretest", "develop", rules, data, cfg, dfp, summ_p)


def cmd_freeze():
    p = R.RULES_DIR / f"{RULE_VERSION}.json"
    rules = json.loads(p.read_text())
    h = R.canonical_hash(rules)
    led = load_ledger()
    if any(u["rule_hash"] != h for u in led["unsealings"]):
        print("WARNING: the test period was already unsealed with different rules; it is no longer held out for this version")
    rules.update({"frozen": True, "frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "hash": h})
    p.write_text(json.dumps(rules, indent=1))
    led["freezes"].append({"rule_version": RULE_VERSION, "rule_hash": h, "frozen_at": rules["frozen_at"],
                           "git_commit_at_freeze": _git("rev-parse", "HEAD")})
    save_ledger(led)
    print("frozen", RULE_VERSION, h)


def cmd_test():
    rules = R.load_rules(RULE_VERSION)
    led = load_ledger()
    if not rules.get("frozen") or not any(f["rule_hash"] == rules["hash"] for f in led["freezes"]):
        sys.exit("refusing to unseal: rule version is not frozen in the ledger")
    rel = f"ipo-evaluator/rules/{RULE_VERSION}.json"
    if _git("status", "--porcelain", "--", f"rules/{RULE_VERSION}.json", "PREREGISTRATION.md"):
        sys.exit("refusing to unseal: frozen rules / preregistration are not committed to git")
    freeze_commit = _git("log", "-1", "--format=%H", "--", f"rules/{RULE_VERSION}.json")
    prior = [u for u in led["unsealings"] if u["rule_hash"] != rules["hash"]]
    data, cfg = C.Data(), C.Config()
    data.unsealed = True
    test_ids = ids_in(data, *C.PERIODS["test"])
    df = evaluate_deals(data, rules, cfg, test_ids)
    summary = {"scope": f"held-out test period: IPOs priced from {C.TEST_START}, frozen rules {RULE_VERSION}",
               "held_out_integrity": {"freeze_commit": freeze_commit, "rule_hash": rules["hash"],
                                      "unsealed_before_with_other_rules": bool(prior), "prior_unsealings": led["unsealings"]},
               "coverage": coverage_summary(data, test_ids),
               "modes": {m: summarize_mode(data, df, m, cfg) for m in C.MODES},
               "missing_price_bounds": missing_price_bounds(df)}
    print("test evaluated; running sensitivity", flush=True)
    summary["sensitivity"] = sensitivity(data, rules, cfg, test_ids)
    print("running walk-forward", flush=True)
    wf, folds = walk_forward(data, cfg, range(2016, 2026))
    summary["walk_forward"] = {"folds": folds,
                               "modes": {m: summarize_mode(data, wf, m, cfg) for m in C.MODES if len(wf) and (wf["mode"] == m).any()},
                               "by_year": {m: {"strategy": breakdown(wf[(wf["mode"] == m) & (wf["action"] == "BUY")], "strat", "wf_year"),
                                               "buy_all": breakdown(wf[(wf["mode"] == m) & wf["base_entry_date"].notna()], "base", "wf_year")}
                                           for m in C.MODES if len(wf)}}
    run_id = write_run("test", "test", rules, data, cfg, df, summary, extra={"freeze_commit": freeze_commit})
    if len(wf):
        cols = [c for c in DECISION_COLS + ["wf_year"] if c in wf] + sorted(c for c in wf if c.startswith(("strat_", "base_")) and "entry_bar" not in c and "px_adj" not in c)
        wf[cols].to_csv(RUNS / run_id / "walkforward_decisions.csv", index=False, float_format="%.6g")
    led["unsealings"].append({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "rule_version": RULE_VERSION,
                              "rule_hash": rules["hash"], "run_id": run_id, "git_commit": _git("rev-parse", "HEAD")})
    save_ledger(led)


if __name__ == "__main__":
    {"develop": cmd_develop, "freeze": cmd_freeze, "test": cmd_test}[sys.argv[1]]()
