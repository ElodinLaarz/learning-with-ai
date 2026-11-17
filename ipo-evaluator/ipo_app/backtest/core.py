"""Backtest core: point-in-time decision reconstruction, executable entries, outcomes.

Timeline of what is known when (the only inputs a decision may use):

  mode A_offer        decision: evening before first trade.  Known: deal terms, SIC, market state at
                      the prior close.  Entry: offer price (hypothetical allocation).
  mode A_retail       decision: after the first-day close.   Known: + first-day close.
                      Entry: OPEN of the 2nd trading day (or later, see `entry_lag`).
  mode B_post_report  decision: after the close on the filing date of the first 10-Q/10-K.
                      Known: + facts carried by that filing's accession number, close that day.
                      Entry: OPEN of the next trading day.

WAIT means "watchlist": the IPO is re-evaluated at each later close for `wait_days` trading days with
the new price (fundamentals and market state stay as of the decision) and bought at the next open
once the rule says BUY.  AVOID / ABSTAIN / INELIGIBLE are final.  Under offer access there is no
waiting: an allocation is taken or declined once.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path

import numpy as np
import pandas as pd

from ..engine.calc import IPOInput
from ..engine import recommend as R

ROOT = Path(__file__).resolve().parents[2]
PROC = ROOT / "data" / "processed"
SNAP = ROOT / "data" / "snapshot"

HORIZONS = {"1m": 21, "3m": 63, "6m": 126, "12m": 252}     # trading days after entry
PERIODS = {"dev": ("2012-01-01", "2016-12-31"), "val": ("2017-01-01", "2018-12-31"),
           "embargo": ("2019-01-01", "2019-12-31"), "test": ("2020-01-01", "2099-12-31")}
TEST_START = PERIODS["test"][0]
MODES = ("A_offer", "A_retail", "B_post_report")


@dataclass
class Config:
    cost_bps_stock: float = 25.0        # per side: half-spread + slippage on a newly listed stock
    cost_bps_etf: float = 2.0           # per side on benchmark ETFs
    commission: float = 0.0             # per trade, USD (portfolio simulation)
    wait_days: int = 60                 # watchlist window for WAIT (trading days)
    entry_lag: int = 1                  # A_retail: bars after the first trading day (1 = 2nd-day open)
    entry_at: str = "open"              # "open" | "close" of the entry bar
    delist_haircut: dict = field(default_factory=lambda: {
        "bankruptcy": 1.00, "acquired": 0.00, "delisted_other": 0.30, "active": 0.30})
    use_diluted: bool = True            # stage B: add reported anti-dilutive securities to the share count
    hold_days: int = 252                # portfolio simulation holding period
    position_frac: float = 0.05         # of current equity per new position
    max_positions: int = 20
    start_capital: float = 100_000.0

    def to_dict(self):
        return asdict(self)


class Bars:
    """Daily bars of one IPO. `adj` is the total-return (split+dividend adjusted) close;
    `close_raw`/`open_raw` are as-traded prices comparable with the offer price."""
    __slots__ = ("d", "open_raw", "close_raw", "adj", "open_adj")

    def __init__(self, g: pd.DataFrame):
        self.d = g["date"].values.astype("datetime64[D]")
        close = g["close"].values.astype(float)
        op = g["open"].values.astype(float)
        op = np.where(np.isfinite(op) & (op > 0), op, close)
        fac = g["split_factor"].values.astype(float)
        self.adj = g["adjclose"].values.astype(float)
        self.close_raw = close * fac
        self.open_raw = op * fac
        self.open_adj = op * self.adj / close


class SealError(RuntimeError):
    """Raised when code asks for a test-period outcome before the rules were frozen and unsealed."""


class Data:
    unsealed = False     # set True only by `run.py test` after the freeze ledger checks pass

    def __init__(self, proc: Path = PROC, snap: Path = SNAP):
        allrows = pd.read_csv(proc / "universe.csv", dtype={"cik": str, "deal_id": str})
        self.all = allrows
        self.uni = allrows[allrows["eligible"]].set_index("deal_id", drop=False)
        rep = pd.read_csv(proc / "first_report.csv", dtype={"deal_id": str})
        self.rep = rep.set_index("deal_id") if len(rep) else rep
        px = pd.read_csv(snap / "prices.csv.gz", parse_dates=["date"], dtype={"deal_id": str})
        self.px = {k: Bars(g) for k, g in px.groupby("deal_id", sort=False)}
        b = pd.read_csv(snap / "bench.csv.gz", parse_dates=["date"])
        self.bench = {}
        for s, g in b.groupby("symbol"):
            g = g.sort_values("date")
            close = g["close"].values.astype(float)
            op = np.where(np.isfinite(g["open"].values.astype(float)), g["open"].values.astype(float), close)
            self.bench[s] = {"d": g["date"].values.astype("datetime64[D]"), "adj": g["adjclose"].values.astype(float),
                             "open_adj": op * g["adjclose"].values.astype(float) / close, "close": close}
        self.cal = self.bench["SPY"]["d"]
        self.snapshot = self.cal[-1]
        # IPO "heat": pricing dates of every deal that passed the calendar-only prefilter
        pre = allrows[~allrows["exclusion"].isin(["no_price", "no_date", "before_universe_start",
                                                  "non_major_exchange", "offer_price_below_5",
                                                  "spac_name_and_10usd_unit", "unit_offering_10usd"])]
        self.priced_sorted = np.sort(pd.to_datetime(pre["priced_date"]).values.astype("datetime64[D]"))
        self.provenance = {}
        pp = proc / "provenance.json"
        if pp.exists():
            import json
            self.provenance = json.loads(pp.read_text())

    # ---------------------------------------------------------------- market state (as of a close)
    def _bench_at(self, sym, day, field="adj"):
        b = self.bench[sym]
        i = np.searchsorted(b["d"], day, side="right") - 1
        return (b[field][i], i) if i >= 0 else (None, -1)

    def market_state(self, asof) -> dict:
        asof = np.datetime64(asof, "D")
        vix, _ = self._bench_at("^VIX", asof, "close")
        spy, i = self._bench_at("SPY", asof)
        ret6 = float(spy / self.bench["SPY"]["adj"][i - 126] - 1.0) if i >= 126 else None
        lo = np.searchsorted(self.priced_sorted, asof - np.timedelta64(90, "D"), side="right")
        hi = np.searchsorted(self.priced_sorted, asof, side="right")
        return {"vix": None if vix is None else float(vix), "spy_ret_6m": ret6, "ipo_count_90d": float(hi - lo)}

    def usable_bars(self, deal_id: str):
        """Bars, unless the first-day close is implausible against the offer price (below 0.2x or
        above 30x), which signals a split-scale error in the vendor data rather than a real move."""
        bars = self.px.get(deal_id)
        if bars is None:
            return None
        op = self.uni.loc[deal_id, "offer_price"]
        if op and op > 0 and not (0.2 <= bars.close_raw[0] / float(op) <= 30.0):
            return None
        return bars

    # ---------------------------------------------------------------- decision reconstruction
    def base_input(self, deal_id: str, access: str, stage: str) -> IPOInput:
        u = self.uni.loc[deal_id]

        def g(k):
            v = u.get(k)
            return None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)

        return IPOInput(name=str(u["name"]), ticker=str(u["symbol"]), exchange=str(u["exchange"]),
                        sic=None if pd.isna(u.get("sic")) else int(u["sic"]), priced_date=u["priced_date"],
                        stage=stage, access=access, offer_price=g("offer_price"), shares_offered=g("shares_offered"),
                        secondary_shares=g("secondary_shares"), shares_outstanding_post=g("shares_outstanding_post"),
                        offering_expenses=g("offering_expenses"), lockup_days=g("lockup_days"), employees=g("employees"))

    def reconstruct(self, deal_id: str, mode: str, cfg: Config):
        """Returns (IPOInput, ctx) for the initial decision of `mode`, or (None, reason).
        ctx: decision_bar (index of the bar whose close is known; -1 for the offer), asof date."""
        u = self.uni.loc[deal_id]
        bars = self.usable_bars(deal_id)
        if mode == "A_offer":
            inp = self.base_input(deal_id, "offer", "at_ipo")
            if bars is not None:
                ci = np.searchsorted(self.cal, bars.d[0])           # first trade date in the calendar
                asof = self.cal[max(ci - 1, 0)]
            else:                                                    # no price history: last close before pricing
                asof = np.datetime64(u["priced_date"], "D") - np.timedelta64(1, "D")
            inp.price = inp.offer_price
            for k, v in self.market_state(asof).items():
                setattr(inp, k, v)
            return inp, {"decision_bar": -1, "asof": str(asof)}
        if bars is None:
            return None, "no_price_history"
        if mode == "A_retail":
            inp = self.base_input(deal_id, "retail", "at_ipo")
            k = cfg.entry_lag - 1                                    # bar whose close is the last known price
            if k >= len(bars.d):
                return None, "no_bar_at_decision"
            inp.price = float(bars.close_raw[k])
            for kk, v in self.market_state(bars.d[k]).items():
                setattr(inp, kk, v)
            return inp, {"decision_bar": k, "asof": str(bars.d[k])}
        if mode == "B_post_report":
            if not len(self.rep) or deal_id not in self.rep.index:
                return None, "no_periodic_report_found"
            r = self.rep.loc[deal_id]
            filed = np.datetime64(r["report_filed"], "D")
            k = int(np.searchsorted(bars.d, filed, side="right") - 1)   # last bar on/before the filing date
            if k < 0:
                return None, "report_before_first_trade"
            if filed - bars.d[k] > np.timedelta64(7, "D"):
                return None, "not_trading_at_report_date"
            inp = self.base_input(deal_id, "retail", "post_report")

            def g(c):
                v = r.get(c)
                return None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)

            for f in ("revenue", "revenue_prior", "net_income", "operating_cash_flow", "cash", "debt",
                      "total_assets", "total_liabilities", "equity", "intangibles"):
                setattr(inp, f, g(f))
            pe = r.get("report_period_end")
            if isinstance(pe, str):
                inp.financials_age_days = float((filed - np.datetime64(pe, "D")).astype(int))
                inp.balance_includes_proceeds = bool(
                    np.datetime64(pe, "D") > np.datetime64(u["priced_date"], "D") + np.timedelta64(5, "D"))
            cover = g("cover_shares")
            if cover and (inp.shares_outstanding_post is None or cover > inp.shares_outstanding_post):
                inp.shares_outstanding_post = cover      # cover-page count is newer; never lower than the deal record
                if inp.shares_offered and inp.shares_offered > cover:
                    inp.shares_offered = None
            if cfg.use_diluted:
                inp.dilutive_securities_count = g("antidilutive_securities")
            inp.price = float(bars.close_raw[k])
            for kk, v in self.market_state(bars.d[k]).items():
                setattr(inp, kk, v)
            return inp, {"decision_bar": k, "asof": str(bars.d[k]), "report_filed": str(filed)}
        raise ValueError(mode)

    # ---------------------------------------------------------------- execution
    def entry_point(self, deal_id: str, mode: str, decision_bar: int, cfg: Config):
        """Executable entry strictly after the decision. Returns (bar index, adjusted entry price,
        entry cost fraction) or None."""
        bars = self.usable_bars(deal_id)
        if bars is None:
            return None
        if mode == "A_offer":
            op = float(self.uni.loc[deal_id, "offer_price"])
            # offer price expressed in the adjusted-price scale of the first trading day
            return 0, op * bars.adj[0] / bars.close_raw[0], 0.0
        i = decision_bar + 1
        if i >= len(bars.d):
            return None
        px = bars.open_adj[i] if cfg.entry_at == "open" else bars.adj[i]
        return i, float(px), cfg.cost_bps_stock / 1e4

    def outcome(self, deal_id: str, entry_bar: int, entry_px_adj: float, cost_in: float, cfg: Config,
                horizons=HORIZONS) -> dict:
        """Net returns at fixed horizons after the entry date, with benchmark returns over the same dates.
        status: complete | delisted (exit at last price less a haircut, then cash) | incomplete."""
        bars = self.px[deal_id]
        u = self.uni.loc[deal_id]
        if not self.unsealed and str(u["priced_date"]) >= TEST_START:
            raise SealError(f"outcome requested for test-period IPO {deal_id} while the test period is sealed")
        sector_etf = R.SECTOR_ETF[R.sector_of(u.get("sic"))]
        entry_day = bars.d[entry_bar]
        ci = int(np.searchsorted(self.cal, entry_day))
        cs, ce = cfg.cost_bps_stock / 1e4, cfg.cost_bps_etf / 1e4
        # true last quote date (the stored series is truncated to ~3 years, so use the universe record)
        lb = u.get("last_bar")
        last_bar = np.datetime64(lb, "D") if isinstance(lb, str) else bars.d[-1]
        stopped = (self.snapshot - last_bar) > np.timedelta64(10, "D")       # no quotes for 10+ days: delisted
        truncated = last_bar > bars.d[-1]
        out = {"entry_date": str(entry_day), "sector_etf": sector_etf}
        for name, h in horizons.items():
            if ci + h >= len(self.cal):
                out[f"status_{name}"] = "incomplete"
                continue
            exit_day = self.cal[ci + h]
            j = int(np.searchsorted(bars.d, exit_day, side="right") - 1)
            if bars.d[j] < exit_day and j == len(bars.d) - 1 and truncated:
                out[f"status_{name}"] = "incomplete"          # beyond the stored window (cannot happen for <=12m)
                continue
            if bars.d[j] < exit_day and j == len(bars.d) - 1 and stopped:
                reason = str(u.get("sec_outcome") or "active")
                hc = cfg.delist_haircut.get(reason, cfg.delist_haircut["active"])
                gross = bars.adj[j] * (1.0 - hc) / entry_px_adj
                out[f"status_{name}"] = "delisted"
                out[f"ret_{name}"] = gross / (1.0 + cost_in) - 1.0
            elif bars.d[j] < exit_day and j == len(bars.d) - 1 and not stopped:
                out[f"status_{name}"] = "incomplete"
                continue
            else:
                out[f"status_{name}"] = "complete"
                out[f"ret_{name}"] = bars.adj[j] * (1.0 - cs) / (entry_px_adj * (1.0 + cost_in)) - 1.0
            out[f"exit_date_{name}"] = str(exit_day)
            for sym, label in (("SPY", "spy"), ("IWM", "iwm"), ("IPO", "ipoetf"), (sector_etf, "sector")):
                b = self.bench[sym]
                a = int(np.searchsorted(b["d"], entry_day))
                e = int(np.searchsorted(b["d"], exit_day, side="right") - 1)
                if a >= len(b["d"]) or b["d"][a] != entry_day or e <= a:
                    out[f"{label}_{name}"] = np.nan
                    continue
                # benchmark bought at the open of the entry day (for an offer-price allocation this
                # is the morning the allocated shares start trading)
                p0 = b["open_adj"][a]
                out[f"{label}_{name}"] = b["adj"][e] * (1.0 - ce) / (p0 * (1.0 + ce)) - 1.0
        return out


# -------------------------------------------------------------------------------- decisions
def decide(data: Data, deal_id: str, mode: str, rules: dict, cfg: Config) -> dict:
    """Initial decision plus the watchlist logic. No outcome is computed here."""
    rec = {"deal_id": deal_id, "mode": mode, "action": "NO_TRADE", "wait_bars": 0}
    inp, ctx = data.reconstruct(deal_id, mode, cfg)
    if inp is None:
        rec.update({"recommendation": "NO_DECISION", "no_decision_reason": ctx})
        return rec
    ev = R.evaluate(inp, rules, explain=False)
    rec.update({"recommendation": ev["recommendation"], "probability": ev["probability"],
                "asof": ctx["asof"], "decision_price": inp.price,
                "gates": "|".join(g["id"] for g in ev["gates"] if g["triggered"]),
                "decision_bar": ctx["decision_bar"]})
    rec["_input"] = inp
    if ev["recommendation"] == R.BUY:
        if data.usable_bars(deal_id) is None:
            rec["action"] = "BUY_NO_PRICE_DATA"
        else:
            rec["action"] = "BUY"
            rec["entry_decision_bar"] = ctx["decision_bar"]
    elif ev["recommendation"] == R.WAIT and mode != "A_offer":
        bars = data.px[deal_id]
        k0 = ctx["decision_bar"]
        for k in range(k0 + 1, min(k0 + 1 + cfg.wait_days, len(bars.d) - 1)):
            if R.evaluate(inp, rules, price=float(bars.close_raw[k]), explain=False)["recommendation"] == R.BUY:
                rec.update({"action": "BUY", "entry_decision_bar": k, "wait_bars": k - k0})
                break
    return rec


def baseline_flags(data: Data, deal_id: str, mode: str, inp: IPOInput | None) -> dict:
    """Prespecified simple screens (never tuned):
       stage A: offering of at least $100M.   stage B: annualised revenue >= $100M and positive net income."""
    if inp is None:
        return {"screen": False}
    if mode == "B_post_report":
        return {"screen": bool(inp.revenue is not None and inp.revenue >= 100e6
                               and inp.net_income is not None and inp.net_income > 0)}
    ds = (inp.offer_price or 0) * (inp.shares_offered or 0)
    return {"screen": bool(ds >= 100e6)}


def period_of(priced_date: str) -> str:
    for name, (a, b) in PERIODS.items():
        if a <= priced_date <= b:
            return name
    return "pre"
