"""Turn the raw cache into the processed, point-in-time dataset.

Outputs
  data/processed/universe.csv            every priced deal + eligibility / exclusion reason   (committed)
  data/processed/first_report.csv        fundamentals exactly as reported in the first 10-Q/10-K
                                         after the IPO, keyed by accession number            (committed)
  data/processed/coverage.json           coverage and exclusion counts                        (committed)
  data/processed/provenance.json         sources, fetch window, file hashes                   (committed)
  data/snapshot/prices.csv.gz            daily bars for eligible IPOs (vendor data, NOT committed)
  data/snapshot/bench.csv.gz             benchmark / market-state series (NOT committed)

This module never computes a forward return.
"""
from __future__ import annotations

import collections
import gzip
import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import fetch as F

ROOT = Path(__file__).resolve().parents[2]
PROC = ROOT / "data" / "processed"
SNAP = ROOT / "data" / "snapshot"

PERIODIC = {"10-Q", "10-K", "10-KT", "10-QT"}
FPI_FORMS = {"F-1", "F-1/A", "20-F", "40-F", "6-K", "F-6", "20FR12B", "F-1MEF"}
FUND_FORMS = {"N-2", "N-2/A", "N-CSR", "N-Q", "497", "N-PORT", "NPORT-P"}
MERGER_FORMS = {"DEFM14A", "DEFM14C", "PREM14A", "SC TO-T", "SC 14D9", "SC 13E3", "SC TO-T/A", "SC 14D9/A", "SC 13E3/A"}
DEREG_FORMS = {"25", "25-NSE", "15-12B", "15-12G", "15-15D"}
MAX_BARS = 760          # ~3 years of trading days kept per IPO


def _f(x):
    try:
        return float(re.sub(r"[\s$,]|&#8203;", "", str(x)))
    except (TypeError, ValueError):
        return None


def _all_filings(sub: dict) -> pd.DataFrame:
    parts = [sub.get("filings", {}).get("recent") or {}] + list(sub.get("_older_pages") or [])
    frames = []
    for p in parts:
        if p and p.get("form"):
            frames.append(pd.DataFrame({k: p.get(k) for k in ("form", "filingDate", "reportDate", "items",
                                                             "accessionNumber", "acceptanceDateTime")}))
    if not frames:
        return pd.DataFrame(columns=["form", "filingDate", "reportDate", "items", "accessionNumber",
                                     "acceptanceDateTime"])
    return pd.concat(frames, ignore_index=True).sort_values("filingDate").reset_index(drop=True)


def classify_outcome(fil: pd.DataFrame, priced: str, snapshot: str | None = None) -> dict:
    """Corporate fate as visible in SEC filings at the snapshot (used only for delisting treatment
    and to describe IPOs whose price history is unavailable; never as a decision input).

      bankruptcy      an 8-K with item 1.03 (bankruptcy or receivership) after the IPO
      active          a 10-K/10-Q (or, for a recent IPO, any filing) within ~18 months of the snapshot.
                      Form 25/15 filings alone do not end "active": companies file them when they
                      retire a class of notes or warrants or move between exchanges.
      acquired        no longer reporting, and merger/tender documents within 400 days of the
                      deregistration (or of the last filing)
      delisted_other  no longer reporting for any other reason
    """
    snapshot = snapshot or date.today().isoformat()
    post = fil[fil["filingDate"] > priced]
    items = post["items"].fillna("")
    bk = post[(post["form"].isin(["8-K", "8-K/A"])) & items.str.contains(r"\b1\.03\b")]
    dereg = post[post["form"].isin(DEREG_FORMS)]
    merger = post[post["form"].isin(MERGER_FORMS) | ((post["form"] == "8-K") & items.str.contains(r"\b5\.01\b"))]
    periodic = post[post["form"].isin(PERIODIC)]
    out = {"bankruptcy_date": bk["filingDate"].min() if len(bk) else None,
           "dereg_date": dereg["filingDate"].max() if len(dereg) else None,
           "merger_doc_date": merger["filingDate"].max() if len(merger) else None,
           "last_periodic_date": periodic["filingDate"].max() if len(periodic) else None,
           "last_filing_date": fil["filingDate"].max() if len(fil) else None}
    cut = (pd.Timestamp(snapshot) - pd.Timedelta(days=550)).date().isoformat()
    reporting = (out["last_periodic_date"] or "") >= cut or (not len(periodic) and (out["last_filing_date"] or "") >= cut)
    end = out["dereg_date"] or out["last_filing_date"]
    if out["bankruptcy_date"]:
        out["sec_outcome"] = "bankruptcy"
    elif reporting:
        out["sec_outcome"] = "active"
    elif out["merger_doc_date"] and end and abs((pd.Timestamp(end) - pd.Timestamp(out["merger_doc_date"])).days) <= 400:
        out["sec_outcome"] = "acquired"
    else:
        out["sec_outcome"] = "delisted_other"
    return out


# --------------------------------------------------------------------------- prices
def parse_yahoo(raw: dict, priced: str):
    """Pick the attempt whose history starts at the IPO. Returns (df, meta) or (None, reason)."""
    pd_priced = pd.Timestamp(priced)
    reason = "no_yahoo_history"
    for a in raw.get("attempts", []):
        ch = a.get("chart")
        if not ch or not ch.get("timestamp"):
            continue
        q = ch["indicators"]["quote"][0]
        adj = (ch["indicators"].get("adjclose") or [{}])[0].get("adjclose")
        df = pd.DataFrame({"date": pd.to_datetime(ch["timestamp"], unit="s").normalize(),
                           "open": q.get("open"), "high": q.get("high"), "low": q.get("low"),
                           "close": q.get("close"), "volume": q.get("volume"),
                           "adjclose": adj if adj else q.get("close")})
        df = df.dropna(subset=["close"]).drop_duplicates("date").sort_values("date").reset_index(drop=True)
        df = df[df["close"] > 0]
        if df.empty:
            continue
        first_trade = ch.get("meta", {}).get("firstTradeDate")
        first_hist = pd.to_datetime(first_trade, unit="s").normalize() if first_trade else df["date"].iloc[0]
        first_bar = min(first_hist, df["date"].iloc[0])
        if first_bar < pd_priced - pd.Timedelta(days=5):
            reason = "prior_trading_history"      # already traded before this deal: uplisting / reused symbol
            continue
        if df["date"].iloc[0] > pd_priced + pd.Timedelta(days=10):
            reason = "yahoo_history_starts_late"  # symbol now belongs to a different listing
            continue
        splits = []
        for s in ((ch.get("events") or {}).get("splits") or {}).values():
            if s.get("numerator") and s.get("denominator"):
                splits.append((pd.to_datetime(s["date"], unit="s").normalize(), s["numerator"] / s["denominator"]))
        # factor that converts split-adjusted quotes back to as-traded prices on each date
        fac = np.ones(len(df))
        for d, ratio in splits:
            fac[df["date"].values < np.datetime64(d)] *= ratio
        df["split_factor"] = fac
        df["open"] = df["open"].fillna(df["close"])
        meta = {"yahoo_symbol": a["symbol"], "first_bar": df["date"].iloc[0].date().isoformat(),
                "last_bar": df["date"].iloc[-1].date().isoformat(), "n_bars": int(len(df)),
                "n_splits": len(splits)}
        return df.iloc[:MAX_BARS].copy(), meta
    return None, reason


# --------------------------------------------------------------------------- fundamentals
def _facts_for_accession(facts: dict, accn: str):
    out = collections.defaultdict(list)
    for key, units in (facts.get("facts") or {}).items():
        for unit, arr in units.items():
            for start, end, val, a, form, filed, fy, fp in arr:
                if a == accn and val is not None:
                    out[key].append((start, end, float(val), unit))
    return out


def _days(a, b):
    return (pd.Timestamp(b) - pd.Timestamp(a)).days


def _flow(byacc, tags, period_end, want_days):
    """Flow value ending at period_end with duration closest to want_days, annualised.
    Returns (annualised value, duration days, tag) or (None, None, None)."""
    for tag in tags:
        cands = [(s, e, v) for s, e, v, u in byacc.get(tag, []) if s and e == period_end and u == "USD"]
        if not cands:
            continue
        s, e, v = min(cands, key=lambda c: abs(_days(c[0], c[1]) - want_days))
        d = max(_days(s, e) + 1, 1)
        return v * 365.0 / d, d, tag
    return None, None, None


def _flow_prior(byacc, tag, period_end, dur):
    """Same-length period ending one year earlier (the comparative column of the same filing)."""
    best = None
    for s, e, v, u in byacc.get(tag, []):
        if not s or u != "USD":
            continue
        gap = _days(e, period_end)
        if 350 <= gap <= 380 and abs(_days(s, e) + 1 - dur) <= 12:
            best = v * 365.0 / max(_days(s, e) + 1, 1)
    return best


def _instant(byacc, tags, period_end, unit="USD"):
    for tag in tags:
        vals = [v for s, e, v, u in byacc.get(tag, []) if not s and e == period_end and u == unit]
        if vals:
            return vals[-1]
    return None


REV_TAGS = ["us-gaap:Revenues", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
            "us-gaap:RevenueFromContractWithCustomerIncludingAssessedTax", "us-gaap:SalesRevenueNet",
            "us-gaap:RevenuesNetOfInterestExpense", "us-gaap:SalesRevenueGoodsNet",
            "us-gaap:SalesRevenueServicesNet", "us-gaap:RealEstateRevenueNet", "us-gaap:OilAndGasRevenue",
            "us-gaap:InterestAndDividendIncomeOperating"]


def first_report(fil: pd.DataFrame, facts: dict | None, priced: str) -> dict | None:
    """Fundamentals from the first 10-Q/10-K filed strictly after the pricing date, restricted to
    the facts carried by THAT accession number (so later restatements cannot leak in)."""
    rep = fil[(fil["form"].isin(PERIODIC)) & (fil["filingDate"] > priced)]
    if rep.empty:
        return None
    r = rep.iloc[0]
    out = {"report_form": r["form"], "report_filed": r["filingDate"], "report_accession": r["accessionNumber"],
           "report_accepted": r.get("acceptanceDateTime"), "report_period_end": r["reportDate"] or None}
    if not facts:
        out["xbrl_available"] = False
        return out
    byacc = _facts_for_accession(facts, r["accessionNumber"])
    out["xbrl_available"] = bool(byacc)
    if not byacc:
        return out
    pe = out["report_period_end"]
    if not pe:   # fall back to the latest balance-sheet date in the filing
        ends = [e for k in ("us-gaap:Assets",) for s, e, v, u in byacc.get(k, []) if not s]
        pe = max(ends) if ends else None
        out["report_period_end"] = pe
    if not pe:
        return out
    want = 365 if r["form"].startswith("10-K") else 91
    rev, dur, tag = _flow(byacc, REV_TAGS, pe, want)
    out["revenue"] = rev
    out["revenue_tag"] = tag
    out["revenue_period_days"] = dur
    out["revenue_prior"] = _flow_prior(byacc, tag, pe, dur) if tag else None
    out["net_income"] = _flow(byacc, ["us-gaap:NetIncomeLoss", "us-gaap:ProfitLoss"], pe, want)[0]
    out["operating_cash_flow"] = _flow(byacc, ["us-gaap:NetCashProvidedByUsedInOperatingActivities"], pe, 365)[0]
    out["total_assets"] = _instant(byacc, ["us-gaap:Assets"], pe)
    out["total_liabilities"] = _instant(byacc, ["us-gaap:Liabilities"], pe)
    out["equity"] = _instant(byacc, ["us-gaap:StockholdersEquity",
                                     "us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"], pe)
    cash = _instant(byacc, ["us-gaap:CashAndCashEquivalentsAtCarryingValue",
                            "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"], pe)
    sti = _instant(byacc, ["us-gaap:ShortTermInvestments", "us-gaap:MarketableSecuritiesCurrent",
                           "us-gaap:AvailableForSaleSecuritiesDebtSecuritiesCurrent"], pe)
    out["cash"] = None if cash is None else cash + (sti or 0.0)
    ltd = _instant(byacc, ["us-gaap:LongTermDebt", "us-gaap:LongTermDebtNoncurrent"], pe)
    cur = _instant(byacc, ["us-gaap:DebtCurrent", "us-gaap:LongTermDebtCurrent"], pe)
    out["debt"] = None if ltd is None and cur is None else (ltd or 0.0) + (cur or 0.0)
    gw = _instant(byacc, ["us-gaap:Goodwill"], pe)
    ia = _instant(byacc, ["us-gaap:IntangibleAssetsNetExcludingGoodwill"], pe)
    out["intangibles"] = None if gw is None and ia is None else (gw or 0.0) + (ia or 0.0)
    sh = [v for s, e, v, u in byacc.get("dei:EntityCommonStockSharesOutstanding", []) if u == "shares"]
    out["cover_shares"] = max(sh) if sh else None
    anti = [(e, v) for s, e, v, u in byacc.get(
        "us-gaap:AntidilutiveSecuritiesExcludedFromComputationOfEarningsPerShareAmount", []) if u == "shares" and e == pe]
    out["antidilutive_securities"] = max(v for e, v in anti) if anti else None
    return out


# --------------------------------------------------------------------------- main build
def build():
    PROC.mkdir(parents=True, exist_ok=True)
    SNAP.mkdir(parents=True, exist_ok=True)
    rows = F.load_calendar_rows()
    recs, price_frames, reports = [], [], []
    seen_cik: dict[str, str] = {}
    cal = []
    for r in rows:
        ok, why = F.prelim_eligible(r)
        try:
            priced = datetime.strptime(r["pricedDate"], "%m/%d/%Y").date().isoformat()
        except (KeyError, ValueError):
            priced = None
        cal.append((priced, ok))
    for r, (priced, _) in sorted(zip(rows, cal), key=lambda t: (t[1][0] or "", t[0]["dealID"])):
        ok, why = F.prelim_eligible(r)
        rec = {"deal_id": r["dealID"], "symbol": (r.get("proposedTickerSymbol") or "").upper(),
               "name": r.get("companyName"), "exchange": r.get("proposedExchange"), "priced_date": priced,
               "offer_price": _f(r.get("proposedSharePrice")), "shares_offered": _f(r.get("sharesOffered")),
               "deal_size": _f(r.get("dollarValueOfSharesOffered")), "eligible": False, "exclusion": None}
        if not ok:
            rec["exclusion"] = why
            recs.append(rec)
            continue
        ov = F.load_overview(r["dealID"])
        cik = F._cik_of(ov)
        if ov:
            emp = re.match(r"\s*([\d,]+)", str(ov.get("NumberOfEmployees") or ""))
            rec.update({"cik": cik, "shares_outstanding_post": _f(ov.get("SharesOutstanding")),
                        "offering_expenses": _f(ov.get("TotalExpenseOfTheOffering")),
                        "lockup_days": _f(ov.get("LockupPeriodNumberofDays")),
                        "employees": _f(emp.group(1)) if emp else None,
                        "secondary_shares": _f(ov.get("ShareholderSharesOffered")),
                        "overallotment_shares": _f(ov.get("SharesOverAlloted"))})
        if not cik:
            rec["exclusion"] = "no_cik_in_deal_record"
            recs.append(rec)
            continue
        sub = F.load_submissions(cik)
        if not sub:
            rec["exclusion"] = "no_sec_submissions"
            recs.append(rec)
            continue
        fil = _all_filings(sub)
        try:
            rec["sic"] = int(sub.get("sic")) if sub.get("sic") else None
        except ValueError:
            rec["sic"] = None
        rec["sec_tickers_now"] = "|".join(sub.get("tickers") or [])
        near = fil[(fil["filingDate"] >= (pd.Timestamp(priced) - pd.Timedelta(days=400)).date().isoformat()) &
                   (fil["filingDate"] <= (pd.Timestamp(priced) + pd.Timedelta(days=500)).date().isoformat())]
        forms_near = set(near["form"])
        rec.update(classify_outcome(fil, priced))
        if rec["sic"] == 6770:
            rec["exclusion"] = "spac_sic_6770"
        elif rec["sic"] == 6221 or (forms_near & FUND_FORMS):
            rec["exclusion"] = "fund_or_commodity_pool"
        elif forms_near & FPI_FORMS:
            rec["exclusion"] = "foreign_private_issuer"
        elif cik in seen_cik:
            rec["exclusion"] = "not_first_offering_for_cik"
        if rec["exclusion"]:
            recs.append(rec)
            continue
        seen_cik[cik] = r["dealID"]

        yp = F.RAW / "yahoo" / "ipo" / f"{r['dealID']}.json.gz"
        df, meta = (None, "yahoo_not_fetched")
        if yp.exists():
            df, meta = parse_yahoo(json.loads(gzip.decompress(yp.read_bytes())), priced)
        if df is None and meta == "prior_trading_history":
            rec["exclusion"] = "prior_trading_history"
            recs.append(rec)
            continue
        rec["eligible"] = True
        if df is None:
            rec["price_status"] = meta
        else:
            rec["price_status"] = "ok"
            rec.update(meta)
            df.insert(0, "deal_id", r["dealID"])
            price_frames.append(df)
        facts = F.load_facts(cik)
        # does SEC's XBRL API hold ANY fact that was filed on or before the pricing date?
        rec["pre_ipo_xbrl"] = bool(facts) and any(
            row[5] and row[5] <= priced for units in (facts.get("facts") or {}).values()
            for arr in units.values() for row in arr)
        fr = first_report(fil, facts, priced)
        if fr:
            fr["deal_id"] = r["dealID"]
            reports.append(fr)
            rec["report_filed"] = fr["report_filed"]
        recs.append(rec)

    uni = pd.DataFrame(recs)
    uni.to_csv(PROC / "universe.csv", index=False)
    rep = pd.DataFrame(reports)
    rep.to_csv(PROC / "first_report.csv", index=False)
    prices = pd.concat(price_frames, ignore_index=True) if price_frames else pd.DataFrame()
    prices.to_csv(SNAP / "prices.csv.gz", index=False, float_format="%.6g")

    bframes = []
    for s in F.BENCH_SYMBOLS:
        p = F.RAW / "yahoo" / "bench" / f"{s.replace('^', '_')}.json.gz"
        if not p.exists():
            continue
        ch = json.loads(gzip.decompress(p.read_bytes()))["chart"]["result"][0]
        q = ch["indicators"]["quote"][0]
        adj = (ch["indicators"].get("adjclose") or [{}])[0].get("adjclose") or q["close"]
        b = pd.DataFrame({"symbol": s, "date": pd.to_datetime(ch["timestamp"], unit="s").normalize(),
                          "open": q["open"], "close": q["close"], "adjclose": adj}).dropna(subset=["close"])
        bframes.append(b)
    bench = pd.concat(bframes, ignore_index=True)
    bench.to_csv(SNAP / "bench.csv.gz", index=False, float_format="%.6g")

    el = uni[uni["eligible"]]
    cov = {
        "snapshot_date": date.today().isoformat(),
        "calendar_priced_deals": int(len(uni)),
        "exclusions": uni.loc[~uni["eligible"], "exclusion"].value_counts().to_dict(),
        "eligible": int(len(el)),
        "eligible_by_year": el.groupby(el["priced_date"].str[:4]).size().to_dict(),
        "price_status": el["price_status"].value_counts().to_dict(),
        "price_ok_by_year": el[el["price_status"] == "ok"].groupby(el["priced_date"].str[:4]).size().to_dict(),
        "sec_outcome_all_eligible": el["sec_outcome"].value_counts().to_dict(),
        "sec_outcome_when_price_missing": el.loc[el["price_status"] != "ok", "sec_outcome"].value_counts().to_dict(),
        "sec_outcome_when_price_ok": el.loc[el["price_status"] == "ok", "sec_outcome"].value_counts().to_dict(),
        "first_report_found": int(len(rep)),
        "first_report_with_xbrl": int(rep["xbrl_available"].sum()) if len(rep) else 0,
        "shares_outstanding_missing": int(el["shares_outstanding_post"].isna().sum()),
        "pre_ipo_xbrl_available": int(el["pre_ipo_xbrl"].fillna(False).astype(bool).sum()),
    }
    (PROC / "coverage.json").write_text(json.dumps(cov, indent=1))

    def sha(p):
        return hashlib.sha256(Path(p).read_bytes()).hexdigest()

    prov = {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "client_identification": F.UA,
        "sources": [
            {"name": "Nasdaq IPO calendar", "url": "https://api.nasdaq.com/api/ipo/calendar?date=YYYY-MM",
             "fields": "deal id, symbol, company, exchange, offer price, shares offered, pricing date",
             "months": [min(p.stem for p in (F.RAW / 'nasdaq' / 'calendar').glob('*.json')),
                        max(p.stem for p in (F.RAW / 'nasdaq' / 'calendar').glob('*.json'))]},
            {"name": "Nasdaq IPO deal overview", "url": "https://api.nasdaq.com/api/ipo/overview/?dealId=...",
             "fields": "CIK, shares outstanding after offering, offering expenses, lock-up, employees"},
            {"name": "SEC EDGAR submissions", "url": "https://data.sec.gov/submissions/CIK##########.json",
             "fields": "SIC code, filing index (form, filing date, 8-K items, accession numbers), current tickers"},
            {"name": "SEC EDGAR XBRL company facts", "url": "https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json",
             "fields": "financial-statement facts, selected by the accession number of the first 10-Q/10-K after the IPO"},
            {"name": "Yahoo Finance chart", "url": "https://query1.finance.yahoo.com/v8/finance/chart/SYMBOL",
             "fields": "daily open/high/low/close/adjusted close/volume, splits, dividends; ETF and index series"},
        ],
        "files": {"universe.csv": sha(PROC / "universe.csv"), "first_report.csv": sha(PROC / "first_report.csv"),
                  "prices.csv.gz": sha(SNAP / "prices.csv.gz"), "bench.csv.gz": sha(SNAP / "bench.csv.gz")},
    }
    prov["data_hash"] = hashlib.sha256(json.dumps(prov["files"], sort_keys=True).encode()).hexdigest()
    (PROC / "provenance.json").write_text(json.dumps(prov, indent=1))
    print(json.dumps(cov, indent=1))
    return cov


if __name__ == "__main__":
    build()
