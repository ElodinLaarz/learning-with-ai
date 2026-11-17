# Historical Validation Report — IPO Evaluator

*Generated from run `test-c45c835418` · rules `v1.0.0` (hash `6a1aac31ace69804…`) · data snapshot `22dc77a8a0861d22…`, last market date 2026-11-16. Every figure below is read from the run outputs in `results/runs/`.*

## 1. Verdict

> **NOT HISTORICALLY VALIDATED**
>
> Pre-registered verdict: **NOT SUPPORTED**. The evidence does not support an advantage over the benchmarks: price history exists for only 78% of eligible test-period IPOs, so results describe survivors of the price vendor's database, not all IPOs; BUY recommendations underperformed SPY over 12 months: -25.3% [-36.5%, -10.5%]. BUY recommendations did lose less than buying every eligible IPO (difference 9.3% [3.1%, 18.1%]), but a smaller loss is not an advantage over the market, and the walk-forward difference is 3.2% [-2.1%, 8.9%].

| Pre-registered criterion (primary endpoint: retail access, 12 months, held-out period) | Result | Met |
|---|---|:-:|
| H1 — BUY trades beat SPY over 12 months (95% interval above zero) | mean excess -25.3% [-36.5%, -10.5%], n = 277 | no |
| H2 — BUY trades beat buying every eligible IPO (95% interval above zero) | difference 9.3% [3.1%, 18.1%] | yes |
| H3 — Brier score better than the base rate | Brier 0.2173 vs reference 0.1570 (skill -0.383) | no |
| Guardrail 1 — at least 30 BUY trades over at least 8 entry quarters | 277 trades, 24 quarters | yes |
| Guardrail 2 — still positive without the best 5% of BUY trades | -36.6% | no |
| Guardrail 3 — still positive at 50 bps per side | -25.8% | no |
| Guardrail 4 — price history for at least 90% of eligible test-period IPOs | 78.4% (649 of 828) | no |
| Test period was held out (never unsealed with other rules) | yes | yes |

The criteria were written to `PREREGISTRATION.md` and committed together with the frozen rule file before the test period was opened (freeze commit `d3a9e2cd7f39`; the code refuses to unseal otherwise).

## 2. What was tested

- **Application**: `ipo_app/engine` — deterministic calculations (dilution, proceeds, enterprise value, runway), hard gates, a logistic probability model, and BUY / WAIT / AVOID / ABSTAIN output. The backtest calls the same `evaluate()` function the web app uses.
- **No LLM in the loop**: each historical decision is assembled by code from filings and quotes dated on or before the decision. Model weights were fitted by an algorithm on pre-2020 outcomes; no weight or threshold was set by the author.
- **Rule version**: `v1.0.0`, frozen at 2026-11-17T05:48:24+00:00. Models trained on outcomes known before 2020-01-01.

| Model | training IPOs | L2 λ (chosen on validation Brier) | buy threshold quantile (chosen on validation excess return) | buy threshold | avoid threshold |
|---|--:|--:|--:|--:|--:|
| A_offer | 449 | 10 | 0.8 | p ≥ 0.670 | p < 0.400 |
| A_retail | 449 | 100 | 0.5 | p ≥ 0.415 | p < 0.364 |
| B_post_report | 311 | 100 | 0.5 | p ≥ 0.396 | p < 0.339 |

## 3. Dataset: coverage, exclusions, sources

Universe: every deal marked *priced* in the Nasdaq IPO calendar from 2012-01 to the snapshot (4587 deals including SPACs). **1971 are eligible** operating-company IPOs after the exclusions below. The list is taken as published; no company was added or removed by hand.

| Exclusion | deals |
|---|--:|
| SPAC by name with a $10 unit price | 817 |
| $10 unit offering (SPAC-style) | 671 |
| Foreign private issuer (files F-1/20-F/6-K; no quarterly XBRL) | 565 |
| Offer price below $5 | 336 |
| Priced before 2012 (calendar lead-in only) | 62 |
| No final offer price in the calendar record | 43 |
| Already traded before the deal (uplisting, not an IPO) | 40 |
| Not NYSE / Nasdaq / NYSE American | 34 |
| Blank-check company (SIC 6770) | 29 |
| Fund or commodity pool | 19 |

| IPO year | 2012 | 2013 | 2014 | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| eligible | 118 | 193 | 226 | 138 | 87 | 125 | 143 | 113 | 171 | 314 | 52 | 52 | 74 | 74 | 91 |
| with price history | 40 | 62 | 89 | 63 | 45 | 65 | 90 | 73 | 118 | 212 | 40 | 42 | 73 | 73 | 91 |
| coverage | 34% | 32% | 39% | 46% | 52% | 52% | 63% | 65% | 69% | 68% | 77% | 81% | 99% | 99% | 100% |

**Unsuccessful IPOs are in the universe, but mostly not in the price data.** Later fate of each eligible IPO, classified mechanically from SEC filings (bankruptcy = an 8-K with item 1.03; still filing = a 10-K/10-Q within about 18 months of the snapshot; acquired = stopped reporting with merger or tender-offer documents on file; other = stopped reporting for any other reason):

| Fate per SEC filings (as of snapshot) | eligible IPOs | with price history | without price history | coverage |
|---|--:|--:|--:|--:|
| Still filing | 1256 | 1132 | 124 | 90% |
| Acquired / merged | 533 | 9 | 524 | 2% |
| Delisted or deregistered, other | 76 | 23 | 53 | 30% |
| Bankruptcy | 106 | 12 | 94 | 11% |

Price-history status of eligible IPOs: ok 1176, no_yahoo_history 696, yahoo_history_starts_late 99.

**Sources** (public, no API key; raw responses cached under `data/raw/`, hashes in `data/processed/provenance.json`):

| Source | Endpoint | Used for |
|---|---|---|
| Nasdaq IPO calendar | `https://api.nasdaq.com/api/ipo/calendar?date=YYYY-MM` | deal id, symbol, company, exchange, offer price, shares offered, pricing date |
| Nasdaq IPO deal overview | `https://api.nasdaq.com/api/ipo/overview/?dealId=...` | CIK, shares outstanding after offering, offering expenses, lock-up, employees |
| SEC EDGAR submissions | `https://data.sec.gov/submissions/CIK##########.json` | SIC code, filing index (form, filing date, 8-K items, accession numbers), current tickers |
| SEC EDGAR XBRL company facts | `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` | financial-statement facts, selected by the accession number of the first 10-Q/10-K after the IPO |
| Yahoo Finance chart | `https://query1.finance.yahoo.com/v8/finance/chart/SYMBOL` | daily open/high/low/close/adjusted close/volume, splits, dividends; ETF and index series |

First periodic report located for 1965 eligible IPOs, of which 1531 carry machine-readable (XBRL) facts. Shares outstanding after the offering are missing for 21 deals (the engine abstains on those). Eligible IPOs with any XBRL fact filed on or before the pricing date: 96.

## 4. Point-in-time reconstruction

| Decision | Information used | Executable entry |
|---|---|---|
| Offer-price access | Deal terms from the IPO calendar record, SIC code, VIX / S&P 500 trend / IPO count as of the close before the first trade | Offer price (no spread) on the first trading day |
| Retail, at IPO (primary) | The above plus the first-day closing price | Open of the 2nd trading day, +25 bps |
| Retail, post-report | The above plus facts tagged with the accession number of the first 10-Q/10-K filed after pricing, and that day's close | Open of the trading day after the filing date, +25 bps |

Later filings, restated figures and anything dated after the decision are excluded by construction and by tests (`tests/test_backtest.py`: decisions are unchanged when future prices and index data are rewritten; a later restatement of the same period is ignored). Known departures from strict point-in-time are listed in §11.

## 5. Protocol

Development 2012–2016 → validation 2017–2018 → embargo 2019 → **held-out test 2020 onward**. Training labels need a 12-month outcome fully realised before the period being evaluated. Walk-forward refits each January on outcomes known by then and decides that year's IPOs. Horizons are 21 / 63 / 126 / 252 trading days from entry; a horizon that ends after the snapshot is *incomplete* and is counted, not scored.

| Ledger event | UTC | rule hash | git commit |
|---|---|---|---|
| rules frozen | 2026-11-17T05:48:24+00:00 | `6a1aac31ace69804` | `1257435a3dde` |
| test period unsealed → `test-c45c835418` | 2026-11-17T05:49:27+00:00 | `6a1aac31ace69804` | `d3a9e2cd7f39` |
| test period unsealed → `test-c45c835418` | 2026-11-17T05:51:02+00:00 | `6a1aac31ace69804` | `d3a9e2cd7f39` |
| test period unsealed → `test-c45c835418` | 2026-11-17T05:52:56+00:00 | `6a1aac31ace69804` | `a5b0eea12b2f` |

## 6. Held-out test results (IPOs priced 2020-01-01 → snapshot)

Eligible test-period IPOs: 828; with price history: 649 (78.4%). Without price history: acquired 94, active 59, bankruptcy 15, delisted_other 11.

### Retail access — decide after the first-day close, buy at the 2nd-day open (PRIMARY)

- Eligible IPOs: **828**. Initial recommendations: BUY 336, NO_DECISION 182, AVOID 160, WAIT 137, ABSTAIN 13. Final actions: NO_TRADE 479, BUY 349.
- BUY trades: **349** (13 after a watchlist wait). **Abstention rate: 57.9%**.
- Hard gates triggered: MICRO_DEAL 55, PENNY_PRICE 40, CRITICAL_DATA_MISSING 13. No decision possible: no_price_history 182.
- Of 277 BUYs with a complete 12-month outcome, **65 beat SPY (23.5%)** and **212 were false positives (76.5%)**.
- Base rate: 20.3% of 546 eligible IPOs beat SPY when bought at the same entry. **Missed winners: 46 of 111 (41.4%)**; losers avoided: 222 (51.0%).

| Horizon | Group | n | incomplete | delisted before horizon | mean net return | median | SPY same dates | mean excess vs SPY [95%] | vs sector ETF | vs IWM | vs IPO ETF | % beating SPY | volatility | worst | 5th pct |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1m | Strategy BUYs | 346 | 3 | 0 | 0.3% | 0.3% | 1.8% | -1.6% [-4.4%, 1.5%] | -1.8% | -1.3% | -0.8% | 43.9% | 21.3% | -81.5% | -32.0% |
| 1m | Buy every eligible IPO | 641 | 5 | 0 | -2.9% | -2.1% | 1.6% | -4.5% [-7.6%, -1.8%] | -4.7% | -4.2% | -3.5% | 39.3% | 28.3% | -97.5% | -46.6% |
| 1m | Simple screen | 440 | 4 | 0 | 1.3% | 0.4% | 1.9% | -0.7% [-3.7%, 2.2%] | -0.7% | -0.4% | 0.1% | 44.3% | 22.1% | -72.6% | -31.4% |
| 1m | *Strategy minus buy-all* | 346 vs 641 | | | | | | 3.0% [0.6%, 5.5%] | | | | | | | |
| 1m | *Strategy minus simple screen* | 346 vs 440 | | | | | | -0.9% [-2.4%, 0.5%] | | | | | | | |
| 3m | Strategy BUYs | 340 | 9 | 0 | -2.6% | -7.5% | 4.9% | -7.5% [-14.2%, 0.1%] | -7.0% | -6.9% | -5.4% | 33.2% | 46.4% | -88.7% | -53.4% |
| 3m | Buy every eligible IPO | 633 | 13 | 0 | -4.9% | -11.0% | 4.4% | -9.2% [-18.2%, 0.4%] | -9.1% | -8.7% | -6.7% | 29.5% | 58.4% | -99.1% | -70.9% |
| 3m | Simple screen | 433 | 11 | 0 | 0.9% | -5.8% | 5.1% | -4.2% [-13.2%, 6.0%] | -3.7% | -4.0% | -2.9% | 34.4% | 48.2% | -79.8% | -51.5% |
| 3m | *Strategy minus buy-all* | 340 vs 633 | | | | | | 1.8% [-2.8%, 6.5%] | | | | | | | |
| 3m | *Strategy minus simple screen* | 340 vs 433 | | | | | | -3.3% [-7.2%, 0.5%] | | | | | | | |
| 6m | Strategy BUYs | 322 | 27 | 0 | -7.4% | -13.2% | 8.9% | -16.3% [-23.1%, -8.3%] | -15.7% | -14.9% | -9.5% | 31.1% | 51.3% | -90.3% | -71.8% |
| 6m | Buy every eligible IPO | 602 | 44 | 0 | -12.6% | -21.1% | 8.3% | -20.9% [-29.3%, -10.3%] | -20.5% | -19.7% | -13.3% | 26.2% | 59.7% | -99.1% | -79.0% |
| 6m | Simple screen | 407 | 37 | 0 | -6.6% | -11.9% | 9.6% | -16.1% [-24.5%, -6.3%] | -15.4% | -15.8% | -10.1% | 29.7% | 50.9% | -85.9% | -69.4% |
| 6m | *Strategy minus buy-all* | 322 vs 602 | | | | | | 4.6% [-1.4%, 9.8%] | | | | | | | |
| 6m | *Strategy minus simple screen* | 322 vs 407 | | | | | | -0.1% [-4.4%, 3.8%] | | | | | | | |
| 12m | Strategy BUYs | 277 | 72 | 0 | -11.9% | -29.0% | 13.4% | -25.3% [-36.5%, -10.5%] | -22.9% | -20.8% | -6.8% | 23.5% | 73.8% | -95.5% | -82.9% |
| 12m | Buy every eligible IPO | 546 | 100 | 0 | -22.0% | -39.7% | 12.7% | -34.7% [-44.0%, -23.9%] | -33.5% | -30.3% | -16.5% | 20.3% | 75.8% | -99.5% | -89.5% |
| 12m | Simple screen | 361 | 83 | 0 | -14.0% | -28.2% | 13.9% | -27.9% [-38.2%, -14.5%] | -25.9% | -23.9% | -9.2% | 23.3% | 70.2% | -95.3% | -82.8% |
| 12m | *Strategy minus buy-all* | 277 vs 546 | | | | | | 9.3% [3.1%, 18.1%] | | | | | | | |
| 12m | *Strategy minus simple screen* | 277 vs 361 | | | | | | 2.6% [-1.3%, 6.8%] | | | | | | | |

**Capital-constrained account** ($100k, 5% per position, max 20 positions, 12-month holds, idle cash in T-bills)

| Account | total return | CAGR | annualised volatility | max drawdown | worst day | trades taken / offered | average invested |
|---|--:|--:|--:|--:|--:|--:|--:|
| Strategy | -1.1% | -0.2% | 25.2% | -57.7% | -7.8% | 120 / 349 | 78% |
| Strategy — same trades in SPY | 140.0% | 13.7% | 14.1% | -19.2% | -5.8% | 121 / 349 | 82% |
| Strategy — SPY buy & hold, same window | 145.6% | 14.1% | 20.1% | -33.7% | -10.9% |  |  |
| Buy every eligible IPO | -71.2% | -16.7% | 33.9% | -85.7% | -10.0% | 140 / 646 | 88% |
| Buy every eligible IPO — same trades in SPY | 154.1% | 14.6% | 17.1% | -22.7% | -6.6% | 140 / 646 | 93% |
| Buy every eligible IPO — SPY buy & hold, same window | 145.6% | 14.1% | 20.1% | -33.7% | -10.9% |  |  |
| Simple screen | -2.1% | -0.3% | 25.6% | -60.2% | -8.2% | 118 / 444 | 78% |
| Simple screen — same trades in SPY | 150.2% | 14.5% | 14.0% | -17.8% | -5.5% | 120 / 444 | 82% |
| Simple screen — SPY buy & hold, same window | 151.1% | 14.5% | 20.1% | -33.7% | -10.9% |  |  |

- Strategy: calendar-time alpha vs SPY **-16.5%/yr** (Newey–West t = -1.82, beta 1.12, 81 months, 47 positions on average)
- Buy every eligible IPO: calendar-time alpha vs SPY **-18.6%/yr** (Newey–West t = -1.57, beta 1.18, 81 months, 88 positions on average)
- Simple screen: calendar-time alpha vs SPY **-9.5%/yr** (Newey–West t = -0.83, beta 1.02, 81 months, 60 positions on average)

### Offer-price access — hypothetical allocation at the offer price

- Eligible IPOs: **828**. Initial recommendations: WAIT 407, AVOID 229, BUY 175, ABSTAIN 17. Final actions: NO_TRADE 653, BUY 135, BUY_NO_PRICE_DATA 40.
- BUY trades: **135** (0 after a watchlist wait). **Abstention rate: 83.7%**.
- Hard gates triggered: MICRO_DEAL 64, CRITICAL_DATA_MISSING 17. No decision possible: none.
- Of 120 BUYs with a complete 12-month outcome, **40 beat SPY (33.3%)** and **80 were false positives (66.7%)**.
- Base rate: 29.7% of 546 eligible IPOs beat SPY when bought at the same entry. **Missed winners: 122 of 162 (75.3%)**; losers avoided: 304 (79.2%).

| Horizon | Group | n | incomplete | delisted before horizon | mean net return | median | SPY same dates | mean excess vs SPY [95%] | vs sector ETF | vs IWM | vs IPO ETF | % beating SPY | volatility | worst | 5th pct |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1m | Strategy BUYs | 135 | 0 | 0 | 34.3% | 21.4% | 2.0% | 32.2% [18.3%, 47.3%] | 31.9% | 33.0% | 34.2% | 74.1% | 53.4% | -37.7% | -17.6% |
| 1m | Buy every eligible IPO | 642 | 4 | 0 | 25.2% | 10.3% | 1.5% | 23.7% [13.1%, 36.7%] | 23.5% | 24.0% | 24.8% | 60.0% | 115.0% | -91.8% | -49.8% |
| 1m | Simple screen | 441 | 3 | 0 | 35.3% | 19.8% | 1.8% | 33.4% [20.4%, 50.4%] | 33.3% | 33.7% | 34.3% | 70.7% | 126.6% | -56.8% | -26.2% |
| 1m | *Strategy minus buy-all* | 135 vs 642 | | | | | | 8.5% [-5.5%, 21.1%] | | | | | | | |
| 1m | *Strategy minus simple screen* | 135 vs 441 | | | | | | -1.2% [-19.1%, 10.9%] | | | | | | | |
| 3m | Strategy BUYs | 135 | 0 | 0 | 32.8% | 12.4% | 4.8% | 27.9% [9.6%, 48.3%] | 27.6% | 28.5% | 31.3% | 57.0% | 64.8% | -76.9% | -28.8% |
| 3m | Buy every eligible IPO | 633 | 13 | 0 | 22.8% | 2.0% | 4.3% | 18.5% [1.2%, 37.5%] | 18.7% | 19.1% | 21.1% | 48.2% | 120.8% | -98.3% | -69.4% |
| 3m | Simple screen | 433 | 11 | 0 | 34.1% | 12.0% | 5.0% | 29.1% [10.4%, 50.9%] | 29.5% | 29.2% | 30.4% | 56.8% | 115.1% | -76.9% | -41.2% |
| 3m | *Strategy minus buy-all* | 135 vs 633 | | | | | | 9.4% [-5.6%, 22.0%] | | | | | | | |
| 3m | *Strategy minus simple screen* | 135 vs 433 | | | | | | -1.1% [-19.3%, 11.0%] | | | | | | | |
| 6m | Strategy BUYs | 129 | 6 | 0 | 19.0% | 8.7% | 8.9% | 10.0% [-5.6%, 28.6%] | 10.0% | 11.4% | 19.9% | 44.2% | 61.1% | -70.2% | -61.3% |
| 6m | Buy every eligible IPO | 602 | 44 | 0 | 10.4% | -6.6% | 8.3% | 2.1% [-14.2%, 23.3%] | 2.4% | 3.3% | 9.6% | 38.0% | 112.2% | -98.9% | -78.1% |
| 6m | Simple screen | 407 | 37 | 0 | 23.2% | 6.6% | 9.5% | 13.7% [-4.3%, 36.2%] | 14.5% | 14.1% | 19.8% | 45.5% | 120.5% | -85.0% | -64.7% |
| 6m | *Strategy minus buy-all* | 129 vs 602 | | | | | | 7.9% [-4.7%, 19.9%] | | | | | | | |
| 6m | *Strategy minus simple screen* | 129 vs 407 | | | | | | -3.7% [-19.5%, 7.6%] | | | | | | | |
| 12m | Strategy BUYs | 120 | 15 | 0 | 9.6% | -18.5% | 11.7% | -2.1% [-20.2%, 22.5%] | -1.2% | 3.6% | 21.5% | 33.3% | 80.9% | -91.5% | -75.9% |
| 12m | Buy every eligible IPO | 546 | 100 | 0 | -0.7% | -28.3% | 12.6% | -13.4% [-30.3%, 8.6%] | -12.2% | -9.0% | 4.8% | 29.7% | 124.5% | -99.7% | -89.2% |
| 12m | Simple screen | 361 | 83 | 0 | 16.7% | -10.3% | 13.9% | 2.8% [-18.0%, 30.7%] | 4.9% | 6.8% | 21.5% | 36.0% | 139.1% | -94.6% | -79.6% |
| 12m | *Strategy minus buy-all* | 120 vs 546 | | | | | | 11.3% [-3.4%, 29.6%] | | | | | | | |
| 12m | *Strategy minus simple screen* | 120 vs 361 | | | | | | -5.0% [-23.8%, 9.5%] | | | | | | | |

**Capital-constrained account** ($100k, 5% per position, max 20 positions, 12-month holds, idle cash in T-bills)

| Account | total return | CAGR | annualised volatility | max drawdown | worst day | trades taken / offered | average invested |
|---|--:|--:|--:|--:|--:|--:|--:|
| Strategy | 112.2% | 11.8% | 30.9% | -61.9% | -8.9% | 84 / 135 | 67% |
| Strategy — same trades in SPY | 85.1% | 9.5% | 12.4% | -21.2% | -5.0% | 88 / 135 | 64% |
| Strategy — SPY buy & hold, same window | 145.0% | 14.1% | 20.1% | -33.7% | -10.9% |  |  |
| Buy every eligible IPO | 13.8% | 1.9% | 47.0% | -83.8% | -23.2% | 136 / 646 | 90% |
| Buy every eligible IPO — same trades in SPY | 151.5% | 14.5% | 17.1% | -22.8% | -6.6% | 140 / 646 | 93% |
| Buy every eligible IPO — SPY buy & hold, same window | 145.2% | 14.0% | 20.1% | -33.7% | -10.9% |  |  |
| Simple screen | 421.3% | 27.5% | 59.1% | -61.3% | -12.4% | 111 / 444 | 83% |
| Simple screen — same trades in SPY | 149.0% | 14.4% | 14.0% | -18.0% | -5.5% | 120 / 444 | 82% |
| Simple screen — SPY buy & hold, same window | 152.9% | 14.6% | 20.1% | -33.7% | -10.9% |  |  |

- Strategy: calendar-time alpha vs SPY **-6.6%/yr** (Newey–West t = -0.40, beta 1.70, 80 months, 19 positions on average)
- Buy every eligible IPO: calendar-time alpha vs SPY **-17.0%/yr** (Newey–West t = -1.35, beta 1.19, 81 months, 88 positions on average)
- Simple screen: calendar-time alpha vs SPY **-6.5%/yr** (Newey–West t = -0.51, beta 1.00, 81 months, 60 positions on average)

### Retail access — decide after the first 10-Q/10-K, buy at the next open

- Eligible IPOs: **828**. Initial recommendations: AVOID 244, BUY 208, NO_DECISION 188, ABSTAIN 110, WAIT 78. Final actions: NO_TRADE 619, BUY 209.
- BUY trades: **209** (1 after a watchlist wait). **Abstention rate: 74.8%**.
- Hard gates triggered: FINANCIALS_MISSING_OR_STALE 104, PENNY_PRICE 68, MICRO_DEAL 55, CASH_RUNWAY 10, CRITICAL_DATA_MISSING 6. No decision possible: no_price_history 182, no_periodic_report_found 6.
- Of 162 BUYs with a complete 12-month outcome, **55 beat SPY (34.0%)** and **107 were false positives (66.0%)**.
- Base rate: 20.3% of 531 eligible IPOs beat SPY when bought at the same entry. **Missed winners: 53 of 108 (49.1%)**; losers avoided: 316 (74.7%).

| Horizon | Group | n | incomplete | delisted before horizon | mean net return | median | SPY same dates | mean excess vs SPY [95%] | vs sector ETF | vs IWM | vs IPO ETF | % beating SPY | volatility | worst | 5th pct |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1m | Strategy BUYs | 207 | 2 | 0 | -2.5% | -3.8% | 1.4% | -3.9% [-7.8%, 0.3%] | -3.9% | -3.9% | -4.6% | 37.2% | 18.0% | -67.8% | -30.7% |
| 1m | Buy every eligible IPO | 633 | 7 | 0 | -2.2% | -4.7% | 1.5% | -3.7% [-9.5%, 2.8%] | -3.5% | -3.6% | -4.3% | 35.5% | 41.9% | -88.1% | -38.6% |
| 1m | Simple screen | 101 | 2 | 0 | -0.9% | -3.2% | 1.4% | -2.3% [-6.1%, 1.8%] | -2.0% | -2.1% | -3.7% | 37.6% | 16.4% | -39.9% | -24.9% |
| 1m | *Strategy minus buy-all* | 207 vs 633 | | | | | | -0.2% [-5.6%, 4.1%] | | | | | | | |
| 1m | *Strategy minus simple screen* | 207 vs 101 | | | | | | -1.6% [-4.5%, 1.4%] | | | | | | | |
| 3m | Strategy BUYs | 204 | 5 | 0 | -4.4% | -3.3% | 4.3% | -8.7% [-15.5%, -1.5%] | -9.0% | -9.6% | -7.1% | 36.3% | 31.2% | -68.2% | -51.4% |
| 3m | Buy every eligible IPO | 623 | 17 | 0 | -6.2% | -9.9% | 4.7% | -10.9% [-20.0%, 0.2%] | -10.6% | -11.2% | -9.9% | 31.0% | 48.5% | -95.6% | -62.3% |
| 3m | Simple screen | 100 | 3 | 0 | -0.1% | -0.7% | 4.4% | -4.5% [-11.7%, 4.0%] | -4.1% | -4.8% | -3.7% | 41.0% | 30.5% | -62.3% | -47.7% |
| 3m | *Strategy minus buy-all* | 204 vs 623 | | | | | | 2.1% [-7.2%, 9.4%] | | | | | | | |
| 3m | *Strategy minus simple screen* | 204 vs 100 | | | | | | -4.2% [-9.5%, 1.0%] | | | | | | | |
| 6m | Strategy BUYs | 186 | 23 | 0 | -1.3% | -7.5% | 7.0% | -8.3% [-16.0%, 1.1%] | -7.5% | -8.1% | -0.3% | 34.4% | 51.2% | -84.1% | -64.9% |
| 6m | Buy every eligible IPO | 581 | 59 | 0 | -12.5% | -18.1% | 7.0% | -19.5% [-26.7%, -10.5%] | -18.8% | -17.9% | -11.8% | 24.6% | 55.4% | -96.9% | -74.4% |
| 6m | Simple screen | 94 | 9 | 0 | 3.0% | 1.4% | 7.2% | -4.1% [-12.6%, 6.0%] | -2.6% | -3.8% | 3.3% | 37.2% | 48.2% | -79.1% | -54.0% |
| 6m | *Strategy minus buy-all* | 186 vs 581 | | | | | | 11.2% [4.6%, 17.1%] | | | | | | | |
| 6m | *Strategy minus simple screen* | 186 vs 94 | | | | | | -4.2% [-10.8%, 2.2%] | | | | | | | |
| 12m | Strategy BUYs | 162 | 47 | 0 | -5.0% | -13.7% | 11.9% | -16.9% [-24.9%, -6.3%] | -15.8% | -13.1% | 1.9% | 34.0% | 57.3% | -97.3% | -75.1% |
| 12m | Buy every eligible IPO | 531 | 109 | 0 | -22.0% | -40.8% | 11.6% | -33.6% [-43.3%, -19.5%] | -32.9% | -28.6% | -12.7% | 20.3% | 80.6% | -99.2% | -88.9% |
| 12m | Simple screen | 81 | 22 | 0 | -4.6% | -9.3% | 12.4% | -17.0% [-28.0%, -4.3%] | -14.5% | -12.3% | 1.6% | 35.8% | 56.5% | -81.6% | -73.7% |
| 12m | *Strategy minus buy-all* | 162 vs 531 | | | | | | 16.6% [6.6%, 26.0%] | | | | | | | |
| 12m | *Strategy minus simple screen* | 162 vs 81 | | | | | | 0.1% [-8.8%, 8.4%] | | | | | | | |

**Capital-constrained account** ($100k, 5% per position, max 20 positions, 12-month holds, idle cash in T-bills)

| Account | total return | CAGR | annualised volatility | max drawdown | worst day | trades taken / offered | average invested |
|---|--:|--:|--:|--:|--:|--:|--:|
| Strategy | 12.8% | 1.9% | 22.5% | -48.6% | -5.7% | 112 / 209 | 79% |
| Strategy — same trades in SPY | 108.4% | 12.4% | 14.0% | -23.0% | -4.8% | 112 / 209 | 81% |
| Strategy — SPY buy & hold, same window | 142.5% | 15.2% | 16.7% | -24.5% | -5.9% |  |  |
| Buy every eligible IPO | -14.4% | -2.3% | 30.4% | -74.0% | -7.8% | 138 / 638 | 89% |
| Buy every eligible IPO — same trades in SPY | 173.4% | 16.2% | 16.2% | -24.7% | -5.6% | 139 / 638 | 93% |
| Buy every eligible IPO — SPY buy & hold, same window | 196.6% | 17.7% | 19.4% | -24.5% | -10.9% |  |  |
| Simple screen | 7.3% | 1.1% | 18.1% | -46.8% | -4.4% | 88 / 103 | 64% |
| Simple screen — same trades in SPY | 81.0% | 9.9% | 11.6% | -20.4% | -3.7% | 88 / 103 | 66% |
| Simple screen — SPY buy & hold, same window | 142.5% | 15.2% | 16.7% | -24.5% | -5.9% |  |  |

- Strategy: calendar-time alpha vs SPY **-13.0%/yr** (Newey–West t = -1.89, beta 1.00, 75 months, 30 positions on average)
- Buy every eligible IPO: calendar-time alpha vs SPY **-21.0%/yr** (Newey–West t = -1.84, beta 1.29, 79 months, 88 positions on average)
- Simple screen: calendar-time alpha vs SPY **-15.9%/yr** (Newey–West t = -2.04, beta 1.02, 75 months, 15 positions on average)

### Worst BUY outcomes (primary endpoint)

| Symbol | Company | IPO priced | Entered | 12-month net return | SPY same dates | Status |
|---|---|---|---|--:|--:|---|
| NMAX | Newsmax Inc. | 2025-03-31 | 2025-04-01 | -95.5% | 18.9% | complete |
| RENT | Rent the Runway, Inc. | 2021-10-27 | 2021-10-28 | -90.7% | -13.3% | complete |
| KYTX | Kyverna Therapeutics, Inc. | 2024-02-08 | 2024-02-12 | -90.0% | 23.2% | complete |
| BOLD | Boundless Bio, Inc. | 2024-03-28 | 2024-04-01 | -89.8% | 9.1% | complete |
| FRMI | Fermi Inc. | 2025-10-01 | 2025-10-21 | -89.3% | 15.0% | complete |
| BIRD | Smartbird, Inc. | 2021-11-03 | 2021-11-04 | -88.8% | -17.9% | complete |
| GUTS | FRACTYL HEALTH, INC. | 2024-02-02 | 2024-02-05 | -88.5% | 24.3% | complete |
| FBLG | FibroBiologics, Inc. | 2024-01-31 | 2024-02-02 | -88.0% | 24.9% | complete |
| GEMI | Gemini Space Station, Inc. | 2025-09-12 | 2025-09-15 | -87.6% | 15.5% | complete |
| MSGM | Motorsport Games Inc. | 2021-01-13 | 2021-01-14 | -87.2% | 23.6% | complete |

### Probability calibration (primary endpoint)

Brier score **0.2173** on 533 forecasts; base-rate reference 0.1570; always-50% reference 0.2500; **skill vs base rate -0.383** (positive = better than always forecasting the base rate). Mean forecast 43.8%, observed rate 19.5%.

| Probability bin | n | mean forecast | observed share beating SPY |
|---|--:|--:|--:|
| 1 (25%–35%) | 107 | 31.3% | 13.1% |
| 2 (35%–40%) | 106 | 37.7% | 17.9% |
| 3 (40%–46%) | 107 | 42.4% | 23.4% |
| 4 (46%–54%) | 106 | 49.4% | 17.0% |
| 5 (54%–66%) | 107 | 58.1% | 26.2% |


- A_offer: Brier 0.2713 vs base-rate reference 0.2054 (skill -0.321, n = 533)
- B_post_report: Brier 0.1813 vs base-rate reference 0.1633 (skill -0.111, n = 438)

### By IPO year, sector and market conditions (primary endpoint, 12-month excess vs SPY)

| IPO year | BUY n | BUY mean excess | BUY % beating SPY | all-IPO n | all-IPO mean excess | all-IPO % beating SPY |
|---|--:|--:|--:|--:|--:|--:|
| 2020 | 51 | 3.6% | 35.3% | 118 | -14.3% | 28.8% |
| 2021 | 103 | -47.2% | 7.8% | 212 | -49.6% | 9.9% |
| 2022 | 10 | -16.7% | 30.0% | 40 | -38.6% | 22.5% |
| 2023 | 16 | -10.3% | 37.5% | 40 | -48.5% | 22.5% |
| 2024 | 45 | -14.0% | 35.6% | 72 | -21.3% | 27.8% |
| 2025 | 52 | -26.6% | 26.9% | 64 | -26.7% | 28.1% |

| Sector | BUY n | BUY mean excess | BUY % beating SPY | all-IPO n | all-IPO mean excess | all-IPO % beating SPY |
|---|--:|--:|--:|--:|--:|--:|
| consumer | 39 | -32.5% | 20.5% | 52 | -44.9% | 15.4% |
| energy_utilities | 10 | -15.2% | 30.0% | 17 | -23.7% | 29.4% |
| financial | 39 | -6.1% | 38.5% | 60 | -5.7% | 41.7% |
| health | 47 | -22.7% | 17.0% | 231 | -41.3% | 14.7% |
| industrial_other | 43 | -27.5% | 20.9% | 59 | -38.3% | 16.9% |
| real_estate | 9 | -19.4% | 33.3% | 17 | -18.7% | 41.2% |
| tech | 89 | -32.7% | 21.3% | 109 | -34.1% | 20.2% |
| unknown | 1 | -30.1% | 0.0% | 1 | -30.1% | 0.0% |

| Market conditions at decision | BUY n | BUY mean excess | BUY % beating SPY | all-IPO n | all-IPO mean excess | all-IPO % beating SPY |
|---|--:|--:|--:|--:|--:|--:|
| calm (VIX<15) | 43 | 0.8% | 39.5% | 68 | -12.4% | 30.9% |
| normal (VIX 15-25) | 197 | -32.4% | 17.8% | 382 | -41.2% | 16.2% |
| stressed (VIX>=25) | 37 | -18.4% | 35.1% | 96 | -24.6% | 29.2% |

Sub-group figures are descriptive; several rest on very few trades.

## 7. Sensitivity and dependence on a few winners

These variants re-run the frozen rules under changed assumptions. They are robustness checks on the test period, not candidates for adoption.

**Primary endpoint**

| Assumption | Variant | BUY n | BUY mean excess 12m | BUY median excess | BUY % beating SPY | buy-all mean excess | difference |
|---|---|--:|--:|--:|--:|--:|--:|
| baseline | baseline (frozen settings) | 277 | -25.3% | -41.0% | 23.5% | -34.7% | 9.3% |
| costs | 0 bps per side | 277 | -24.9% | -40.7% | 23.5% | -34.3% | 9.4% |
| costs | 10 bps per side | 277 | -25.1% | -40.8% | 23.5% | -34.5% | 9.4% |
| costs | 50 bps per side | 277 | -25.8% | -41.2% | 23.1% | -35.1% | 9.3% |
| costs | 100 bps per side | 277 | -26.7% | -42.0% | 22.7% | -35.8% | 9.2% |
| thresholds | buy threshold at train quantile -10 pts | 343 | -30.3% | -42.7% | 21.6% | -34.7% | 4.4% |
| thresholds | buy threshold at train quantile +10 pts | 230 | -25.7% | -41.0% | 23.5% | -34.7% | 9.0% |
| thresholds | no AVOID band (everything below BUY waits) | 277 | -25.3% | -41.0% | 23.5% | -34.7% | 9.3% |
| waiting | watchlist window 0 days | 266 | -24.4% | -40.9% | 23.7% | -34.7% | 10.3% |
| waiting | watchlist window 120 days | 280 | -24.6% | -40.9% | 23.9% | -34.7% | 10.1% |
| execution | retail entry at 2nd-day CLOSE | 277 | -26.5% | -41.2% | 22.7% | -35.0% | 8.5% |
| execution | retail entry at 6th-day open | 279 | -27.2% | -38.5% | 23.7% | -34.6% | 7.4% |
| delisting | delisting: no haircut | 277 | -25.3% | -41.0% | 23.5% | -34.7% | 9.3% |
| delisting | delisting: total loss unless acquired | 277 | -25.3% | -41.0% | 23.5% | -34.7% | 9.3% |
| gates | hard gates relaxed (price/deal-size/runway off) | 290 | -28.0% | -41.6% | 22.4% | -34.7% | 6.7% |
| gates | hard gates stricter ($50M deal, 12-month runway) | 270 | -24.8% | -40.1% | 23.7% | -34.7% | 9.9% |

**Offer-price access**

| Assumption | Variant | BUY n | BUY mean excess 12m | BUY median excess | BUY % beating SPY | buy-all mean excess | difference |
|---|---|--:|--:|--:|--:|--:|--:|
| baseline | baseline (frozen settings) | 120 | -2.1% | -23.1% | 33.3% | -13.4% | 11.3% |
| costs | 0 bps per side | 120 | -1.8% | -22.9% | 33.3% | -13.1% | 11.3% |
| costs | 10 bps per side | 120 | -2.0% | -23.0% | 33.3% | -13.2% | 11.3% |
| costs | 50 bps per side | 120 | -2.4% | -23.3% | 33.3% | -13.6% | 11.2% |
| costs | 100 bps per side | 120 | -2.9% | -23.8% | 33.3% | -14.1% | 11.2% |
| thresholds | buy threshold at train quantile -10 pts | 156 | -5.0% | -23.1% | 32.7% | -13.4% | 8.4% |
| thresholds | buy threshold at train quantile +10 pts | 69 | -0.9% | -23.0% | 31.9% | -13.4% | 12.5% |
| thresholds | no AVOID band (everything below BUY waits) | 120 | -2.1% | -23.1% | 33.3% | -13.4% | 11.3% |
| waiting | watchlist window 0 days | 120 | -2.1% | -23.1% | 33.3% | -13.4% | 11.3% |
| waiting | watchlist window 120 days | 120 | -2.1% | -23.1% | 33.3% | -13.4% | 11.3% |
| delisting | delisting: no haircut | 120 | -2.1% | -23.1% | 33.3% | -13.4% | 11.3% |
| delisting | delisting: total loss unless acquired | 120 | -2.1% | -23.1% | 33.3% | -13.4% | 11.3% |
| gates | hard gates relaxed (price/deal-size/runway off) | 122 | -3.1% | -23.1% | 32.8% | -13.4% | 10.2% |
| gates | hard gates stricter ($50M deal, 12-month runway) | 119 | -1.7% | -23.0% | 33.6% | -13.4% | 11.7% |

**Post-report**

| Assumption | Variant | BUY n | BUY mean excess 12m | BUY median excess | BUY % beating SPY | buy-all mean excess | difference |
|---|---|--:|--:|--:|--:|--:|--:|
| baseline | baseline (frozen settings) | 162 | -16.9% | -22.5% | 34.0% | -33.6% | 16.6% |
| costs | 0 bps per side | 162 | -16.5% | -22.1% | 34.0% | -33.2% | 16.7% |
| costs | 10 bps per side | 162 | -16.6% | -22.3% | 34.0% | -33.3% | 16.7% |
| costs | 50 bps per side | 162 | -17.4% | -22.9% | 33.3% | -34.0% | 16.6% |
| costs | 100 bps per side | 162 | -18.3% | -23.6% | 33.3% | -34.7% | 16.4% |
| thresholds | buy threshold at train quantile -10 pts | 184 | -19.5% | -26.0% | 32.1% | -33.6% | 14.1% |
| thresholds | buy threshold at train quantile +10 pts | 139 | -12.8% | -19.2% | 36.0% | -33.6% | 20.7% |
| thresholds | no AVOID band (everything below BUY waits) | 162 | -16.9% | -22.5% | 34.0% | -33.6% | 16.6% |
| waiting | watchlist window 0 days | 161 | -16.3% | -22.3% | 34.2% | -33.6% | 17.2% |
| waiting | watchlist window 120 days | 162 | -16.9% | -22.5% | 34.0% | -33.6% | 16.6% |
| execution | retail entry at 2nd-day CLOSE | 162 | -16.9% | -20.5% | 34.0% | -33.2% | 16.3% |
| delisting | delisting: no haircut | 162 | -16.9% | -22.5% | 34.0% | -33.6% | 16.6% |
| delisting | delisting: total loss unless acquired | 162 | -16.9% | -22.5% | 34.0% | -33.6% | 16.6% |
| valuation | valuation on basic shares (no dilutive securities) | 163 | -16.7% | -22.3% | 34.4% | -33.6% | 16.9% |
| gates | hard gates relaxed (price/deal-size/runway off) | 178 | -18.1% | -26.0% | 32.6% | -33.6% | 15.5% |
| gates | hard gates stricter ($50M deal, 12-month runway) | 151 | -15.9% | -22.7% | 33.1% | -33.6% | 17.7% |

**Concentration of results in the best trades (primary endpoint)**

| BUY trades, 12-month excess vs SPY | value |
|---|--:|
| all 277 trades — mean | -25.3% |
| median | -41.0% |
| without the single best trade | -27.3% |
| without the best 5 trades | -31.2% |
| without the best 5% (14 trades) | -36.6% |
| winsorised at the 95th percentile | -30.3% |


For comparison, buying every eligible IPO: mean -34.7%, median -50.1%, without the best 5% -46.4%.

## 8. What the missing IPOs could do to the results

The offer-stage decision needs no price data, so it was made for every eligible IPO, including those with no surviving price history. The table shows the 12-month mean excess return under explicit assumptions about those unobserved IPOs. These are bounds, not results.

| Group | observed | missing | observed only | missing = total loss | missing = market return | missing = +50% excess | bankrupt −100%, acquired +25%, others = observed mean |
|---|--:|--:|--:|--:|--:|--:|--:|
| Strategy BUYs (offer access) | 120 | 40 | -2.1% | -29.5% | -1.6% | 10.9% | -0.3% |
| Every eligible IPO (offer access) | 546 | 179 | -13.4% | -37.9% | -10.1% | 2.3% | -10.5% |

## 9. Walk-forward evaluation (2016–2025)

Each year's IPOs are decided by models fitted only on outcomes known before 1 January of that year (λ = 10, buy threshold at the 70th percentile of training probabilities, no per-fold tuning).

| Year | Mode | training IPOs | training base rate | buy threshold |
|---|---|--:|--:|--:|
| 2016 | A_offer | 189 | 56.1% | 0.667 |
| 2016 | A_retail | 189 | 49.2% | 0.574 |
| 2017 | A_offer | 252 | 53.2% | 0.618 |
| 2017 | A_retail | 252 | 45.2% | 0.527 |
| 2017 | B_post_report | 163 | 41.7% | 0.513 |
| 2018 | A_offer | 296 | 53.7% | 0.647 |
| 2018 | A_retail | 296 | 45.6% | 0.539 |
| 2018 | B_post_report | 199 | 42.7% | 0.530 |
| 2019 | A_offer | 359 | 54.3% | 0.648 |
| 2019 | A_retail | 359 | 46.0% | 0.553 |
| 2019 | B_post_report | 243 | 44.4% | 0.553 |
| 2020 | A_offer | 449 | 50.3% | 0.595 |
| 2020 | A_retail | 449 | 42.3% | 0.502 |
| 2020 | B_post_report | 311 | 39.9% | 0.489 |
| 2021 | A_offer | 521 | 51.1% | 0.607 |
| 2021 | A_retail | 521 | 43.6% | 0.503 |
| 2021 | B_post_report | 372 | 40.3% | 0.484 |
| 2022 | A_offer | 636 | 50.6% | 0.599 |
| 2022 | A_retail | 636 | 40.6% | 0.478 |
| 2022 | B_post_report | 459 | 37.9% | 0.464 |
| 2023 | A_offer | 842 | 41.9% | 0.494 |
| 2023 | A_retail | 842 | 32.9% | 0.390 |
| 2023 | B_post_report | 639 | 30.4% | 0.392 |
| 2024 | A_offer | 879 | 41.2% | 0.489 |
| 2024 | A_retail | 879 | 32.4% | 0.385 |
| 2024 | B_post_report | 674 | 29.7% | 0.383 |
| 2025 | A_offer | 919 | 40.3% | 0.477 |
| 2025 | A_retail | 919 | 32.0% | 0.377 |
| 2025 | B_post_report | 711 | 29.4% | 0.384 |

### Retail access — decide after the first-day close, buy at the 2nd-day open (PRIMARY)

- Eligible IPOs: **1205**. Initial recommendations: NO_DECISION 380, BUY 330, WAIT 265, AVOID 216, ABSTAIN 14. Final actions: NO_TRADE 844, BUY 361.
- BUY trades: **361** (31 after a watchlist wait). **Abstention rate: 70.0%**.
- Hard gates triggered: MICRO_DEAL 74, PENNY_PRICE 47, CRITICAL_DATA_MISSING 14. No decision possible: no_price_history 380.
- Of 351 BUYs with a complete 12-month outcome, **93 beat SPY (26.5%)** and **258 were false positives (73.5%)**.
- Base rate: 27.5% of 816 eligible IPOs beat SPY when bought at the same entry. **Missed winners: 132 of 224 (58.9%)**; losers avoided: 332 (56.1%).

| Horizon | Group | n | incomplete | delisted before horizon | mean net return | median | SPY same dates | mean excess vs SPY [95%] | vs sector ETF | vs IWM | vs IPO ETF | % beating SPY | volatility | worst | 5th pct |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1m | Strategy BUYs | 361 | 0 | 0 | 1.9% | 1.2% | 1.9% | 0.1% [-2.5%, 3.1%] | -0.1% | 0.3% | 1.1% | 48.2% | 22.5% | -81.3% | -31.4% |
| 1m | Buy every eligible IPO | 825 | 0 | 0 | -0.8% | -1.3% | 1.5% | -2.2% [-4.8%, 0.4%] | -2.3% | -1.8% | -1.2% | 41.9% | 30.1% | -97.5% | -42.8% |
| 1m | Simple screen | 505 | 0 | 0 | 2.5% | 1.3% | 1.8% | 0.6% [-1.9%, 3.3%] | 0.6% | 0.9% | 1.4% | 47.9% | 20.8% | -72.6% | -29.3% |
| 1m | *Strategy minus buy-all* | 361 vs 825 | | | | | | 2.3% [0.0%, 4.7%] | | | | | | | |
| 1m | *Strategy minus simple screen* | 361 vs 505 | | | | | | -0.6% [-2.4%, 1.5%] | | | | | | | |
| 3m | Strategy BUYs | 361 | 0 | 0 | -0.1% | -3.6% | 4.3% | -4.4% [-9.7%, 1.4%] | -4.3% | -3.7% | -2.1% | 37.1% | 40.8% | -93.1% | -52.3% |
| 3m | Buy every eligible IPO | 825 | 0 | 0 | -1.6% | -6.4% | 3.7% | -5.3% [-12.5%, 2.2%] | -5.0% | -4.5% | -2.9% | 33.7% | 56.6% | -99.1% | -65.1% |
| 3m | Simple screen | 505 | 0 | 0 | 3.9% | -3.0% | 4.5% | -0.6% [-8.3%, 8.4%] | -0.1% | -0.3% | 0.8% | 38.0% | 51.1% | -79.8% | -48.9% |
| 3m | *Strategy minus buy-all* | 361 vs 825 | | | | | | 0.9% [-3.8%, 5.4%] | | | | | | | |
| 3m | *Strategy minus simple screen* | 361 vs 505 | | | | | | -3.8% [-10.4%, 1.8%] | | | | | | | |
| 6m | Strategy BUYs | 361 | 0 | 0 | -6.2% | -10.4% | 7.9% | -14.1% [-20.2%, -6.5%] | -13.5% | -12.2% | -8.2% | 31.9% | 48.0% | -94.5% | -70.4% |
| 6m | Buy every eligible IPO | 825 | 0 | 0 | -8.1% | -14.6% | 7.0% | -15.1% [-22.2%, -7.2%] | -14.9% | -13.4% | -9.2% | 31.5% | 56.8% | -99.1% | -77.3% |
| 6m | Simple screen | 505 | 0 | 0 | -4.5% | -8.7% | 8.2% | -12.7% [-20.3%, -4.0%] | -12.1% | -11.8% | -7.6% | 33.7% | 48.1% | -85.9% | -68.0% |
| 6m | *Strategy minus buy-all* | 361 vs 825 | | | | | | 1.0% [-4.1%, 6.1%] | | | | | | | |
| 6m | *Strategy minus simple screen* | 361 vs 505 | | | | | | -1.4% [-6.3%, 3.3%] | | | | | | | |
| 12m | Strategy BUYs | 351 | 10 | 0 | -5.1% | -20.7% | 13.3% | -18.5% [-28.8%, -4.8%] | -16.7% | -12.8% | -8.1% | 26.5% | 68.6% | -95.3% | -80.1% |
| 12m | Buy every eligible IPO | 816 | 9 | 0 | -9.6% | -25.1% | 12.1% | -21.7% [-31.6%, -9.9%] | -21.0% | -16.4% | -12.2% | 27.5% | 79.3% | -99.5% | -88.1% |
| 12m | Simple screen | 499 | 6 | 0 | -4.0% | -16.9% | 12.9% | -16.9% [-27.8%, -2.8%] | -15.7% | -12.0% | -6.0% | 29.7% | 70.6% | -95.3% | -80.3% |
| 12m | *Strategy minus buy-all* | 351 vs 816 | | | | | | 3.2% [-2.1%, 8.9%] | | | | | | | |
| 12m | *Strategy minus simple screen* | 351 vs 499 | | | | | | -1.6% [-7.3%, 3.3%] | | | | | | | |

| Year | BUY n | BUY mean excess 12m | BUY % beating SPY | all-IPO n | all-IPO mean excess |
|---|--:|--:|--:|--:|--:|
| 2016 | 18 | 0.3% | 44.4% | 44 | 4.4% |
| 2017 | 16 | 17.4% | 43.8% | 64 | 18.6% |
| 2018 | 31 | -6.0% | 29.0% | 90 | -17.0% |
| 2019 | 31 | 33.8% | 45.2% | 72 | 19.2% |
| 2020 | 34 | -19.8% | 29.4% | 118 | -14.3% |
| 2021 | 87 | -49.9% | 4.6% | 212 | -49.6% |
| 2022 | 3 | 1.5% | 33.3% | 40 | -38.6% |
| 2023 | 25 | -21.3% | 32.0% | 40 | -48.5% |
| 2024 | 52 | -18.1% | 30.8% | 72 | -21.3% |
| 2025 | 54 | -21.3% | 29.6% | 64 | -26.7% |

Walk-forward Brier 0.2418 vs base-rate reference 0.1974 (skill -0.225, n = 802).

### Offer-price access — hypothetical allocation at the offer price

- Eligible IPOs: **1205**. Initial recommendations: BUY 451, WAIT 446, AVOID 288, ABSTAIN 20. Final actions: NO_TRADE 754, BUY 332, BUY_NO_PRICE_DATA 119.
- BUY trades: **332** (0 after a watchlist wait). **Abstention rate: 72.4%**.
- Hard gates triggered: MICRO_DEAL 94, CRITICAL_DATA_MISSING 19, DATA_INCONSISTENT 1. No decision possible: none.
- Of 324 BUYs with a complete 12-month outcome, **131 beat SPY (40.4%)** and **193 were false positives (59.6%)**.
- Base rate: 36.0% of 816 eligible IPOs beat SPY when bought at the same entry. **Missed winners: 163 of 294 (55.4%)**; losers avoided: 329 (63.0%).

| Horizon | Group | n | incomplete | delisted before horizon | mean net return | median | SPY same dates | mean excess vs SPY [95%] | vs sector ETF | vs IWM | vs IPO ETF | % beating SPY | volatility | worst | 5th pct |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1m | Strategy BUYs | 332 | 0 | 0 | 31.2% | 20.1% | 1.6% | 29.7% [21.1%, 39.5%] | 29.4% | 29.9% | 30.7% | 71.1% | 57.1% | -80.9% | -26.9% |
| 1m | Buy every eligible IPO | 825 | 0 | 0 | 27.6% | 12.5% | 1.4% | 26.2% [17.0%, 36.7%] | 26.1% | 26.6% | 27.3% | 61.9% | 112.5% | -91.8% | -43.6% |
| 1m | Simple screen | 505 | 0 | 0 | 39.9% | 21.5% | 1.7% | 38.2% [25.6%, 53.3%] | 38.1% | 38.4% | 39.0% | 73.5% | 133.8% | -56.8% | -21.1% |
| 1m | *Strategy minus buy-all* | 332 vs 825 | | | | | | 3.4% [-6.2%, 11.2%] | | | | | | | |
| 1m | *Strategy minus simple screen* | 332 vs 505 | | | | | | -8.5% [-22.6%, 0.7%] | | | | | | | |
| 3m | Strategy BUYs | 332 | 0 | 0 | 27.4% | 14.3% | 4.1% | 23.4% [12.3%, 35.6%] | 23.6% | 24.1% | 25.9% | 57.8% | 67.4% | -93.7% | -44.6% |
| 3m | Buy every eligible IPO | 825 | 0 | 0 | 26.0% | 6.5% | 3.7% | 22.3% [8.1%, 36.6%] | 22.6% | 23.1% | 24.7% | 52.5% | 116.2% | -98.3% | -65.5% |
| 3m | Simple screen | 505 | 0 | 0 | 40.0% | 17.1% | 4.4% | 35.6% [18.7%, 54.6%] | 36.0% | 35.9% | 37.0% | 61.0% | 123.7% | -76.9% | -36.5% |
| 3m | *Strategy minus buy-all* | 332 vs 825 | | | | | | 1.0% [-8.7%, 8.9%] | | | | | | | |
| 3m | *Strategy minus simple screen* | 332 vs 505 | | | | | | -12.2% [-24.8%, -2.0%] | | | | | | | |
| 6m | Strategy BUYs | 332 | 0 | 0 | 17.3% | 9.8% | 7.7% | 9.6% [-0.4%, 20.9%] | 10.1% | 11.3% | 15.9% | 50.0% | 63.3% | -95.0% | -65.3% |
| 6m | Buy every eligible IPO | 825 | 0 | 0 | 14.5% | -1.1% | 7.0% | 7.5% [-5.4%, 21.9%] | 7.8% | 9.2% | 13.4% | 44.4% | 101.4% | -98.9% | -76.5% |
| 6m | Simple screen | 505 | 0 | 0 | 26.0% | 9.7% | 8.2% | 17.9% [2.6%, 36.2%] | 18.5% | 18.7% | 23.0% | 50.9% | 112.0% | -85.0% | -61.5% |
| 6m | *Strategy minus buy-all* | 332 vs 825 | | | | | | 2.1% [-6.9%, 9.5%] | | | | | | | |
| 6m | *Strategy minus simple screen* | 332 vs 505 | | | | | | -8.2% [-20.8%, 1.8%] | | | | | | | |
| 12m | Strategy BUYs | 324 | 8 | 0 | 22.1% | 0.6% | 13.1% | 9.0% [-5.8%, 28.0%] | 10.4% | 14.6% | 19.9% | 40.4% | 93.9% | -95.3% | -77.9% |
| 12m | Buy every eligible IPO | 816 | 9 | 0 | 14.2% | -14.1% | 12.1% | 2.2% [-13.4%, 20.1%] | 2.8% | 7.4% | 11.6% | 36.0% | 130.4% | -99.7% | -87.3% |
| 12m | Simple screen | 499 | 6 | 0 | 29.3% | 0.8% | 12.9% | 16.4% [-3.3%, 40.8%] | 17.6% | 21.3% | 27.3% | 42.1% | 144.4% | -94.6% | -77.2% |
| 12m | *Strategy minus buy-all* | 324 vs 816 | | | | | | 6.9% [-3.8%, 17.3%] | | | | | | | |
| 12m | *Strategy minus simple screen* | 324 vs 499 | | | | | | -7.4% [-22.5%, 4.5%] | | | | | | | |

| Year | BUY n | BUY mean excess 12m | BUY % beating SPY | all-IPO n | all-IPO mean excess |
|---|--:|--:|--:|--:|--:|
| 2016 | 10 | 50.6% | 80.0% | 44 | 28.3% |
| 2017 | 21 | 50.1% | 71.4% | 64 | 35.8% |
| 2018 | 20 | 38.5% | 55.0% | 90 | 17.6% |
| 2019 | 29 | 89.3% | 58.6% | 72 | 54.8% |
| 2020 | 32 | 32.2% | 59.4% | 118 | 46.4% |
| 2021 | 77 | -37.3% | 10.4% | 212 | -39.7% |
| 2022 | 2 | 28.8% | 100.0% | 40 | -40.1% |
| 2023 | 24 | -7.5% | 29.2% | 40 | -39.8% |
| 2024 | 54 | -0.1% | 40.7% | 72 | -10.6% |
| 2025 | 55 | -0.5% | 40.0% | 64 | -6.3% |

Walk-forward Brier 0.2717 vs base-rate reference 0.2294 (skill -0.184, n = 802).

### Retail access — decide after the first 10-Q/10-K, buy at the next open

- Eligible IPOs: **1118**. Initial recommendations: NO_DECISION 337, AVOID 264, WAIT 190, BUY 181, ABSTAIN 146. Final actions: NO_TRADE 931, BUY 187.
- BUY trades: **187** (6 after a watchlist wait). **Abstention rate: 83.3%**.
- Hard gates triggered: FINANCIALS_MISSING_OR_STALE 140, PENNY_PRICE 78, MICRO_DEAL 71, CASH_RUNWAY 9, CRITICAL_DATA_MISSING 6. No decision possible: no_price_history 337.
- Of 174 BUYs with a complete 12-month outcome, **57 beat SPY (32.8%)** and **117 were false positives (67.2%)**.
- Base rate: 25.2% of 757 eligible IPOs beat SPY when bought at the same entry. **Missed winners: 133 of 191 (69.6%)**; losers avoided: 450 (79.5%).

| Horizon | Group | n | incomplete | delisted before horizon | mean net return | median | SPY same dates | mean excess vs SPY [95%] | vs sector ETF | vs IWM | vs IPO ETF | % beating SPY | volatility | worst | 5th pct |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1m | Strategy BUYs | 187 | 0 | 0 | -1.8% | -3.0% | 1.4% | -3.2% [-6.7%, 0.3%] | -3.2% | -2.7% | -3.3% | 34.8% | 16.4% | -44.0% | -26.4% |
| 1m | Buy every eligible IPO | 781 | 0 | 0 | -0.6% | -3.0% | 1.3% | -1.9% [-6.4%, 3.7%] | -1.6% | -1.7% | -2.0% | 37.3% | 39.2% | -88.1% | -35.9% |
| 1m | Simple screen | 116 | 0 | 0 | -0.9% | -2.2% | 1.6% | -2.5% [-5.8%, 1.2%] | -2.2% | -2.2% | -3.6% | 38.8% | 14.7% | -39.9% | -24.1% |
| 1m | *Strategy minus buy-all* | 187 vs 781 | | | | | | -1.3% [-6.3%, 3.0%] | | | | | | | |
| 1m | *Strategy minus simple screen* | 187 vs 116 | | | | | | -0.8% [-3.0%, 1.6%] | | | | | | | |
| 3m | Strategy BUYs | 187 | 0 | 0 | -3.0% | -2.8% | 4.1% | -7.1% [-13.3%, -0.9%] | -7.1% | -6.3% | -5.6% | 35.3% | 29.6% | -76.0% | -48.4% |
| 3m | Buy every eligible IPO | 781 | 0 | 0 | -3.6% | -7.5% | 4.0% | -7.6% [-15.0%, 2.0%] | -7.2% | -7.5% | -6.7% | 32.4% | 49.8% | -95.6% | -57.6% |
| 3m | Simple screen | 116 | 0 | 0 | -0.2% | -2.3% | 4.5% | -4.7% [-10.4%, 1.8%] | -4.4% | -4.7% | -4.1% | 36.2% | 28.1% | -52.7% | -41.0% |
| 3m | *Strategy minus buy-all* | 187 vs 781 | | | | | | 0.5% [-6.8%, 6.8%] | | | | | | | |
| 3m | *Strategy minus simple screen* | 187 vs 116 | | | | | | -2.4% [-6.5%, 1.5%] | | | | | | | |
| 6m | Strategy BUYs | 187 | 0 | 0 | -2.6% | -7.3% | 6.6% | -9.2% [-16.8%, -0.3%] | -8.0% | -6.0% | -3.6% | 34.2% | 47.7% | -79.1% | -63.9% |
| 6m | Buy every eligible IPO | 781 | 0 | 0 | -8.7% | -15.3% | 6.4% | -15.1% [-21.6%, -6.8%] | -14.7% | -13.0% | -9.5% | 27.9% | 56.9% | -96.9% | -73.2% |
| 6m | Simple screen | 116 | 0 | 0 | 0.8% | 0.8% | 6.7% | -5.9% [-13.5%, 3.2%] | -4.5% | -5.0% | 0.4% | 36.2% | 43.0% | -79.1% | -52.7% |
| 6m | *Strategy minus buy-all* | 187 vs 781 | | | | | | 5.8% [0.2%, 11.4%] | | | | | | | |
| 6m | *Strategy minus simple screen* | 187 vs 116 | | | | | | -3.4% [-11.1%, 5.1%] | | | | | | | |
| 12m | Strategy BUYs | 174 | 13 | 0 | 0.1% | -10.8% | 12.0% | -11.9% [-21.5%, 0.6%] | -10.2% | -5.3% | -3.6% | 32.8% | 63.5% | -91.2% | -76.6% |
| 12m | Buy every eligible IPO | 757 | 24 | 0 | -11.4% | -27.6% | 11.4% | -22.8% [-33.5%, -9.4%] | -22.4% | -17.1% | -11.4% | 25.2% | 82.7% | -99.2% | -87.5% |
| 12m | Simple screen | 107 | 9 | 0 | -1.6% | -7.8% | 11.7% | -13.3% [-22.7%, -2.7%] | -11.0% | -8.0% | -1.3% | 37.4% | 53.7% | -81.6% | -73.2% |
| 12m | *Strategy minus buy-all* | 174 vs 757 | | | | | | 10.9% [4.0%, 18.2%] | | | | | | | |
| 12m | *Strategy minus simple screen* | 174 vs 107 | | | | | | 1.4% [-8.3%, 13.6%] | | | | | | | |

| Year | BUY n | BUY mean excess 12m | BUY % beating SPY | all-IPO n | all-IPO mean excess |
|---|--:|--:|--:|--:|--:|
| 2017 | 9 | -3.5% | 44.4% | 64 | 13.1% |
| 2018 | 21 | -4.6% | 23.8% | 90 | -18.0% |
| 2019 | 18 | 37.0% | 50.0% | 72 | 18.8% |
| 2020 | 9 | -16.2% | 33.3% | 118 | -21.9% |
| 2021 | 38 | -39.6% | 13.2% | 212 | -46.8% |
| 2022 | 4 | -2.9% | 50.0% | 40 | -33.4% |
| 2023 | 22 | -21.2% | 40.9% | 40 | -52.3% |
| 2024 | 32 | -7.6% | 34.4% | 72 | -18.3% |
| 2025 | 21 | -11.1% | 42.9% | 49 | -11.8% |

Walk-forward Brier 0.2097 vs base-rate reference 0.1903 (skill -0.102, n = 614).

## 10. Development-stage results (seen before the freeze)

**Validation period 2017–2018, models fitted on 2012–2016 only** (run `validation-cf30422e43`). This is where λ and the buy threshold were chosen, so it flatters the chosen settings.

- A_retail: BUY n = 69, mean 12-month excess 5.0% [-12.1%, 20.7%]; buy-all n = 154, mean excess -2.2% [-17.5%, 14.2%]; Brier skill -0.044
- A_offer: BUY n = 27, mean 12-month excess 55.3% [26.0%, 87.7%]; buy-all n = 154, mean excess 25.2% [1.5%, 47.4%]; Brier skill +0.031
- B_post_report: BUY n = 54, mean 12-month excess -7.0% [-22.4%, 10.8%]; buy-all n = 154, mean excess -5.1% [-18.8%, 12.6%]; Brier skill -0.023

**Embargo year 2019 with the final rules** (out-of-sample, but seen before the freeze; run `pretest-da632f63fb`):

- A_retail: BUY n = 42, mean 12-month excess 23.1% [-12.5%, 88.0%]; buy-all n = 72, mean excess 19.2% [-16.6%, 69.5%]
- A_offer: BUY n = 26, mean 12-month excess 105.5% [52.5%, 304.5%]; buy-all n = 72, mean excess 54.8% [3.5%, 101.1%]
- B_post_report: BUY n = 28, mean 12-month excess 61.4% [13.4%, 131.7%]; buy-all n = 72, mean excess 18.8% [-11.4%, 60.5%]

## 11. Limitations

**These limit what the numbers above can be taken to mean. The first is disqualifying on its own.**

1. **Survivorship in the price data.** Yahoo Finance removes price history for delisted symbols. Price history exists for 60% of all eligible IPOs and 78% of test-period IPOs. Of 533 IPOs later acquired only 9 have prices; of 106 that went bankrupt only 12 do. Every return in this report is therefore conditional on the company's symbol still existing at the snapshot. The direction of the bias is not known (acquisitions usually carry premiums; bankruptcies are near-total losses), and it need not be the same for the strategy as for the baselines. Other free sources were tried and failed at a named point: Stooq serves a browser-verification challenge to automated clients (not circumvented); stockanalysis.com redirects delisted symbols to the acquirer's page; Nasdaq's quote API answers "Symbol not exists" for delisted symbols. **Cheapest fix:** a survivorship-free daily price file (CRSP, Norgate, Sharadar, EODHD, or Tiingo's free tier at ~50 symbols/hour) keyed by the CIK/ticker/date columns already in `data/processed/universe.csv`, then re-run `build`, `test` and `report` with the same frozen rules.
2. **No prospectus financials at the IPO date.** SEC's XBRL API carries no facts filed before pricing for most IPOs (96 of 1971 eligible IPOs have any), and requests to `www.sec.gov` were refused (HTTP 403) for a client that sends no contact address, so prospectus documents in the EDGAR archives were not retrieved. The at-IPO models therefore see deal terms and market conditions only. The web app accepts hand-typed prospectus financials at the IPO stage, and its calculations and gates on them are unit-tested, but their effect on recommendations at the IPO stage has **no historical test** here.
3. **Gates that could not be exercised historically.** Going-concern doubt is not available as a machine-readable historical field, and option/warrant strike prices are not either (the backtest uses the count of anti-dilutive securities reported in the first 10-Q/10-K as a strike-zero upper bound on dilution). These paths are covered by unit tests only.
4. **Author hindsight.** The code was written by a language model whose training data covers this period. Weights and thresholds were fitted mechanically on pre-2020 outcomes and the gates follow listing conventions, but the choice of features, exclusions and model family cannot be proven free of hindsight.
5. **Mild point-in-time approximations.** SIC codes and the Nasdaq deal record (shares outstanding, employees, expenses) are read as they stand today and are assumed unchanged since the IPO; the first-report decision uses the filing date and assumes the report was public by that day's close; the watchlist re-evaluates with new prices but keeps fundamentals and market conditions fixed at the decision date.
6. **Execution realism.** Entries use the official open of a daily bar; opening auctions of newly listed stocks can be thin, and 25 bps per side may understate costs for small floats (see the 50 and 100 bps rows). Offer-price access assumes a full allocation in every IPO, which retail investors do not receive, least of all in the deals that open strongly; the offer-price results are an upper bound on what allocation access could have delivered.
7. **Delisting outcomes are implemented but were not exercised by real data.** When a price series ends before a horizon, the position is closed at the last price less a haircut that depends on the SEC-derived reason. In the test period this happened 0 times across all groups and horizons: a company that delists loses its entire price history at the vendor, so it drops out of the sample instead of appearing as a delisting. The logic is covered by synthetic-data tests only, which is why the delisting sensitivity rows do not move.
8. **Sample size and overlap.** Twelve-month windows overlap heavily and IPOs cluster in hot markets (2020–2021 dominate the test period), so the effective number of independent observations is far below the trade count. Intervals are clustered by entry quarter; sub-group tables are descriptive only. Secondary analyses are not adjusted for multiple comparisons.
9. **Universe.** US-listed operating-company IPOs with an offer price of at least $5. Foreign private issuers, SPACs, units, funds, sub-$5 offerings and uplistings are excluded; conclusions do not extend to them. Sector benchmarks are broad SPDR sector ETFs chosen by SIC code, an approximation (biotechnology IPOs are compared with XLV, for example).

## 12. Reproduce

```bash
cd ipo-evaluator
pip install -r requirements.txt
python -m pytest tests -q                    # calculation, dilution, missing-data, gate, price-sensitivity and backtest-integrity tests
python -m ipo_app.data.fetch all             # re-download raw data (about an hour; hosts listed in README)
python -m ipo_app.data.build                 # processed dataset + provenance hashes
python -m ipo_app.backtest.run develop       # fit on dev, select on validation (test stays sealed)
python -m ipo_app.backtest.run test          # frozen rules on the held-out period, sensitivity, walk-forward
python -m ipo_app.backtest.report            # this report, verdict.json, static dashboard
python -m ipo_app.server                     # dashboard at http://127.0.0.1:8765
```

A run id is a hash of the rule hash, data hash and configuration; the same three inputs reproduce the same run id and the same numbers (the bootstrap is seeded). Vendor price data is not redistributed in the repository, so a rebuild uses a fresh download and its data hash will differ from the one recorded here; prices for symbols delisted in the meantime will be gone.
