"""Loan-level expected credit loss.

    ECL = sum_t  marginal PD_t x LGD_t x EAD_t x DF_t

    marginal PD_t = S_{t-1} x h_t                 (defaults in month t)
    S_t           = S_{t-1} x (1 - h_t) x (1 - SMM) (still alive and on the books)
    DF_t          = (1 + r / 12)^(-t),  r = current note rate (EIR proxy)

h_t is the hazard model's default probability for month t under a scenario
path, SMM the loan's prepayment rate (ead.py), EAD_t the scheduled balance and
LGD_t the cure-adjusted severity at the projected current LTV. Because
S_{t-1} removes loans that have already defaulted or prepaid, the marginal PDs
sum to a cumulative PD that is at most 1, with no double counting.

Stage 1 = the first 12 months; Stage 2 = all months up to the remaining term;
Stage 3 = LGD x EAD with PD = 1, where LGD reflects house prices over the
workout period under the scenario.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import hazard as hz
from .dates import date_to_mi
from .ead import balance_schedule
from .lgd import judicial


def survival_components(h: np.ndarray, smm: np.ndarray, ead: np.ndarray, lgd: np.ndarray, rate: np.ndarray,
                        rem: np.ndarray, T12: int = 12) -> dict:
    n, T = h.shape
    t = np.arange(1, T + 1)[None, :]
    mask = t <= np.asarray(rem)[:, None]
    h = np.where(mask, h, 0.0)
    surv = np.cumprod((1 - h) * (1 - np.asarray(smm)[:, None]), axis=1)
    s_prev = np.hstack([np.ones((n, 1)), surv[:, :-1]])
    marg = s_prev * h
    df = (1 + np.asarray(rate)[:, None] / 1200) ** (-t)
    pe = marg * ead * df          # PV of exposure at default, before LGD
    el = pe * lgd
    k = min(T12, T)
    return {
        "pd12": marg[:, :k].sum(1), "pd_life": marg.sum(1),
        "ecl12": el[:, :k].sum(1), "ecl_life": el.sum(1),
        "pe12": pe[:, :k].sum(1), "pe_life": pe.sum(1),
        "marg": marg,
    }


def _path_arrays(path: pd.DataFrame, rd: int, T: int) -> dict:
    p = path.reindex(np.arange(rd + 1, rd + T + 1))
    return {c: p[c].to_numpy()[None, :] for c in ("hpi", "dur12", "hpa12")}


def project(snap: pd.DataFrame, path: pd.DataFrame, reporting_date: str, model: hz.HazardModel, lgdm, smm: np.ndarray,
            cfg: dict, origination: bool = False, chunk: int = 5000, keep_curve: int = 0) -> dict:
    """Project PD/ECL components for every loan in `snap` under one macro path.

    origination=True gives the lifetime PD that would have been expected at
    origination for the same remaining window: original LTV amortised on the
    original schedule and indexed at long-run house-price growth, performing,
    no modification, through-the-cycle macro (zero unemployment change)."""
    rd = date_to_mi(reporting_date)
    Tmax = int(min(snap["rem_months"].max(), cfg["ecl"]["max_lifetime_months"]))
    T12 = cfg["ecl"]["stage1_horizon_months"]
    g = cfg["macro"]["long_run_hpi_growth"] / 100
    out = {k: np.zeros(len(snap)) for k in ("pd12", "pd_life", "ecl12", "ecl_life", "pe12", "pe_life")}
    curves = np.zeros((len(snap), keep_curve)) if keep_curve else None
    for lo in range(0, len(snap), chunk):
        s = snap.iloc[lo: lo + chunk]
        n = len(s)
        rem = np.minimum(s["rem_months"].to_numpy(), Tmax).astype(int)
        T = int(rem.max())
        t = np.arange(1, T + 1)[None, :]
        age = s["age_fpd"].to_numpy()[:, None] + t
        deferred = s["deferred_upb"].to_numpy()[:, None]
        B = balance_schedule(s["upb"].to_numpy() - s["deferred_upb"].to_numpy(), s["current_rate"].to_numpy(), rem, T)
        ead = B[:, :-1] + deferred
        P = _path_arrays(path, rd, T)
        if origination:
            Bo = balance_schedule(s["orig_upb"].to_numpy(), s["orig_rate"].to_numpy(), s["orig_term"].to_numpy(),
                                  int(age.max()))
            bal_o = np.take_along_axis(Bo, np.clip(age - 1, 0, Bo.shape[1] - 1).astype(int), axis=1)
            cltv = s["ltv"].to_numpy()[:, None] * bal_o / s["orig_upb"].to_numpy()[:, None] * (1 + g) ** (-(age + 2) / 12)
            status = np.zeros((n, 1), int)
            mod = assist = prior = np.zeros((n, 1))
            dur12 = np.zeros((1, T))
            hpa12 = np.full((1, T), 100 * np.log1p(g))
        else:
            cltv = (s["ltv"].to_numpy()[:, None] * ead / s["orig_upb"].to_numpy()[:, None]
                    * s["hpi_orig"].to_numpy()[:, None] / P["hpi"])
            status = s["state"].to_numpy().astype(int)[:, None]
            mod = s["modified"].to_numpy().astype(float)[:, None]
            assist = s["assisted"].to_numpy().astype(float)[:, None]
            prior = s["prior_default"].to_numpy().astype(float)[:, None]
            dur12, hpa12 = P["dur12"], P["hpa12"]
        f = hz.features(s["score"].to_numpy()[:, None], age, cltv, status, t, mod, assist, prior, dur12, hpa12, cfg,
                        vintage=s["vintage"].to_numpy()[:, None])
        h = 1 / (1 + np.exp(-model.eta(f)))
        h = np.where(hz.at_risk(status, t, cfg), h, 0.0)
        lgd = lgdm.effective(cltv, s["mi_pct"].fillna(0).to_numpy()[:, None],
                             (s["occupancy"] == "I").to_numpy()[:, None], s["upb"].to_numpy()[:, None],
                             judicial(s["property_state"])[:, None])
        c = survival_components(h, smm[lo: lo + n], ead, lgd, s["current_rate"].to_numpy(), rem, T12)
        for k in out:
            out[k][lo: lo + n] = c[k]
        if keep_curve:
            cum = np.cumsum(c["marg"], axis=1)[:, :keep_curve]
            curves[lo: lo + n, : cum.shape[1]] = cum
            if cum.shape[1] < keep_curve:
                curves[lo: lo + n, cum.shape[1]:] = cum[:, -1:]
    if keep_curve:
        out["curve"] = curves
    return out


def stage3_lgd(snap: pd.DataFrame, path: pd.DataFrame, reporting_date: str, lgdm, cfg: dict) -> np.ndarray:
    """LGD for credit-impaired loans: current LTV moved by the scenario's
    house-price change over the assumed workout period."""
    rd = date_to_mi(reporting_date)
    W = cfg["lgd"]["stage3_workout_months"]
    hpi_now = path["hpi"].get(rd)
    hpi_w = path["hpi"].get(rd + W)
    cltv_now = snap["ltv"] * snap["upb"] / snap["orig_upb"] * snap["hpi_orig"] / hpi_now
    cltv_w = cltv_now * hpi_now / hpi_w
    return lgdm.effective(cltv_w.to_numpy(), snap["mi_pct"].fillna(0).to_numpy(), (snap["occupancy"] == "I").to_numpy(),
                          snap["upb"].to_numpy(), judicial(snap["property_state"]))


def stage_ecl(stage: np.ndarray, ecl12: np.ndarray, ecl_life: np.ndarray, ecl3: np.ndarray) -> np.ndarray:
    return np.where(stage == 1, ecl12, np.where(stage == 2, ecl_life, ecl3))
