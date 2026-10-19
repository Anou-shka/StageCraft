"""Loss given default.

1. Workout LGD per resolved default (credit-event exit with loss data, exit on
   or before the reporting date):
       accounting LGD = loss / UPB at default        (loss sign from datacheck)
       economic LGD   = (removal UPB + expenses + delinquent interest
                         - recoveries x DF(workout months)) / UPB at default
   where recoveries = net sale proceeds + MI + non-MI recoveries and DF
   discounts at the note rate from default to disposition.
2. Severity model: fractional logit of LGD on current LTV at default
   (a single slope, so severity can only rise as LTV rises; a hinge at 100%
   was tested but too few defaults sit above 100% to estimate it)
   (original LTV indexed by HPI), MI coverage and investor occupancy. The
   current-LTV term is the macro link: scenario house prices move LTV, so
   they move LGD.
3. Cure adjustment: effective LGD = P(liquidation | default) x severity,
   because a share of defaults cure with (almost) no loss.
4. Downturn LGD: severity observed for defaults in 2008-2011, by LTV band.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import polars as pl
import statsmodels.api as sm

from .buckets import n_transient
from .dates import date_to_mi


def band(cltv, cuts) -> np.ndarray:
    cuts = list(cuts)
    labels = [f"<={cuts[0]}"] + [f"{a}-{b}" for a, b in zip(cuts[:-1], cuts[1:])] + [f">{cuts[-1]}"]
    return np.array(labels, dtype=object)[np.searchsorted(cuts, np.asarray(cltv, float), side="left")]


def resolved_defaults(loans: pl.DataFrame, orig: pl.DataFrame, hpi: pd.Series, reporting_date: str, cfg: dict,
                      sign: int) -> pd.DataFrame:
    rd = date_to_mi(reporting_date)
    d = loans.filter(
        pl.col("exit_code").is_in(cfg["default_definition"]["credit_event_zb_codes"])
        & pl.col("actual_loss").is_not_null() & (pl.col("exit_mi") <= rd) & pl.col("default_mi").is_not_null()
    ).join(orig.select("loan_id", "ltv", "orig_upb", "fpd_mi", "mi_pct", "occupancy", "orig_rate"), on="loan_id").to_pandas()
    if d.empty:
        return d
    d["upb_def"] = d["upb_at_default"].where(d["upb_at_default"] > 0, d["zb_removal_upb"])
    d["lgd_acct"] = sign * d["actual_loss"] / d["upb_def"]
    rate = d["last_rate"].fillna(d["orig_rate"]) / 1200
    months = (d["exit_mi"] - d["default_mi"]).clip(lower=0)
    dfac = (1 + rate) ** (-months)
    rec = d["net_sales_proceeds"] + d["mi_recoveries"].fillna(0) + d["non_mi_recoveries"].fillna(0)
    cost = d["expenses"].fillna(0).abs() + d["dai"].fillna(0)
    econ = (d["zb_removal_upb"] + cost - rec * dfac) / d["upb_def"]
    use_econ = cfg["lgd"]["discount_recoveries"] & rec.notna()
    d["lgd"] = np.where(use_econ, econ, d["lgd_acct"])
    d["lgd"] = d["lgd"].clip(-0.2, 1.5)
    hpi_o = hpi.reindex(d["fpd_mi"] - 2).to_numpy()
    hpi_d = hpi.reindex(d["default_mi"]).to_numpy()
    d["cltv_def"] = d["ltv"] * d["upb_def"] / d["orig_upb"] * hpi_o / hpi_d
    d["default_year"] = d["default_mi"] // 12
    d["workout_months"] = months
    d["ltv_band"] = band(d["cltv_def"], cfg["lgd"]["ltv_band_cuts"])
    return d


def cure_rate(panel: pl.LazyFrame, loans: pl.DataFrame, reporting_date: str, cfg: dict) -> dict:
    """Share of first defaults that are performing (or repaid voluntarily)
    `cure_obs_months` after default, among defaults observable that long
    before the reporting date."""
    rd = date_to_mi(reporting_date)
    N = cfg["lgd"]["cure_obs_months"]
    k = n_transient(cfg)
    dl = loans.filter(pl.col("default_mi").is_not_null() & (pl.col("default_mi") + N <= rd)).select(
        "loan_id", "default_mi", "exit_mi", "exit_type")
    later = panel.select("loan_id", "mi", "state").join(dl.lazy(), on="loan_id").filter(
        pl.col("mi") == pl.col("default_mi") + N).select("loan_id", (pl.col("state") < k).alias("perf")).collect()
    x = dl.join(later, on="loan_id", how="left").with_columns(
        (pl.col("perf").fill_null(False)
         | (pl.col("exit_type").is_in(["prepaid", "censored"]) & (pl.col("exit_mi") <= pl.col("default_mi") + N)))
        .alias("cured"))
    n = x.height
    cured = float(x["cured"].mean()) if n else 0.0
    return {"n_defaults": n, "cure_rate": cured, "p_liquidation": 1 - cured}


def _design(cltv, mi_pct, investor) -> np.ndarray:
    c = np.clip(np.asarray(cltv, float), 0, 250) / 100
    return np.column_stack([np.ones_like(c), c, np.asarray(mi_pct, float) / 100, np.asarray(investor, float)])


@dataclass
class LGDModel:
    params: np.ndarray
    bse: np.ndarray
    p_liq: float
    floor: float
    cap: float
    apply_cure: bool
    downturn: pd.DataFrame       # severity by LTV band, 2008-2011 defaults
    table: pd.DataFrame          # severity by LTV band, all defaults
    n: int
    band_cuts: list

    names = ["const", "cltv", "mi_pct", "investor"]

    def severity(self, cltv, mi_pct, investor):
        eta = self.params[0] + self.params[1] * np.clip(cltv, 0, 250) / 100 \
            + self.params[2] * np.asarray(mi_pct) / 100 + self.params[3] * np.asarray(investor)
        return 1 / (1 + np.exp(-eta))

    def effective(self, cltv, mi_pct, investor):
        sev = self.severity(cltv, mi_pct, investor)
        p = self.p_liq if self.apply_cure else 1.0
        return np.clip(p * sev, self.floor, self.cap)

    def downturn_effective(self, cltv):
        b = band(cltv, self.band_cuts)
        dt = self.downturn.set_index("ltv_band")["mean_lgd"]
        overall = self.downturn.attrs.get("overall", float(dt.mean()) if len(dt) else 0.3)
        sev = pd.Series(b).map(dt).fillna(overall).to_numpy()
        p = self.p_liq if self.apply_cure else 1.0
        return np.clip(p * sev, self.floor, self.cap)

    def coef_table(self) -> pd.DataFrame:
        return pd.DataFrame({"coef": self.params, "std_err": self.bse}, index=self.names)


def _band_table(d: pd.DataFrame, min_obs: int) -> pd.DataFrame:
    t = d.groupby("ltv_band").agg(n=("lgd", "size"), mean_lgd=("lgd", "mean"), median_lgd=("lgd", "median")).reset_index()
    t.attrs["overall"] = float(d["lgd"].mean()) if len(d) else np.nan
    t["credible"] = t["n"] >= min_obs
    return t


def fit(d: pd.DataFrame, cure: dict, cfg: dict) -> LGDModel:
    c = cfg["lgd"]
    y = d["lgd"].clip(0, 1).to_numpy()
    X = _design(d["cltv_def"], d["mi_pct"].fillna(0), d["occupancy"] == "I")
    # Fractional logit (Papke-Wooldridge): binomial quasi-likelihood on y in [0,1].
    res = sm.GLM(y, X, family=sm.families.Binomial()).fit(cov_type="HC0")
    y0, y1 = c["downturn_years"]
    dt = d[d["default_year"].between(y0, y1)]
    down = _band_table(dt, c["min_obs_per_band"])
    return LGDModel(np.asarray(res.params), np.asarray(res.bse), cure["p_liquidation"], c["floor"], c["cap"],
                    c["apply_cure_rate"], down, _band_table(d, c["min_obs_per_band"]), len(d), c["ltv_band_cuts"])
