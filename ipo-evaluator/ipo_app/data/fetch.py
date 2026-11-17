"""Raw data acquisition for the historical IPO dataset.

Every network response is cached verbatim under ``data/raw/`` so that builds are
resumable and the provenance of each field can be audited. Nothing in this module
computes returns or looks at outcomes; it only downloads.

Sources (all public, no API key):
  * Nasdaq IPO calendar + deal overview  (api.nasdaq.com)   -> universe, deal terms, CIK
  * SEC EDGAR submissions + XBRL facts   (data.sec.gov)     -> SIC, filing history, point-in-time facts
  * Yahoo Finance chart endpoint         (query1.finance.yahoo.com) -> daily prices, splits, dividends

Usage:  python -m ipo_app.data.fetch {calendar|overview|sec|yahoo|bench|all}
"""
from __future__ import annotations

import gzip
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
# An honest, generic client name. No personal contact details are sent.
UA = "ipo-backtest-research/0.1 (automated research client)"

FIRST_MONTH = (2011, 7)   # calendar start: 6 months of lead-in for the IPO-heat feature
UNIVERSE_START = "2012-01-01"

# XBRL tags kept from SEC companyfacts (everything else is discarded to save space).
FACT_TAGS = {
    "us-gaap": [
        "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet",
        "SalesRevenueGoodsNet", "SalesRevenueServicesNet", "RevenuesNetOfInterestExpense",
        "InterestAndDividendIncomeOperating", "RealEstateRevenueNet", "OilAndGasRevenue",
        "NetIncomeLoss", "ProfitLoss", "OperatingIncomeLoss", "GrossProfit",
        "Assets", "Liabilities", "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "ShortTermInvestments", "MarketableSecuritiesCurrent", "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
        "NetCashProvidedByUsedInOperatingActivities", "ResearchAndDevelopmentExpense",
        "LongTermDebt", "LongTermDebtNoncurrent", "DebtCurrent", "LongTermDebtCurrent",
        "Goodwill", "IntangibleAssetsNetExcludingGoodwill",
        "CommonStockSharesOutstanding",
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "WeightedAverageNumberOfSharesOutstandingBasic",
        "AntidilutiveSecuritiesExcludedFromComputationOfEarningsPerShareAmount",
        "SubstantialDoubtAboutGoingConcernWithinOneYear",
    ],
    "dei": ["EntityCommonStockSharesOutstanding", "EntityPublicFloat"],
}

BENCH_SYMBOLS = [
    "SPY", "IWM", "IWO", "IPO", "BIL", "^VIX", "^IRX",
    "XLK", "XLV", "XLF", "XLE", "XLI", "XLY", "XLP", "XLB", "XLU", "XLRE", "XLC", "XBI",
]

_session = requests.Session()
_session.headers.update({"User-Agent": UA, "Accept-Encoding": "gzip, deflate", "Accept": "application/json"})
_last_call: dict[str, float] = {}


def _get(url: str, host_delay: float, tries: int = 4, timeout: int = 60):
    """Polite GET with per-host spacing and exponential backoff. Returns (status, bytes)."""
    host = url.split("/")[2]
    for attempt in range(tries):
        wait = host_delay - (time.time() - _last_call.get(host, 0.0))
        if wait > 0:
            time.sleep(wait)
        _last_call[host] = time.time()
        try:
            r = _session.get(url, timeout=timeout)
        except requests.RequestException:
            time.sleep(2 ** attempt * 2)
            continue
        if r.status_code == 200:
            return 200, r.content
        if r.status_code in (404, 400):
            return r.status_code, r.content
        time.sleep(2 ** attempt * 3)  # 403/429/5xx: back off, do not hammer
    return -1, b""


def _write(path: Path, content: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(content)
    tmp.replace(path)


def _months(first=FIRST_MONTH, last: date | None = None):
    last = last or date.today()
    y, m = first
    while (y, m) <= (last.year, last.month):
        yield f"{y:04d}-{m:02d}"
        m += 1
        if m == 13:
            y, m = y + 1, 1


# --------------------------------------------------------------------------- calendar
def fetch_calendar():
    out = RAW / "nasdaq" / "calendar"
    for ym in _months():
        p = out / f"{ym}.json"
        # the current and previous month can still change; older months are frozen
        fresh_cut = (date.today().replace(day=1) - timedelta(days=40)).strftime("%Y-%m")
        if p.exists() and ym < fresh_cut:
            continue
        st, body = _get(f"https://api.nasdaq.com/api/ipo/calendar?date={ym}", 0.6)
        if st == 200:
            _write(p, body)
        else:
            print("calendar FAIL", ym, st, flush=True)
    print("calendar done", flush=True)


def load_calendar_rows() -> list[dict]:
    rows = []
    for p in sorted((RAW / "nasdaq" / "calendar").glob("*.json")):
        try:
            d = json.loads(p.read_text())
        except json.JSONDecodeError:
            continue
        priced = ((d.get("data") or {}).get("priced") or {}).get("rows") or []
        for r in priced:
            r = dict(r)
            r["calendar_month"] = p.stem
            rows.append(r)
    return rows


SPAC_NAME = re.compile(r"\b(ACQUISITION|ACQUISITIONS|BLANK CHECK|SPAC)\b", re.I)


def prelim_eligible(r: dict) -> tuple[bool, str]:
    """Calendar-only prefilter used to avoid downloading deals that can never be eligible.
    The authoritative eligibility rules live in ipo_app.data.build (they also use SEC data)."""
    try:
        px = float(re.sub(r"[\s$,]|&#8203;", "", str(r.get("proposedSharePrice") or "")))
    except ValueError:
        return False, "no_price"
    try:
        d = datetime.strptime(r["pricedDate"], "%m/%d/%Y").date().isoformat()
    except (KeyError, ValueError):
        return False, "no_date"
    if d < UNIVERSE_START:
        return False, "before_universe_start"
    exch = (r.get("proposedExchange") or "").upper()
    if not any(k in exch for k in ("NASDAQ", "NYSE", "NEW YORK", "AMEX", "AMERICAN")):
        return False, "non_major_exchange"
    if px < 5.0:
        return False, "offer_price_below_5"
    name = r.get("companyName") or ""
    sym = (r.get("proposedTickerSymbol") or "").upper()
    if SPAC_NAME.search(name) and 9.5 <= px <= 10.5:
        return False, "spac_name_and_10usd_unit"
    if len(sym) >= 5 and sym.endswith("U") and 9.5 <= px <= 10.5:
        return False, "unit_offering_10usd"
    return True, "ok"


# --------------------------------------------------------------------------- overview
def fetch_overview(shard: int = 0, nshards: int = 1):
    out = RAW / "nasdaq" / "overview"
    rows = [r for r in load_calendar_rows() if prelim_eligible(r)[0]]
    rows = [r for i, r in enumerate(rows) if i % nshards == shard]
    print("overview targets", len(rows), flush=True)
    for i, r in enumerate(rows):
        did = r["dealID"]
        p = out / f"{did}.json"
        if p.exists():
            continue
        st, body = _get(f"https://api.nasdaq.com/api/ipo/overview/?dealId={did}", 0.45)
        if st == 200:
            _write(p, body)
        else:
            _write(out / f"{did}.fail", str(st).encode())
        if i % 200 == 0:
            print("overview", i, len(rows), flush=True)
    print("overview done", flush=True)


def load_overview(deal_id: str) -> dict | None:
    p = RAW / "nasdaq" / "overview" / f"{deal_id}.json"
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text()).get("data") or {}
    except json.JSONDecodeError:
        return None
    po = d.get("poOverview") or {}
    flat = {k: (v or {}).get("value") for k, v in po.items()}
    flat["companyDescription"] = (d.get("companyInformation") or {}).get("companyDescription")
    return flat


def _cik_of(ov: dict | None) -> str | None:
    if not ov:
        return None
    c = re.sub(r"\D", "", str(ov.get("SECCIK") or ""))
    return c.zfill(10) if c and int(c) > 0 else None


def target_ciks() -> dict[str, list[dict]]:
    by_cik: dict[str, list[dict]] = {}
    for r in load_calendar_rows():
        if not prelim_eligible(r)[0]:
            continue
        cik = _cik_of(load_overview(r["dealID"]))
        if cik:
            by_cik.setdefault(cik, []).append(r)
    return by_cik


# --------------------------------------------------------------------------- SEC
def _compact_facts(raw: dict) -> dict:
    out = {"cik": raw.get("cik"), "entityName": raw.get("entityName"), "facts": {}}
    for tax, tags in FACT_TAGS.items():
        src = (raw.get("facts") or {}).get(tax) or {}
        for tag in tags:
            if tag not in src:
                continue
            units = {}
            for unit, arr in (src[tag].get("units") or {}).items():
                units[unit] = [
                    [a.get("start"), a.get("end"), a.get("val"), a.get("accn"), a.get("form"), a.get("filed"),
                     a.get("fy"), a.get("fp")]
                    for a in arr
                ]
            out["facts"][f"{tax}:{tag}"] = units
    return out


def fetch_sec(shard: int = 0, nshards: int = 1):
    sub_dir = RAW / "sec" / "submissions"
    fact_dir = RAW / "sec" / "facts"
    ciks = [c for c in sorted(target_ciks()) if int(c) % nshards == shard]
    if os.environ.get("FETCH_REVERSE"):
        ciks.reverse()          # a second worker walking the list from the other end
    print("sec targets", len(ciks), flush=True)
    for i, cik in enumerate(ciks):
        p = sub_dir / f"{cik}.json.gz"
        if not p.exists() and not (sub_dir / f"{cik}.fail").exists():
            st, body = _get(f"https://data.sec.gov/submissions/CIK{cik}.json", 0.3)
            if st == 200:
                d = json.loads(body)
                # companies with long histories split older filings into extra pages
                extra = []
                for f in (d.get("filings") or {}).get("files") or []:
                    st2, b2 = _get(f"https://data.sec.gov/submissions/{f['name']}", 0.3)
                    if st2 == 200:
                        extra.append(json.loads(b2))
                d["_older_pages"] = extra
                _write(p, gzip.compress(json.dumps(d).encode()))
            else:
                _write(sub_dir / f"{cik}.fail", str(st).encode())
        q = fact_dir / f"{cik}.json.gz"
        if not q.exists() and not (fact_dir / f"{cik}.fail").exists():
            st, body = _get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json", 0.3, timeout=120)
            if st == 200:
                _write(q, gzip.compress(json.dumps(_compact_facts(json.loads(body))).encode()))
            else:
                _write(fact_dir / f"{cik}.fail", str(st).encode())
        if i % 200 == 0:
            print("sec", i, len(ciks), flush=True)
    print("sec done", flush=True)


def load_submissions(cik: str) -> dict | None:
    p = RAW / "sec" / "submissions" / f"{cik}.json.gz"
    if not p.exists():
        return None
    return json.loads(gzip.decompress(p.read_bytes()))


def load_facts(cik: str) -> dict | None:
    p = RAW / "sec" / "facts" / f"{cik}.json.gz"
    if not p.exists():
        return None
    return json.loads(gzip.decompress(p.read_bytes()))


# --------------------------------------------------------------------------- Yahoo
def _yahoo_chart(symbol: str, start: date, end: date):
    p1 = int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp())
    p2 = int(datetime(end.year, end.month, end.day, tzinfo=timezone.utc).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{requests.utils.quote(symbol)}"
           f"?period1={p1}&period2={p2}&interval=1d&events=div%2Csplit")
    st, body = _get(url, 0.5)
    if st not in (200, 404, 400) or not body:
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return None


def fetch_yahoo(retry_missing: bool = False):
    """First pass uses the symbol at IPO (plus SEC tickers if already downloaded). With
    retry_missing=True, deals that found no price history are retried once SEC's current
    ticker list for the CIK is available (handles renamed tickers and OTC successors)."""
    out = RAW / "yahoo" / "ipo"
    today = date.today()
    by_cik = target_ciks()
    deals = [(cik, r) for cik, rs in by_cik.items() for r in rs]
    if os.environ.get("FETCH_REVERSE"):
        deals.reverse()
    print("yahoo targets", len(deals), flush=True)
    for i, (cik, r) in enumerate(deals):
        did = r["dealID"]
        p = out / f"{did}.json.gz"
        priced = datetime.strptime(r["pricedDate"], "%m/%d/%Y").date()
        if p.exists():
            if not retry_missing:
                continue
            prev = json.loads(gzip.decompress(p.read_bytes()))
            tried = {a["symbol"] for a in prev["attempts"]}
            sec_syms = {(t or "").upper().replace(".", "-") for t in (load_submissions(cik) or {}).get("tickers") or []}
            # an attempt only counts if its history starts at the IPO; a symbol that was later
            # reused by another security (history starting years later) must not block the retry
            limit = datetime(priced.year, priced.month, priced.day, tzinfo=timezone.utc).timestamp() + 10 * 86400
            usable = any(a["n"] > 0 and a["chart"]["timestamp"][0] <= limit for a in prev["attempts"])
            if usable or not (sec_syms - tried):
                continue
            keep_prev = prev["attempts"]
        else:
            keep_prev = []
        sub = load_submissions(cik) or {}
        # candidate symbols: the symbol at IPO first, then whatever SEC lists for the CIK today
        cands = []
        for s in [r.get("proposedTickerSymbol")] + list(sub.get("tickers") or []):
            s = (s or "").upper().strip().replace(".", "-")
            if s and s not in cands:
                cands.append(s)
        attempts = list(keep_prev)
        cands = [s for s in cands if s not in {a["symbol"] for a in attempts}]
        for s in cands[:4]:
            d = _yahoo_chart(s, priced - timedelta(days=10), today)
            res = ((d or {}).get("chart") or {}).get("result") or []
            n = len(res[0].get("timestamp") or []) if res else 0
            err = ((d or {}).get("chart") or {}).get("error")
            attempts.append({"symbol": s, "n": n, "error": err, "chart": res[0] if res else None})
        _write(p, gzip.compress(json.dumps({"dealID": did, "cik": cik, "pricedDate": priced.isoformat(),
                                            "attempts": attempts}).encode()))
        if i % 200 == 0:
            print("yahoo", i, len(deals), flush=True)
    print("yahoo done", flush=True)


def fetch_bench():
    out = RAW / "yahoo" / "bench"
    for s in BENCH_SYMBOLS:
        d = _yahoo_chart(s, date(2011, 1, 1), date.today())
        if d and (d.get("chart") or {}).get("result"):
            _write(out / f"{s.replace('^', '_')}.json.gz", gzip.compress(json.dumps(d).encode()))
        else:
            print("bench FAIL", s, flush=True)
    print("bench done", flush=True)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    steps = {"calendar": fetch_calendar, "overview": fetch_overview, "sec": fetch_sec,
             "yahoo": fetch_yahoo, "bench": fetch_bench}
    if cmd == "sec" and len(sys.argv) == 4:
        fetch_sec(int(sys.argv[2]), int(sys.argv[3]))
    elif cmd == "overview" and len(sys.argv) == 4:
        fetch_overview(int(sys.argv[2]), int(sys.argv[3]))
    elif cmd == "yahoo-retry":
        fetch_yahoo(retry_missing=True)
    else:
        for name in (steps if cmd == "all" else [cmd]):
            steps[name]()
