# PLAN — IPO Evaluator + Mandatory Historical Validation

Canonical plan for this run. Status lines are appended at the bottom.

## Context / load-bearing assumptions (stated as assumptions)

- A1. **No IPO application existed** in this repo (it holds a talk on learning with AI) or in any
  other repo reachable from the session. The request says "deliver the working application", so the
  application is built here, in `ipo-evaluator/`, alongside its validation suite.
- A2. Only **public, key-less data** is available: Nasdaq IPO calendar, SEC EDGAR (`data.sec.gov`),
  Yahoo Finance chart endpoint. No CRSP/Compustat/SDC.
- A3. An LLM wrote this code. It cannot un-know market history, so **no rule threshold or weight may
  be chosen by the author's judgment about what worked**: weights are fitted by an algorithm on the
  development period only, risk gates are fixed a priori from listing-standard conventions, and the
  per-IPO inputs are assembled mechanically from filings and quotes (no LLM in the decision loop).
- A4. "Validated" is a claim that must be earned on a held-out period after a rule freeze. If the
  data cannot support it, the application is labelled **NOT HISTORICALLY VALIDATED**.

## Milestones (priority order) and definition of done

1. **Data spine** — mechanical universe of priced IPOs 2012→2026 incl. later-delisted names,
   point-in-time filings, prices, benchmarks. *Done when* a coverage table (by year, by outcome
   class, by missing-price reason) exists and exclusions are counted.  ← riskiest item, attacked first
2. **Evaluator engine** — calculations (dilution, proceeds, EV, runway), hard gates, probability
   model, BUY / WAIT / AVOID / ABSTAIN, max-buy-price. *Done when* unit tests cover calculation
   correctness, dilution, missing data, gates and price sensitivity.
3. **Backtester** — sealed test period, executable entries, costs, delisting outcomes, baselines,
   benchmarks, clustered uncertainty, Brier/calibration, walk-forward, sensitivity.
   *Done when* a dev/validation run completes end-to-end without touching test-period outcomes.
4. **Pre-registration + freeze + unblinding** — success criteria and rule file committed to git
   *before* the test period is evaluated; unblinding recorded in a ledger.
5. **Dashboard + report** — Historical Validation page (runs, rule versions, decisions, benchmarks,
   downloads), evaluate page, `VALIDATION_REPORT.md`, README with setup and limitations.

## Do NOT polish yet

- Visual design of the dashboard beyond legible tables/charts.
- Extra data vendors, S-1 HTML parsing, founding-date / VC-backing features.
- Intraday execution modelling, tax modelling, borrow/short strategies.
- Performance optimisation of the backtester.

## Status log

- (1) Data spine: sources probed. Yahoo purges delisted tickers (named breakage); Stooq is behind a
  bot gate (left alone); stockanalysis redirects acquired tickers to the acquirer; Nasdaq quote
  history rejects delisted symbols; SEC `companyfacts` has **no pre-IPO S-1 facts** and
  `www.sec.gov/Archives` refuses an anonymous generic client. Consequence: at-IPO decisions are
  reconstructed from deal terms + market state only; full fundamentals enter at the first periodic
  report after the IPO. Downloads running.
