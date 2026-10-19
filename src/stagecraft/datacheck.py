"""Data checks written to docs/data_report.md before any modelling."""

from __future__ import annotations

import polars as pl

from .buckets import read_loans
from .config import ROOT, load_config, path
from .dates import mi_label
from .load import is_synthetic, read_orig, scan_perf
from .macro import load_macro

ZB_MEANING = {
    "01": "Prepaid or matured (voluntary payoff)",
    "02": "Third-party sale",
    "03": "Short sale or charge-off",
    "09": "REO disposition",
    "15": "Whole-loan sale",
    "16": "Reperforming-loan securitisation",
    "96": "Defect prior to other termination event",
}


PLAIN_INT = {"vintage", "default year", "dlq_raw"}


def _md(df: pl.DataFrame, floatfmt: str = "{:,.4g}") -> str:
    cols = df.columns
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for row in df.iter_rows():
        cells = []
        for c, v in zip(cols, row):
            if isinstance(v, float):
                cells.append(floatfmt.format(v))
            elif isinstance(v, int) and c not in PLAIN_INT:
                cells.append(f"{v:,}")
            else:
                cells.append("" if v is None else str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _missing(df: pl.DataFrame) -> pl.DataFrame:
    n = df.height
    return pl.DataFrame({
        "column": df.columns,
        "missing": [int(df[c].null_count()) for c in df.columns],
        "missing %": [100 * df[c].null_count() / n for c in df.columns],
    })


def sign_convention(loans: pl.DataFrame, cfg: dict) -> dict:
    """Which sign does Actual Loss use for a loss? Compare with the loss
    rebuilt from its components per the User Guide."""
    ce = loans.filter(pl.col("exit_code").is_in(cfg["default_definition"]["credit_event_zb_codes"])
                      & pl.col("actual_loss").is_not_null() & pl.col("net_sales_proceeds").is_not_null())
    if ce.height == 0:
        return {"sign": -1, "n": 0, "match_share": float("nan")}
    rebuilt = (ce["zb_removal_upb"] + ce["dai"].fill_null(0) - ce["net_sales_proceeds"]
               - ce["mi_recoveries"].fill_null(0) - ce["non_mi_recoveries"].fill_null(0)
               + ce["expenses"].fill_null(0).abs())
    pos = ((ce["actual_loss"] - rebuilt).abs() < 0.01 * ce["zb_removal_upb"]).mean()
    neg = ((ce["actual_loss"] + rebuilt).abs() < 0.01 * ce["zb_removal_upb"]).mean()
    return {"sign": 1 if pos >= neg else -1, "n": ce.height, "match_share": float(max(pos, neg))}


def write_report(cfg: dict | None = None) -> str:
    cfg = cfg or load_config()
    orig = read_orig(cfg)
    perf = scan_perf(cfg)
    loans = read_loans(cfg)
    synthetic = is_synthetic(cfg)
    out: list[str] = ["# Data report", ""]
    if synthetic:
        out += [
            "> **SYNTHETIC DATA.** This report was generated from the bundled synthetic sample",
            "> (`data/sample/freddie`, written by `stagecraft.synth` in the Freddie Mac file format).",
            "> Every number below describes simulated loans, not Freddie Mac loans. Drop the real",
            "> `sample_YYYY.zip` files into `data/raw/freddie/` and rerun `python -m stagecraft.pipeline`",
            "> to regenerate this report on real data.",
            "",
        ]
    src = (path(cfg, "processed") / "SOURCE.txt").read_text().splitlines()[0]
    out += [f"Source folder: `{src}`", ""]

    # Row counts.
    pc = perf.group_by(pl.col("loan_id").str.slice(1, 2).alias("yy")).agg(
        pl.len().alias("loan_months"), pl.col("mi").min().alias("first"), pl.col("mi").max().alias("last")
    ).collect().with_columns(("20" + pl.col("yy")).cast(pl.Int16).alias("vintage")).drop("yy")
    oc = orig.group_by("vintage").agg(pl.len().alias("loans"))
    counts = oc.join(pc, on="vintage", how="left").sort("vintage").with_columns(
        pl.col("first").map_elements(mi_label, return_dtype=pl.String),
        pl.col("last").map_elements(mi_label, return_dtype=pl.String),
    )
    out += ["## 1. Row counts", "", _md(counts), "",
            f"Total: {orig.height:,} loans, {int(counts['loan_months'].sum()):,} loan-months.", ""]
    dups = perf.group_by("loan_id", "mi").len().filter(pl.col("len") > 1).select(pl.len()).collect().item()
    orphans = perf.select("loan_id").unique().join(orig.select("loan_id").lazy(), on="loan_id", how="anti") \
        .select(pl.len()).collect().item()
    gaps = perf.sort("loan_id", "mi").with_columns((pl.col("mi").diff().over("loan_id")).alias("d")) \
        .filter(pl.col("d") > 1).select(pl.col("loan_id").n_unique()).collect().item()
    out += [f"- Duplicate (loan, month) records: {dups:,}",
            f"- Performance records with no origination record: {orphans:,}",
            f"- Loans with a gap in their monthly history: {gaps:,}", ""]

    # Missing values.
    om = _missing(orig).filter(pl.col("missing") > 0)
    out += ["## 2. Missing values", "", "### Origination file (columns with any missing; 9999/999 codes mapped to null)", "",
            _md(om) if om.height else "None.", ""]
    pm = _missing(perf.select("current_upb", "status", "loan_age", "rem_months", "current_rate", "eltv",
                              "mod_flag", "assistance", "deferral_flag").collect())
    out += ["### Performance file (selected fields)", "", _md(pm), "",
            "Modification, assistance and deferral flags are blank unless the event applies, so "
            "high missing shares there are expected. ELTV is only populated from April 2017. "
            "A missing numeric `status` is the `RA` (REO acquired) code.", ""]

    # Delinquency codes.
    dq = perf.group_by("dlq_raw").len().collect().sort("len", descending=True)
    dq = dq.with_columns((100 * pl.col("len") / pl.col("len").sum()).alias("share %"))
    out += ["## 3. Delinquency status codes present", "",
            "Freddie Mac reports missed payments under the MBA method: 0 = current, 1 = 30-59 days, 2 = 60-89, "
            "3 = 90-119, and so on; `RA` = REO acquisition.", "", _md(dq.head(15)), "",
            f"{dq.height} distinct codes in total (status values above 14 are grouped out of this table).", ""]

    # Zero balance codes.
    zb = loans.group_by("exit_code").agg(
        pl.len().alias("loans"),
        pl.col("actual_loss").is_not_null().mean().alias("actual loss populated"),
        (pl.col("nsp_raw") == "U").mean().alias("NSP = 'U'"),
        pl.col("default_mi").is_not_null().mean().alias("share ever 90+ / credit event"),
    ).sort("exit_code", nulls_last=True).with_columns(
        pl.col("exit_code").replace_strict(ZB_MEANING, default="(still active)").alias("meaning"))
    out += ["## 4. Zero-balance codes (loan terminations)", "",
            "A loan's last record carries the zero-balance code; the code is set at most once per loan.", "",
            _md(zb.select("exit_code", "meaning", "loans", "actual loss populated", "NSP = 'U'",
                          "share ever 90+ / credit event")), ""]

    # Loss fields.
    sc = sign_convention(loans, cfg)
    out += ["## 5. Loss fields", "",
            "Loss components (net sale proceeds, MI and non-MI recoveries, expenses, delinquent accrued interest, "
            "zero-balance removal UPB) are disclosed on the final record of credit-event loans (codes 02, 03, 09, 15). "
            "Actual Loss is null for dispositions within three months of the performance cut-off and for defect loans.", "",
            f"- Credit-event loans with Actual Loss and Net Sale Proceeds: {sc['n']:,}",
            f"- Sign convention detected: losses are **{'positive' if sc['sign'] > 0 else 'negative'}** "
            f"(Actual Loss matches the User Guide formula rebuilt from components with that sign for "
            f"{100 * sc['match_share']:.1f}% of loans). The LGD module applies this sign.", ""]
    ce = loans.filter(pl.col("exit_type") == "credit_event")
    if ce.height:
        sev = ce.with_columns((sc["sign"] * pl.col("actual_loss") / pl.col("upb_at_default")).alias("sev")) \
            .group_by((pl.col("default_mi") // 12).alias("default year")).agg(
                pl.len().alias("credit events"), pl.col("sev").mean().alias("mean loss / UPB at default"),
                pl.col("actual_loss").null_count().alias("loss missing")).sort("default year")
        out += ["Loss severity by default year (accounting loss, before discounting and cure adjustment):", "", _md(sev), ""]

    # Macro.
    m = load_macro(cfg)
    out += ["## 6. Macro data (FRED)", "",
            f"- UNRATE monthly, HPI (USSTHPI) quarterly interpolated to monthly, MORTGAGE30US weekly averaged to monthly.",
            f"- Common monthly coverage: {mi_label(m.index.min())} to {mi_label(m.index.max())}.",
            f"- HPI interpolation: each quarterly value is placed at the middle month of its quarter and "
            f"log-linearly interpolated (`macro.hpi_monthly`).",
            f"- Publication lags applied at each reporting date: unemployment {cfg['macro']['ur_publication_lag_months']} month, "
            f"HPI {cfg['macro']['hpi_publication_lag_months']} months.", ""]

    # Default definition summary.
    d = cfg["default_definition"]
    nd = loans.filter(pl.col("default_mi").is_not_null())
    via_dpd = nd.filter(pl.col("dpd_default_mi") <= pl.col("default_mi")).height
    out += ["## 7. Default flag", "",
            f"Default = first month with status >= {d['min_dpd_status']}, REO status, or zero-balance code in "
            f"{', '.join(d['credit_event_zb_codes'])}.", "",
            f"- Loans ever in default: {nd.height:,} ({100 * nd.height / max(loans.height, 1):.1f}%)",
            f"- First flagged by delinquency status: {via_dpd:,}; by a credit-event code with no prior 90+: {nd.height - via_dpd:,}",
            ""]
    text = "\n".join(out)
    (ROOT / "docs" / "data_report.md").write_text(text)
    return text
