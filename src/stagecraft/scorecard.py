"""Origination scorecard: logistic regression of default within N months of
first payment on information known at origination.

Its log-odds score is the borrower-risk input to the hazard model, which is
what lets the SICR test compare "lifetime PD now" with "lifetime PD we would
have expected at origination" on a like-for-like basis.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import polars as pl
import statsmodels.api as sm

from .dates import date_to_mi

FEATURES = [
    "fico_c", "fico_missing", "ltv_c", "ltv_over80", "dti_c", "dti_missing", "cashout", "refi_no_cashout",
    "second_home", "investor", "third_party", "multi_unit", "first_time_buyer", "single_borrower", "condo_mh",
]


def design(orig: pl.DataFrame | pd.DataFrame) -> pd.DataFrame:
    o = orig.to_pandas() if isinstance(orig, pl.DataFrame) else orig
    fico = o["credit_score"].astype(float)
    dti = o["dti"].astype(float)
    ltv = o["ltv"].astype(float).fillna(80)
    X = pd.DataFrame(index=o.index)
    X["fico_c"] = (fico.fillna(fico.median()).clip(550, 830) - 740) / 50
    X["fico_missing"] = fico.isna().astype(float)
    X["ltv_c"] = (ltv.clip(20, 105) - 80) / 10
    X["ltv_over80"] = np.maximum(ltv - 80, 0) / 10
    X["dti_c"] = (dti.fillna(dti.median()).clip(0, 65) - 35) / 10
    X["dti_missing"] = dti.isna().astype(float)
    X["cashout"] = (o["loan_purpose"] == "C").astype(float)
    X["refi_no_cashout"] = (o["loan_purpose"] == "N").astype(float)
    X["second_home"] = (o["occupancy"] == "S").astype(float)
    X["investor"] = (o["occupancy"] == "I").astype(float)
    X["third_party"] = o["channel"].isin(["B", "C", "T"]).astype(float)
    X["multi_unit"] = (o["units"].fillna(1) > 1).astype(float)
    X["first_time_buyer"] = (o["first_time_homebuyer"] == "Y").astype(float)
    X["single_borrower"] = (o["n_borrowers"].fillna(2) == 1).astype(float)
    X["condo_mh"] = o["property_type"].isin(["CO", "MH"]).astype(float)
    return X[FEATURES]


@dataclass
class Scorecard:
    params: pd.Series
    bse: pd.Series
    target_months: int
    n_train: int
    default_rate: float

    def logit(self, orig) -> np.ndarray:
        X = sm.add_constant(design(orig), has_constant="add")
        return X.to_numpy() @ self.params.reindex(X.columns).to_numpy()

    def pd(self, orig) -> np.ndarray:
        return 1 / (1 + np.exp(-self.logit(orig)))

    def table(self) -> pd.DataFrame:
        return pd.DataFrame({"coef": self.params, "std_err": self.bse, "z": self.params / self.bse})


def training_set(orig: pl.DataFrame, loans: pl.DataFrame, reporting_date: str, cfg: dict) -> pl.DataFrame:
    """Loans whose whole target window ended by the reporting date."""
    T = cfg["scorecard"]["target_months"]
    rd = date_to_mi(reporting_date)
    return outcome(orig, loans, T).filter(
        (pl.col("fpd_mi") + T - 1 <= rd) & (pl.col("vintage") >= cfg["scorecard"]["min_train_vintage"])
    )


def outcome(orig: pl.DataFrame, loans: pl.DataFrame, T: int) -> pl.DataFrame:
    """Default within T months of first payment; loans censored (16/96) before
    then without a default are dropped."""
    df = orig.join(loans.select("loan_id", "default_mi", "exit_mi", "exit_type"), on="loan_id", how="left")
    end = pl.col("fpd_mi") + T - 1
    df = df.with_columns((pl.col("default_mi").is_not_null() & (pl.col("default_mi") <= end)).alias("y"))
    return df.filter(~((pl.col("exit_type") == "censored") & (pl.col("exit_mi") <= end) & ~pl.col("y")))


def fit(train: pl.DataFrame, cfg: dict) -> Scorecard:
    X = sm.add_constant(design(train), has_constant="add")
    y = train["y"].to_numpy().astype(float)
    res = sm.Logit(y, X).fit(disp=0, method="lbfgs", maxiter=500)
    return Scorecard(res.params, res.bse, cfg["scorecard"]["target_months"], len(y), float(y.mean()))
