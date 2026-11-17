"""Backtest tests on a synthetic market: point-in-time integrity, executable entries, costs,
splits, delisting outcomes, incomplete observations, the test-period seal and the statistics."""
import numpy as np
import pandas as pd
import pytest

from ipo_app.backtest import core as C
from ipo_app.backtest import metrics as M
from ipo_app.data import build as B
from ipo_app.engine import recommend as R

CAL = pd.bdate_range("2015-01-01", "2022-12-30")


def _bench(sym, growth=0.0, level=100.0):
    px = level * (1 + growth) ** np.arange(len(CAL))
    return pd.DataFrame({"symbol": sym, "date": CAL, "open": px, "close": px, "adjclose": px})


def _bars(deal, first_day, closes, opens=None, split=None):
    """split=(bar_index, ratio): quotes before the split are stored Yahoo-style (already divided)."""
    days = CAL[CAL.get_loc(pd.Timestamp(first_day)):][:len(closes)]
    closes = np.asarray(closes, float)
    opens = closes.copy() if opens is None else np.asarray(opens, float)
    fac = np.ones(len(closes))
    if split:
        i, ratio = split
        fac[:i] = ratio
        closes, opens = closes / fac, opens / fac
    return pd.DataFrame({"deal_id": deal, "date": days, "open": opens, "high": closes, "low": closes,
                         "close": closes, "volume": 1e6, "adjclose": closes, "split_factor": fac})


def _spec(name, coef):
    return {"name": name, "coef": coef, "mean": 0.0, "std": 1.0, "lo": -9.0, "hi": 9.0, "impute": 0.0, "coef_missing": 0.0}


@pytest.fixture
def rules():
    # probability falls as the price runs above the offer: BUY below +10%, WAIT to +60%, AVOID above
    def model():
        return {"intercept": 0.5, "features": [_spec("return_vs_offer", -3.0)],
                "thresholds": {"buy": 0.55, "avoid": 0.22}}
    r = {"version": "t", "gates": dict(R.DEFAULT_GATES),
         "models": {"A_offer": model(), "A_retail": model(), "B_post_report": model()}}
    r["hash"] = R.canonical_hash(r)
    return r


@pytest.fixture
def data(tmp_path):
    proc, snap = tmp_path / "p", tmp_path / "s"
    proc.mkdir(), snap.mkdir()
    last = CAL[-1]

    def deal(i, priced, **kw):
        d = dict(deal_id=f"D{i}", symbol=f"SYM{i}", name=f"Co {i}", exchange="NASDAQ Global Select", priced_date=priced,
                 offer_price=20.0, shares_offered=10e6, deal_size=200e6, eligible=True, exclusion=None, cik=f"{i:010d}",
                 shares_outstanding_post=50e6, offering_expenses=3e6, lockup_days=180, employees=500,
                 secondary_shares=None, sic=7372, sec_outcome="active", price_status="ok", last_bar=None)
        d.update(kw)
        return d

    n = 400
    frames = [
        _bars("D1", "2016-03-02", 21 + 0.05 * np.arange(n), opens=21.5 + 0.05 * np.arange(n)),
        _bars("D2", "2016-03-02", np.full(100, 30.0)),                 # acquired after 100 bars
        _bars("D3", "2016-03-02", np.full(100, 30.0)),                 # dropped by the exchange
        _bars("D4", "2016-03-02", np.full(100, 30.0)),                 # bankrupt
        _bars("D5", str(CAL[-60].date()), np.full(60, 25.0)),          # listed 60 days before the snapshot
        _bars("D6", "2016-03-02", np.r_[np.full(50, 40.0), np.full(n - 50, 20.0)], split=(50, 2.0)),
        _bars("D7", "2021-03-02", np.full(n, 22.0)),                   # test-period IPO
        _bars("D9", "2016-03-02", np.r_[30.0, np.linspace(30, 21, 20), np.full(n - 21, 21.0)]),  # pops, then fades
    ]
    uni = pd.DataFrame([
        deal(1, "2016-03-01", last_bar=str(last.date()), report_filed="2016-05-10"),
        deal(2, "2016-03-01", sec_outcome="acquired", last_bar=str(frames[1]["date"].iloc[-1].date())),
        deal(3, "2016-03-01", sec_outcome="delisted_other", last_bar=str(frames[2]["date"].iloc[-1].date())),
        deal(4, "2016-03-01", sec_outcome="bankruptcy", last_bar=str(frames[3]["date"].iloc[-1].date())),
        deal(5, str(CAL[-61].date()), last_bar=str(last.date())),
        deal(6, "2016-03-01", last_bar=str(last.date())),
        deal(7, "2021-03-01", last_bar=str(last.date())),
        deal(8, "2016-03-01", price_status="no_yahoo_history", sec_outcome="acquired"),
        deal(9, "2016-03-01", last_bar=str(last.date())),
    ])
    uni.to_csv(proc / "universe.csv", index=False)
    pd.DataFrame([{"deal_id": "D1", "report_form": "10-Q", "report_filed": "2016-05-10", "report_period_end": "2016-03-31",
                   "revenue": 80e6, "revenue_prior": 60e6, "net_income": -4e6, "operating_cash_flow": -8e6,
                   "cash": 190e6, "equity": 250e6, "cover_shares": 51e6, "antidilutive_securities": 4e6}]
                 ).to_csv(proc / "first_report.csv", index=False)
    pd.concat(frames).to_csv(snap / "prices.csv.gz", index=False)
    pd.concat([_bench("SPY", 0.0004), _bench("IWM"), _bench("IPO"), _bench("BIL"), _bench("^VIX", level=18.0),
               _bench("XLK", 0.0002), _bench("XLV"), _bench("XLF"), _bench("XLE"), _bench("XLY"), _bench("XLI")]
              ).to_csv(snap / "bench.csv.gz", index=False)
    d = C.Data(proc, snap)
    return d


CFG = C.Config()


# ------------------------------------------------------------------ point-in-time integrity
def test_retail_decision_uses_only_the_first_day_close(data, rules):
    rec = C.decide(data, "D1", "A_retail", rules, CFG)
    inp = rec["_input"]
    assert rec["decision_bar"] == 0 and rec["asof"] == "2016-03-02"
    assert inp.price == pytest.approx(21.0)                       # first-day close, nothing later
    before = (rec["recommendation"], rec["probability"])
    bars = data.px["D1"]
    bars.close_raw[1:] *= 5                                       # rewrite the future
    bars.adj[1:] *= 5
    again = C.decide(data, "D1", "A_retail", rules, CFG)
    assert (again["recommendation"], again["probability"]) == before


def test_offer_decision_is_made_before_any_trading(data, rules):
    rec = C.decide(data, "D1", "A_offer", rules, CFG)
    assert rec["decision_bar"] == -1 and rec["asof"] < "2016-03-02"
    assert rec["_input"].price == 20.0 and rec["decision_price"] == 20.0
    # the first-day price must not influence it
    data.px["D1"].close_raw[0] = 99.0
    assert C.decide(data, "D1", "A_offer", rules, CFG)["probability"] == rec["probability"]


def test_market_state_ignores_later_data(data):
    s0 = data.market_state("2016-03-02")
    i = int(np.searchsorted(data.bench["SPY"]["d"], np.datetime64("2016-03-02")))
    data.bench["SPY"]["adj"][i + 1:] *= 0.5
    data.bench["^VIX"]["close"][i + 1:] = 80.0
    assert data.market_state("2016-03-02") == s0
    assert s0["vix"] == 18.0 and s0["spy_ret_6m"] == pytest.approx(1.0004 ** 126 - 1)


def test_ipo_heat_counts_only_deals_already_priced(data):
    assert data.market_state("2016-02-29")["ipo_count_90d"] == 0
    assert data.market_state("2016-03-01")["ipo_count_90d"] == 7      # the seven 2016-03-01 pricings
    assert data.market_state("2016-07-01")["ipo_count_90d"] == 0      # more than 90 days later


def test_post_report_decision_waits_for_the_filing(data, rules):
    rec = C.decide(data, "D1", "B_post_report", rules, CFG)
    inp, bars = rec["_input"], data.px["D1"]
    assert str(bars.d[rec["decision_bar"]]) == "2016-05-10"            # close on the filing date
    assert inp.revenue == 80e6 and inp.financials_age_days == 40
    assert inp.shares_outstanding_post == 51e6                         # newer cover-page share count
    assert inp.dilutive_securities_count == 4e6
    assert inp.balance_includes_proceeds is True                       # quarter ended after the IPO
    ep = data.entry_point("D1", "B_post_report", rec["decision_bar"], CFG)
    assert str(bars.d[ep[0]]) == "2016-05-11"                          # executable only the next morning
    assert C.decide(data, "D2", "B_post_report", rules, CFG)["no_decision_reason"] == "no_periodic_report_found"


def test_first_report_uses_only_facts_from_that_accession():
    fil = pd.DataFrame({"form": ["10-Q", "S-1/A", "10-Q", "10-K/A"],
                        "filingDate": ["2016-02-01", "2016-02-20", "2016-05-10", "2017-03-01"],
                        "reportDate": ["2015-12-31", "", "2016-03-31", "2016-03-31"], "items": ["", "", "", ""],
                        "accessionNumber": ["A0", "A1", "A2", "A3"], "acceptanceDateTime": [""] * 4})
    row = lambda s, e, v, accn: [s, e, v, accn, "10-Q", "x", 2016, "Q1"]
    facts = {"facts": {
        "us-gaap:Revenues": {"USD": [row("2016-01-01", "2016-03-31", 20e6, "A2"), row("2015-01-01", "2015-03-31", 16e6, "A2"),
                                     row("2016-01-01", "2016-03-31", 99e6, "A3"),      # later restatement
                                     row("2015-10-01", "2015-12-31", 5e6, "A0")]},     # filed before pricing
        "us-gaap:NetIncomeLoss": {"USD": [row("2016-01-01", "2016-03-31", -1e6, "A2")]},
        "us-gaap:Assets": {"USD": [row(None, "2016-03-31", 300e6, "A2"), row(None, "2016-03-31", 111e6, "A3")]},
        "us-gaap:CashAndCashEquivalentsAtCarryingValue": {"USD": [row(None, "2016-03-31", 50e6, "A2")]},
        "us-gaap:ShortTermInvestments": {"USD": [row(None, "2016-03-31", 25e6, "A2")]},
        "dei:EntityCommonStockSharesOutstanding": {"shares": [row(None, "2016-04-30", 51e6, "A2")]}}}
    r = B.first_report(fil, facts, "2016-03-01")
    assert r["report_accession"] == "A2" and r["report_filed"] == "2016-05-10"    # not the pre-IPO 10-Q
    assert r["revenue"] == pytest.approx(20e6 * 365 / 91)                          # annualised quarter, as filed
    assert r["revenue_prior"] == pytest.approx(16e6 * 365 / 90)
    assert r["total_assets"] == 300e6                                              # restated 111e6 ignored
    assert r["cash"] == 75e6 and r["cover_shares"] == 51e6
    assert B.first_report(fil[fil["filingDate"] < "2016-03-01"], facts, "2016-03-01") is None


# ------------------------------------------------------------------ execution and costs
def test_entry_is_next_open_after_the_decision_with_costs(data):
    bars = data.px["D1"]
    i, px, cost = data.entry_point("D1", "A_retail", 0, CFG)
    assert i == 1 and px == pytest.approx(bars.open_adj[1]) == pytest.approx(21.55) and cost == 0.0025
    o = data.outcome("D1", i, px, cost, CFG)
    exit_close = 21 + 0.05 * (1 + 252)
    assert o["status_12m"] == "complete"
    assert o["ret_12m"] == pytest.approx(exit_close * (1 - 0.0025) / (21.55 * 1.0025) - 1)
    # zero-cost variant is strictly better by roughly two half-spreads
    free = data.outcome("D1", i, px, 0.0, C.Config(cost_bps_stock=0.0))
    assert free["ret_12m"] - o["ret_12m"] == pytest.approx(0.005 * exit_close / 21.55, rel=0.02)
    # benchmark over the same dates, with ETF costs
    assert o["spy_12m"] == pytest.approx(1.0004 ** 252 * (1 - 0.0002) / 1.0002 - 1)
    assert o["sector_etf"] == "XLK" and o["sector_12m"] == pytest.approx(1.0002 ** 252 * (1 - 0.0002) / 1.0002 - 1)


def test_offer_price_access_enters_at_the_offer_without_spread(data):
    i, px, cost = data.entry_point("D1", "A_offer", -1, CFG)
    assert (i, cost) == (0, 0.0) and px == pytest.approx(20.0)
    o = data.outcome("D1", i, px, cost, CFG)
    assert o["ret_1m"] == pytest.approx((21 + 0.05 * 21) * (1 - 0.0025) / 20.0 - 1)   # only the exit pays a spread


def test_split_adjustment_keeps_offer_and_returns_consistent(data, rules):
    bars = data.px["D6"]
    assert bars.close_raw[0] == pytest.approx(40.0)       # traded at $40 before the 2:1 split
    assert bars.adj[0] == pytest.approx(20.0)             # stored split-adjusted
    rec = C.decide(data, "D6", "A_retail", rules, CFG)
    assert rec["_input"].price == pytest.approx(40.0)     # compared with the $20 offer as traded: +100%
    i, px, cost = data.entry_point("D6", "A_offer", -1, CFG)
    o = data.outcome("D6", i, px, cost, CFG)
    # $20 offer -> $40 pre-split == $20 post-split: a 100% gain, not 0% and not 300%
    assert o["ret_12m"] == pytest.approx(2.0 * (1 - 0.0025) - 1)


# ------------------------------------------------------------------ delisting and follow-up
@pytest.mark.parametrize("deal,haircut", [("D2", 0.0), ("D3", 0.30), ("D4", 1.0)])
def test_delisting_before_the_horizon(data, deal, haircut):
    i, px, cost = data.entry_point(deal, "A_retail", 0, CFG)
    o = data.outcome(deal, i, px, cost, CFG)
    assert o["status_1m"] == "complete" and o["status_3m"] == "complete"
    assert o["status_6m"] == "delisted" and o["status_12m"] == "delisted"
    assert o["ret_12m"] == pytest.approx(30.0 * (1 - haircut) / (30.0 * 1.0025) - 1)
    assert np.isfinite(o["spy_12m"])                       # the benchmark is still held to the horizon


def test_insufficient_follow_up_is_incomplete_not_a_result(data):
    data.unsealed = True          # D5 listed 60 days before the snapshot, i.e. inside the test period
    i, px, cost = data.entry_point("D5", "A_retail", 0, CFG)
    o = data.outcome("D5", i, px, cost, CFG)
    assert o["status_1m"] == "complete" and "ret_1m" in o
    for h in ("3m", "6m", "12m"):
        assert o[f"status_{h}"] == "incomplete" and f"ret_{h}" not in o


def test_no_price_history_still_gets_an_offer_stage_decision(data, rules):
    rec = C.decide(data, "D8", "A_offer", rules, CFG)
    assert rec["recommendation"] == R.BUY and rec["action"] == "BUY_NO_PRICE_DATA"
    assert C.decide(data, "D8", "A_retail", rules, CFG)["no_decision_reason"] == "no_price_history"
    assert data.entry_point("D8", "A_offer", -1, CFG) is None


# ------------------------------------------------------------------ waiting
def test_wait_converts_to_buy_when_the_price_comes_in(data, rules):
    rec = C.decide(data, "D9", "A_retail", rules, CFG)      # +50% on day one
    assert rec["recommendation"] == R.WAIT
    assert rec["action"] == "BUY" and rec["wait_bars"] > 0
    bars = data.px["D9"]
    k = rec["entry_decision_bar"]
    assert bars.close_raw[k] / 20.0 - 1 < 0.10 <= bars.close_raw[k - 1] / 20.0 - 1   # first close under the line
    i, _, _ = data.entry_point("D9", "A_retail", k, CFG)
    assert i == k + 1                                                          # bought the next morning
    no_wait = C.decide(data, "D9", "A_retail", rules, C.Config(wait_days=0))
    assert no_wait["recommendation"] == R.WAIT and no_wait["action"] == "NO_TRADE"
    assert C.decide(data, "D9", "A_offer", rules, CFG)["action"] in ("BUY", "NO_TRADE")   # no waiting on allocations


def test_avoid_is_final(data, rules):
    r = dict(rules)
    r["models"] = {k: {**v, "thresholds": {"buy": 0.999, "avoid": 0.99}} for k, v in rules["models"].items()}
    rec = C.decide(data, "D9", "A_retail", r, CFG)
    assert rec["recommendation"] == R.AVOID and rec["action"] == "NO_TRADE" and rec["wait_bars"] == 0


# ------------------------------------------------------------------ the seal
def test_test_period_outcomes_are_sealed(data):
    assert C.period_of("2021-03-01") == "test" and C.period_of("2019-06-01") == "embargo"
    i, px, cost = data.entry_point("D7", "A_retail", 0, CFG)
    with pytest.raises(C.SealError):
        data.outcome("D7", i, px, cost, CFG)
    data.unsealed = True
    assert data.outcome("D7", i, px, cost, CFG)["status_12m"] == "complete"


def test_training_labels_respect_the_embargo(data):
    from ipo_app.backtest import train as T
    ids = ["D1", "D2", "D3", "D4", "D6", "D9"]
    full = T.feature_frame(data, ids, "A_retail", CFG, label_before="2019-01-01")
    assert set(full["deal_id"]) == set(ids)
    # the 12-month outcomes end in March 2017: a cutoff before that leaves no usable label
    assert T.feature_frame(data, ids, "A_retail", CFG, label_before="2017-01-01").empty
    with pytest.raises(C.SealError):
        T.feature_frame(data, ["D7"], "A_retail", CFG, label_before=None)


# ------------------------------------------------------------------ raw-data parsing
def _chart(first_ts, n, splits=None, first_trade=None):
    ts = [int(pd.Timestamp(d).timestamp()) for d in pd.bdate_range(first_ts, periods=n)]
    return {"symbol": "X", "n": n, "error": None, "chart": {
        "meta": {"firstTradeDate": first_trade or ts[0]}, "timestamp": ts,
        "indicators": {"quote": [{"open": [10.0] * n, "high": [10.0] * n, "low": [10.0] * n, "close": [10.0] * n,
                                  "volume": [1] * n}], "adjclose": [{"adjclose": [10.0] * n}]},
        "events": {"splits": splits or {}}}}


def test_parse_yahoo_identity_checks_and_split_factor():
    df, meta = B.parse_yahoo({"attempts": [_chart("2016-03-02", 30)]}, "2016-03-01")
    assert meta["first_bar"] == "2016-03-02" and (df["split_factor"] == 1).all()
    # a 1-for-10 reverse split on bar 10: earlier as-traded prices were a tenth of the adjusted ones
    sp = {"1": {"date": int(pd.Timestamp(pd.bdate_range("2016-03-02", periods=30)[10]).timestamp()),
                "numerator": 1, "denominator": 10}}
    df, _ = B.parse_yahoo({"attempts": [_chart("2016-03-02", 30, splits=sp)]}, "2016-03-01")
    assert df["split_factor"].iloc[0] == pytest.approx(0.1) and df["split_factor"].iloc[10] == 1.0
    # symbol that already traded before the deal -> not an IPO
    old = int(pd.Timestamp("2014-01-02").timestamp())
    assert B.parse_yahoo({"attempts": [_chart("2016-03-02", 30, first_trade=old)]}, "2016-03-01") == (None, "prior_trading_history")
    # symbol whose history starts months later belongs to someone else
    assert B.parse_yahoo({"attempts": [_chart("2016-09-01", 30)]}, "2016-03-01") == (None, "yahoo_history_starts_late")
    assert B.parse_yahoo({"attempts": [{"symbol": "X", "n": 0, "chart": None}]}, "2016-03-01") == (None, "no_yahoo_history")


def test_outcome_classification_from_filings():
    f = lambda rows: pd.DataFrame(rows, columns=["form", "filingDate", "items"])
    snap = "2020-06-30"
    cls = lambda rows: B.classify_outcome(f(rows), "2016-03-01", snap)["sec_outcome"]
    assert cls([("10-K", "2020-03-01", "")]) == "active"
    assert cls([("8-K", "2018-05-01", "1.03,9.01"), ("25-NSE", "2018-05-20", "")]) == "bankruptcy"
    assert cls([("10-K", "2017-03-01", ""), ("DEFM14A", "2018-01-10", ""), ("15-12B", "2018-04-01", "")]) == "acquired"
    assert cls([("10-K", "2018-03-01", ""), ("25", "2018-09-01", "")]) == "delisted_other"
    assert cls([("10-Q", "2017-05-01", "")]) == "delisted_other"                 # simply stopped reporting
    # a company that is still reporting is active even if it retired a class of securities (Form 25)
    # or made a tender offer for another company (SC TO-T appears in the bidder's own index)
    assert cls([("25", "2018-09-01", ""), ("SC TO-T", "2019-01-01", ""), ("10-Q", "2020-05-01", "")]) == "active"
    # filings before the IPO are irrelevant
    assert cls([("8-K", "2015-05-01", "1.03"), ("10-K", "2020-03-01", "")]) == "active"
    # a recent IPO that has not filed a periodic report yet is active
    assert B.classify_outcome(f([("424B4", "2020-05-01", ""), ("8-K", "2020-06-01", "2.02")]), "2020-05-01", snap)["sec_outcome"] == "active"


# ------------------------------------------------------------------ statistics
def test_cluster_bootstrap_is_wider_when_returns_share_a_quarter():
    rng = np.random.default_rng(0)
    shock = rng.normal(0, 0.3, 20)
    clusters = np.repeat(np.arange(20), 30)
    x = shock[clusters] + rng.normal(0, 0.1, 600) + 0.02
    clustered = M.cluster_bootstrap(x, clusters)
    naive = M.cluster_bootstrap(x, np.arange(600))        # pretends every trade is independent
    assert (clustered["ci_hi"] - clustered["ci_lo"]) > 3 * (naive["ci_hi"] - naive["ci_lo"])
    assert clustered["n_clusters"] == 20 and clustered["estimate"] == pytest.approx(x.mean())
    again = M.cluster_bootstrap(x, clusters)
    assert again == clustered                             # seeded -> reproducible


def test_cluster_bootstrap_diff_detects_a_real_gap_and_ignores_shared_shocks():
    rng = np.random.default_rng(1)
    clusters = np.repeat(np.arange(24), 20)
    shock = rng.normal(0, 0.4, 24)[clusters]
    a = shock + 0.10 + rng.normal(0, 0.05, 480)
    b = shock + rng.normal(0, 0.05, 480)
    d = M.cluster_bootstrap_diff(a, clusters, b, clusters)
    assert d["ci_lo"] > 0 and d["estimate"] == pytest.approx(0.10, abs=0.02)
    same = M.cluster_bootstrap_diff(b, clusters, shock + rng.normal(0, 0.05, 480), clusters)
    assert same["ci_lo"] < 0 < same["ci_hi"]


def test_brier_and_calibration():
    y = np.array([1, 0, 1, 0, 1, 0, 1, 0], float)
    assert M.brier(y, y)["brier"] == 0.0
    b = M.brier(np.full(8, 0.5), y)
    assert b["brier"] == pytest.approx(0.25) and b["skill_vs_base_rate"] == pytest.approx(0.0)
    assert M.brier(1 - y, y)["skill_vs_base_rate"] < 0     # confidently wrong is worse than the base rate
    p = np.r_[np.full(50, 0.2), np.full(50, 0.8)]
    yy = np.r_[np.r_[np.ones(10), np.zeros(40)], np.r_[np.ones(40), np.zeros(10)]]
    t = M.calibration_table(p, yy, bins=2)
    assert [round(r["observed_rate"], 2) for r in t] == [0.2, 0.8]


def test_summary_drawdown_and_winner_dependence():
    s = M.summarize([0.5, -0.5, 0.1, np.nan], [0.1, 0.1, 0.1, 0.1])
    assert s["n"] == 3 and s["pct_outperform"] == pytest.approx(1 / 3) and s["worst"] == -0.5
    assert M.max_drawdown([100, 120, 60, 90, 130]) == pytest.approx(-0.5)
    ret = np.r_[np.full(95, -0.05), np.full(5, 4.0)]
    w = M.winner_dependence(ret, np.zeros(100))
    assert w["mean_excess"] > 0 > w["mean_excess_drop_top5pct"]       # the edge is five trades
    assert w["share_of_total_excess_from_top5pct"] > 1


def test_newey_west_recovers_alpha_and_beta():
    rng = np.random.default_rng(2)
    m = rng.normal(0.01, 0.04, 240)
    y = 0.004 + 1.3 * m + rng.normal(0, 0.01, 240)
    r = M.newey_west_alpha(y, m)
    assert r["beta"] == pytest.approx(1.3, abs=0.05) and r["alpha_monthly"] == pytest.approx(0.004, abs=0.002)
    assert r["alpha_t"] > 3
