"""Macro-linked discrete-time logistic hazard model: the scenario PD engine.

Design: "snapshot x horizon" panel. At each snapshot month s (every June
and December before the reporting date) take every loan that is performing
(Current / 30 / 60 DPD) and follow it for h = 1..60 months, or until it
defaults, exits, or reaches the reporting date. Each loan-month is a row:

    y = 1 if the loan enters default in month s + h (rows stop at that month)

    logit P(y = 1 | at risk) =
        b0 + b1 * origination score                       (scorecard log-odds)
           + f(loan age at s + h)                         (piecewise linear)
           + g(current LTV at s + h)                      (HPI-indexed, hinges at 80 and 100)
           + status at s x horizon bucket dummies         (a 60-DPD loan is far riskier
                                                           next quarter than in 3 years)
           + modified at s + forbearance/assistance at s + defaulted before s
           + c1 * 12m change in unemployment at s + h
           + c2 * 12m house-price growth at s + h
           + legacy-underwriting flag (vintage <= legacy_vintage_max)

Why this design: every covariate is either fixed at the snapshot or a known
function of time and the macro path (age, LTV via scheduled amortisation and
HPI, the macro variables). So at a reporting date the model projects a full
monthly PD term structure for each loan under any scenario without having to
simulate future delinquency states. Delinquency enters through the
status x horizon terms, whose effect decays as the horizon lengthens.

Structural zero: payments are missed one month at a time, so a loan j
payments behind cannot reach `min_dpd_status` in fewer than
(min_dpd_status - j) months. Those loan-months are not at risk; they are left
out of the fit and get hazard 0 in projection.

Seasoning constraint: before 2019 the only loans older than six years are
2005-2012 vintages, so a rising late-age effect is confounded with those
cohorts. If the fitted age_72_180 slope is positive it is set to zero and the
model refitted (hazard flat beyond age 72 unless the data say it falls).

Prepayment is a competing risk handled outside this model (ead.py): a loan
that prepays in month t was at risk of default in t (y = 0) and leaves.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import polars as pl

from .buckets import CENSORED, DEFAULT, PREPAID, n_transient
from .dates import date_to_mi


def horizon_bucket(h, cuts) -> np.ndarray:
    return np.searchsorted(np.asarray(cuts), np.asarray(h), side="left")


def feature_names(cfg: dict) -> list[str]:
    k = n_transient(cfg)
    nb = len(cfg["hazard"]["horizon_buckets"]) + 1
    names = ["const", "score", "age_0_12", "age_12_36", "age_36_72", "age_72_180", "cltv", "cltv_over80",
             "cltv_over100", "modified", "assisted", "prior_default", "dur12", "hpa12", "legacy_vintage"]
    for j in range(k):
        for b in range(nb):
            if j == 0 and b == nb - 1:
                continue  # reference cell: current at snapshot, long horizon
            names.append(f"s{j}_h{b}")
    return names


def features(score, age, cltv, status, h, modified, assisted, prior_default, dur12, hpa12, cfg: dict,
             vintage=None) -> dict:
    """Feature arrays. Inputs broadcast: 1-D for training rows, or (n, 1)
    loan attributes against (1, T) / (n, T) time paths in projection."""
    k = n_transient(cfg)
    cuts = cfg["hazard"]["horizon_buckets"]
    nb = len(cuts) + 1
    # A missing original LTV (a handful of loans) is treated as 80%, the modal value.
    c = np.clip(np.nan_to_num(np.asarray(cltv, dtype=float), nan=80.0), 0, 200) / 100
    f = {
        "score": score,
        "age_0_12": np.minimum(age, 12) / 12,
        "age_12_36": np.clip(age - 12, 0, 24) / 24,
        "age_36_72": np.clip(age - 36, 0, 36) / 36,
        "age_72_180": np.clip(age - 72, 0, 108) / 108,
        "cltv": c,
        "cltv_over80": np.maximum(c - 0.8, 0),
        "cltv_over100": np.maximum(c - 1.0, 0),
        "modified": modified,
        "assisted": assisted,
        "prior_default": prior_default,
        "dur12": dur12,
        "hpa12": hpa12,
        "legacy_vintage": 0.0 if vintage is None else (vintage <= cfg["hazard"]["legacy_vintage_max"]).astype(float),
    }
    hb = horizon_bucket(h, cuts)
    for j in range(k):
        sj = status == j
        for b in range(nb):
            if j == 0 and b == nb - 1:
                continue
            f[f"s{j}_h{b}"] = (sj & (hb == b)).astype(float)
    return f


def at_risk(status, h, cfg: dict):
    return h >= n_transient(cfg) - status


@dataclass
class HazardModel:
    params: pd.Series
    bse: pd.Series
    n_rows: int
    n_events: int
    cfg_k: int

    def eta(self, f: dict) -> np.ndarray:
        out = self.params["const"]
        for name, b in self.params.items():
            if name != "const":
                out = out + b * f[name]
        return out

    def table(self) -> pd.DataFrame:
        return pd.DataFrame({"coef": self.params, "std_err": self.bse, "z": self.params / self.bse})


def snapshots(reporting_date: str, cfg: dict) -> list[int]:
    rd = date_to_mi(reporting_date)
    first = date_to_mi(cfg["hazard"]["first_snapshot"])
    months = set(cfg["hazard"]["snapshot_months"])
    return [m for m in range(first, rd) if m % 12 + 1 in months]


def training_panel(panel: pl.LazyFrame, scores: pl.DataFrame, macro: pd.DataFrame, reporting_date: str,
                   cfg: dict, seed: int = 0) -> pd.DataFrame:
    """(snapshot, horizon) rows with outcome y, using data up to the reporting date only."""
    k = n_transient(cfg)
    rd = date_to_mi(reporting_date)
    H = cfg["hazard"]["max_horizon"]
    base = panel.select("loan_id", "mi", "state", "default_entry", "cltv", "age_fpd", "modified", "assisted",
                        "prior_default").filter(pl.col("mi") <= rd)
    snaps = snapshots(reporting_date, cfg)
    # Size the panel first, then keep every default row and a hash-based
    # random share of the non-default rows so the panel stays under
    # `max_training_rows`; weights 1/share restore the population.
    counts = (base.filter(pl.col("mi").is_in(snaps) & (pl.col("state") < k)).group_by("mi").len().collect())
    est = sum(int(n) * min(H, rd - int(m)) for m, n in counts.iter_rows())
    frac = min(1.0, cfg["hazard"]["nonevent_sample_frac"], cfg["hazard"]["max_training_rows"] / max(est, 1))
    frames = []
    for s in snaps:
        snap = base.filter((pl.col("mi") == s) & (pl.col("state") < k)).select(
            "loan_id", pl.col("state").alias("s_status"), pl.col("modified").alias("s_mod"),
            pl.col("assisted").alias("s_assist"), pl.col("prior_default").alias("s_prior"))
        fol = (
            base.filter(pl.col("mi").is_between(s + 1, min(s + H, rd)))
            .join(snap, on="loan_id", how="inner")
            .sort("loan_id", "mi")
            # stop at the first default entry after the snapshot
            .filter(pl.col("default_entry").cast(pl.Int32).cum_sum().over("loan_id")
                    - pl.col("default_entry").cast(pl.Int32) == 0)
            .filter((pl.col("state") < k) | pl.col("state").is_in([DEFAULT, PREPAID, CENSORED]))
            .select("loan_id", "mi", (pl.col("mi") - s).alias("h"), pl.col("default_entry").alias("y"),
                    "cltv", "age_fpd", "s_status", "s_mod", "s_assist", "s_prior")
            .filter(at_risk(pl.col("s_status"), pl.col("h"), cfg))
        )
        if frac < 1:
            u = (pl.struct("loan_id", "mi", "h").hash(seed + s) % 1_000_000).cast(pl.Float64) / 1_000_000
            fol = fol.filter(pl.col("y") | (u < frac))
        frames.append(fol.collect())
    df = pl.concat(frames).join(scores, on="loan_id", how="left")
    df = df.with_columns(pl.when(pl.col("y")).then(1.0).otherwise(1 / frac).alias("w"))
    out = df.to_pandas()
    m = macro.reindex(out["mi"].to_numpy())
    out["dur12"] = m["dur12"].to_numpy()
    out["hpa12"] = m["hpa12"].to_numpy()
    return out


def design_matrix(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    f = features(df["score"].to_numpy(), df["age_fpd"].to_numpy(), df["cltv"].to_numpy(),
                 df["s_status"].to_numpy(), df["h"].to_numpy(), df["s_mod"].to_numpy().astype(float),
                 df["s_assist"].to_numpy().astype(float), df["s_prior"].to_numpy().astype(float),
                 df["dur12"].to_numpy(), df["hpa12"].to_numpy(), cfg, vintage=df["vintage"].to_numpy())
    X = pd.DataFrame(f)
    X.insert(0, "const", 1.0)
    return X[feature_names(cfg)]


def irls(X: np.ndarray, y: np.ndarray, w: np.ndarray, lam: float, max_iter: int = 50, tol: float = 1e-8):
    """Ridge-penalised logistic regression by Newton/IRLS. The penalty
    (not applied to the intercept) keeps sparse dummy cells finite;
    standard errors come from the penalised information matrix."""
    n, p = X.shape
    pen = np.full(p, lam)
    pen[0] = 0.0
    beta = np.zeros(p)
    beta[0] = np.log(max(np.average(y, weights=w), 1e-6) / (1 - np.average(y, weights=w)))
    def objective(b):
        eta = X @ b
        # weighted log-likelihood minus the ridge penalty
        return np.sum(w * (y * eta - np.logaddexp(0, eta))) - 0.5 * np.sum(pen * b * b)

    obj = objective(beta)
    for _ in range(max_iter):
        mu = 1 / (1 + np.exp(-np.clip(X @ beta, -30, 30)))
        W = w * mu * (1 - mu)
        H = (X * W[:, None]).T @ X + np.diag(pen)
        g = X.T @ (w * (y - mu)) - pen * beta
        step = np.linalg.solve(H, g)
        t = 1.0
        while t > 1e-4:  # step-halving line search: never accept a worse fit
            cand = beta + t * step
            new = objective(cand)
            if new >= obj - 1e-10:
                break
            t /= 2
        beta, obj = cand, new
        if np.max(np.abs(t * step)) < tol:
            break
    mu = 1 / (1 + np.exp(-np.clip(X @ beta, -30, 30)))
    H = (X * (w * mu * (1 - mu))[:, None]).T @ X + np.diag(pen)
    se = np.sqrt(np.diag(np.linalg.inv(H)))
    return beta, se


def fit(df: pd.DataFrame, cfg: dict) -> HazardModel:
    X = design_matrix(df, cfg)
    # Columns with no variation in this window (e.g. no assistance flags
    # before 2014) are dropped and get a zero coefficient.
    keep = [c for c in X.columns if c == "const" or X[c].std() > 0]
    y = df["y"].to_numpy().astype(float)
    lam = cfg["hazard"]["l2_penalty"]
    beta, se = irls(X[keep].to_numpy(), y, df["w"].to_numpy(), lam)
    if cfg["hazard"]["age_monotone_after_72"] and "age_72_180" in keep and beta[keep.index("age_72_180")] > 0:
        keep.remove("age_72_180")
        beta, se = irls(X[keep].to_numpy(), y, df["w"].to_numpy(), lam)
    params = pd.Series(beta, index=keep).reindex(X.columns, fill_value=0.0)
    bse = pd.Series(se, index=keep).reindex(X.columns)
    return HazardModel(params, bse, len(y), int(y.sum()), n_transient(cfg))
