"""Validation: out-of-time PD backtests, discrimination and calibration,
stage migration, sensitivities and the provision movement waterfall.

Everything here uses data AFTER the reporting date. That data is never used
to estimate anything in the ECL.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import polars as pl
from scipy import stats
from sklearn.metrics import roc_auc_score

from . import ecl, scenarios, scorecard, staging
from .buckets import read_loans, scan_panel
from .config import load_config
from .dates import date_to_mi
from .load import read_orig


# --------------------------------------------------------------------------
# Outcomes after the reporting date
# --------------------------------------------------------------------------
def realised_default(loan_ids: pd.Series, reporting_date: str, months: int, cfg: dict) -> np.ndarray:
    """1 if the loan enters default within `months` after the reporting date."""
    rd = date_to_mi(reporting_date)
    ev = (scan_panel(cfg).filter(pl.col("default_entry") & pl.col("mi").is_between(rd + 1, rd + months))
          .select("loan_id").unique().collect())
    return loan_ids.isin(set(ev["loan_id"].to_list())).to_numpy()


def observed_window_ok(reporting_date: str, months: int, cfg: dict) -> bool:
    last = scan_panel(cfg).select(pl.col("mi").max()).collect().item()
    return date_to_mi(reporting_date) + months <= last


# --------------------------------------------------------------------------
# Backtest
# --------------------------------------------------------------------------
def binomial_light(n: int, d: int, p: float) -> tuple[float, str]:
    """Two-sided binomial test of observed defaults vs mean predicted PD, with
    the Basel-style traffic light: green inside the 95% band, amber inside
    99.9%, red outside."""
    if n == 0:
        return np.nan, "n/a"
    lo95, hi95 = stats.binom.ppf([0.025, 0.975], n, p)
    lo999, hi999 = stats.binom.ppf([0.0005, 0.9995], n, p)
    pval = stats.binomtest(d, n, p).pvalue if 0 < p < 1 else np.nan
    light = "green" if lo95 <= d <= hi95 else ("amber" if lo999 <= d <= hi999 else "red")
    return pval, light


def backtest(res: pd.DataFrame, reporting_date: str, cfg: dict) -> dict:
    H = cfg["validation"]["backtest_horizon_months"]
    perf = res[res["stage"] < 3].copy()
    perf["observed"] = realised_default(perf["loan_id"], reporting_date, H, cfg)

    def table(by: str | None) -> pd.DataFrame:
        groups = [("All", perf)] if by is None else list(perf.groupby(by))
        rows = []
        for key, g in groups:
            n, d = len(g), int(g["observed"].sum())
            p = float(g["pd12_w"].mean())
            pval, light = binomial_light(n, d, p)
            rows.append({"group": key, "loans": n, "defaults": d, "observed_rate": d / max(n, 1),
                         "predicted_pd12_weighted": p, "predicted_pd12_base": float(g["pd12_base"].mean()),
                         "predicted_pd12_markov": float(g["pd12_markov"].mean()), "p_value": pval, "traffic_light": light})
        return pd.DataFrame(rows)

    out = {"overall": table(None), "segment": table("segment"), "vintage": table("vintage"), "stage": table("stage")}
    y = perf["observed"].to_numpy()
    disc = {}
    if 0 < y.sum() < len(y):
        for col in ("pd12_w", "pd12_markov"):
            auc = roc_auc_score(y, perf[col])
            disc[col] = {"auc": auc, "gini": 2 * auc - 1}
    out["discrimination"] = disc
    out["calibration"] = calibration(perf["pd12_w"].to_numpy(), y)
    out["window_complete"] = observed_window_ok(reporting_date, H, cfg)
    out["perf"] = perf[["loan_id", "pd12_w", "observed"]]
    return out


def calibration(pred: np.ndarray, obs: np.ndarray, q: int = 10) -> pd.DataFrame:
    df = pd.DataFrame({"pred": pred, "obs": obs.astype(float)})
    df["decile"] = pd.qcut(df["pred"].rank(method="first"), q, labels=False) + 1
    return df.groupby("decile").agg(loans=("obs", "size"), mean_predicted=("pred", "mean"),
                                    observed_rate=("obs", "mean")).reset_index()


def scorecard_validation(run: dict, cfg: dict) -> dict:
    """In-sample and out-of-time AUC for the origination scorecard. OOT = the
    vintages whose 36-month window had not finished at the reporting date,
    scored on outcomes observed afterwards."""
    rd = run["rd"]
    sc = run["models"]["scorecard"]
    orig, loans = read_orig(cfg), read_loans(cfg)
    T = cfg["scorecard"]["target_months"]
    rdm = date_to_mi(rd)
    last = scan_panel(cfg).select(pl.col("mi").max()).collect().item()
    allo = scorecard.outcome(orig, loans, T)
    ins = allo.filter((pl.col("fpd_mi") + T - 1 <= rdm) & (pl.col("vintage") >= cfg["scorecard"]["min_train_vintage"]))
    oot = allo.filter((pl.col("fpd_mi") + T - 1 > rdm) & (pl.col("fpd_mi") <= rdm) & (pl.col("fpd_mi") + T - 1 <= last))
    out = {}
    for name, d in (("in_sample", ins), ("out_of_time", oot)):
        y = d["y"].to_numpy()
        if 0 < y.sum() < len(y):
            p = sc.pd(d)
            auc = roc_auc_score(y, p)
            out[name] = {"loans": len(y), "default_rate": float(y.mean()), "auc": auc, "gini": 2 * auc - 1,
                         "calibration": calibration(p, y)}
    return out


def hazard_insample_auc(run: dict) -> dict:
    """Loan-month AUC of the fitted hazard on its own training panel."""
    from . import hazard as hz
    cfg = load_config()
    tp = run["models"]["hazard_train"]
    X = hz.design_matrix(tp, cfg)
    eta = X.to_numpy() @ run["models"]["hazard"].params.reindex(X.columns).to_numpy()
    auc = roc_auc_score(tp["y"], eta, sample_weight=tp["w"])
    return {"auc": auc, "gini": 2 * auc - 1, "rows": len(tp)}


# --------------------------------------------------------------------------
# Migration between reporting dates
# --------------------------------------------------------------------------
def exit_category(loan_ids: pd.Series, d0: str, d1: str, cfg: dict) -> pd.Series:
    loans = read_loans(cfg).to_pandas().set_index("loan_id")
    a, b = date_to_mi(d0), date_to_mi(d1)
    x = loans.reindex(loan_ids)
    in_window = x["exit_mi"].between(a + 1, b)
    cat = np.where(in_window & (x["exit_type"] == "prepaid"), "Repaid / prepaid",
                   np.where(in_window & (x["exit_type"] == "credit_event"), "Written off",
                            np.where(in_window, "Sold / other exit", "Other exit")))
    return pd.Series(cat, index=loan_ids.index)


def migration(r0: pd.DataFrame, r1: pd.DataFrame, d0: str, d1: str, cfg: dict) -> pd.DataFrame:
    m = r0[["loan_id", "stage", "upb"]].merge(r1[["loan_id", "stage"]], on="loan_id", how="left", suffixes=("_0", "_1"))
    gone = m["stage_1"].isna()
    m["to"] = m["stage_1"].map(lambda s: f"Stage {int(s)}" if pd.notna(s) else None)
    m.loc[gone, "to"] = exit_category(m.loc[gone, "loan_id"], d0, d1, cfg)
    m["from"] = "Stage " + m["stage_0"].astype(int).astype(str)
    cnt = pd.crosstab(m["from"], m["to"])
    order = [c for c in ["Stage 1", "Stage 2", "Stage 3", "Repaid / prepaid", "Written off", "Sold / other exit", "Other exit"]
             if c in cnt.columns]
    cnt = cnt[order]
    pct = cnt.div(cnt.sum(axis=1), axis=0)
    return pd.concat({"loans": cnt, "share": pct}, axis=1)


# --------------------------------------------------------------------------
# Sensitivities
# --------------------------------------------------------------------------
def weighted(res: pd.DataFrame, col: str, w: dict) -> pd.Series:
    return sum(wt * res[f"{col}_{s}"] for s, wt in w.items())


def restage_ecl(run: dict, cfg: dict, multiple: float | None = None, w: dict | None = None,
                downturn_lgd: bool = False, basis_scenario: str | None = None) -> dict:
    res, snap = run["res"], run["snap"]
    w = w or scenarios.weights(cfg)
    s3 = res["stage"].to_numpy() == 3
    if basis_scenario:
        basis = res[f"pd_life_{basis_scenario}"]
    elif cfg["staging"]["sicr_pd_basis"] == "weighted":
        basis = weighted(res, "pd_life", w)
    else:
        basis = res["pd_life_base"]
    st = staging.assign(snap, s3, basis.to_numpy(), res["pd_orig_life"].to_numpy(), cfg, multiple=multiple)["stage"].to_numpy()
    if downturn_lgd:
        e12 = weighted(res, "pe12", w) * res["lgd_downturn"]
        el = weighted(res, "pe_life", w) * res["lgd_downturn"]
        e3 = res["lgd_downturn"] * res["upb"]
    else:
        e12, el, e3 = weighted(res, "ecl12", w), weighted(res, "ecl_life", w), weighted(res, "ecl3", w)
    e = ecl.stage_ecl(st, e12.to_numpy(), el.to_numpy(), e3.to_numpy())
    return {"ecl": float(e.sum()), "stage2_share": float((st == 2).mean()),
            "stage2_upb_share": float(res["upb"][st == 2].sum() / res["upb"].sum()),
            "by_stage": pd.Series(e).groupby(st).sum().to_dict()}


def sensitivities(run: dict, cfg: dict) -> pd.DataFrame:
    base = restage_ecl(run, cfg)
    rows = [{"test": "Model as configured", "setting": f"SICR {cfg['staging']['sicr_relative_multiple']}x, "
             + "/".join(f"{int(100 * v)}" for v in scenarios.weights(cfg).values()), **_row(base, base)}]
    for mlt in cfg["validation"]["sicr_multiples"]:
        r = restage_ecl(run, cfg, multiple=mlt)
        rows.append({"test": "SICR relative threshold", "setting": f"{mlt}x", **_row(r, base)})
    stress = cfg["scenarios"]["stress_only"][0]
    for mlt in cfg["validation"]["sicr_multiples"]:
        r = restage_ecl(run, cfg, multiple=mlt, w={stress: 1.0}, basis_scenario=stress)
        rows.append({"test": "SICR threshold under stress staging", "setting": f"{mlt}x", **_row(r, base)})
    for name, w in cfg["validation"]["alt_weights"].items():
        r = restage_ecl(run, cfg, w=w)
        rows.append({"test": "Scenario weights", "setting": name, **_row(r, base)})
    r = restage_ecl(run, cfg, downturn_lgd=True)
    rows.append({"test": "LGD", "setting": "downturn (2008-2011) LGD", **_row(r, base)})
    for s in scenarios.scenario_names(cfg):
        r = restage_ecl(run, cfg, w={s: 1.0})
        rows.append({"test": "Single scenario (100%)", "setting": s, **_row(r, base)})
    return pd.DataFrame(rows)


def _row(r: dict, base: dict) -> dict:
    return {"ecl": r["ecl"], "change_vs_model": r["ecl"] / base["ecl"] - 1, "stage2_share_loans": r["stage2_share"],
            "stage2_share_upb": r["stage2_upb_share"]}


# --------------------------------------------------------------------------
# Provision movement waterfall (IFRS 7.35H style)
# --------------------------------------------------------------------------
def waterfall(run0: dict, run1: dict, cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Attribute the change in the weighted ECL between two reporting dates.

    For each loan on the opening book:
      - not on the closing book and repaid/prepaid/sold -> derecognition (- opening ECL)
      - not on the closing book after a credit event   -> write-off (- opening ECL)
      - still on the book: transfer = ECL at OPENING parameters under the
        CLOSING stage - opening ECL; remeasurement = closing ECL - that amount
        (new PDs, LGDs, macro, models, amortisation)
    Loans on the closing book only -> new originations (+ closing ECL).
    Closing = opening + all lines, by construction (tested)."""
    d0, d1 = run0["rd"], run1["rd"]
    w = scenarios.weights(cfg)
    r0, r1 = run0["res"].copy(), run1["res"].copy()
    for r in (r0, r1):
        r["e12"] = weighted(r, "ecl12", w)
        r["el"] = weighted(r, "ecl_life", w)
        r["e3"] = weighted(r, "ecl3", w)
    m = r0[["loan_id", "stage", "ecl_w", "e12", "el", "e3"]].merge(
        r1[["loan_id", "stage", "ecl_w"]], on="loan_id", how="outer", suffixes=("_0", "_1"), indicator=True)
    lines = []
    opening = float(r0["ecl_w"].sum())
    new = m[m["_merge"] == "right_only"]
    gone = m[m["_merge"] == "left_only"].copy()
    gone["cat"] = exit_category(gone["loan_id"], d0, d1, cfg).to_numpy()
    cont = m[m["_merge"] == "both"].copy()
    stg1 = cont["stage_1"].to_numpy().astype(int)
    stg0 = cont["stage_0"].to_numpy().astype(int)
    # Opening-date ECL recomputed under the closing stage. Loans that were
    # Stage 3 at the opening date have no performing-loan projection, so their
    # whole change is remeasurement.
    at_new_stage = np.where(stg0 == 3, cont["ecl_w_0"], ecl.stage_ecl(stg1, cont["e12"], cont["el"], cont["e3"]))
    cont["transfer"] = at_new_stage - cont["ecl_w_0"]
    cont["remeasure"] = cont["ecl_w_1"] - at_new_stage
    wo = gone["cat"] == "Written off"
    lines = [
        ("Opening ECL " + d0, opening),
        ("New originations", float(new["ecl_w_1"].sum())),
        ("Derecognitions (repaid, prepaid, sold)", -float(gone.loc[~wo, "ecl_w_0"].sum())),
        ("Transfers to Stage 1", float(cont.loc[(stg1 == 1) & (stg0 != 1), "transfer"].sum())),
        ("Transfers to Stage 2", float(cont.loc[(stg1 == 2) & (stg0 != 2), "transfer"].sum())),
        ("Transfers to Stage 3", float(cont.loc[(stg1 == 3) & (stg0 != 3), "transfer"].sum())),
        ("Remeasurement (PD, LGD, EAD, macro)", float(cont["remeasure"].sum())),
        ("Write-offs", -float(gone.loc[wo, "ecl_w_0"].sum())),
    ]
    closing = float(r1["ecl_w"].sum())
    wf = pd.DataFrame(lines, columns=["line", "amount"])
    wf.loc[len(wf)] = ["Closing ECL " + d1, closing]
    # By-stage version (IFRS 7.35H): columns Stage 1/2/3.
    rows = []
    def by_stage(label, vals, stages):
        s = pd.Series(np.asarray(vals, float)).groupby(np.asarray(stages, int)).sum()
        rows.append({"line": label, **{f"Stage {k}": float(s.get(k, 0.0)) for k in (1, 2, 3)}})
    by_stage("Opening ECL", r0["ecl_w"], r0["stage"])
    by_stage("New originations", new["ecl_w_1"], new["stage_1"])
    by_stage("Derecognitions", -gone.loc[~wo, "ecl_w_0"], gone.loc[~wo, "stage_0"])
    # transfers move ECL out of the old stage and into the new one
    mv = (stg1 != stg0)
    by_stage("Transfers out (at opening ECL)", -cont.loc[mv, "ecl_w_0"], stg0[mv])
    by_stage("Transfers in (at opening parameters)", at_new_stage[mv], stg1[mv])
    by_stage("Remeasurement", cont["remeasure"], stg1)
    by_stage("Write-offs", -gone.loc[wo, "ecl_w_0"], gone.loc[wo, "stage_0"])
    by_stage("Closing ECL", r1["ecl_w"], r1["stage"])
    return wf, pd.DataFrame(rows)


def run_all(runs: dict, cfg: dict, hist: pd.DataFrame) -> dict:
    dates = list(runs)
    out = {"backtest": {}, "scorecard": {}, "hazard_auc": {}, "sensitivity": {}}
    for d in dates:
        out["backtest"][d] = backtest(runs[d]["res"], d, cfg)
        out["scorecard"][d] = scorecard_validation(runs[d], cfg)
        out["hazard_auc"][d] = hazard_insample_auc(runs[d])
        out["sensitivity"][d] = sensitivities(runs[d], cfg)
    if len(dates) >= 2:
        out["migration"] = migration(runs[dates[0]]["res"], runs[dates[1]]["res"], dates[0], dates[1], cfg)
        out["waterfall"], out["waterfall_by_stage"] = waterfall(runs[dates[0]], runs[dates[1]], cfg)
    return out
