"""Delinquency buckets, the default flag and the enriched loan-month panel.

Freddie Mac's `Current Loan Delinquency Status` counts missed monthly
payments under the MBA method (0 = current, 1 = 30-59 days, 2 = 60-89,
3 = 90-119, ...; "RA" = REO acquired). Monthly model states:

    0 .. k-1      performing buckets: Current, 30 DPD, 60 DPD (k = min_dpd_status)
    DEFAULT       status >= k, RA, or a credit-event zero-balance code
    PREPAID       voluntary payoff / maturity (zero-balance code 01)
    CENSORED      other exits (16 RPL securitisation, 96 defect)

The PD event is ENTRY into default: a month in DEFAULT whose previous month
was performing (or the loan's first record). A loan that cures returns to a
performing bucket and is at risk of re-default, which is what a PD for a
cured or modified loan has to measure. `default_mi` in loans.parquet is the
first default ever (used by the origination scorecard and LGD).
"""

from __future__ import annotations

import polars as pl

from .config import load_config, path
from .load import read_orig
from .macro import load_macro

DEFAULT = 7
PREPAID = 8
CENSORED = 9

STATE_LABELS = {0: "Current", 1: "30 DPD", 2: "60 DPD", 3: "90 DPD", DEFAULT: "Default", PREPAID: "Prepaid/closed",
                CENSORED: "Censored"}

# Freddie status -> bucket labels used in reports and the SMA/NPA mapping.
BUCKETS = [
    # (status, MBA label, days past due at a month-end snapshot, RBI class)
    ("0", "Current", "0 (all instalments due have been paid)", "Standard"),
    ("1", "30-59 days", "~30 (one instalment missed)", "SMA-0 (1-30 days)"),
    ("2", "60-89 days", "~60 (two instalments missed)", "SMA-1 (31-60 days)"),
    ("3", "90-119 days", "~90 (three instalments missed)", "SMA-2 (61-90 days), NPA from day 91"),
    ("4+ / RA", "120+ days / REO", "120+", "NPA (sub-standard, then doubtful / loss)"),
]


def n_transient(cfg: dict) -> int:
    return int(cfg["default_definition"]["min_dpd_status"])


def is_dpd_default(status: pl.Expr, reo: pl.Expr, cfg: dict) -> pl.Expr:
    d = cfg["default_definition"]
    flag = status.fill_null(-1) >= d["min_dpd_status"]
    if d["reo_status_is_default"]:
        flag = flag | reo.fill_null(False)
    return flag


def bucket_of_status(status: pl.Expr, cfg: dict) -> pl.Expr:
    """0..min_dpd_status-1 for performing loans, DEFAULT otherwise."""
    k = n_transient(cfg)
    return pl.when(status >= k).then(pl.lit(DEFAULT)).otherwise(status).cast(pl.Int8)


def loan_events(perf: pl.LazyFrame, cfg: dict) -> pl.LazyFrame:
    """One row per loan: first default month, exit month/type, loss data."""
    d = cfg["default_definition"]
    perf = perf.with_columns(
        is_dpd_default(pl.col("status"), pl.col("reo"), cfg).alias("_dpd_def"),
        pl.col("zb_code").is_in(d["credit_event_zb_codes"]).fill_null(False).alias("_credit"),
    )
    zb = pl.col("zb_code").is_not_null()
    agg = perf.sort(["loan_id", "mi"]).group_by("loan_id").agg(
        pl.col("mi").min().alias("first_mi"),
        pl.col("mi").max().alias("last_mi"),
        pl.col("mi").filter(pl.col("_dpd_def")).min().alias("dpd_default_mi"),
        pl.col("current_upb").filter(pl.col("_dpd_def")).first().alias("upb_at_dpd_default"),
        pl.col("mi").filter(pl.col("_credit")).min().alias("credit_event_mi"),
        pl.col("mi").filter(zb).min().alias("exit_mi"),
        pl.col("zb_code").filter(zb).first().alias("exit_code"),
        pl.col("actual_loss").filter(zb).first().alias("actual_loss"),
        pl.col("net_sales_proceeds").filter(zb).first().alias("net_sales_proceeds"),
        pl.col("nsp_raw").filter(zb).first().alias("nsp_raw"),
        pl.col("mi_recoveries").filter(zb).first().alias("mi_recoveries"),
        pl.col("non_mi_recoveries").filter(zb).first().alias("non_mi_recoveries"),
        pl.col("expenses").filter(zb).first().alias("expenses"),
        pl.col("dai").filter(zb).first().alias("dai"),
        pl.col("zb_removal_upb").filter(zb).first().alias("zb_removal_upb"),
        pl.col("current_rate").last().alias("last_rate"),
        pl.col("mod_flag").is_in(["Y", "P"]).any().alias("ever_modified"),
    )
    return agg.with_columns(
        pl.min_horizontal("dpd_default_mi", "credit_event_mi").alias("default_mi"),
    ).with_columns(
        pl.when(pl.col("dpd_default_mi").is_not_null() & (pl.col("dpd_default_mi") <= pl.col("default_mi")))
        .then(pl.col("upb_at_dpd_default")).otherwise(pl.col("zb_removal_upb")).alias("upb_at_default"),
        pl.when(pl.col("exit_code").is_in(d["credit_event_zb_codes"])).then(pl.lit("credit_event"))
        .when(pl.col("exit_code").is_in(d["prepay_zb_codes"])).then(pl.lit("prepaid"))
        .when(pl.col("exit_code").is_in(d["censor_zb_codes"])).then(pl.lit("censored"))
        .when(pl.col("exit_code").is_not_null()).then(pl.lit("other"))
        .otherwise(None).alias("exit_type"),
    )


def build_panel(cfg: dict | None = None) -> None:
    """Write data/processed/loans.parquet and panel/panel_YYYY.parquet.

    Loans never cross vintage files, so the panel is built one vintage at a
    time: memory stays bounded by the largest vintage, not the whole dataset."""
    cfg = cfg or load_config()
    out = path(cfg, "processed")
    (out / "panel").mkdir(parents=True, exist_ok=True)
    for old in (out / "panel").glob("*.parquet"):
        old.unlink()
    d = cfg["default_definition"]
    perf_files = sorted((out / "perf").glob("perf_*.parquet"))
    loans = pl.concat([loan_events(pl.scan_parquet(f), cfg).collect() for f in perf_files])
    orig = read_orig(cfg)
    macro = load_macro(cfg)
    hpi = pl.DataFrame({"mi": macro.index.to_numpy().astype("int32"), "hpi": macro["hpi"].to_numpy()})
    # Note date is not in the data; Freddie loans typically make the first
    # payment about two months after the note date.
    orig = orig.drop("orig_mi", "hpi_orig", strict=False).with_columns((pl.col("fpd_mi") - 2).alias("orig_mi")).join(
        hpi.rename({"mi": "orig_mi", "hpi": "hpi_orig"}), on="orig_mi", how="left")
    orig.write_parquet(out / "orig.parquet")  # now carries orig_mi and hpi_orig
    loans = loans.join(orig.select("loan_id", "vintage"), on="loan_id", how="left")
    loans.write_parquet(out / "loans.parquet")

    for f in perf_files:
        _panel_one(pl.scan_parquet(f), loans, orig, hpi, cfg).sink_parquet(out / "panel" / f.name.replace("perf_", "panel_"))


def _panel_one(perf: pl.LazyFrame, loans: pl.DataFrame, orig: pl.DataFrame, hpi: pl.DataFrame, cfg: dict) -> pl.LazyFrame:
    d = cfg["default_definition"]
    k = n_transient(cfg)
    ev = loans.lazy().select("loan_id", "default_mi", "exit_mi", "exit_code")
    return (
        perf.join(ev, on="loan_id", how="left")
        .join(orig.lazy().select("loan_id", "fpd_mi", "orig_mi", "ltv", "orig_upb", "credit_score", "hpi_orig",
                                 "orig_rate", "orig_term"), on="loan_id", how="left")
        .join(hpi.lazy(), on="mi", how="left")
        .with_columns(
            pl.when(pl.col("current_upb") > 0).then(pl.col("current_upb"))
            .otherwise(pl.col("zb_removal_upb")).alias("upb"),
        )
        .with_columns(
            (pl.col("ltv") * pl.col("upb") / pl.col("orig_upb") * pl.col("hpi_orig") / pl.col("hpi"))
            .clip(0, 250).alias("cltv"),
            (pl.col("mi") - pl.col("fpd_mi") + 1).alias("age_fpd"),
            pl.col("mod_flag").is_in(["Y", "P"]).fill_null(False).alias("modified"),
            pl.col("assistance").is_in(["F", "R", "T"]).fill_null(False).alias("assisted"),
            pl.col("deferral_flag").is_in(["Y", "P"]).fill_null(False).alias("deferred"),
            is_dpd_default(pl.col("status"), pl.col("reo"), cfg).alias("dpd_default_now"),
        )
        .with_columns(
            pl.when(pl.col("zb_code").is_in(d["credit_event_zb_codes"]) | pl.col("dpd_default_now")).then(pl.lit(DEFAULT))
            .when(pl.col("zb_code").is_in(d["prepay_zb_codes"])).then(pl.lit(PREPAID))
            .when(pl.col("zb_code").is_not_null()).then(pl.lit(CENSORED))
            .otherwise(pl.col("status").fill_null(0)).cast(pl.Int8).alias("state")
        )
        .sort(["loan_id", "mi"])
        .with_columns(
            ((pl.col("state") == DEFAULT)
             & (pl.col("state").shift(1).over("loan_id").fill_null(0) != DEFAULT)).alias("default_entry"),
            pl.when(pl.col("state") == DEFAULT).then(pl.col("mi")).otherwise(None)
            .forward_fill().over("loan_id").alias("last_default_mi"),
        )
        .with_columns(
            (pl.col("last_default_mi").shift(1).over("loan_id").is_not_null()).alias("prior_default"),
        )
        .select(
            "loan_id", "mi", "state", "default_entry", "last_default_mi", "prior_default", "status", "reo", "upb", "current_rate", "rem_months",
            "loan_age", "age_fpd", "cltv", "eltv", "modified", "assisted", "deferred", "deferred_upb", "zb_code",
            "default_mi", "exit_mi",
        )
        .sort(["loan_id", "mi"])
    )


def scan_panel(cfg: dict) -> pl.LazyFrame:
    return pl.scan_parquet(path(cfg, "processed") / "panel" / "*.parquet")


def read_loans(cfg: dict) -> pl.DataFrame:
    return pl.read_parquet(path(cfg, "processed") / "loans.parquet")
