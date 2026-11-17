# DECISIONS — journal of defaults taken during the run

One line each. These are choices, not facts; any of them can be overturned cheaply.

| # | Decision | Why | Overturn by |
|---|----------|-----|-------------|
| 1 | Build the IPO application from scratch in `ipo-evaluator/` | None existed; request asks for the working application | Point me at the real app and re-target the suite |
| 2 | Universe = every "priced" deal in the Nasdaq IPO calendar, 2012-01 → snapshot date | Mechanical, includes later-delisted/bankrupt names, not hand-picked | Swap in CRSP/SDC |
| 3 | Exclude SPACs/units, offer price < $5, non-major exchanges, foreign private issuers, prior-listed uplistings | Standard IPO-research conventions (Ritter); FPIs have no quarterly XBRL | Edit `data/build.py` eligibility |
| 4 | No vendor price snapshot is committed to the public repo; only derived, decision-level results | Yahoo terms; pushing is outward-facing | `git add -f data/snapshot` |
| 5 | Client identifies as a generic research client; no personal contact sent to any host | Privacy default | Provide a contact string for SEC to unlock `www.sec.gov/Archives` |
| 6 | Decision stages: **A** at IPO (deal terms + market state), **B** at first 10-Q/10-K after IPO (adds fundamentals) | S-1 financials are not mechanically reachable; first periodic report is | Add an S-1 parser |
| 7 | Probabilities come from an L2 logistic model fitted on the development period; author sets no weights | Removes LLM hindsight from rule design | Replace model spec in `rules/` |
| 8 | Hard gates fixed a priori: price < $5, deal < $15M, going-concern, runway < 6 months, inconsistent/missing critical data | Risk/data-sanity controls, never tuned | Change in rule file → new version |
| 9 | Primary pre-registered claim: Stage A, retail access, entry at open of 2nd trading day, 12-month horizon, excess vs SPY | One primary endpoint avoids a garden of forking paths | See PREREGISTRATION.md |
| 10 | Delisting before horizon: exit at last traded price with a haircut by reason (bankruptcy −100% floor option, performance −30%, merger 0%) | Shumway (1997) convention; varied in sensitivity | Rule-independent setting in backtest config |
| 11 | Costs: 25 bps per side on IPO shares (spread + slippage), 2 bps on ETFs, $0 commission; varied 0–100 bps | Early-trading spreads are wide; retail commissions are zero | Backtest config |
| 12 | Uncertainty: bootstrap clustered by entry quarter + calendar-time portfolio alpha with Newey–West errors | 12-month windows overlap and share market exposure | Stats module |

## After the test period was unsealed (2026-11-17)

Nothing that can change a decision was touched after unsealing: the rule file, its hash and the
backtest configuration are identical in every recorded test run, and re-running reproduces the same
run id. Reporting-only changes made after seeing results, listed for transparency:

| # | Change | Effect on results |
|---|--------|-------------------|
| 13 | Missing-price bounds table: the "every eligible IPO" row now includes IPOs the engine abstained on, matching the buy-all baseline elsewhere | bounds row n 533 → 546 observed; no change to any pre-registered criterion |
| 14 | Verdict text adds that H2 (less bad than buy-all) is not an advantage over the market, with the walk-forward figure | wording only |
| 15 | Limitation 7 now states how many delisting exits were actually observed (none) | wording only |
| 16 | Dashboard layout: wide tables moved below their charts | presentation only |
