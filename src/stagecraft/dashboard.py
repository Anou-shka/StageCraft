"""Recalculation engine behind the Streamlit app.

The pipeline saves, per reporting date, every loan's 12-month, lifetime and
Stage 3 ECL under each scenario plus the fitted models. Changing weights, the
SICR threshold or the LGD basis only re-weights and re-stages those saved
numbers (instant). Editing a scenario's macro path re-projects that scenario
through the hazard and LGD models (a few seconds on the bundled sample).
"""

from __future__ import annotations

import copy
import pickle
from functools import lru_cache

import numpy as np
import pandas as pd

from . import ecl, scenarios, staging
from .config import load_config, path


@lru_cache(maxsize=4)
def bundle(rd: str) -> dict:
    cfg = load_config()
    app = path(cfg, "app_bundle")
    with open(app / f"models_{rd}.pkl", "rb") as f:
        models = pickle.load(f)
    hist = pd.read_csv(app / "macro_history.csv", index_col=0)
    return {"models": models, "snap": pd.read_parquet(app / f"snapshot_{rd}.parquet"),
            "res": pd.read_parquet(app / f"results_{rd}.parquet"), "hist": hist}


def available_dates() -> list[str]:
    cfg = load_config()
    app = path(cfg, "app_bundle")
    return [d for d in cfg["reporting_dates"] if (app / f"results_{d}.parquet").exists()]


def reproject(rd: str, name: str, unemployment: tuple, hpi_growth: tuple) -> dict:
    """Recompute one scenario's loan-level components for an edited path."""
    cfg = load_config()
    b = bundle(rd)
    snap, m = b["snap"], b["models"]
    p = scenarios.macro_path(b["hist"], rd, {"unemployment": list(unemployment), "hpi_growth": list(hpi_growth)}, cfg)
    perf = ~staging.stage3_flag(snap, rd, cfg)
    sp = snap[perf].reset_index(drop=True)
    c = ecl.project(sp, p, rd, m["hazard"], m["lgd"], snap["smm"].to_numpy()[perf], cfg)
    out = {}
    for k in ("pd12", "pd_life", "ecl12", "ecl_life", "pe12", "pe_life"):
        col = np.zeros(len(snap))
        col[perf] = c[k]
        out[f"{k}_{name}"] = col
    out[f"lgd3_{name}"] = ecl.stage3_lgd(snap, p, rd, m["lgd"], cfg)
    out[f"ecl3_{name}"] = out[f"lgd3_{name}"] * snap["upb"].to_numpy()
    out["path"] = p
    return out


def compute(rd: str, weights: dict, multiple: float, abs_bp: float, downturn_lgd: bool = False,
            overrides: dict | None = None) -> pd.DataFrame:
    """Re-stage and re-weight. `overrides` maps scenario -> reproject() output."""
    cfg = copy.deepcopy(load_config())
    cfg["staging"]["sicr_relative_multiple"] = multiple
    cfg["staging"]["sicr_absolute_bp"] = abs_bp
    b = bundle(rd)
    res = b["res"].copy()
    for name, o in (overrides or {}).items():
        for k, v in o.items():
            if k != "path":
                res[k] = v
    w = {k: v for k, v in weights.items() if v > 0}
    tot = sum(w.values())
    w = {k: v / tot for k, v in w.items()}
    s3 = res["stage"].to_numpy() == 3
    pd_life_w = sum(wt * res[f"pd_life_{s}"] for s, wt in w.items())
    basis = pd_life_w if cfg["staging"]["sicr_pd_basis"] == "weighted" else res["pd_life_base"]
    st = staging.assign(b["snap"], s3, basis.to_numpy(), res["pd_orig_life"].to_numpy(), cfg)
    res["stage"], res["trigger"] = st["stage"].to_numpy(), st["trigger"].to_numpy()
    for s in scenarios.scenario_names(cfg):
        if downturn_lgd:
            e12, el, e3 = res[f"pe12_{s}"] * res["lgd_downturn"], res[f"pe_life_{s}"] * res["lgd_downturn"], \
                res["lgd_downturn"] * res["upb"]
        else:
            e12, el, e3 = res[f"ecl12_{s}"], res[f"ecl_life_{s}"], res[f"ecl3_{s}"]
        res[f"ecl_{s}"] = ecl.stage_ecl(res["stage"].to_numpy(), e12.to_numpy(), el.to_numpy(), e3.to_numpy())
    res["ecl_w"] = sum(wt * res[f"ecl_{s}"] for s, wt in w.items())
    res["pd12_w"] = sum(wt * res[f"pd12_{s}"] for s, wt in w.items())
    return res


def summary(res: pd.DataFrame) -> pd.DataFrame:
    g = res.groupby("stage").agg(loans=("loan_id", "size"), gross_carrying_amount=("upb", "sum"),
                                 ecl=("ecl_w", "sum")).reindex([1, 2, 3]).fillna(0)
    g.loc["Total"] = g.sum()
    g["coverage"] = g["ecl"] / g["gross_carrying_amount"].replace(0, np.nan)
    g["share_of_book"] = g["gross_carrying_amount"] / g.loc["Total", "gross_carrying_amount"]
    g.index = [f"Stage {i}" if i != "Total" else "Total" for i in g.index]
    return g


__all__ = ["available_dates", "bundle", "compute", "reproject", "summary"]
