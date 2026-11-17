"""Deterministic IPO calculations. Pure functions; every result is None when an input it
needs is missing, so missing data propagates explicitly instead of becoming a silent zero."""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import Optional

Num = Optional[float]


@dataclass
class DilutiveSecurity:
    """Options / warrants (strike > 0, treasury-stock method) or RSUs / convertibles (strike 0)."""
    count: float
    strike: float = 0.0
    kind: str = "option"


@dataclass
class IPOInput:
    # identity
    name: str = ""
    ticker: str = ""
    exchange: str = ""
    sic: Optional[int] = None
    priced_date: Optional[str] = None
    stage: str = "at_ipo"                 # "at_ipo" | "post_report"
    access: str = "retail"                # "retail" | "offer"  (offer = allocation at the offer price)
    instrument: str = "common"            # "common" | "unit" | "spac" | "fund"
    # deal terms
    offer_price: Num = None
    shares_offered: Num = None            # primary + secondary shares sold in the base deal
    secondary_shares: Num = None          # sold by existing holders (no proceeds to the company)
    shares_outstanding_post: Num = None   # basic shares after the offering
    overallotment_shares: Num = None
    overallotment_exercised: bool = False
    underwriting_discount: Num = None     # fraction of gross proceeds
    offering_expenses: Num = None
    lockup_days: Num = None
    employees: Num = None
    dilutive: list = field(default_factory=list)   # list[DilutiveSecurity]
    dilutive_securities_count: Num = None          # count-only fallback (as-if strike 0)
    # financial statements (point-in-time, annualised flows)
    revenue: Num = None
    revenue_prior: Num = None
    net_income: Num = None
    operating_cash_flow: Num = None
    cash: Num = None
    debt: Num = None
    total_assets: Num = None
    total_liabilities: Num = None
    equity: Num = None
    intangibles: Num = None
    going_concern: Optional[bool] = None
    financials_age_days: Num = None
    balance_includes_proceeds: bool = False
    # market state
    vix: Num = None
    spy_ret_6m: Num = None
    ipo_count_90d: Num = None
    # price at which the decision is evaluated
    price: Num = None

    def to_dict(self):
        return asdict(self)


def _pos(x: Num) -> bool:
    return x is not None and isinstance(x, (int, float)) and math.isfinite(x) and x > 0


def _num(x: Num) -> bool:
    return x is not None and isinstance(x, (int, float)) and math.isfinite(x)


def treasury_method_shares(securities, price: Num) -> Num:
    """Net new shares from dilutive securities at `price` (treasury-stock method).
    In-the-money options add count * (1 - strike/price); out-of-the-money add 0; strike-0
    instruments (RSUs, as-converted preferred) add their full count."""
    if not _pos(price):
        return None
    total = 0.0
    for s in securities or []:
        if isinstance(s, dict):
            s = DilutiveSecurity(**s)
        if not _num(s.count) or s.count < 0 or not _num(s.strike) or s.strike < 0:
            raise ValueError("dilutive security needs non-negative count and strike")
        if s.strike >= price:
            continue
        total += s.count * (1.0 - s.strike / price)
    return total


def fully_diluted_shares(inp: IPOInput, price: Num) -> Num:
    """Basic post-offering shares + exercised over-allotment + treasury-method dilution.
    Dilution therefore *depends on price*: a higher price puts more options in the money."""
    if not _pos(inp.shares_outstanding_post):
        return None
    shares = float(inp.shares_outstanding_post)
    if inp.overallotment_exercised and _pos(inp.overallotment_shares):
        shares += inp.overallotment_shares
    if inp.dilutive:
        extra = treasury_method_shares(inp.dilutive, price)
        if extra is None:
            return None
        shares += extra
    elif _pos(inp.dilutive_securities_count):
        shares += inp.dilutive_securities_count
    return shares


def primary_shares(inp: IPOInput) -> Num:
    if not _pos(inp.shares_offered):
        return None
    sec = inp.secondary_shares if _num(inp.secondary_shares) else 0.0
    if sec < 0 or sec > inp.shares_offered:
        raise ValueError("secondary_shares must be between 0 and shares_offered")
    prim = inp.shares_offered - sec
    if inp.overallotment_exercised and _pos(inp.overallotment_shares):
        prim += inp.overallotment_shares   # convention: greenshoe is primary
    return prim


def net_primary_proceeds(inp: IPOInput, default_discount: float = 0.07) -> Num:
    """Cash to the company: primary shares * offer * (1 - discount) - expenses."""
    prim = primary_shares(inp)
    if prim is None or not _pos(inp.offer_price):
        return None
    disc = inp.underwriting_discount if _num(inp.underwriting_discount) else default_discount
    if not 0 <= disc < 1:
        raise ValueError("underwriting_discount must be a fraction in [0, 1)")
    exp = inp.offering_expenses if _num(inp.offering_expenses) else 0.0
    return prim * inp.offer_price * (1.0 - disc) - exp


def compute_metrics(inp: IPOInput, price: Num = None, default_discount: float = 0.07) -> dict:
    """All derived quantities at `price` (defaults to inp.price)."""
    p = price if price is not None else inp.price
    m: dict = {"price": p if _pos(p) else None}
    op, so, sh = inp.offer_price, inp.shares_outstanding_post, inp.shares_offered

    m["deal_size"] = sh * op if _pos(sh) and _pos(op) else None
    m["market_cap_offer"] = so * op if _pos(so) and _pos(op) else None
    m["float_pct"] = sh / so if _pos(sh) and _pos(so) else None
    m["market_cap_basic"] = so * p if _pos(so) and _pos(p) else None
    fd = fully_diluted_shares(inp, p)
    m["fully_diluted_shares"] = fd
    m["market_cap_diluted"] = fd * p if fd is not None and _pos(p) else None
    m["dilution_overhang_pct"] = (fd / so - 1.0) if fd is not None and _pos(so) else None
    m["return_vs_offer"] = (p / op - 1.0) if _pos(p) and _pos(op) else None
    m["expense_ratio"] = (inp.offering_expenses / m["deal_size"]
                          if _num(inp.offering_expenses) and _pos(m["deal_size"]) else None)

    proceeds = net_primary_proceeds(inp, default_discount)
    m["net_primary_proceeds"] = proceeds
    add = 0.0 if inp.balance_includes_proceeds else proceeds   # None if unknown and needed
    m["pro_forma_cash"] = (inp.cash + add) if _num(inp.cash) and add is not None else None
    m["pro_forma_equity"] = (inp.equity + add) if _num(inp.equity) and add is not None else None

    debt = inp.debt if _num(inp.debt) else None
    if m["market_cap_diluted"] is not None and m["pro_forma_cash"] is not None:
        m["enterprise_value"] = m["market_cap_diluted"] + (debt or 0.0) - m["pro_forma_cash"]
    else:
        m["enterprise_value"] = None
    rev = inp.revenue if _num(inp.revenue) else None
    m["ev_sales"] = (m["enterprise_value"] / rev) if m["enterprise_value"] is not None and _pos(rev) else None
    m["price_sales"] = (m["market_cap_diluted"] / rev) if m["market_cap_diluted"] is not None and _pos(rev) else None
    m["revenue_growth"] = ((rev / inp.revenue_prior - 1.0)
                           if _pos(rev) and _pos(inp.revenue_prior) else None)
    m["net_margin"] = (inp.net_income / rev) if _num(inp.net_income) and _pos(rev) else None
    m["profitable"] = (inp.net_income > 0) if _num(inp.net_income) else None
    m["ocf_positive"] = (inp.operating_cash_flow > 0) if _num(inp.operating_cash_flow) else None

    # cash runway in months at the current annualised operating burn (None if not burning or unknown)
    if _num(inp.operating_cash_flow) and m["pro_forma_cash"] is not None:
        if inp.operating_cash_flow < 0:
            m["runway_months"] = max(m["pro_forma_cash"], 0.0) / (-inp.operating_cash_flow) * 12.0
        else:
            m["runway_months"] = math.inf
    else:
        m["runway_months"] = None

    # dilution borne by new investors: (price paid - pro-forma net tangible book value per share) / price
    if m["pro_forma_equity"] is not None and _pos(so) and _pos(op):
        ntbv = m["pro_forma_equity"] - (inp.intangibles if _num(inp.intangibles) else 0.0)
        m["ntbv_per_share_post"] = ntbv / so
        m["dilution_to_new_investors_pct"] = (op - ntbv / so) / op
    else:
        m["ntbv_per_share_post"] = None
        m["dilution_to_new_investors_pct"] = None
    m["book_to_market"] = (m["pro_forma_equity"] / m["market_cap_basic"]
                           if m["pro_forma_equity"] is not None and _pos(m["market_cap_basic"]) else None)
    return m
