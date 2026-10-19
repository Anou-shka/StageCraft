"""Forward-looking macro scenarios.

A scenario is defined in config/assumptions.yaml by five year-end
unemployment rates and five annual house-price growth rates. This module
turns it into a monthly path that starts from the macro data actually
published by the reporting date (no look-ahead), follows the scenario for
five years, glides to long-run values and then stays there.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .dates import date_to_mi
from .macro import add_features, asat_cutoffs


def scenario_names(cfg: dict, include_stress: bool = True) -> list[str]:
    names = list(cfg["scenarios"]["weights"])
    if include_stress:
        names += [s for s in cfg["scenarios"]["stress_only"] if s not in names]
    return names


def weights(cfg: dict) -> dict[str, float]:
    w = cfg["scenarios"]["weights"]
    total = sum(w.values())
    if abs(total - 1) > 1e-9:
        raise ValueError(f"scenario weights sum to {total}, not 1")
    return dict(w)


def spec(cfg: dict, reporting_date: str, name: str) -> dict:
    return cfg["scenarios"]["paths"][reporting_date][name]


def macro_path(
    hist: pd.DataFrame,
    reporting_date: str,
    sc: dict,
    cfg: dict,
    horizon: int = 480,
) -> pd.DataFrame:
    """Monthly macro path: published history up to the as-at cutoffs, then the
    scenario. Index = month index, from the start of history to
    reporting month + horizon."""
    rd = date_to_mi(reporting_date)
    cut = asat_cutoffs(reporting_date, cfg)
    lr_ur = cfg["macro"]["long_run_unemployment"]
    lr_g = cfg["macro"]["long_run_hpi_growth"]
    rev = 12 * cfg["macro"]["reversion_years"]
    idx = pd.RangeIndex(hist.index.min(), rd + horizon + 1, name="mi")
    out = pd.DataFrame(index=idx)

    # Unemployment: piecewise-linear through anchor points.
    ur_hist = hist["ur"].loc[: cut["ur"]].dropna()
    last_mi = int(ur_hist.index.max())
    xs = [last_mi] + [rd + 12 * (k + 1) for k in range(5)] + [rd + 60 + rev]
    ys = [ur_hist.iloc[-1]] + list(sc["unemployment"]) + [lr_ur]
    ur = pd.Series(np.nan, index=idx)
    ur.loc[ur_hist.index] = ur_hist.to_numpy()
    fut = idx[idx > last_mi]
    ur.loc[fut] = np.interp(fut, xs, ys)
    out["ur"] = ur

    # House prices: monthly log growth by scenario year after the last
    # published month (the publication gap uses the year-1 growth rate).
    hpi_hist = hist["hpi"].loc[: cut["hpi"]].dropna()
    last_h = int(hpi_hist.index.max())
    g = np.array(sc["hpi_growth"], dtype=float)
    fut_h = np.arange(last_h + 1, idx.max() + 1)
    yr = np.clip((fut_h - rd - 1) // 12, 0, None)  # 0 = first projection year
    ann = np.where(yr < 5, g[np.minimum(yr, 4)], lr_g)
    glide = (yr >= 5) & (fut_h <= rd + 60 + rev)
    frac = np.clip((fut_h - rd - 60) / rev, 0, 1)
    ann = np.where(glide, g[4] + (lr_g - g[4]) * frac, ann)
    logh = np.log(hpi_hist.iloc[-1]) + np.cumsum(np.log1p(ann / 100) / 12)
    hpi = pd.Series(np.nan, index=idx)
    hpi.loc[hpi_hist.index] = hpi_hist.to_numpy()
    hpi.loc[fut_h] = np.exp(logh)
    out["hpi"] = hpi

    mr = hist["mtg_rate"].loc[: cut["mtg_rate"]].dropna()
    out["mtg_rate"] = hist["mtg_rate"].reindex(idx)
    out.loc[out.index > mr.index.max(), "mtg_rate"] = mr.iloc[-1]
    return add_features(out)


def all_paths(hist: pd.DataFrame, reporting_date: str, cfg: dict, horizon: int = 480) -> dict:
    return {
        name: macro_path(hist, reporting_date, spec(cfg, reporting_date, name), cfg, horizon)
        for name in scenario_names(cfg)
    }


def neutral_path(hist: pd.DataFrame, reporting_date: str, cfg: dict, horizon: int = 480) -> pd.DataFrame:
    """Through-the-cycle path used for the origination PD: unemployment flat at
    its long-run level (zero change) and house prices at long-run growth."""
    lr = cfg["macro"]["long_run_unemployment"]
    g = cfg["macro"]["long_run_hpi_growth"]
    sc = {"unemployment": [lr] * 5, "hpi_growth": [g] * 5}
    p = macro_path(hist, reporting_date, sc, cfg, horizon)
    p["dur12"] = 0.0
    p["hpa12"] = 100 * np.log1p(g / 100)
    return p
