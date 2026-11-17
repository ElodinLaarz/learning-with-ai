"""Engine tests: calculation correctness, dilution handling, missing-data behaviour,
hard gates, and how recommendations move with price and assumptions."""
import copy
import json
import math

import pytest

from ipo_app.engine.calc import (DilutiveSecurity, IPOInput, compute_metrics, fully_diluted_shares,
                                 net_primary_proceeds, treasury_method_shares)
from ipo_app.engine import recommend as R


def spec(name, coef, mean=0.0, std=1.0, lo=-1e9, hi=1e9, impute=0.0, coef_missing=0.0):
    return {"name": name, "coef": coef, "mean": mean, "std": std, "lo": lo, "hi": hi,
            "impute": impute, "coef_missing": coef_missing}


@pytest.fixture
def rules():
    """Synthetic rule file: probability falls as valuation (EV/sales) and price-vs-offer rise."""
    model = {"intercept": 0.4, "thresholds": {"buy": 0.55, "avoid": 0.35},
             "features": [spec("log_ev_sales", -1.2, mean=1.5, impute=1.5, coef_missing=-0.5),
                          spec("return_vs_offer", -1.0, lo=-0.9, hi=3.0),
                          spec("profitable", 0.6, impute=0.0)]}
    r = {"version": "test", "gates": dict(R.DEFAULT_GATES),
         "models": {"A_retail": model, "A_offer": model, "B_post_report": model}}
    r["hash"] = R.canonical_hash(r)
    return r


def base(**kw):
    d = dict(name="TestCo", exchange="NASDAQ Global Select", sic=7372, stage="post_report", access="retail",
             offer_price=20.0, shares_offered=10_000_000, shares_outstanding_post=50_000_000,
             offering_expenses=3_000_000, underwriting_discount=0.07,
             revenue=200_000_000, revenue_prior=150_000_000, net_income=10_000_000,
             operating_cash_flow=15_000_000, cash=120_000_000, debt=20_000_000, equity=300_000_000,
             intangibles=50_000_000, financials_age_days=40, balance_includes_proceeds=True, price=20.0)
    d.update(kw)
    return IPOInput(**d)


# ------------------------------------------------------------------ calculation correctness
def test_core_metrics_hand_computed():
    m = compute_metrics(base())
    assert m["deal_size"] == 200_000_000
    assert m["market_cap_offer"] == 1_000_000_000
    assert m["float_pct"] == pytest.approx(0.20)
    assert m["market_cap_basic"] == 1_000_000_000
    # EV = mcap + debt - cash (balance sheet already includes the proceeds)
    assert m["enterprise_value"] == pytest.approx(1_000_000_000 + 20_000_000 - 120_000_000)
    assert m["ev_sales"] == pytest.approx(900 / 200)
    assert m["revenue_growth"] == pytest.approx(200 / 150 - 1)
    assert m["net_margin"] == pytest.approx(0.05)
    assert m["expense_ratio"] == pytest.approx(0.015)
    assert m["runway_months"] == math.inf          # positive operating cash flow: no burn


def test_net_proceeds_discount_expenses_and_secondary_shares():
    # 10M shares, 4M of them sold by existing holders -> only 6M raise cash for the company
    inp = base(secondary_shares=4_000_000)
    assert net_primary_proceeds(inp) == pytest.approx(6_000_000 * 20 * 0.93 - 3_000_000)
    # all-secondary deal: the company receives nothing and still pays expenses
    assert net_primary_proceeds(base(secondary_shares=10_000_000)) == pytest.approx(-3_000_000)
    with pytest.raises(ValueError):
        net_primary_proceeds(base(secondary_shares=11_000_000))


def test_pro_forma_adds_proceeds_only_when_balance_sheet_predates_the_offering():
    pre = compute_metrics(base(stage="at_ipo", balance_includes_proceeds=False, cash=30_000_000, equity=-40_000_000))
    proceeds = 10_000_000 * 20 * 0.93 - 3_000_000
    assert pre["pro_forma_cash"] == pytest.approx(30_000_000 + proceeds)
    assert pre["pro_forma_equity"] == pytest.approx(-40_000_000 + proceeds)
    post = compute_metrics(base(balance_includes_proceeds=True, cash=30_000_000))
    assert post["pro_forma_cash"] == 30_000_000


def test_dilution_to_new_investors():
    # pro-forma equity 300M, intangibles 50M -> NTBV 250M / 50M sh = $5.00; buyers pay $20 -> 75% dilution
    m = compute_metrics(base())
    assert m["ntbv_per_share_post"] == pytest.approx(5.0)
    assert m["dilution_to_new_investors_pct"] == pytest.approx(0.75)


def test_runway_months_when_burning_cash():
    m = compute_metrics(base(operating_cash_flow=-60_000_000, cash=20_000_000))
    assert m["runway_months"] == pytest.approx(20 / 60 * 12)


# ------------------------------------------------------------------ dilution handling
def test_treasury_stock_method():
    secs = [DilutiveSecurity(1_000_000, 5.0), DilutiveSecurity(1_000_000, 25.0), DilutiveSecurity(500_000, 0.0, "rsu")]
    # at $20: 1M*(1-5/20)=750k in the money; $25 strike out of the money; RSUs count in full
    assert treasury_method_shares(secs, 20.0) == pytest.approx(750_000 + 0 + 500_000)
    # at $50 the $25 options come into the money too
    assert treasury_method_shares(secs, 50.0) == pytest.approx(900_000 + 500_000 + 500_000)
    assert treasury_method_shares(secs, None) is None
    with pytest.raises(ValueError):
        treasury_method_shares([DilutiveSecurity(-1, 5.0)], 20.0)


def test_fully_diluted_shares_depend_on_price_and_greenshoe():
    inp = base(dilutive=[DilutiveSecurity(5_000_000, 10.0)], overallotment_shares=1_500_000,
               overallotment_exercised=True)
    assert fully_diluted_shares(inp, 20.0) == pytest.approx(50_000_000 + 1_500_000 + 2_500_000)
    assert fully_diluted_shares(inp, 40.0) == pytest.approx(50_000_000 + 1_500_000 + 3_750_000)
    assert fully_diluted_shares(inp, 8.0) == pytest.approx(51_500_000)      # options under water
    inp.overallotment_exercised = False
    assert fully_diluted_shares(inp, 8.0) == pytest.approx(50_000_000)


def test_dilution_raises_market_cap_and_valuation_multiples():
    plain = compute_metrics(base())
    diluted = compute_metrics(base(dilutive=[{"count": 10_000_000, "strike": 0.0, "kind": "rsu"}]))
    assert diluted["market_cap_diluted"] == pytest.approx(60_000_000 * 20)
    assert diluted["dilution_overhang_pct"] == pytest.approx(0.20)
    assert diluted["ev_sales"] > plain["ev_sales"]
    assert diluted["market_cap_basic"] == plain["market_cap_basic"]     # basic cap is unchanged


def test_count_only_dilution_fallback():
    m = compute_metrics(base(dilutive_securities_count=5_000_000))
    assert m["fully_diluted_shares"] == 55_000_000


# ------------------------------------------------------------------ missing-data behaviour
def test_missing_inputs_propagate_as_none_not_zero():
    m = compute_metrics(base(revenue=None, cash=None, equity=None, net_income=None, operating_cash_flow=None))
    for k in ("ev_sales", "price_sales", "net_margin", "enterprise_value", "runway_months",
              "dilution_to_new_investors_pct", "profitable", "revenue_growth"):
        assert m[k] is None, k
    assert m["market_cap_basic"] == 1_000_000_000      # what can be computed still is


def test_zero_revenue_gives_no_multiple_rather_than_infinity():
    m = compute_metrics(base(revenue=0.0))
    assert m["ev_sales"] is None and m["net_margin"] is None


def test_abstain_when_critical_data_missing(rules):
    for field in ("offer_price", "shares_offered", "shares_outstanding_post", "price"):
        res = R.evaluate(base(**{field: None}), rules)
        assert res["recommendation"] == R.ABSTAIN, field
        assert res["probability"] is None
    assert R.evaluate(base(shares_outstanding_post=float("nan")), rules)["recommendation"] == R.ABSTAIN


def test_abstain_on_inconsistent_share_counts(rules):
    res = R.evaluate(base(shares_offered=60_000_000), rules)    # more shares sold than exist
    assert res["recommendation"] == R.ABSTAIN


def test_post_report_stage_requires_fresh_financials(rules):
    assert R.evaluate(base(financials_age_days=400), rules)["recommendation"] == R.ABSTAIN
    assert R.evaluate(base(financials_age_days=None), rules)["recommendation"] == R.ABSTAIN
    none = base(revenue=None, net_income=None, cash=None)
    assert R.evaluate(none, rules)["recommendation"] == R.ABSTAIN
    # the at-IPO stage does not need statements: it still produces a probability
    at_ipo = base(stage="at_ipo", revenue=None, net_income=None, cash=None, financials_age_days=None)
    assert R.evaluate(at_ipo, rules)["probability"] is not None


def test_missing_optional_feature_is_imputed_and_flagged(rules):
    full = R.evaluate(base(), rules)
    miss = R.evaluate(base(revenue=None), rules)
    c = {x["feature"]: x for x in miss["contributions"]}
    assert c["log_ev_sales"]["missing"] is True
    assert c["log_ev_sales"]["contribution"] == pytest.approx(-0.5)   # imputed at the mean + missing penalty
    assert miss["probability"] != full["probability"]


def test_missing_model_for_stage_abstains(rules):
    r = copy.deepcopy(rules)
    del r["models"]["B_post_report"]
    assert R.evaluate(base(), r)["recommendation"] == R.ABSTAIN


# ------------------------------------------------------------------ hard gates
def gate(res, gid):
    return next(g for g in res["gates"] if g["id"] == gid)["triggered"]


def test_gates_override_a_high_model_probability(rules):
    r = copy.deepcopy(rules)
    r["models"]["B_post_report"]["intercept"] = 25.0        # model says ~100%
    assert R.evaluate(base(), r)["recommendation"] == R.BUY
    cases = {
        "PENNY_PRICE": base(price=4.99),
        "MICRO_DEAL": base(shares_offered=700_000),                       # $14M deal
        "GOING_CONCERN": base(going_concern=True),
        "CASH_RUNWAY": base(operating_cash_flow=-100_000_000, cash=40_000_000),   # 4.8 months
    }
    for gid, inp in cases.items():
        res = R.evaluate(inp, r)
        assert gate(res, gid), gid
        assert res["recommendation"] == R.AVOID, gid
        assert res["probability"] > 0.99          # the probability is still reported, but cannot rescue it


def test_gate_boundaries(rules):
    assert not gate(R.evaluate(base(price=5.0), rules), "PENNY_PRICE")
    assert not gate(R.evaluate(base(shares_offered=750_000), rules), "MICRO_DEAL")        # exactly $15M
    six = base(operating_cash_flow=-80_000_000, cash=40_000_000)                           # exactly 6 months
    assert not gate(R.evaluate(six, rules), "CASH_RUNWAY")
    assert not gate(R.evaluate(base(going_concern=None), rules), "GOING_CONCERN")


def test_ineligible_instruments_take_precedence(rules):
    for inp in (base(instrument="spac"), base(instrument="unit"), base(sic=6770)):
        assert R.evaluate(inp, rules)["recommendation"] == R.INELIGIBLE
    # ineligible outranks abstain and avoid
    assert R.evaluate(base(instrument="spac", price=None, going_concern=True), rules)["recommendation"] == R.INELIGIBLE


def test_runway_gate_uses_pro_forma_cash_at_ipo(rules):
    # burning $60M/yr with $5M cash, but the IPO raises ~$183M -> not gated at the IPO stage
    inp = base(stage="at_ipo", balance_includes_proceeds=False, operating_cash_flow=-60_000_000, cash=5_000_000)
    assert not gate(R.evaluate(inp, rules), "CASH_RUNWAY")
    # the same company after an all-secondary deal gets no cash and is gated
    inp2 = base(stage="at_ipo", balance_includes_proceeds=False, operating_cash_flow=-60_000_000,
                cash=5_000_000, secondary_shares=10_000_000)
    assert gate(R.evaluate(inp2, rules), "CASH_RUNWAY")


# ------------------------------------------------------------------ price / assumption sensitivity
def test_recommendation_changes_as_price_rises(rules):
    recs = [R.evaluate(base(price=p), rules)["recommendation"] for p in (12, 20, 30, 45, 80)]
    probs = [R.evaluate(base(price=p), rules)["probability"] for p in (12, 20, 30, 45, 80)]
    assert probs == sorted(probs, reverse=True)             # richer price -> lower probability
    assert recs[0] == R.BUY and recs[-1] == R.AVOID
    assert R.WAIT in recs
    order = {R.BUY: 0, R.WAIT: 1, R.AVOID: 2}
    assert [order[r] for r in recs] == sorted(order[r] for r in recs)


def test_cheap_enough_to_be_a_penny_stock_is_avoided(rules):
    # valuation says buy at $4, but the price gate wins: recommendation is not monotone in price
    res = R.evaluate(base(price=4.0), rules)
    assert res["probability"] > rules["models"]["B_post_report"]["thresholds"]["buy"]
    assert res["recommendation"] == R.AVOID


def test_max_buy_price_is_consistent_with_evaluate(rules):
    inp = base(price=30.0)
    assert R.evaluate(inp, rules)["recommendation"] != R.BUY
    mbp = R.max_buy_price(inp, rules)
    assert mbp is not None and 5.0 <= mbp < 30.0
    assert R.evaluate(inp, rules, price=mbp)["recommendation"] == R.BUY
    assert R.evaluate(inp, rules, price=mbp * 1.05)["recommendation"] != R.BUY


def test_recommendation_changes_with_assumptions(rules):
    assert R.evaluate(base(price=22), rules)["recommendation"] == R.BUY
    # halve revenue -> EV/sales doubles
    assert R.evaluate(base(price=22, revenue=100_000_000), rules)["recommendation"] != R.BUY
    # heavy option overhang lifts the diluted market cap
    heavy = base(price=22, dilutive=[DilutiveSecurity(40_000_000, 1.0)])
    assert R.evaluate(heavy, rules)["probability"] < R.evaluate(base(price=22), rules)["probability"]
    # an unprofitable twin scores lower
    assert R.evaluate(base(price=22, net_income=-5e6), rules)["probability"] < \
        R.evaluate(base(price=22), rules)["probability"]


def test_thresholds_move_the_decision_not_the_probability(rules):
    r = copy.deepcopy(rules)
    p0 = R.evaluate(base(price=30), r)
    r["models"]["B_post_report"]["thresholds"] = {"buy": 0.05, "avoid": 0.01}
    p1 = R.evaluate(base(price=30), r)
    assert p0["probability"] == p1["probability"]
    assert p0["recommendation"] != R.BUY and p1["recommendation"] == R.BUY


# ------------------------------------------------------------------ rule integrity
def test_rule_file_tampering_is_detected(tmp_path, monkeypatch, rules):
    monkeypatch.setattr(R, "RULES_DIR", tmp_path)
    (tmp_path / "vX.json").write_text(json.dumps(rules))
    assert R.load_rules("vX")["hash"] == rules["hash"]
    tampered = copy.deepcopy(rules)
    tampered["models"]["A_retail"]["thresholds"]["buy"] = 0.10      # edit after hashing
    (tmp_path / "vX.json").write_text(json.dumps(tampered))
    with pytest.raises(ValueError, match="modified after it was hashed"):
        R.load_rules("vX")


def test_sector_and_exchange_mapping():
    assert R.sector_of(2834) == "health" and R.sector_of(7372) == "tech"
    assert R.sector_of(6022) == "financial" and R.sector_of(6798) == "real_estate"
    assert R.sector_of(1311) == "energy_utilities" and R.sector_of(5812) == "consumer"
    assert R.sector_of(None) == "unknown"
    assert R.exchange_tier("NASDAQ Global Select") == 2 and R.exchange_tier("NYSE") == 2
    assert R.exchange_tier("NASDAQ Global") == 1 and R.exchange_tier("NASDAQ Capital") == 0
    assert R.exchange_tier("NYSE MKT") == 0
