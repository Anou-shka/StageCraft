"""Parse Freddie Mac Single-Family Loan-Level Dataset sample files into Parquet.

Column names and positions follow Freddie Mac's official `file_layout.xlsx`
and the Single-Family Loan-Level Dataset General User Guide (the files have no
header row; fields are pipe-delimited). Sample files are distributed as
`sample_YYYY.zip` containing `sample_orig_YYYY.txt` (one row per loan) and
`sample_svcg_YYYY.txt` (one row per loan-month).

Outputs (data/processed/):
    orig.parquet          one row per loan, typed
    perf/perf_YYYY.parquet  loan-month records, typed, one file per vintage
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

import polars as pl

from .config import load_config, path

# Origination data file, positions 1-32.
ORIG_COLS = [
    "credit_score", "first_payment_date", "first_time_homebuyer", "maturity_date", "msa", "mi_pct",
    "units", "occupancy", "cltv", "dti", "orig_upb", "ltv", "orig_rate", "channel", "ppm_flag",
    "amortization_type", "property_state", "property_type", "postal_code", "loan_id", "loan_purpose",
    "orig_term", "n_borrowers", "seller_name", "servicer_name", "super_conforming", "pre_harp_loan_id",
    "program_indicator", "harp_indicator", "property_valuation_method", "io_indicator", "mi_cancellation",
]

# Current release (seen in 2026 downloads): the origination file has 31 fields.
# Servicer Name and MI Cancellation Indicator moved to the performance file
# (positions 34 and 33); a trailing field was added. Positions 1-24 are unchanged.
ORIG_COLS_31 = ORIG_COLS[:24] + [
    "super_conforming", "pre_harp_loan_id", "program_indicator", "harp_indicator", "property_valuation_method",
    "io_indicator", "orig_extra_31",
]

# Monthly performance data file, positions 1-32 (the current release appends
# 33 MI cancellation indicator, 34 current servicer name, 35 an extra amount).
PERF_COLS = [
    "loan_id", "period", "current_upb", "dlq_status", "loan_age", "rem_months", "defect_settlement_date",
    "mod_flag", "zb_code", "zb_date", "current_rate", "deferred_upb", "ddlpi", "mi_recoveries",
    "net_sales_proceeds", "non_mi_recoveries", "expenses", "legal_costs", "maint_costs", "taxes_ins",
    "misc_expenses", "actual_loss", "mod_cost", "step_mod", "deferral_flag", "eltv", "zb_removal_upb",
    "dai", "disaster", "assistance", "current_month_mod_cost", "interest_bearing_upb",
]


def _ym_to_mi(col: str) -> pl.Expr:
    v = pl.col(col).str.strip_chars().cast(pl.Int64, strict=False)
    return ((v // 100) * 12 + (v % 100) - 1).cast(pl.Int32)


def _num(col: str, dtype=pl.Float64) -> pl.Expr:
    return pl.col(col).str.strip_chars().cast(dtype, strict=False)


def _str(col: str) -> pl.Expr:
    s = pl.col(col).str.strip_chars()
    return pl.when(s == "").then(None).otherwise(s)


def discover(raw_dir: Path, vintages: tuple[int, int] | None = None) -> dict[int, dict[str, Path]]:
    """Find sample files by vintage. Accepts zips or already-extracted txts."""
    found: dict[int, dict[str, Path]] = {}
    for p in sorted(raw_dir.glob("*")):
        m = re.fullmatch(r"sample_(\d{4})\.zip", p.name)
        if m:
            found.setdefault(int(m.group(1)), {})["zip"] = p
        m = re.fullmatch(r"sample_(orig|svcg|perf)_(\d{4})\.txt", p.name)
        if m:
            kind = "orig" if m.group(1) == "orig" else "svcg"
            found.setdefault(int(m.group(2)), {})[kind] = p
    if vintages:
        found = {v: f for v, f in found.items() if vintages[0] <= v <= vintages[1]}
    return found


def _extract(files: dict[str, Path], vintage: int, interim: Path) -> dict[str, Path]:
    if "orig" in files and "svcg" in files:
        return files
    out = interim / str(vintage)
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(files["zip"]) as z:
        names = z.namelist()
        # Performance file is sample_svcg_YYYY.txt in older releases, sample_perf_YYYY.txt in newer ones.
        for kind, cands in (("orig", ["orig"]), ("svcg", ["svcg", "perf"])):
            name = next(f"sample_{c}_{vintage}.txt" for c in cands if f"sample_{c}_{vintage}.txt" in names)
            target = out / name
            if not target.exists() or target.stat().st_size != z.getinfo(name).file_size:
                z.extract(name, out)
            files[kind] = target
    return files


def _n_fields(p: Path) -> int:
    with open(p) as f:
        return f.readline().rstrip("\n").count("|") + 1


def _scan(p: Path, cols: list[str]) -> pl.LazyFrame:
    n = _n_fields(p)
    names = cols[:n] + [f"extra_{i}" for i in range(n - len(cols))]
    lf = pl.scan_csv(p, separator="|", has_header=False, schema={c: pl.String for c in names},
                     truncate_ragged_lines=True, quote_char=None)
    missing = [c for c in cols if c not in names]
    return lf.with_columns([pl.lit(None, pl.String).alias(c) for c in missing])


def parse_orig(p: Path, vintage: int) -> pl.DataFrame:
    lf = _scan(p, ORIG_COLS_31 if _n_fields(p) == 31 else ORIG_COLS)
    na = lambda c, bad, dt=pl.Int32: pl.when(_num(c, dt) == bad).then(None).otherwise(_num(c, dt)).alias(c)  # noqa: E731
    return lf.select(
        _str("loan_id").alias("loan_id"),
        pl.lit(vintage, pl.Int16).alias("vintage"),
        na("credit_score", 9999),
        _ym_to_mi("first_payment_date").alias("fpd_mi"),
        _ym_to_mi("maturity_date").alias("maturity_mi"),
        _str("first_time_homebuyer").alias("first_time_homebuyer"),
        na("mi_pct", 999),
        na("units", 99, pl.Int16),
        _str("occupancy").alias("occupancy"),
        na("cltv", 999),
        na("dti", 999),
        _num("orig_upb").alias("orig_upb"),
        na("ltv", 999),
        _num("orig_rate").alias("orig_rate"),
        _str("channel").alias("channel"),
        _str("amortization_type").alias("amortization_type"),
        _str("property_state").alias("property_state"),
        _str("property_type").alias("property_type"),
        _str("loan_purpose").alias("loan_purpose"),
        _num("orig_term", pl.Int16).alias("orig_term"),
        na("n_borrowers", 99, pl.Int16),
        _str("io_indicator").alias("io_indicator"),
    ).collect()


def perf_lazy(p: Path) -> pl.LazyFrame:
    lf = _scan(p, PERF_COLS)
    dlq = pl.col("dlq_status").str.strip_chars()
    zb = pl.col("zb_code").str.strip_chars()
    return lf.select(
        _str("loan_id").alias("loan_id"),
        _ym_to_mi("period").alias("mi"),
        _num("current_upb").alias("current_upb"),
        _str("dlq_status").alias("dlq_raw"),
        dlq.cast(pl.Int16, strict=False).alias("status"),
        (dlq == "RA").alias("reo"),
        _num("loan_age", pl.Int16).alias("loan_age"),
        _num("rem_months", pl.Int16).alias("rem_months"),
        _ym_to_mi("defect_settlement_date").alias("defect_mi"),
        _str("mod_flag").alias("mod_flag"),
        pl.when(zb == "").then(None).otherwise(zb.str.zfill(2)).alias("zb_code"),
        _ym_to_mi("zb_date").alias("zb_mi"),
        _num("current_rate").alias("current_rate"),
        _num("deferred_upb").alias("deferred_upb"),
        _num("mi_recoveries").alias("mi_recoveries"),
        _str("net_sales_proceeds").alias("nsp_raw"),
        _num("net_sales_proceeds").alias("net_sales_proceeds"),
        _num("non_mi_recoveries").alias("non_mi_recoveries"),
        _num("expenses").alias("expenses"),
        _num("actual_loss").alias("actual_loss"),
        _num("mod_cost").alias("mod_cost"),
        _str("deferral_flag").alias("deferral_flag"),
        _num("eltv", pl.Int32).alias("eltv"),
        _num("zb_removal_upb").alias("zb_removal_upb"),
        _num("dai").alias("dai"),
        _str("assistance").alias("assistance"),
    )


def build(cfg: dict | None = None, raw_dir: Path | None = None) -> dict:
    """Parse every vintage found into data/processed. Returns a manifest."""
    cfg = cfg or load_config()
    raw_dir = raw_dir or source_dir(cfg)
    out = path(cfg, "processed")
    (out / "perf").mkdir(parents=True, exist_ok=True)
    for old in (out / "perf").glob("*.parquet"):
        old.unlink()
    found = discover(raw_dir, tuple(cfg["vintages"]))
    if not found:
        raise FileNotFoundError(f"no sample_YYYY files in {raw_dir}")
    origs = []
    for v, files in found.items():
        files = _extract(files, v, path(cfg, "interim"))
        origs.append(parse_orig(files["orig"], v))
        perf_lazy(files["svcg"]).sink_parquet(out / "perf" / f"perf_{v}.parquet")
    orig = pl.concat(origs, how="vertical_relaxed")
    orig.write_parquet(out / "orig.parquet")
    synthetic = (raw_dir / "SYNTHETIC.md").exists()
    manifest = {"source_dir": str(raw_dir), "vintages": sorted(found), "synthetic": synthetic}
    (out / "SOURCE.txt").write_text(f"{raw_dir}\nsynthetic={synthetic}\n")
    return manifest


def source_dir(cfg: dict) -> Path:
    """Real data if present in data/raw/freddie, otherwise the bundled sample."""
    raw = path(cfg, "raw_freddie")
    if discover(raw):
        return raw
    return path(cfg, "sample_freddie")


def is_synthetic(cfg: dict) -> bool:
    f = path(cfg, "processed") / "SOURCE.txt"
    return f.exists() and "synthetic=True" in f.read_text()


def scan_perf(cfg: dict) -> pl.LazyFrame:
    return pl.scan_parquet(path(cfg, "processed") / "perf" / "*.parquet")


def read_orig(cfg: dict) -> pl.DataFrame:
    return pl.read_parquet(path(cfg, "processed") / "orig.parquet")
