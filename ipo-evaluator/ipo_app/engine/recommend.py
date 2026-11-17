"""Hard gates, probability model and recommendation logic.

A rule version is a JSON document (see ``rules/``). It contains only numbers: gate thresholds
fixed a priori and logistic-model coefficients fitted by ``ipo_app.backtest.train`` on data that
precedes the period being evaluated. Nothing here knows about any specific company.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from .calc import IPOInput, compute_metrics, _num, _pos

RULES_DIR = Path(__file__).resolve().parents[2] / "rules"

BUY, WAIT, AVOID, ABSTAIN, INELIGIBLE = "BUY", "WAIT", "AVOID", "ABSTAIN", "INELIGIBLE"

DEFAULT_GATES = {
    "min_price": 5.0,               # penny-stock floor (exchange / Ritter convention)
    "min_deal_size": 15_000_000.0,  # Nasdaq Capital Market minimum public float for an IPO listing
    "min_runway_months": 6.0,       # cash exhausted within two quarters at current burn
    "max_financials_age_days": 200, # older statements are treated as missing
    "default_underwriting_discount": 0.07,
}


# ----------------------------------------------------------------------------- sectors
def sector_of(sic) -> str:
    """Coarse sector from the 4-digit SIC code (mechanical; used for features and benchmarks)."""
    try:
        s = int(sic)
    except (TypeError, ValueError):
        return "unknown"
    if s in (2833, 2834, 2835, 2836, 8731, 8734) or 3840 <= s <= 3851 or 8000 <= s <= 8099:
        return "health"
    if s in (7370, 7371, 7372, 7373, 7374, 7375, 7379) or 3570 <= s <= 3579 or 3660 <= s <= 3679 \
            or 4800 <= s <= 4899 or s in (3559, 3825, 3826, 3827, 3829):
        return "tech"
    if s == 6798 or 6500 <= s <= 6599:
        return "real_estate"
    if 6000 <= s <= 6799:
        return "financial"
    if 1000 <= s <= 1499 or 2900 <= s <= 2999 or 4900 <= s <= 4999:
        return "energy_utilities"
    if 5000 <= s <= 5999 or 2000 <= s <= 2399 or 7000 <= s <= 7299 or 7800 <= s <= 7999 or 3100 <= s <= 3199:
        return "consumer"
    return "industrial_other"


SECTOR_ETF = {"health": "XLV", "tech": "XLK", "financial": "XLF", "real_estate": "XLF",
              "energy_utilities": "XLE", "consumer": "XLY", "industrial_other": "XLI", "unknown": "IWM"}


def exchange_tier(exchange: str) -> int:
    e = (exchange or "").upper()
    if "GLOBAL SELECT" in e or e.strip() in ("NYSE", "NEW YORK STOCK EXCHANGE"):
        return 2
    if "NASDAQ GLOBAL" in e or "NATIONAL MARKET" in e or e.strip() == "NASDAQ":
        return 1
    return 0


# ----------------------------------------------------------------------------- gates
def run_gates(inp: IPOInput, m: dict, gates: dict) -> list[dict]:
    """Returns every gate with its status. Severity order: INELIGIBLE > ABSTAIN > AVOID."""
    g = {**DEFAULT_GATES, **(gates or {})}
    out = []

    def add(gid, triggered, severity, msg):
        out.append({"id": gid, "triggered": bool(triggered), "severity": severity, "message": msg})

    add("INSTRUMENT", inp.instrument != "common" or inp.sic == 6770, INELIGIBLE,
        "Units, SPACs/blank-check shells and funds are not operating-company IPOs")
    critical = {"price": m.get("price"), "offer_price": inp.offer_price,
                "shares_offered": inp.shares_offered, "shares_outstanding_post": inp.shares_outstanding_post}
    missing = [k for k, v in critical.items() if not _pos(v)]
    add("CRITICAL_DATA_MISSING", missing, ABSTAIN, "Missing or non-positive critical inputs: " + ", ".join(missing))
    inconsistent = (_pos(inp.shares_offered) and _pos(inp.shares_outstanding_post)
                    and inp.shares_offered > inp.shares_outstanding_post * 1.0001)
    add("DATA_INCONSISTENT", inconsistent, ABSTAIN,
        "Shares offered exceed shares outstanding after the offering; inputs are inconsistent")
    if inp.stage == "post_report":
        stale = (not _num(inp.financials_age_days)) or inp.financials_age_days > g["max_financials_age_days"]
        no_fin = not (_num(inp.revenue) or _num(inp.net_income) or _num(inp.cash))
        add("FINANCIALS_MISSING_OR_STALE", stale or no_fin, ABSTAIN,
            "Post-report evaluation needs financial statements no older than "
            f"{g['max_financials_age_days']} days")
    add("PENNY_PRICE", _pos(m.get("price")) and m["price"] < g["min_price"], AVOID,
        f"Price below ${g['min_price']:.2f}")
    add("MICRO_DEAL", m.get("deal_size") is not None and m["deal_size"] < g["min_deal_size"], AVOID,
        f"Offering smaller than ${g['min_deal_size']/1e6:.0f}M: float too thin to trade reliably")
    add("GOING_CONCERN", inp.going_concern is True, AVOID, "Auditor/management going-concern doubt")
    rw = m.get("runway_months")
    add("CASH_RUNWAY", rw is not None and rw < g["min_runway_months"], AVOID,
        f"Pro-forma cash covers under {g['min_runway_months']:.0f} months of operating burn")
    return out


# ----------------------------------------------------------------------------- model
def feature_values(inp: IPOInput, m: dict) -> dict:
    """Raw (untransformed) feature values; None = missing."""
    def lg(x):
        return math.log(x) if _pos(x) else None

    sec = sector_of(inp.sic)
    rw = m.get("runway_months")
    f = {
        "log_deal_size": lg(m.get("deal_size")),
        "log_mcap_offer": lg(m.get("market_cap_offer")),
        "float_pct": m.get("float_pct"),
        "log_offer_price": lg(inp.offer_price),
        "exch_tier": float(exchange_tier(inp.exchange)),
        "sec_health": 1.0 if sec == "health" else 0.0,
        "sec_tech": 1.0 if sec == "tech" else 0.0,
        "sec_financial": 1.0 if sec in ("financial", "real_estate") else 0.0,
        "sec_energy": 1.0 if sec == "energy_utilities" else 0.0,
        "sec_consumer": 1.0 if sec == "consumer" else 0.0,
        "vix": inp.vix,
        "spy_ret_6m": inp.spy_ret_6m,
        "log_ipo_count_90d": lg((inp.ipo_count_90d or 0) + 1.0) if _num(inp.ipo_count_90d) else None,
        "log_employees": lg(inp.employees),
        "expense_ratio": m.get("expense_ratio"),
        "return_vs_offer": m.get("return_vs_offer"),
        # fundamentals (stage B)
        "log_mcap_now": lg(m.get("market_cap_diluted")),
        "has_revenue": (1.0 if _pos(inp.revenue) and inp.revenue >= 1e6 else 0.0) if _num(inp.revenue) else None,
        "log_ev_sales": lg(m.get("ev_sales")) if (m.get("ev_sales") or 0) > 0 else None,
        "revenue_growth": m.get("revenue_growth"),
        "profitable": None if m.get("profitable") is None else float(m["profitable"]),
        "ocf_positive": None if m.get("ocf_positive") is None else float(m["ocf_positive"]),
        "runway_months": None if rw is None else min(rw, 36.0),
        "net_margin": m.get("net_margin"),
        "book_to_market": m.get("book_to_market"),
        "dilution_overhang_pct": m.get("dilution_overhang_pct"),
    }
    return f


def model_probability(model: dict, feats: dict) -> tuple[float, list[dict]]:
    """Logistic model with winsorisation, standardisation, median imputation and
    missing-value indicators. Returns (probability, per-feature contributions)."""
    z = model["intercept"]
    contrib = []
    for spec in model["features"]:
        raw = feats.get(spec["name"])
        miss = raw is None or not math.isfinite(raw)
        x = spec["impute"] if miss else min(max(raw, spec["lo"]), spec["hi"])
        xs = (x - spec["mean"]) / spec["std"] if spec["std"] > 0 else 0.0
        c = spec["coef"] * xs + (spec.get("coef_missing", 0.0) if miss else 0.0)
        z += c
        contrib.append({"feature": spec["name"], "value": None if miss else raw, "missing": miss,
                        "contribution": c})
    z = max(min(z, 30.0), -30.0)
    return 1.0 / (1.0 + math.exp(-z)), contrib


# ----------------------------------------------------------------------------- rules I/O
def canonical_hash(obj) -> str:
    # the hash covers everything that can change a decision; bookkeeping fields are excluded so
    # that marking a version as frozen does not alter its identity
    body = {k: v for k, v in obj.items() if k not in ("hash", "frozen", "frozen_at", "meta")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load_rules(version: str) -> dict:
    p = RULES_DIR / f"{version}.json"
    rules = json.loads(p.read_text())
    h = canonical_hash(rules)
    if rules.get("hash") and rules["hash"] != h:
        raise ValueError(f"rule file {p.name} was modified after it was hashed "
                         f"(stored {rules['hash'][:12]}, actual {h[:12]})")
    rules["hash"] = h
    return rules


def list_rule_versions() -> list[dict]:
    out = []
    for p in sorted(RULES_DIR.glob("*.json")):
        try:
            r = load_rules(p.stem)
            out.append({"version": r["version"], "hash": r["hash"], "frozen": r.get("frozen", False),
                        "frozen_at": r.get("frozen_at"), "trained_through": r.get("trained_through"),
                        "description": r.get("description", "")})
        except ValueError as e:
            out.append({"version": p.stem, "error": str(e)})
    return out


# ----------------------------------------------------------------------------- recommendation
def model_key(inp: IPOInput) -> str:
    if inp.stage == "post_report":
        return "B_post_report"
    return "A_offer" if inp.access == "offer" else "A_retail"


def evaluate(inp: IPOInput, rules: dict, price=None, explain: bool = True) -> dict:
    """Evaluate one IPO at one price. Gates dominate the model:
    INELIGIBLE / ABSTAIN / AVOID gates are final; otherwise the probability decides BUY / WAIT / AVOID."""
    m = compute_metrics(inp, price, rules.get("gates", {}).get("default_underwriting_discount", 0.07))
    gates = run_gates(inp, m, rules.get("gates", {}))
    trig = [g for g in gates if g["triggered"]]
    res = {"recommendation": None, "probability": None, "metrics": m, "gates": gates,
           "reasons": [g["message"] for g in trig], "model": model_key(inp),
           "rule_version": rules.get("version"), "rule_hash": rules.get("hash")}
    for sev in (INELIGIBLE, ABSTAIN):
        if any(g["severity"] == sev for g in trig):
            res["recommendation"] = sev
            return res
    model = (rules.get("models") or {}).get(model_key(inp))
    if model is None:
        res["recommendation"] = ABSTAIN
        res["reasons"].append(f"Rule version has no model for {model_key(inp)}")
        return res
    feats = feature_values(inp, m)
    p, contrib = model_probability(model, feats)
    res["probability"] = p
    if explain:
        res["contributions"] = sorted(contrib, key=lambda c: -abs(c["contribution"]))
    if any(g["severity"] == AVOID for g in trig):
        res["recommendation"] = AVOID
        return res
    th = model["thresholds"]
    if p >= th["buy"]:
        res["recommendation"] = BUY
    elif p < th["avoid"]:
        res["recommendation"] = AVOID
        res["reasons"].append(f"Estimated probability of beating the market ({p:.0%}) is below {th['avoid']:.0%}")
    else:
        res["recommendation"] = WAIT
        res["reasons"].append(f"Probability {p:.0%} is between avoid ({th['avoid']:.0%}) and buy ({th['buy']:.0%}) thresholds")
    return res


def max_buy_price(inp: IPOInput, rules: dict, lo_frac: float = 0.3, hi_frac: float = 2.0, steps: int = 171):
    """Highest price in [lo_frac, hi_frac] x current price at which the recommendation is BUY.
    A grid search is used because the recommendation need not be monotone in price
    (a lower price improves valuation but can trip the penny-price gate)."""
    base = inp.price
    if not _pos(base):
        return None
    best = None
    for i in range(steps):
        p = base * (lo_frac + (hi_frac - lo_frac) * i / (steps - 1))
        if evaluate(inp, rules, price=p, explain=False)["recommendation"] == BUY:
            best = p
    return best
