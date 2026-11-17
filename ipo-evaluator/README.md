# IPO Evaluator

A rule-based application that evaluates an IPO (dilution, proceeds, valuation, cash runway, hard
gates, a probability of beating the market) and says **BUY / WAIT / AVOID / ABSTAIN** — together
with the historical backtest that decides whether it is allowed to call itself validated.

> **Status: NOT HISTORICALLY VALIDATED.** See [`results/VALIDATION_REPORT.md`](results/VALIDATION_REPORT.md)
> for the actual held-out results, and [`PREREGISTRATION.md`](PREREGISTRATION.md) for the success
> criteria that were fixed before those results existed. Nothing here is investment advice.

## Setup

Python 3.10+.

```bash
cd ipo-evaluator
pip install -r requirements.txt
python -m pytest tests -q        # 55 tests
python -m ipo_app.server         # http://127.0.0.1:8765
```

The server needs no network and no data download: it reads the committed rule file and the
committed run outputs under `results/`. Open the page for:

- **Historical Validation** — verdict against the pre-registered criteria, every recorded run with
  its rule hash / data hash / git commit / settings, frozen rule versions and the unsealing ledger,
  fixed-horizon results against all benchmarks, false positives and missed winners, calibration,
  splits by year / sector / market conditions, sensitivity, walk-forward, the individual decisions
  (filterable), and CSV / JSON downloads.
- **Evaluate an IPO** — type the offering terms, dilutive securities, financials and market
  conditions; get the calculations, each gate, the probability, the recommendation, the highest
  price that would still be a BUY, and how the recommendation changes across a price ladder. Empty
  fields are treated as missing, never as zero.

A static copy of the validation dashboard (no server) is at `results/validation_dashboard.html`.

## Re-running the validation

```bash
python -m ipo_app.data.fetch all        # raw downloads into data/raw/ (about an hour, resumable)
python -m ipo_app.data.build            # processed dataset, coverage.json, provenance.json
python -m ipo_app.backtest.run develop  # fit on 2012-16, select on 2017-18; the test period stays sealed
python -m ipo_app.backtest.run freeze   # mark the rule file frozen; then `git commit` it
python -m ipo_app.backtest.run test     # refuses to run unless the frozen rules are committed
python -m ipo_app.backtest.report       # VALIDATION_REPORT.md, verdict.json, static dashboard
```

Network hosts used by `fetch`: `api.nasdaq.com`, `data.sec.gov`, `query1.finance.yahoo.com`. The
client identifies itself with a generic name and sends no personal contact details.

The rules in `rules/v1.0.0.json` are frozen and their hash is recorded in
`results/freeze_ledger.json`. Editing them (or re-running `develop`) creates a different hash; the
2020+ period has already been unsealed once, so it is **not** a held-out period for any new
version, and the code flags that in the next run's integrity block.

## Layout

```
ipo_app/engine/      calc.py (dilution, proceeds, EV, runway)   recommend.py (gates, model, BUY/WAIT/AVOID)
ipo_app/data/        fetch.py (downloads + cache)               build.py (point-in-time dataset, provenance)
ipo_app/backtest/    core.py (decision reconstruction, execution, outcomes, seal)
                     train.py (model fitting with embargo)      metrics.py (clustered bootstrap, Brier, alpha)
                     run.py (develop / freeze / test, portfolio simulation, sensitivity, walk-forward)
                     report.py (pre-registered verdict, report, static dashboard)
ipo_app/server.py    local web app (standard library only)      ipo_app/web/index.html
rules/               versioned, hashed rule files               tests/  unit and integrity tests
data/processed/      universe.csv, first_report.csv, coverage.json, provenance.json (committed)
data/raw/, data/snapshot/   raw cache and vendor price snapshot (NOT committed)
results/             runs/<run_id>/{manifest.json, summary.json, decisions.csv}, freeze_ledger.json,
                     verdict.json, VALIDATION_REPORT.md, validation_dashboard.html
PLAN.md  DECISIONS.md  PREREGISTRATION.md
```

## How a decision is made

1. **Calculations** — offering size, net cash to the company (primary shares only, less discount
   and expenses), fully diluted shares by the treasury-stock method (dilution depends on price),
   market cap, enterprise value (pro-forma for proceeds when the balance sheet predates the
   offering), EV/sales, growth, margin, cash runway, net tangible book value per share and dilution
   to new investors. A quantity whose inputs are missing is `None`, not zero.
2. **Hard gates** (fixed a priori, final): SPAC / unit / fund → INELIGIBLE; missing or inconsistent
   critical inputs, or stale statements at the post-report stage → ABSTAIN; price under $5, offering
   under $15M, going-concern doubt, or under 6 months of cash → AVOID.
3. **Probability** — a logistic model per decision stage, with coefficients fitted on IPOs whose
   12-month outcome was known before 2020. The app shows each input's contribution.
4. **Recommendation** — BUY at or above the buy threshold, AVOID below the avoid threshold, WAIT in
   between (watchlist: re-evaluated as the price changes).

## Data provenance

| Source | Used for |
|---|---|
| Nasdaq IPO calendar and deal overview | the universe of priced IPOs (including companies that later failed), offer terms, shares outstanding, CIK |
| SEC EDGAR `data.sec.gov` submissions | SIC code, filing index, 8-K items and deregistration forms (fate of each company) |
| SEC EDGAR XBRL company facts | financial statements exactly as carried by the first 10-Q/10-K after the IPO |
| Yahoo Finance chart endpoint | daily prices with splits and dividends; SPY, IWM, sector ETFs, IPO ETF, T-bill ETF, VIX |

Counts, exclusions and file hashes: `data/processed/coverage.json`, `data/processed/provenance.json`.
Vendor price data is deliberately not committed to this public repository; the decision-level
results derived from it are.

## Documented limitations

The full list with figures is §11 of the validation report. The ones that matter most:

- **Price history is missing for most IPOs that were later acquired, delisted or went bankrupt**,
  because the free price source deletes delisted symbols. All returns are conditional on survival
  in that database. This alone prevents a claim of validation.
- **Prospectus financials could not be reconstructed mechanically at the IPO date**; the at-IPO
  models use deal terms and market conditions only.
- Going-concern and option-strike inputs exist in the app and are unit-tested but could not be
  exercised historically.
- The author is a language model that cannot un-know the period; weights and thresholds were fitted
  by algorithm on pre-2020 data to limit that.

**Cheapest way to lift the main limitation:** obtain a survivorship-free daily price file (CRSP,
Norgate, Sharadar, EODHD, or Tiingo's free tier at roughly 50 symbols per hour), write it to
`data/snapshot/prices.csv.gz` in the column format produced by `build.py`
(`deal_id,date,open,high,low,close,volume,adjclose,split_factor`), and re-run `test` and `report`
with the same frozen rules.
