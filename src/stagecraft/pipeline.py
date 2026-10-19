"""End-to-end run: raw files -> panel -> models -> staging -> ECL -> validation -> report.

    python -m stagecraft.pipeline            # everything
    python -m stagecraft.pipeline --no-pdf   # skip the PDF
"""

from __future__ import annotations

import argparse
import json
import pickle
import time

import numpy as np
import pandas as pd
import polars as pl

from . import buckets, datacheck, ecl, ead, hazard, load, lgd, macro, markov, scenarios, scorecard, staging
from .config import load_config, path
from .dates import date_to_mi
from .segments import fico_band, ltv_band, segment


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def fit_models(rd: str, cfg: dict, hist: pd.DataFrame) -> dict:
    """Every model estimated as at `rd`, using data up to `rd` only."""
    orig = load.read_orig(cfg)
    loans = buckets.read_loans(cfg)
    panel = buckets.scan_panel(cfg)
    asat = scenarios.macro_path(hist, rd, scenarios.spec(cfg, rd, "base"), cfg)

    sc = scorecard.fit(scorecard.training_set(orig, loans, rd, cfg), cfg)
    scores = pl.DataFrame({"loan_id": orig["loan_id"], "score": sc.logit(orig), "vintage": orig["vintage"]})
    log(f"{rd}: scorecard on {sc.n_train:,} loans (default rate {sc.default_rate:.2%})")

    tp = hazard.training_panel(panel, scores, asat, rd, cfg)
    hm = hazard.fit(tp, cfg)
    log(f"{rd}: hazard on {hm.n_rows:,} loan-months, {hm.n_events:,} defaults")

    mk = markov.fit(markov.transitions(panel, orig, rd, cfg), cfg)

    sign = datacheck.sign_convention(loans, cfg)["sign"]
    hpi_actual = hist["hpi"]  # realised HPI at past default dates is known by rd
    rdf = lgd.resolved_defaults(loans, orig, hpi_actual, rd, cfg, sign)
    cure = lgd.cure_rate(panel, loans, rd, cfg)
    lm = lgd.fit(rdf, cure, cfg)
    log(f"{rd}: LGD on {lm.n:,} resolved defaults, P(liquidation) {lm.p_liq:.1%}")

    cpr = ead.cpr_table(panel, hist, rd, cfg)
    return {"scorecard": sc, "scores": scores, "hazard": hm, "markov": mk, "lgd": lm, "lgd_data": rdf,
            "cure": cure, "cpr": cpr, "asat": asat, "hazard_train": tp}


def run_date(rd: str, cfg: dict, hist: pd.DataFrame) -> dict:
    m = fit_models(rd, cfg, hist)
    orig = load.read_orig(cfg)
    panel = buckets.scan_panel(cfg)
    snap = staging.snapshot(panel, orig, m["scores"], rd)
    rdm = date_to_mi(rd)
    paths = scenarios.all_paths(hist, rd, cfg)
    base = paths["base"]
    snap["cltv"] = snap["ltv"] * snap["upb"] / snap["orig_upb"] * snap["hpi_orig"] / base["hpi"].get(rdm)
    snap["segment"] = segment(snap["credit_score"], snap["cltv"], cfg)
    snap["fico_band"] = fico_band(snap["credit_score"], cfg)
    snap["ltv_band"] = ltv_band(snap["cltv"], cfg)
    smm = ead.loan_smm(snap["current_rate"], float(hist["mtg_rate"].get(rdm)), m["cpr"], cfg)
    snap["smm"] = smm
    s3 = staging.stage3_flag(snap, rd, cfg)
    perf = ~s3
    sp = snap[perf].reset_index(drop=True)
    log(f"{rd}: {len(snap):,} loans on book, {int(s3.sum()):,} credit-impaired")

    res = snap[["loan_id", "vintage", "segment", "fico_band", "ltv_band", "state", "status", "upb", "cltv",
                "current_rate", "rem_months", "smm"]].copy()
    T12 = cfg["ecl"]["stage1_horizon_months"]
    curve_len = 120
    curves = {}
    for name, p in paths.items():
        c = ecl.project(sp, p, rd, m["hazard"], m["lgd"], smm[perf], cfg, keep_curve=curve_len if name == "base" else 0)
        for k in ("pd12", "pd_life", "ecl12", "ecl_life", "pe12", "pe_life"):
            col = np.zeros(len(snap))
            col[perf] = c[k]
            res[f"{k}_{name}"] = col
        res[f"lgd3_{name}"] = ecl.stage3_lgd(snap, p, rd, m["lgd"], cfg)
        res[f"ecl3_{name}"] = res[f"lgd3_{name}"] * snap["upb"]
        if name == "base":
            curves["hazard_base"] = c["curve"]
    o = ecl.project(sp, scenarios.neutral_path(hist, rd, cfg), rd, m["hazard"], m["lgd"], smm[perf], cfg,
                    origination=True)
    res["pd_orig_life"] = 0.0
    res.loc[perf, "pd_orig_life"] = o["pd_life"]

    w = scenarios.weights(cfg)
    res["pd12_w"] = sum(wt * res[f"pd12_{s}"] for s, wt in w.items())
    res["pd_life_w"] = sum(wt * res[f"pd_life_{s}"] for s, wt in w.items())
    basis = res["pd_life_w"] if cfg["staging"]["sicr_pd_basis"] == "weighted" else res["pd_life_base"]
    st = staging.assign(snap, s3, basis.to_numpy(), res["pd_orig_life"].to_numpy(), cfg)
    res = pd.concat([res, st], axis=1)
    for s in scenarios.scenario_names(cfg):
        res[f"ecl_{s}"] = ecl.stage_ecl(res["stage"].to_numpy(), res[f"ecl12_{s}"].to_numpy(),
                                        res[f"ecl_life_{s}"].to_numpy(), res[f"ecl3_{s}"].to_numpy())
    res["ecl_w"] = sum(wt * res[f"ecl_{s}"] for s, wt in w.items())
    if cfg["overlay"]["enabled"]:
        res["overlay"] = res["ecl_w"] * res["stage"].map(cfg["overlay"]["pct_by_stage"]).fillna(0)
        res["ecl_w"] = res["ecl_w"] + res["overlay"]

    # Markov challenger PDs (12-month and remaining term).
    pd12_mk, pdl_mk = m["markov"].loan_pds(snap["segment"].to_numpy(), np.minimum(snap["state"].to_numpy(), m["markov"].k - 1),
                                            np.minimum(snap["rem_months"].to_numpy(), cfg["ecl"]["max_lifetime_months"]).astype(int))
    res["pd12_markov"] = np.where(perf, pd12_mk, 1.0)
    res["pd_life_markov"] = np.where(perf, pdl_mk, 1.0)
    # Markov term structure (average over performing loans, same horizon as the hazard curve).
    mk_curve = np.zeros(curve_len)
    for (seg, stt), g in snap[perf].groupby(["segment", "state"]):
        mk_curve += m["markov"].cum_pd(seg, int(stt), curve_len) * len(g)
    curves["markov"] = mk_curve / max(perf.sum(), 1)
    curves["hazard_base"] = curves["hazard_base"].mean(axis=0)

    # Downturn-LGD sensitivity inputs.
    res["lgd_downturn"] = m["lgd"].downturn_effective(snap["cltv"].to_numpy())
    return {"rd": rd, "models": m, "snap": snap, "res": res, "paths": paths, "curves": curves, "perf_mask": perf}


def save(run: dict, cfg: dict) -> None:
    rd = run["rd"]
    out = path(cfg, "outputs")
    md = out / "models" / rd
    md.mkdir(parents=True, exist_ok=True)
    m = run["models"]
    m["scorecard"].table().to_csv(md / "scorecard_coefficients.csv")
    m["hazard"].table().to_csv(md / "hazard_coefficients.csv")
    m["lgd"].coef_table().to_csv(md / "lgd_coefficients.csv")
    m["lgd"].table.to_csv(md / "lgd_by_ltv_band.csv", index=False)
    m["lgd"].downturn.to_csv(md / "lgd_downturn_by_ltv_band.csv", index=False)
    m["cpr"].to_csv(md / "cpr_by_incentive.csv", index=False)
    m["markov"].matrix_frame().to_csv(md / "markov_pooled_matrix.csv")
    with open(md / "summary.json", "w") as f:
        json.dump({"cure": m["cure"], "scorecard_n": m["scorecard"].n_train, "hazard_rows": m["hazard"].n_rows,
                   "hazard_events": m["hazard"].n_events, "lgd_n": m["lgd"].n}, f, indent=2)
    pd.DataFrame(run["curves"]).rename_axis("month").to_csv(md / "pd_term_structure.csv")
    if not cfg.get("_demo"):
        run["res"].to_parquet(out / f"loan_ecl_{rd}.parquet", index=False)

    # Bundle for the dashboard: models + snapshot + macro history.
    app = path(cfg, "app_bundle")
    app.mkdir(parents=True, exist_ok=True)
    keep = {k: m[k] for k in ("hazard", "lgd", "markov")}
    with open(app / f"models_{rd}.pkl", "wb") as f:
        pickle.dump(keep, f)
    run["snap"].to_parquet(app / f"snapshot_{rd}.parquet", index=False)
    (app / "SOURCE.txt").write_text("synthetic\n" if load.is_synthetic(cfg) else "freddie\n")
    run["res"].to_parquet(app / f"results_{rd}.parquet", index=False)


def demo_config() -> dict:
    """Config for building the dashboard's demo bundle from the synthetic
    sample, in separate folders so it never touches a real-data run."""
    import copy

    cfg = copy.deepcopy(load_config())
    cfg["paths"].update({"interim": "data/interim_demo", "processed": "data/processed_demo",
                         "outputs": "data/processed_demo/outputs", "app_bundle": "app/demo_bundle"})
    cfg["_demo"] = True
    return cfg


def run(cfg: dict | None = None, pdf: bool = True, dump: bool = True, source: str = "auto") -> dict:
    cfg = cfg or load_config()
    from . import report, validation

    src = {"auto": load.source_dir(cfg), "raw": path(cfg, "raw_freddie"), "sample": path(cfg, "sample_freddie")}[source]
    log(f"parsing {src}")
    manifest = load.build(cfg, src)
    buckets.build_panel(cfg)
    if not cfg.get("_demo"):
        datacheck.write_report(cfg)
    log(f"panel built ({'SYNTHETIC sample' if manifest['synthetic'] else 'Freddie Mac data'})")
    hist = macro.load_macro(cfg)
    hist.to_csv(path(cfg, "app_bundle").mkdir(parents=True, exist_ok=True) or path(cfg, "app_bundle") / "macro_history.csv")
    runs = {}
    for rd in cfg["reporting_dates"]:
        runs[rd] = run_date(rd, cfg, hist)
        save(runs[rd], cfg)
    if dump:
        import pickle as _p
        with open(path(cfg, "processed") / "runs.pkl", "wb") as f:
            _p.dump(runs, f)
    log("validation")
    val = validation.run_all(runs, cfg, hist)
    log("charts and tables")
    report.outputs(runs, val, cfg)
    if pdf and not cfg.get("_demo"):
        log("model documentation PDF")
        report.build_pdf(runs, val, cfg)
    log("done")
    return {"runs": runs, "validation": val}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-pdf", action="store_true")
    ap.add_argument("--source", choices=["auto", "raw", "sample"], default="auto",
                    help="auto = data/raw/freddie if it has files, else the bundled synthetic sample")
    ap.add_argument("--demo", action="store_true",
                    help="rebuild the dashboard's committed demo bundle (app/demo_bundle) from the synthetic sample")
    a = ap.parse_args()
    if a.demo:
        run(demo_config(), pdf=False, dump=False, source="sample")
    else:
        run(pdf=not a.no_pdf, source=a.source)


if __name__ == "__main__":
    main()
