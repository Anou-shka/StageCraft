"""Matplotlib charts written to outputs/charts. One look for all of them."""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

# Categorical slots in fixed order (validated reference palette).
C = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
STAGE = {1: C[0], 2: C[1], 3: C[2]}
SCEN = {"base": C[0], "upside": C[2], "downside": C[1], "severe": C[6], "weighted": "#0b0b0b"}
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"

plt.rcParams.update({
    "figure.facecolor": SURF, "axes.facecolor": SURF, "savefig.facecolor": SURF,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False,
    "font.size": 9.5, "axes.titlesize": 11, "axes.titleweight": "bold", "axes.titlelocation": "left",
    "legend.frameon": False, "lines.linewidth": 2, "figure.dpi": 150,
})


def _finish(fig, path, note: str | None = None):
    if note:
        fig.text(0.01, 0.005, note, fontsize=7.5, color=INK2, ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.03 if note else 0, 1, 1))
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def money(x, _=None):
    a = abs(x)
    sign = "\u2212" if x < 0 else ""
    if a >= 1e9:
        return f"{sign}${a / 1e9:.1f}bn"
    if a >= 1e6:
        return f"{sign}${a / 1e6:.2f}m"
    if a >= 1e3:
        return f"{sign}${a / 1e3:.0f}k"
    return f"{sign}${a:.0f}"


def ecl_by_stage(tables: dict, path, note=None):
    """Coverage ratio by stage at each date (bars) - one measure, one axis."""
    fig, ax = plt.subplots(figsize=(7, 3.4))
    dates = list(tables)
    x = np.arange(3)
    wdt = 0.8 / len(dates)
    for i, d in enumerate(dates):
        t = tables[d].set_index("stage")
        vals = [t.loc[s, "coverage"] if s in t.index else 0 for s in (1, 2, 3)]
        bars = ax.bar(x + i * wdt - 0.4 + wdt / 2, vals, wdt - 0.03, color=C[i], label=d, zorder=3)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.2%}", ha="center", va="bottom", fontsize=8, color=INK2)
    ax.set_xticks(x, ["Stage 1", "Stage 2", "Stage 3"])
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}" if v >= 0.01 else f"{v:.1%}")
    ax.set_title("ECL coverage ratio by stage (weighted ECL / gross carrying amount)")
    ax.legend(loc="upper left")
    _finish(fig, path, note)


def pd_term_structure(curves: dict, path, note=None):
    fig, ax = plt.subplots(figsize=(7, 3.6))
    for i, (d, c) in enumerate(curves.items()):
        t = np.arange(1, len(c["hazard_base"]) + 1) / 12
        ax.plot(t, c["hazard_base"], color=C[i], label=f"Hazard (base scenario), {d}")
        ax.plot(t, c["markov"], color=C[i], linestyle="--", label=f"Markov roll-rate, {d}")
    ax.set_xlabel("Years after reporting date")
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.set_title("Cumulative PD term structure, performing loans (net of prepayment)")
    ax.legend(fontsize=8)
    _finish(fig, path, note)


def scenario_paths(paths: dict, hist_end: int, rd: int, path, note=None):
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.4))
    lo, hi = rd - 36, rd + 84
    ref = paths["base"]["hpi"].get(rd)
    for name, p in paths.items():
        s = p.loc[lo:hi]
        yrs = s.index / 12
        axes[0].plot(yrs, s["ur"], color=SCEN[name], label=name)
        axes[1].plot(yrs, 100 * s["hpi"] / ref, color=SCEN[name], label=name)
    for ax in axes:
        ax.axvline(rd / 12 + 1 / 12, color=INK2, linewidth=0.8, linestyle=":")
    axes[0].set_title("Unemployment rate (%)")
    axes[1].set_title("House price index (base path at reporting date = 100)")
    axes[0].legend()
    _finish(fig, path, note)


def ecl_by_scenario(df: pd.DataFrame, path, note=None):
    """df: date x scenario ECL (+ weighted)."""
    fig, ax = plt.subplots(figsize=(7, 3.4))
    cols = [c for c in ["upside", "base", "weighted", "downside", "severe"] if c in df.columns]
    x = np.arange(len(df.index))
    wdt = 0.8 / len(cols)
    for i, c in enumerate(cols):
        b = ax.bar(x + i * wdt - 0.4 + wdt / 2, df[c], wdt - 0.03, color=SCEN[c], label=c, zorder=3)
        for r in b:
            ax.text(r.get_x() + r.get_width() / 2, r.get_height(), money(r.get_height()), ha="center",
                    va="bottom", fontsize=7, color=INK2)
    ax.set_xticks(x, df.index)
    ax.yaxis.set_major_formatter(money)
    ax.set_title("Total ECL by scenario (severe = stress only, not weighted)")
    ax.set_ylim(0, ax.get_ylim()[1] * 1.18)
    ax.legend(ncol=5, fontsize=8, loc="upper left")
    _finish(fig, path, note)


def waterfall(wf: pd.DataFrame, path, note=None):
    fig, ax = plt.subplots(figsize=(9, 3.8))
    vals = wf["amount"].to_numpy()
    import textwrap

    labels = [textwrap.fill(s.replace(" (", " ("), 14) for s in wf["line"]]
    run = 0.0
    for i, v in enumerate(vals):
        total = i == 0 or i == len(vals) - 1
        if total:
            ax.bar(i, v, 0.6, color=INK2, zorder=3)
            run = v
            y = v
        else:
            ax.bar(i, v, 0.6, bottom=run, color=C[2] if v < 0 else C[1], zorder=3)
            run += v
            y = run if v > 0 else run - v
        ax.text(i, y, money(v), ha="center", va="bottom", fontsize=7.5, color=INK2)
    ax.set_xticks(range(len(vals)), labels, fontsize=7)
    ax.yaxis.set_major_formatter(money)
    ax.set_ylim(0, ax.get_ylim()[1] * 1.08)
    ax.set_title("Provision movement: opening to closing weighted ECL")
    _finish(fig, path, note)


def backtest_bars(tables: dict, path, note=None, by="segment"):
    fig, axes = plt.subplots(1, len(tables), figsize=(9.5, 4), sharey=True, squeeze=False)
    for ax, (d, t) in zip(axes[0], tables.items()):
        t = t[t["loans"] >= 30]
        y = np.arange(len(t))
        ax.barh(y + 0.2, t["predicted_pd12_weighted"], 0.38, color=C[0], label="Predicted 12m PD", zorder=3)
        ax.barh(y - 0.2, t["observed_rate"], 0.38, color=C[1], label="Observed 12m default rate", zorder=3)
        ax.set_yticks(y, t["group"].astype(str), fontsize=7.5)
        ax.xaxis.set_major_formatter(lambda v, _: f"{v:.1%}")
        ax.set_title(f"From {d}", fontsize=10)
    axes[0][0].legend(fontsize=8, loc="lower right")
    fig.suptitle(f"Out-of-time PD backtest by {by} (groups with 30+ loans)", x=0.01, ha="left", fontweight="bold")
    _finish(fig, path, note)


def calibration_plot(cals: dict, path, note=None):
    fig, ax = plt.subplots(figsize=(5.2, 4))
    mx = 0
    for i, (lab, c) in enumerate(cals.items()):
        ax.plot(c["mean_predicted"], c["observed_rate"], marker="o", markersize=5, color=C[i], label=lab)
        mx = max(mx, c["mean_predicted"].max(), c["observed_rate"].max())
    ax.plot([0, mx], [0, mx], color=INK2, linewidth=1, linestyle=":")
    ax.set_xlabel("Mean predicted PD (decile)")
    ax.set_ylabel("Observed default rate")
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.set_title("Calibration by decile")
    ax.legend(fontsize=7.5)
    _finish(fig, path, note)


def lgd_bands(all_t: pd.DataFrame, down: pd.DataFrame, path, note=None):
    def key(s):
        if s.startswith("<="):
            return -1.0
        if s.startswith(">"):
            return float(s[1:]) + 0.5
        return float(s.split("-")[0])
    order = sorted(set(all_t["ltv_band"]) | set(down["ltv_band"]), key=key)
    a = all_t.set_index("ltv_band").reindex(order)
    d = down.set_index("ltv_band").reindex(order)
    x = np.arange(len(order))
    fig, ax = plt.subplots(figsize=(7, 3.4))
    ax.bar(x - 0.2, a["mean_lgd"], 0.38, color=C[0], label="All resolved defaults", zorder=3)
    ax.bar(x + 0.2, d["mean_lgd"], 0.38, color=C[1], label="Downturn (2008-2011 defaults)", zorder=3)
    for i in range(len(order)):
        for off, t in ((-0.2, a), (0.2, d)):
            n = t["n"].iloc[i]
            if pd.notna(n):
                ax.text(i + off, t["mean_lgd"].iloc[i], f"n={int(n)}", ha="center", va="bottom", fontsize=7, color=INK2)
    ax.set_xticks(x, [f"LTV {o}" for o in order])
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.set_title("Loss severity by current LTV at default (economic, before cure adjustment)")
    ax.set_ylim(0, ax.get_ylim()[1] * 1.25)
    ax.legend(fontsize=8, loc="upper left", ncol=2)
    _finish(fig, path, note)


def sicr_cliff(sens: pd.DataFrame, path, note=None):
    fig, axes = plt.subplots(1, 2, figsize=(8.5, 3.3))
    for i, (test, lab) in enumerate((("SICR relative threshold", "Weighted scenarios (as booked)"),
                                     ("SICR threshold under stress staging", "Severe scenario at 100% (stress staging)"))):
        s = sens[sens["test"] == test]
        if s.empty:
            continue
        axes[0].plot(s["setting"], s["stage2_share_upb"], marker="o", markersize=6, color=C[i], label=lab)
        axes[1].plot(s["setting"], s["ecl"], marker="o", markersize=6, color=C[i], label=lab)
    axes[0].set_title("Stage 2 share of book (UPB)")
    axes[0].yaxis.set_major_formatter(lambda v, _: f"{v:.1%}")
    axes[1].set_title("Total ECL")
    axes[1].yaxis.set_major_formatter(money)
    axes[0].legend(fontsize=7.5)
    for ax in axes:
        ax.set_xlabel("SICR relative PD multiple")
    _finish(fig, path, note)


def migration_heat(mig: pd.DataFrame, path, note=None):
    share = mig["share"]
    cnt = mig["loans"]
    fig, ax = plt.subplots(figsize=(7.5, 2.6))
    ax.imshow(share.to_numpy(), cmap="Blues", vmin=0, vmax=1, aspect="auto")
    ax.grid(False)
    for i in range(share.shape[0]):
        for j in range(share.shape[1]):
            v = share.iat[i, j]
            ax.text(j, i, f"{v:.1%}\n({cnt.iat[i, j]:,})", ha="center", va="center", fontsize=7.5,
                    color="white" if v > 0.6 else INK)
    ax.set_xticks(range(share.shape[1]), share.columns, fontsize=8)
    ax.set_yticks(range(share.shape[0]), share.index, fontsize=8)
    ax.set_title("Stage migration between reporting dates (row = opening stage)")
    _finish(fig, path, note)


def ecl_by_vintage(t: pd.DataFrame, path, note=None):
    fig, ax = plt.subplots(figsize=(8, 3.4))
    dates = t["date"].unique()
    vint = sorted(t["vintage"].unique())
    x = np.arange(len(vint))
    wdt = 0.8 / len(dates)
    for i, d in enumerate(dates):
        s = t[t["date"] == d].set_index("vintage").reindex(vint)
        ax.bar(x + i * wdt - 0.4 + wdt / 2, s["coverage"], wdt - 0.03, color=C[i], label=d, zorder=3)
    ax.set_xticks(x, vint, rotation=0, fontsize=8)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.1%}")
    ax.set_title("ECL coverage by origination vintage")
    ax.legend()
    _finish(fig, path, note)


def roc_curves(curves: dict, path, note=None):
    from sklearn.metrics import roc_curve

    fig, ax = plt.subplots(figsize=(4.8, 4))
    for i, (lab, (y, p)) in enumerate(curves.items()):
        fpr, tpr, _ = roc_curve(y, p)
        ax.plot(fpr, tpr, color=C[i], label=lab)
    ax.plot([0, 1], [0, 1], color=INK2, linestyle=":", linewidth=1)
    ax.set_xlabel("False positive rate")
    ax.set_ylabel("True positive rate")
    ax.set_title("ROC curves (out-of-time)")
    ax.legend(fontsize=7, loc="lower right")
    _finish(fig, path, note)
