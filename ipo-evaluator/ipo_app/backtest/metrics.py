"""Statistics for the backtest. Pure numpy/pandas; all randomness is seeded."""
from __future__ import annotations

import numpy as np
import pandas as pd

SEED = 20261117


def _clean(x):
    x = np.asarray(x, dtype=float)
    return x[np.isfinite(x)]


def summarize(ret, bench) -> dict:
    """Fixed-horizon summary of net returns against a same-dates benchmark."""
    ret, bench = np.asarray(ret, float), np.asarray(bench, float)
    ok = np.isfinite(ret) & np.isfinite(bench)
    r, b = ret[ok], bench[ok]
    if len(r) == 0:
        return {"n": 0}
    ex = r - b
    return {"n": int(len(r)), "mean_ret": float(r.mean()), "median_ret": float(np.median(r)),
            "mean_bench": float(b.mean()), "mean_excess": float(ex.mean()), "median_excess": float(np.median(ex)),
            "pct_outperform": float((ex > 0).mean()), "pct_positive": float((r > 0).mean()),
            "std_ret": float(r.std(ddof=1)) if len(r) > 1 else None,
            "worst": float(r.min()), "p05": float(np.percentile(r, 5)), "p95": float(np.percentile(r, 95)),
            "best": float(r.max()), "pct_lost_half": float((r <= -0.5).mean())}


def cluster_bootstrap(values, clusters, stat=np.mean, n_boot=2000, seed=SEED):
    """Bootstrap that resamples whole clusters (entry quarters). IPOs entered in the same quarter
    share market exposure over heavily overlapping holding windows, so they are not independent
    draws; resampling quarters keeps that dependence inside each resampled block."""
    values, clusters = np.asarray(values, float), np.asarray(clusters)
    ok = np.isfinite(values)
    values, clusters = values[ok], clusters[ok]
    if len(values) == 0:
        return {"n": 0, "n_clusters": 0}
    groups = [values[clusters == c] for c in pd.unique(clusters)]
    rng = np.random.default_rng(seed)
    k = len(groups)
    boots = np.empty(n_boot)
    for i in range(n_boot):
        pick = rng.integers(0, k, k)
        boots[i] = stat(np.concatenate([groups[j] for j in pick]))
    return {"n": int(len(values)), "n_clusters": int(k), "estimate": float(stat(values)),
            "ci_lo": float(np.percentile(boots, 2.5)), "ci_hi": float(np.percentile(boots, 97.5)),
            "p_le_zero": float((boots <= 0).mean())}


def cluster_bootstrap_diff(a_vals, a_clu, b_vals, b_clu, n_boot=2000, seed=SEED):
    """Difference in means between two groups observed in the same quarters (e.g. the strategy's
    buys vs buying every eligible IPO); quarters are resampled jointly so shared exposure cancels."""
    a_vals, b_vals = np.asarray(a_vals, float), np.asarray(b_vals, float)
    a_clu, b_clu = np.asarray(a_clu), np.asarray(b_clu)
    oa, ob = np.isfinite(a_vals), np.isfinite(b_vals)
    a_vals, a_clu, b_vals, b_clu = a_vals[oa], a_clu[oa], b_vals[ob], b_clu[ob]
    if len(a_vals) == 0 or len(b_vals) == 0:
        return {"n_a": int(len(a_vals)), "n_b": int(len(b_vals))}
    keys = list(pd.unique(np.concatenate([a_clu, b_clu])))
    ga = {c: a_vals[a_clu == c] for c in keys}
    gb = {c: b_vals[b_clu == c] for c in keys}
    rng = np.random.default_rng(seed)
    boots = []
    for _ in range(n_boot):
        pick = [keys[j] for j in rng.integers(0, len(keys), len(keys))]
        xa = np.concatenate([ga[c] for c in pick])
        xb = np.concatenate([gb[c] for c in pick])
        if len(xa) and len(xb):
            boots.append(xa.mean() - xb.mean())
    boots = np.array(boots)
    return {"n_a": int(len(a_vals)), "n_b": int(len(b_vals)), "n_clusters": len(keys),
            "estimate": float(a_vals.mean() - b_vals.mean()),
            "ci_lo": float(np.percentile(boots, 2.5)), "ci_hi": float(np.percentile(boots, 97.5)),
            "p_le_zero": float((boots <= 0).mean())}


def newey_west_alpha(y, x, lags=3) -> dict:
    """OLS of y on [1, x] with Newey–West (HAC) standard errors. y, x: monthly excess returns."""
    y, x = np.asarray(y, float), np.asarray(x, float)
    ok = np.isfinite(y) & np.isfinite(x)
    y, x = y[ok], x[ok]
    n = len(y)
    if n < 12:
        return {"n_months": int(n)}
    X = np.column_stack([np.ones(n), x])
    XtX_inv = np.linalg.inv(X.T @ X)
    beta = XtX_inv @ X.T @ y
    e = y - X @ beta
    S = (X * e[:, None]).T @ (X * e[:, None])
    for l in range(1, lags + 1):
        w = 1.0 - l / (lags + 1.0)
        G = (X[l:] * e[l:, None]).T @ (X[:-l] * e[:-l, None])
        S += w * (G + G.T)
    cov = XtX_inv @ S @ XtX_inv * n / (n - 2)
    se = np.sqrt(np.diag(cov))
    return {"n_months": int(n), "alpha_monthly": float(beta[0]), "alpha_annualized": float(beta[0] * 12),
            "alpha_t": float(beta[0] / se[0]), "beta": float(beta[1]), "beta_t": float(beta[1] / se[1])}


def brier(p, y) -> dict:
    """Brier score with its reliability decomposition against two references: the outcome base rate
    of the evaluated sample (uninformed-but-calibrated forecaster) and a fixed 0.5 forecast."""
    p, y = np.asarray(p, float), np.asarray(y, float)
    ok = np.isfinite(p) & np.isfinite(y)
    p, y = p[ok], y[ok]
    if len(p) == 0:
        return {"n": 0}
    bs = float(np.mean((p - y) ** 2))
    base = float(y.mean())
    ref = float(np.mean((base - y) ** 2))
    return {"n": int(len(p)), "brier": bs, "base_rate": base, "mean_forecast": float(p.mean()),
            "brier_base_rate_reference": ref, "brier_coinflip_reference": float(np.mean((0.5 - y) ** 2)),
            "skill_vs_base_rate": float(1.0 - bs / ref) if ref > 0 else None}


def calibration_table(p, y, bins=5) -> list[dict]:
    p, y = np.asarray(p, float), np.asarray(y, float)
    ok = np.isfinite(p) & np.isfinite(y)
    p, y = p[ok], y[ok]
    if len(p) < bins:
        return []
    edges = np.quantile(p, np.linspace(0, 1, bins + 1))
    idx = np.clip(np.searchsorted(edges, p, side="right") - 1, 0, bins - 1)
    out = []
    for b in range(bins):
        m = idx == b
        if m.sum():
            out.append({"bin": b + 1, "n": int(m.sum()), "p_lo": float(p[m].min()), "p_hi": float(p[m].max()),
                        "mean_forecast": float(p[m].mean()), "observed_rate": float(y[m].mean())})
    return out


def max_drawdown(equity) -> float:
    e = np.asarray(equity, float)
    if len(e) == 0:
        return 0.0
    peak = np.maximum.accumulate(e)
    return float((e / peak - 1.0).min())


def equity_stats(equity, dates) -> dict:
    e = np.asarray(equity, float)
    if len(e) < 3:
        return {"n_days": int(len(e))}
    r = e[1:] / e[:-1] - 1.0
    years = (pd.Timestamp(dates[-1]) - pd.Timestamp(dates[0])).days / 365.25
    return {"n_days": int(len(e)), "years": float(years), "total_return": float(e[-1] / e[0] - 1.0),
            "cagr": float((e[-1] / e[0]) ** (1 / years) - 1.0) if years > 0 else None,
            "ann_vol": float(r.std(ddof=1) * np.sqrt(252)), "max_drawdown": max_drawdown(e),
            "worst_day": float(r.min()), "final_equity": float(e[-1])}


def winner_dependence(ret, bench) -> dict:
    """How much of the average excess return comes from the best few trades."""
    ret, bench = np.asarray(ret, float), np.asarray(bench, float)
    ok = np.isfinite(ret) & np.isfinite(bench)
    ex = np.sort((ret - bench)[ok])[::-1]
    n = len(ex)
    if n < 5:
        return {"n": int(n)}
    k5 = max(1, int(round(n * 0.05)))
    out = {"n": int(n), "mean_excess": float(ex.mean()), "median_excess": float(np.median(ex)),
           "mean_excess_drop_top1": float(ex[1:].mean()), "mean_excess_drop_top5": float(ex[5:].mean()) if n > 5 else None,
           "mean_excess_drop_top5pct": float(ex[k5:].mean()), "top5pct_count": int(k5),
           "mean_excess_winsor_95": float(np.clip(ex, None, np.percentile(ex, 95)).mean())}
    tot = ex.sum()
    out["share_of_total_excess_from_top5pct"] = float(ex[:k5].sum() / tot) if tot > 0 else None
    return out
