"""Result tables (CSV), charts (PNG) and the model documentation PDF."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import charts, scenarios
from .config import ROOT, path
from .dates import date_to_mi
from .load import is_synthetic


def note(cfg) -> str | None:
    return "Synthetic sample data (stagecraft.synth), not Freddie Mac loans." if is_synthetic(cfg) else \
        "Source: Freddie Mac Single-Family Loan-Level Dataset (sample files); FRED."


# --------------------------------------------------------------------------
# Tables
# --------------------------------------------------------------------------
def by_stage(res: pd.DataFrame, cfg) -> pd.DataFrame:
    names = scenarios.scenario_names(cfg)
    g = res.groupby("stage").agg(loans=("loan_id", "size"), gross_carrying_amount=("upb", "sum"),
                                 ecl_weighted=("ecl_w", "sum"), **{f"ecl_{s}": (f"ecl_{s}", "sum") for s in names},
                                 mean_pd12=("pd12_w", "mean"), mean_pd_lifetime=("pd_life_w", "mean")).reset_index()
    tot = g.drop(columns="stage").sum().astype(object)
    tot["stage"] = "Total"
    tot["mean_pd12"] = res["pd12_w"].mean()
    tot["mean_pd_lifetime"] = res["pd_life_w"].mean()
    g = pd.concat([g.astype({"stage": object}), tot.to_frame().T], ignore_index=True)
    g["coverage"] = g["ecl_weighted"].astype(float) / g["gross_carrying_amount"].astype(float)
    g["share_of_book"] = g["gross_carrying_amount"].astype(float) / float(res["upb"].sum())
    return g


def by_group(res: pd.DataFrame, col: str) -> pd.DataFrame:
    g = res.groupby(col).agg(loans=("loan_id", "size"), gross_carrying_amount=("upb", "sum"),
                             ecl_weighted=("ecl_w", "sum"), stage2_loans=("stage", lambda s: int((s == 2).sum())),
                             stage3_loans=("stage", lambda s: int((s == 3).sum())), mean_pd12=("pd12_w", "mean")).reset_index()
    g["coverage"] = g["ecl_weighted"] / g["gross_carrying_amount"]
    return g


def by_scenario(res: pd.DataFrame, cfg) -> pd.DataFrame:
    w = scenarios.weights(cfg)
    rows = []
    for s in scenarios.scenario_names(cfg):
        rows.append({"scenario": s, "weight": w.get(s, 0.0), "ecl": res[f"ecl_{s}"].sum(),
                     **{f"stage{k}": res.loc[res["stage"] == k, f"ecl_{s}"].sum() for k in (1, 2, 3)}})
    rows.append({"scenario": "probability-weighted", "weight": 1.0, "ecl": res["ecl_w"].sum(),
                 **{f"stage{k}": res.loc[res["stage"] == k, "ecl_w"].sum() for k in (1, 2, 3)}})
    return pd.DataFrame(rows)


def headline(runs: dict, val: dict, cfg) -> dict:
    h = {"synthetic": is_synthetic(cfg), "dates": {}}
    for d, r in runs.items():
        res = r["res"]
        st = by_stage(res, cfg).set_index("stage")
        bt = val["backtest"][d]
        o = bt["overall"].iloc[0]
        h["dates"][d] = {
            "loans": int(len(res)), "gross_carrying_amount": float(res["upb"].sum()),
            "ecl_weighted": float(res["ecl_w"].sum()), "ecl_base": float(res["ecl_base"].sum()),
            "ecl_upside": float(res["ecl_upside"].sum()), "ecl_downside": float(res["ecl_downside"].sum()),
            "ecl_severe": float(res["ecl_severe"].sum()),
            "coverage": {str(k): float(st.loc[k, "coverage"]) for k in st.index},
            "share_of_book": {str(k): float(st.loc[k, "share_of_book"]) for k in st.index},
            "loans_by_stage": {str(k): int(st.loc[k, "loans"]) for k in st.index},
            "backtest": {"loans": int(o["loans"]), "defaults": int(o["defaults"]), "observed": float(o["observed_rate"]),
                         "predicted": float(o["predicted_pd12_weighted"]), "markov": float(o["predicted_pd12_markov"]),
                         "traffic_light": o["traffic_light"], "p_value": float(o["p_value"]),
                         "auc": bt["discrimination"].get("pd12_w", {}).get("auc"),
                         "auc_markov": bt["discrimination"].get("pd12_markov", {}).get("auc"),
                         "segments_green": int((bt["segment"]["traffic_light"] == "green").sum()),
                         "segments_total": int(len(bt["segment"]))},
            "scorecard": {k: {"auc": v["auc"], "gini": v["gini"], "loans": v["loans"]} for k, v in val["scorecard"][d].items()},
            "hazard_auc_in_sample": val["hazard_auc"][d]["auc"],
            "lgd": {"n": r["models"]["lgd"].n, "p_liq": r["models"]["lgd"].p_liq,
                    "mean_severity": float(r["models"]["lgd"].table.attrs.get("overall", np.nan)),
                    "downturn_severity": float(r["models"]["lgd"].downturn.attrs.get("overall", np.nan))},
        }
    if "waterfall" in val:
        h["waterfall"] = val["waterfall"].to_dict(orient="records")
    return h


def outputs(runs: dict, val: dict, cfg) -> dict:
    out = path(cfg, "outputs")
    ch = out / "charts"
    ch.mkdir(parents=True, exist_ok=True)
    n = note(cfg)
    stage_tables, vint, sc_tab, curves = {}, [], {}, {}
    for d, r in runs.items():
        res = r["res"]
        st = by_stage(res, cfg)
        st.to_csv(out / f"ecl_by_stage_{d}.csv", index=False)
        stage_tables[d] = st[st["stage"] != "Total"].assign(stage=lambda x: x["stage"].astype(int))
        by_group(res, "vintage").to_csv(out / f"ecl_by_vintage_{d}.csv", index=False)
        by_group(res, "segment").to_csv(out / f"ecl_by_segment_{d}.csv", index=False)
        by_group(res, "trigger").to_csv(out / f"stage_triggers_{d}.csv", index=False)
        bs = by_scenario(res, cfg)
        bs.to_csv(out / f"ecl_by_scenario_{d}.csv", index=False)
        sc_tab[d] = bs.set_index("scenario")["ecl"].rename({"probability-weighted": "weighted"})
        vint.append(by_group(res, "vintage").assign(date=d))
        curves[d] = r["curves"]
        bt = val["backtest"][d]
        for k in ("overall", "segment", "vintage", "stage"):
            bt[k].to_csv(out / f"backtest_{k}_{d}.csv", index=False)
        bt["calibration"].to_csv(out / f"calibration_hazard_{d}.csv", index=False)
        val["sensitivity"][d].to_csv(out / f"sensitivity_{d}.csv", index=False)
        disc = {"hazard_pd12_oot": bt["discrimination"].get("pd12_w"), "markov_pd12_oot": bt["discrimination"].get("pd12_markov"),
                "hazard_in_sample_loan_month": val["hazard_auc"][d],
                **{f"scorecard_{k}": {kk: vv for kk, vv in v.items() if kk != "calibration"} for k, v in val["scorecard"][d].items()}}
        with open(out / f"discrimination_{d}.json", "w") as f:
            json.dump(disc, f, indent=2, default=float)
        rd = date_to_mi(d)
        charts.scenario_paths(r["paths"], rd, rd, ch / f"scenario_paths_{d}.png", n)
        charts.sicr_cliff(val["sensitivity"][d], ch / f"sicr_cliff_{d}.png", n)
    last = list(runs)[-1]
    first = list(runs)[0]
    charts.ecl_by_stage(stage_tables, ch / "ecl_coverage_by_stage.png", n)
    charts.pd_term_structure(curves, ch / "pd_term_structure.png", n)
    charts.ecl_by_scenario(pd.DataFrame(sc_tab).T, ch / "ecl_by_scenario.png", n)
    charts.ecl_by_vintage(pd.concat(vint), ch / "ecl_coverage_by_vintage.png", n)
    charts.backtest_bars({d: val["backtest"][d]["segment"] for d in runs}, ch / "backtest_by_segment.png", n)
    charts.backtest_bars({d: val["backtest"][d]["vintage"] for d in runs}, ch / "backtest_by_vintage.png", n, by="vintage")
    m = runs[first]["models"]["lgd"]
    charts.lgd_bands(m.table, m.downturn, ch / "lgd_by_ltv_band.png", n)
    cal = {f"Hazard 12m PD from {d}": val["backtest"][d]["calibration"] for d in runs}
    for d in runs:
        if "out_of_time" in val["scorecard"][d]:
            cal[f"Scorecard 36m PD, OOT ({d} model)"] = val["scorecard"][d]["out_of_time"]["calibration"]
    charts.calibration_plot(cal, ch / "calibration.png", n)
    rocs = {}
    for d in runs:
        p = val["backtest"][d]["perf"]
        rocs[f"Hazard 12m PD, {d} (AUC {val['backtest'][d]['discrimination'].get('pd12_w', {}).get('auc', float('nan')):.2f})"] = (p["observed"], p["pd12_w"])
    charts.roc_curves(rocs, ch / "roc.png", n)
    if "waterfall" in val:
        val["waterfall"].to_csv(out / "provision_waterfall.csv", index=False)
        val["waterfall_by_stage"].to_csv(out / "provision_waterfall_by_stage.csv", index=False)
        val["migration"].to_csv(out / "stage_migration.csv")
        charts.waterfall(val["waterfall"], ch / "provision_waterfall.png", n)
        charts.migration_heat(val["migration"], ch / "stage_migration.png", n)
    h = headline(runs, val, cfg)
    with open(out / "headline.json", "w") as f:
        json.dump(h, f, indent=2, default=float)
    if not cfg.get("_demo"):
        update_readme(h)
    return h


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------
def build_pdf(runs: dict, val: dict, cfg) -> None:
    from .docpdf import build

    build(runs, val, cfg, ROOT / "report" / "model_documentation.pdf")


# --------------------------------------------------------------------------
# README results block
# --------------------------------------------------------------------------
def readme_block(h: dict) -> str:
    dates = list(h["dates"])
    lines = []
    if h["synthetic"]:
        lines += ["> **These numbers come from the bundled synthetic sample**, not Freddie Mac loans. They show the engine",
                  "> working end to end. Run the pipeline on the real sample files to replace them.", ""]
    lines += ["| | " + " | ".join(dates) + " |", "|---|" + "---|" * len(dates)]

    def row(label, f):
        lines.append(f"| {label} | " + " | ".join(f(h["dates"][d]) for d in dates) + " |")

    m = lambda v: f"{'−' if v < 0 else ''}${abs(v) / 1e6:,.2f}m"  # noqa: E731
    row("Loans on book", lambda x: f"{x['loans']:,}")
    row("Gross carrying amount", lambda x: f"${x['gross_carrying_amount'] / 1e9:,.2f}bn")
    row("**Probability-weighted ECL**", lambda x: f"**{m(x['ecl_weighted'])}**")
    row("Coverage: total", lambda x: f"{x['coverage']['Total']:.3%}")
    for s in ("1", "2", "3"):
        row(f"Stage {s}: share of book / coverage",
            lambda x, s=s: f"{x['share_of_book'].get(s, 0):.1%} / {x['coverage'].get(s, 0):.2%}")
    row("Base-scenario ECL", lambda x: m(x["ecl_base"]))
    row("Weighted vs base", lambda x: f"{x['ecl_weighted'] / x['ecl_base'] - 1:+.1%}")
    row("Severe stress ECL", lambda x: f"{m(x['ecl_severe'])} ({x['ecl_severe'] / x['ecl_weighted']:.1f}x)")
    row("12m PD backtest: predicted vs observed",
        lambda x: f"{x['backtest']['predicted']:.2%} vs {x['backtest']['observed']:.2%} ({x['backtest']['traffic_light']})")
    row("Out-of-time AUC (hazard / Markov)",
        lambda x: f"{(x['backtest']['auc'] or float('nan')):.2f} / {(x['backtest']['auc_markov'] or float('nan')):.2f}")
    row("Scorecard AUC (in-sample / out-of-time)",
        lambda x: f"{x['scorecard'].get('in_sample', {}).get('auc', float('nan')):.2f} / "
                  f"{x['scorecard'].get('out_of_time', {}).get('auc', float('nan')):.2f}")
    if "waterfall" in h:
        lines += ["", "Provision movement " + " → ".join(dates) + ":", ""]
        lines += ["| Movement | Amount |", "|---|---|"]
        lines += [f"| {r['line']} | {m(r['amount'])} |" for r in h["waterfall"]]
    return "\n".join(lines)


def update_readme(h: dict) -> None:
    p = ROOT / "README.md"
    if not p.exists():
        return
    t = p.read_text()
    a, b = "<!-- RESULTS:START -->", "<!-- RESULTS:END -->"
    if a in t and b in t:
        t = t[: t.index(a) + len(a)] + "\n" + readme_block(h) + "\n" + t[t.index(b):]
        p.write_text(t)
