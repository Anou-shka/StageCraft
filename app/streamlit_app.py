"""Stagecraft dashboard.

    streamlit run app/streamlit_app.py

Reads the bundle written by `python -m stagecraft.pipeline` (outputs/app/,
kept out of git because it is loan-level Freddie Mac data). Without it the app
falls back to the committed synthetic demo bundle (app/demo_bundle/), so it
runs from a fresh clone.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import altair as alt  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from stagecraft import dashboard, scenarios  # noqa: E402
from stagecraft.config import load_config  # noqa: E402

COLORS = {"Stage 1": "#2a78d6", "Stage 2": "#eb6834", "Stage 3": "#1baf7a",
          "base": "#2a78d6", "upside": "#1baf7a", "downside": "#eb6834", "severe": "#6250d6", "weighted": "#0b0b0b"}

st.set_page_config(page_title="Stagecraft ECL", layout="wide")
cfg = load_config()
dates = dashboard.available_dates()
if not dates:
    st.error("No results found. Run `python -m stagecraft.pipeline` (or `--demo`) first.")
    st.stop()

st.title("Stagecraft: IFRS 9 expected credit loss")
if dashboard.is_demo():
    st.info("**Demo mode.** You are looking at the bundled synthetic sample (Freddie Mac file format, simulated "
            "loans), because Freddie Mac's licence does not allow loan-level data in a public repo. The headline "
            "results in the README come from the real data. Put the Freddie Mac sample files in `data/raw/freddie/` "
            "and run `python -m stagecraft.pipeline` to switch this dashboard to them.")
else:
    st.caption("Freddie Mac Single-Family Loan-Level Dataset (sample files, 2005-2019 vintages) and FRED macro data.")

with st.sidebar:
    rd = st.selectbox("Reporting date", dates, index=len(dates) - 1)
    st.subheader("Scenario weights")
    w0 = scenarios.weights(cfg)
    wb = st.slider("Base", 0, 100, int(round(100 * w0["base"])), 5)
    wu = st.slider("Upside", 0, 100, int(round(100 * w0["upside"])), 5)
    wd = st.slider("Downside", 0, 100, int(round(100 * w0["downside"])), 5)
    total = wb + wu + wd
    if total == 0:
        st.warning("All weights are zero; using the configured weights.")
        weights = w0
    else:
        weights = {"base": wb / total, "upside": wu / total, "downside": wd / total}
        if total != 100:
            st.caption(f"Weights sum to {total}; normalised to {weights['base']:.0%} / {weights['upside']:.0%} / {weights['downside']:.0%}.")
    st.subheader("SICR (Stage 2) test")
    mult = st.slider("Relative lifetime-PD multiple", 1.0, 4.0, float(cfg["staging"]["sicr_relative_multiple"]), 0.1)
    abs_bp = st.slider("Minimum absolute increase (bp)", 0, 200, int(cfg["staging"]["sicr_absolute_bp"]), 10)
    st.subheader("LGD")
    downturn = st.toggle("Use downturn (2008-2011) LGD", value=False)
    stress = st.toggle("Show severe stress (100% weight)", value=False)

kpis = st.container()
results = st.container()

st.subheader("Macro paths")
st.caption("Year-end unemployment rate (%) and house-price growth (% per year), years 1-5 after the reporting date. "
           "Edit a cell to re-project that scenario through the hazard and LGD models.")
spec = {s: scenarios.spec(cfg, rd, s) for s in scenarios.scenario_names(cfg)}
grid = pd.DataFrame(
    {f"Y{i + 1}": [spec[s]["unemployment"][i] for s in spec] + [spec[s]["hpi_growth"][i] for s in spec] for i in range(5)},
    index=[f"{s} - unemployment" for s in spec] + [f"{s} - HPI growth" for s in spec],
)
edited = st.data_editor(grid, width="stretch", key=f"grid_{rd}")


@st.cache_data(show_spinner="Re-projecting scenario through the hazard model...")
def _reproject(rd, name, ur, hpi):
    return dashboard.reproject(rd, name, ur, hpi)


overrides = {}
for s in spec:
    ur = tuple(float(x) for x in edited.loc[f"{s} - unemployment"])
    hg = tuple(float(x) for x in edited.loc[f"{s} - HPI growth"])
    if ur != tuple(spec[s]["unemployment"]) or hg != tuple(spec[s]["hpi_growth"]):
        overrides[s] = _reproject(rd, s, ur, hg)

w_used = {"severe": 1.0} if stress else weights
res = dashboard.compute(rd, w_used, mult, abs_bp, downturn, overrides)
base_res = dashboard.compute(rd, scenarios.weights(cfg), cfg["staging"]["sicr_relative_multiple"],
                             cfg["staging"]["sicr_absolute_bp"])
summ = dashboard.summary(res)
summ0 = dashboard.summary(base_res)

c1, c2, c3, c4 = kpis.columns(4)
tot, tot0 = summ.loc["Total", "ecl"], summ0.loc["Total", "ecl"]
c1.metric("Total ECL", f"${tot / 1e6:,.2f}m", f"{tot / tot0 - 1:+.1%} vs configured")
c2.metric("Coverage ratio", f"{summ.loc['Total', 'coverage']:.3%}")
c3.metric("Stage 2 share of book", f"{summ.loc['Stage 2', 'share_of_book']:.2%}",
          f"{summ.loc['Stage 2', 'share_of_book'] - summ0.loc['Stage 2', 'share_of_book']:+.2%} pts")
ecl_base = float(res["ecl_base"].sum())
c4.metric("Weighted vs base ECL", f"{tot / ecl_base - 1:+.1%}" if not stress else "stress view")

left, right = results.columns(2)
with left:
    st.markdown("**ECL and coverage by stage**")
    show = summ.copy()
    show["gross_carrying_amount"] = show["gross_carrying_amount"].map("${:,.0f}".format)
    show["ecl"] = show["ecl"].map("${:,.0f}".format)
    show["coverage"] = show["coverage"].map(lambda v: f"{v:.2%}")
    show["share_of_book"] = show["share_of_book"].map(lambda v: f"{v:.2%}")
    show["loans"] = show["loans"].astype(int).map("{:,}".format)
    show = show.rename(columns={"loans": "Loans", "gross_carrying_amount": "Gross carrying amount", "ecl": "ECL",
                                "coverage": "Coverage", "share_of_book": "Share of book"})
    st.dataframe(show, width="stretch")
    mix = summ.drop("Total").reset_index(names="stage")
    st.altair_chart(
        alt.Chart(mix).mark_bar(cornerRadiusEnd=4).encode(
            x=alt.X("ecl:Q", title="Weighted ECL ($)"), y=alt.Y("stage:N", title=None),
            color=alt.Color("stage:N", scale=alt.Scale(domain=list(COLORS)[:3], range=list(COLORS.values())[:3]), legend=None),
            tooltip=["stage", alt.Tooltip("ecl:Q", format="$,.0f"), alt.Tooltip("coverage:Q", format=".2%"), "loans"],
        ).properties(height=140),
        width="stretch",
    )
with right:
    st.markdown("**ECL by scenario**")
    rows = [{"scenario": s, "ecl": float(res[f"ecl_{s}"].sum())} for s in scenarios.scenario_names(cfg)]
    rows.append({"scenario": "weighted", "ecl": float(tot)})
    sc = pd.DataFrame(rows)
    st.altair_chart(
        alt.Chart(sc).mark_bar(cornerRadiusEnd=4).encode(
            x=alt.X("scenario:N", sort=["upside", "base", "weighted", "downside", "severe"], title=None,
                    axis=alt.Axis(labelAngle=0)),
            y=alt.Y("ecl:Q", title="ECL ($)"),
            color=alt.Color("scenario:N", scale=alt.Scale(domain=list(COLORS)[3:], range=list(COLORS.values())[3:]), legend=None),
            tooltip=["scenario", alt.Tooltip("ecl:Q", format="$,.0f")],
        ).properties(height=260),
        width="stretch",
    )
    st.caption("Severe is a stress test only and is never part of the weighted ECL. Weighted > base because "
               "losses rise faster in the downside than they fall in the upside (convex PD and LGD).")

st.markdown("**Stage 2 triggers**")
trig = res[res["stage"] == 2]["trigger"].value_counts().rename_axis("trigger").reset_index(name="loans")
st.dataframe(trig, width="stretch", hide_index=True)

charts = ROOT / "outputs" / "charts"
with st.expander("Provision movement, PD term structure and backtest (from the last pipeline run)"):
    for f in ("provision_waterfall.png", "pd_term_structure.png", "backtest_by_segment.png"):
        if (charts / f).exists():
            st.image(str(charts / f))
