# Pre-registration — what counts as success, written before the test period is unsealed

This file and the frozen rule file `rules/v1.0.0.json` are committed to git **before**
`python -m ipo_app.backtest.run test` is executed. The code refuses to unseal the test period
unless both are committed (`run.py: cmd_test`), and `results/freeze_ledger.json` records every
unsealing. If the rules are changed after an unsealing, the 2020+ period is no longer held out for
the new version and reports must say so.

## Periods (by IPO pricing date)

| Period | Dates | Use |
|---|---|---|
| Development | 2012-01-01 → 2016-12-31 | fit model coefficients |
| Validation | 2017-01-01 → 2018-12-31 | choose L2 strength and buy threshold from the grids below |
| Embargo | 2019-01-01 → 2019-12-31 | never used for fitting (12-month labels would overlap the test period); reported as an out-of-sample check seen before the freeze |
| **Held-out test** | 2020-01-01 → data snapshot | evaluated once, with frozen rules |

Training labels are subject to an embargo: an IPO contributes to a fit only if its 12-month exit
date is strictly before the first day of the period being evaluated.

## What is fixed in advance

- **Hard gates** (never tuned): price < $5; offering < $15M; going-concern doubt; pro-forma cash
  runway < 6 months; critical inputs missing or inconsistent → abstain; SPAC/unit/fund → ineligible.
- **Model family**: L2-penalised logistic regression on the feature lists in
  `ipo_app/backtest/train.py`; label = "12-month net return after an immediate entry beats SPY over
  the same dates".
- **Hyper-parameter grids**: λ ∈ {1, 10, 100} chosen by lowest validation Brier score; buy threshold
  = the q-th quantile of training-set probabilities, q ∈ {0.5, 0.6, 0.7, 0.8, 0.9}, chosen by highest
  validation mean 12-month excess return among IPOs at/above the threshold (at least 10% of
  validation IPOs must qualify); avoid threshold = 30th percentile (fixed).
- **Walk-forward** uses λ = 10, q = 0.70 for every fold (no per-fold tuning): fit on outcomes known
  before 1 January of year Y, decide the IPOs priced in Y, for Y = 2016 … 2025.
- **Execution**: entry at the open of the 2nd trading day (retail, stage A), at the offer price
  (allocation access), or at the open after the first 10-Q/10-K filing date (stage B). 25 bps per
  side on IPO shares, 2 bps per side on ETFs, total-return prices (dividends and splits included),
  delisting before a horizon exits at the last price less a haircut (bankruptcy 100%, exchange
  removal/unknown 30%, merger 0%), then cash.
- **Baselines**: (1) buy every eligible IPO at the same entry; (2) SPY over the same dates;
  (3) sector ETF by SIC code; also IWM and the Renaissance IPO ETF; (4) simple screens fixed here:
  stage A — offering ≥ $100M; stage B — annualised revenue ≥ $100M and positive net income.
- **Horizons**: 21 / 63 / 126 / 252 trading days after entry ("1/3/6/12 months").
- **Incomplete observations**: if the horizon date is after the data snapshot the observation is
  *incomplete at that horizon*: it is counted and reported but is neither a success nor a failure.

## Primary endpoint (the only one that can support a claim of advantage)

Mode **A_retail** (ordinary retail access, decision after the first-day close, entry at the open of
the second trading day), **12-month horizon**, held-out test period, net of costs.

- **H1 — absolute edge.** Mean excess return of the strategy's BUY trades over SPY (same dates) is
  positive and the 95% interval (bootstrap clustered by entry quarter, 2,000 resamples, fixed seed)
  excludes zero.
- **H2 — selection skill.** Mean excess return of BUY trades minus mean excess return of buying
  every eligible IPO is positive and its 95% clustered interval excludes zero.
- **H3 — probabilities.** Test-period Brier score is below the base-rate reference (skill > 0).

Guardrails (all required for a positive verdict):

1. At least 30 BUY trades with complete 12-month outcomes, spread over at least 8 entry quarters.
2. Mean excess return stays positive after removing the best 5% of BUY trades.
3. Mean excess return stays positive at 50 bps per side.
4. Price history is available for at least **90%** of eligible test-period IPOs. Below that, the
   sample is conditioned on survival in the price vendor's database and no advantage may be claimed.

## Verdict rule

| Verdict | Condition |
|---|---|
| **SUPPORTED** | H1 and H2 hold and all four guardrails hold |
| **NOT SUPPORTED** | the 95% interval for H1 or for H2 lies entirely below zero |
| **INCONCLUSIVE** | anything else |

Independently of the verdict on H1/H2, the application is labelled **NOT HISTORICALLY VALIDATED**
unless the verdict is SUPPORTED. Guardrail 4 failing forces that label on its own.

Secondary analyses (offer-price access, stage B, other horizons and benchmarks, sector / year /
regime splits, walk-forward, sensitivity, calibration tables) are reported in full but cannot
upgrade the verdict. They are not corrected for multiplicity and must be read as descriptive.

## Known threats acknowledged before looking

- The author is a language model that has read about these years. Mitigation: no hand-set weights
  or thresholds, mechanical inputs, algorithmic selection on pre-2020 data only.
- Price history comes from a vendor that deletes delisted symbols; coverage will be measured and
  reported by SEC-derived outcome class before any return is computed.
- Prospectus financial statements could not be extracted mechanically; the stage-A model sees deal
  terms and market state only. The app's use of user-typed prospectus financials at the IPO stage
  is therefore outside what this backtest can validate.
