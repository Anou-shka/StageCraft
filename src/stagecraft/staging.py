"""Portfolio snapshot at a reporting date and IFRS 9 stage allocation.

Stage 3  credit-impaired: in default now (status >= min_dpd_status, REO, or a
         credit event), or cured from default less than
         `stage3_probation_months` ago.
Stage 2  significant increase in credit risk since initial recognition, any of:
           - 30+ DPD backstop (status >= backstop_min_status)
           - relative test: lifetime PD now >= multiple x lifetime PD expected
             at origination for the same remaining term, AND the increase is
             at least `sicr_absolute_bp`
           - watchlist: modified, in a borrower-assistance plan (forbearance,
             repayment, trial) or granted a payment deferral
Stage 1  everything else.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import polars as pl

from .buckets import DEFAULT
from .dates import date_to_mi


def snapshot(panel: pl.LazyFrame, orig: pl.DataFrame, scores: pl.DataFrame, reporting_date: str) -> pd.DataFrame:
    """Loans on the books at the reporting month end (a record that month and
    no zero-balance event in it)."""
    rd = date_to_mi(reporting_date)
    snap = (
        panel.filter((pl.col("mi") == rd) & pl.col("zb_code").is_null())
        .select("loan_id", "state", "status", "reo", "upb", "deferred_upb", "current_rate", "rem_months", "age_fpd",
                "modified", "assisted", "deferred", "last_default_mi", "prior_default")
        .join(orig.lazy().select("loan_id", "vintage", "credit_score", "ltv", "orig_upb", "orig_rate", "orig_term",
                                 "hpi_orig", "mi_pct", "occupancy", "fpd_mi"), on="loan_id", how="left")
        .join(scores.lazy().select("loan_id", "score"), on="loan_id", how="left")
        .collect()
        .to_pandas()
    )
    snap["deferred_upb"] = snap["deferred_upb"].fillna(0.0)
    snap["rem_months"] = snap["rem_months"].clip(lower=1)
    return snap


def stage3_flag(snap: pd.DataFrame, reporting_date: str, cfg: dict) -> np.ndarray:
    rd = date_to_mi(reporting_date)
    prob = cfg["staging"]["stage3_probation_months"]
    in_default = snap["state"].to_numpy() == DEFAULT
    recent = snap["last_default_mi"].notna().to_numpy() & ((rd - snap["last_default_mi"].fillna(-10_000)).to_numpy() < prob)
    return in_default | recent


def assign(snap: pd.DataFrame, s3: np.ndarray, pd_life: np.ndarray, pd_orig: np.ndarray, cfg: dict,
           multiple: float | None = None) -> pd.DataFrame:
    """Stage plus the trigger that put each loan in Stage 2."""
    st = cfg["staging"]
    multiple = st["sicr_relative_multiple"] if multiple is None else multiple
    backstop = snap["status"].fillna(0).to_numpy() >= st["backstop_min_status"]
    relative = (pd_life >= multiple * pd_orig) & (pd_life - pd_orig >= st["sicr_absolute_bp"] / 1e4)
    w = st["watchlist"]
    watch = np.zeros(len(snap), bool)
    if w["modification"]:
        watch |= snap["modified"].to_numpy().astype(bool)
    if w["borrower_assistance"]:
        watch |= snap["assisted"].to_numpy().astype(bool)
    if w["payment_deferral"]:
        watch |= snap["deferred"].to_numpy().astype(bool)
    stage = np.where(s3, 3, np.where(backstop | relative | watch, 2, 1))
    trig = np.where(s3, "default/probation",
                    np.where(backstop, "30+ DPD", np.where(relative, "relative PD", np.where(watch, "watchlist", ""))))
    return pd.DataFrame({"stage": stage, "trigger": trig, "sicr_backstop": backstop & ~s3,
                         "sicr_relative": relative & ~s3, "sicr_watchlist": watch & ~s3})
