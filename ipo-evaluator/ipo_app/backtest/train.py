"""Fits the probability models. The author sets no weights: coefficients come from an
L2-penalised logistic regression on IPOs whose 12-month outcome was fully realised BEFORE a
cutoff date (an embargo, so no label can overlap the period being evaluated)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..engine.calc import compute_metrics
from ..engine import recommend as R
from . import core as C

FEATS_A_OFFER = ["log_deal_size", "log_mcap_offer", "float_pct", "log_offer_price", "exch_tier",
                 "sec_health", "sec_tech", "sec_financial", "sec_energy", "sec_consumer",
                 "vix", "spy_ret_6m", "log_ipo_count_90d", "log_employees", "expense_ratio"]
FEATS_A_RETAIL = FEATS_A_OFFER + ["return_vs_offer"]
FEATS_B = FEATS_A_RETAIL + ["log_mcap_now", "has_revenue", "log_ev_sales", "revenue_growth", "profitable",
                            "ocf_positive", "runway_months", "net_margin", "book_to_market",
                            "dilution_overhang_pct"]
FEATURES = {"A_offer": FEATS_A_OFFER, "A_retail": FEATS_A_RETAIL, "B_post_report": FEATS_B}

# Pre-declared hyper-parameter candidates (see PREREGISTRATION.md)
LAMBDA_GRID = (1.0, 10.0, 100.0)
BUY_Q_GRID = (0.5, 0.6, 0.7, 0.8, 0.9)
AVOID_Q = 0.30
DEFAULT_LAMBDA, DEFAULT_BUY_Q = 10.0, 0.70      # used by the walk-forward (no per-fold tuning)
MIN_TRAIN = 120


def feature_frame(data: C.Data, deal_ids, mode: str, cfg: C.Config, label_before: str | None,
                  with_labels: bool = True) -> pd.DataFrame:
    """One row per IPO: features at the initial decision and (optionally) the 12-month label for an
    immediate entry. A label is kept only if its exit date is strictly before `label_before`."""
    rows = []
    for did in deal_ids:
        inp, ctx = data.reconstruct(did, mode, cfg)
        if inp is None:
            continue
        ev = R.evaluate(inp, {"gates": R.DEFAULT_GATES, "models": {}}, explain=False)
        if any(g["triggered"] and g["severity"] in (R.INELIGIBLE, R.ABSTAIN) and g["id"] != "FINANCIALS_MISSING_OR_STALE"
               for g in ev["gates"]) or (mode == "B_post_report" and any(
                g["triggered"] and g["id"] == "FINANCIALS_MISSING_OR_STALE" for g in ev["gates"])):
            continue          # the engine would abstain on these; they never reach the model
        row = {"deal_id": did, **R.feature_values(inp, ev["metrics"])}
        if with_labels:
            ep = data.entry_point(did, mode, ctx["decision_bar"], cfg)
            if ep is None:
                continue
            o = data.outcome(did, ep[0], ep[1], ep[2], cfg, horizons={"12m": C.HORIZONS["12m"]})
            if o.get("status_12m") not in ("complete", "delisted") or not np.isfinite(o.get("spy_12m", np.nan)):
                continue
            if label_before is not None and not (o["exit_date_12m"] < label_before):
                continue      # embargo: outcome not yet known at the cutoff
            row["y"] = float(o["ret_12m"] > o["spy_12m"])
            row["excess_12m"] = o["ret_12m"] - o["spy_12m"]
        rows.append(row)
    return pd.DataFrame(rows)


def _design(df: pd.DataFrame, feats, specs=None):
    """Winsorise (2nd/98th pct of train), impute the train median, standardise; add missing indicators."""
    fit = specs is None
    specs = specs or []
    cols, miss_cols = [], []
    for i, f in enumerate(feats):
        x = pd.to_numeric(df[f], errors="coerce").astype(float).values if f in df else np.full(len(df), np.nan)
        x = np.where(np.isfinite(x), x, np.nan)
        miss = np.isnan(x)
        if fit:
            obs = x[~miss]
            if len(obs) == 0:
                lo = hi = med = mean = 0.0
                std = 0.0
            else:
                lo, hi = np.percentile(obs, [2, 98])
                med = float(np.median(obs))
                xw = np.clip(np.where(miss, med, x), lo, hi)
                mean, std = float(xw.mean()), float(xw.std())
            specs.append({"name": f, "lo": float(lo), "hi": float(hi), "impute": float(med), "mean": float(mean),
                          "std": float(std), "n_missing_train": int(miss.sum()),
                          "use_missing_indicator": bool(15 <= miss.sum() <= len(x) - 15)})
        s = specs[i]
        xw = np.clip(np.where(miss, s["impute"], x), s["lo"], s["hi"])
        cols.append((xw - s["mean"]) / s["std"] if s["std"] > 0 else np.zeros(len(x)))
        miss_cols.append(miss.astype(float) if s["use_missing_indicator"] else None)
    X = np.column_stack(cols) if cols else np.zeros((len(df), 0))
    M = [m for m in miss_cols if m is not None]
    return X, (np.column_stack(M) if M else np.zeros((len(df), 0))), specs


def _fit_logit(X, y, lam, iters=100):
    """Newton–Raphson for L2-penalised logistic regression (intercept unpenalised)."""
    n, k = X.shape
    Z = np.column_stack([np.ones(n), X])
    w = np.zeros(k + 1)
    P = np.eye(k + 1) * lam
    P[0, 0] = 0.0
    for _ in range(iters):
        p = 1.0 / (1.0 + np.exp(-np.clip(Z @ w, -30, 30)))
        g = Z.T @ (p - y) + P @ w
        H = (Z * (p * (1 - p))[:, None]).T @ Z + P + np.eye(k + 1) * 1e-8
        step = np.linalg.solve(H, g)
        w -= step
        if np.abs(step).max() < 1e-9:
            break
    return w


def fit_model(train: pd.DataFrame, mode: str, lam: float, buy_q: float, avoid_q: float = AVOID_Q) -> dict:
    feats = FEATURES[mode]
    X, M, specs = _design(train, feats)
    y = train["y"].values.astype(float)
    w = _fit_logit(np.column_stack([X, M]), y, lam)
    k = X.shape[1]
    mi = 0
    for i, s in enumerate(specs):
        s["coef"] = float(w[1 + i])
        if s.pop("use_missing_indicator"):
            s["coef_missing"] = float(w[1 + k + mi])
            mi += 1
        else:
            s["coef_missing"] = 0.0
    model = {"intercept": float(w[0]), "features": specs, "l2_lambda": lam,
             "n_train": int(len(train)), "train_base_rate": float(y.mean())}
    p = predict(model, train)
    q = {f"{int(round(x * 100))}": float(np.quantile(p, x)) for x in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)}
    model["train_prob_quantiles"] = q
    model["thresholds"] = {"buy": float(np.quantile(p, buy_q)), "avoid": float(np.quantile(p, avoid_q)),
                           "buy_quantile": buy_q, "avoid_quantile": avoid_q}
    return model


def predict(model: dict, df: pd.DataFrame) -> np.ndarray:
    out = np.empty(len(df))
    names = [s["name"] for s in model["features"]]
    recs = df.reindex(columns=names).to_dict("records")
    for i, r in enumerate(recs):
        feats = {k: (None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)) for k, v in r.items()}
        out[i] = R.model_probability(model, feats)[0]
    return out


def select_hyper(dev: pd.DataFrame, val: pd.DataFrame, mode: str) -> dict:
    """Validation-period selection. lambda: lowest validation Brier score. buy quantile: highest mean
    12-month excess return of validation IPOs at/above the threshold, requiring at least 10% of them."""
    table = []
    best_lam, best_bs = None, np.inf
    for lam in LAMBDA_GRID:
        m = fit_model(dev, mode, lam, DEFAULT_BUY_Q)
        p = predict(m, val)
        bs = float(np.mean((p - val["y"].values) ** 2))
        table.append({"lambda": lam, "val_brier": bs})
        if bs < best_bs:
            best_lam, best_bs = lam, bs
    qtable = []
    best_q, best_ex = None, -np.inf
    m = fit_model(dev, mode, best_lam, DEFAULT_BUY_Q)
    p = predict(m, val)
    pdev = predict(m, dev)
    for q in BUY_Q_GRID:
        th = float(np.quantile(pdev, q))
        sel = p >= th
        ex = float(val.loc[sel, "excess_12m"].mean()) if sel.sum() else float("nan")
        qtable.append({"buy_quantile": q, "threshold": th, "n_val_selected": int(sel.sum()),
                       "share_val_selected": float(sel.mean()), "val_mean_excess_12m": ex})
        if sel.mean() >= 0.10 and ex > best_ex:
            best_q, best_ex = q, ex
    if best_q is None:
        best_q = DEFAULT_BUY_Q
    return {"lambda": best_lam, "buy_quantile": best_q, "lambda_table": table, "buy_quantile_table": qtable,
            "n_dev": int(len(dev)), "n_val": int(len(val)), "val_base_rate": float(val["y"].mean()),
            "val_mean_excess_all": float(val["excess_12m"].mean()),
            "val_brier_base_rate_reference": float(np.mean((dev["y"].mean() - val["y"].values) ** 2))}
