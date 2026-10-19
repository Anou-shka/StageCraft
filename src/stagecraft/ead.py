"""Exposure at default and prepayment.

EAD: the contractual amortisation schedule from the current interest-bearing
UPB, current note rate and remaining term, plus any non-interest-bearing
(deferred) UPB, which stays outstanding until payoff. EAD_t is the balance
at the start of month t, i.e. if the loan defaults in month t.

Prepayment: a single monthly prepayment rate (SMM) per loan, estimated over
the look-back window as the share of Current loans that pay off in full the
next month, segmented by refinancing incentive (note rate minus the market
30-year rate). CPR = 1 - (1 - SMM)^12. Prepayment enters the ECL once, as a
competing exit in the survival curve: a loan that has prepaid cannot default.
That is equivalent to scaling EAD by the probability of not having prepaid.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import polars as pl

from .dates import date_to_mi


def balance_schedule(upb, rate, rem, T: int) -> np.ndarray:
    """(n, T + 1) scheduled balances B_0..B_T; zero after the remaining term."""
    upb = np.asarray(upb, float)[:, None]
    r = (np.asarray(rate, float) / 1200)[:, None]
    n = np.maximum(np.asarray(rem, float), 1)[:, None]
    t = np.arange(T + 1)[None, :]
    tt = np.minimum(t, n)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        a = (1 + r) ** n
        b = np.where(r > 0, upb * (a - (1 + r) ** tt) / (a - 1), upb * (1 - tt / n))
    return np.maximum(np.nan_to_num(b), 0.0)


def incentive_band(incentive, cuts) -> np.ndarray:
    cuts = list(cuts)
    labels = [f"<{cuts[0]:+.1f}pp"] + [f"{a:+.1f} to {b:+.1f}pp" for a, b in zip(cuts[:-1], cuts[1:])] + [f">{cuts[-1]:+.1f}pp"]
    return np.array(labels, dtype=object)[np.searchsorted(cuts, np.asarray(incentive, float), side="right")]


def cpr_table(panel: pl.LazyFrame, macro: pd.DataFrame, reporting_date: str, cfg: dict) -> pd.DataFrame:
    from .buckets import PREPAID

    rd = date_to_mi(reporting_date)
    w = cfg["prepayment"]["window_months"]
    p = (
        panel.select("loan_id", "mi", "state", "current_rate")
        .filter(pl.col("mi").is_between(rd - w - 1, rd))
        .sort("loan_id", "mi")
        .with_columns(pl.col("state").shift(1).over("loan_id").alias("prev"),
                      pl.col("mi").shift(1).over("loan_id").alias("prev_mi"),
                      pl.col("current_rate").shift(1).over("loan_id").alias("prev_rate"))
        .filter((pl.col("mi") > rd - w) & (pl.col("prev") == 0) & (pl.col("prev_mi") == pl.col("mi") - 1))
        .select("prev_mi", "prev_rate", (pl.col("state") == PREPAID).alias("prepaid"))
        .collect().to_pandas()
    )
    p["incentive"] = p["prev_rate"] - macro["mtg_rate"].reindex(p["prev_mi"]).to_numpy()
    p["band"] = incentive_band(p["incentive"], cfg["prepayment"]["incentive_cuts"])
    t = p.groupby("band").agg(loan_months=("prepaid", "size"), prepayments=("prepaid", "sum")).reset_index()
    pooled = t["prepayments"].sum() / max(t["loan_months"].sum(), 1)
    # Credibility weighting towards the pooled rate (100 pseudo prepayments' worth of exposure).
    a = 100 / max(pooled, 1e-4)
    t["smm"] = (t["prepayments"] + a * pooled) / (t["loan_months"] + a)
    t["cpr"] = 1 - (1 - t["smm"]) ** 12
    t.attrs["pooled_smm"] = pooled
    return t


def loan_smm(rate, market_rate: float, table: pd.DataFrame, cfg: dict) -> np.ndarray:
    b = incentive_band(np.asarray(rate, float) - market_rate, cfg["prepayment"]["incentive_cuts"])
    s = table.set_index("band")["smm"]
    return pd.Series(b).map(s).fillna(table.attrs.get("pooled_smm", s.mean())).to_numpy()
