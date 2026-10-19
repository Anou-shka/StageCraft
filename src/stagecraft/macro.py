"""Macro history from FRED: unemployment (UNRATE), house prices (USSTHPI),
30-year mortgage rate (MORTGAGE30US, used only for the prepayment incentive).

All series are put on a monthly grid indexed by month index (see dates.py).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .config import load_config, path
from .dates import date_to_mi

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
SERIES = ("UNRATE", "USSTHPI", "MORTGAGE30US")


def download_fred(out_dir: Path, series=SERIES) -> None:
    """Fetch FRED CSVs (used once; the files are committed to data/raw/macro)."""
    import urllib.request

    out_dir.mkdir(parents=True, exist_ok=True)
    for s in series:
        urllib.request.urlretrieve(FRED_URL.format(series=s), out_dir / f"{s}.csv")


def _read(macro_dir: Path, series: str) -> pd.Series:
    df = pd.read_csv(macro_dir / f"{series}.csv")
    df.columns = ["date", "value"]
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.dropna().set_index("date")["value"]


def _mi(idx: pd.DatetimeIndex) -> np.ndarray:
    return (idx.year * 12 + idx.month - 1).to_numpy()


def hpi_monthly(q: pd.Series) -> pd.Series:
    """Quarterly HPI -> monthly. Each quarterly value (dated at quarter start)
    is placed at the quarter's middle month; months in between are
    log-linearly interpolated; the edges extend the nearest quarterly growth."""
    mid = _mi(q.index) + 1
    logv = np.log(q.to_numpy())
    grid = np.arange(mid.min() - 1, mid.max() + 2)
    out = np.interp(grid, mid, logv)
    out[0] = logv[0] - (logv[1] - logv[0]) / 3
    out[-1] = logv[-1] + (logv[-1] - logv[-2]) / 3
    return pd.Series(np.exp(out), index=grid)


def load_macro(cfg: dict | None = None) -> pd.DataFrame:
    """Monthly macro table indexed by month index with columns
    ur, hpi, mtg_rate, dur12 (pp change in unemployment over 12 months) and
    hpa12 (% log change in HPI over 12 months)."""
    cfg = cfg or load_config()
    d = path(cfg, "raw_macro")
    ur = _read(d, "UNRATE")
    ur = pd.Series(ur.to_numpy(), index=_mi(ur.index))
    hpi = hpi_monthly(_read(d, "USSTHPI"))
    mr = _read(d, "MORTGAGE30US")
    mr = mr.groupby(mr.index.to_period("M")).mean()
    mr = pd.Series(mr.to_numpy(), index=mr.index.year * 12 + mr.index.month - 1)
    lo, hi = max(ur.index.min(), hpi.index.min(), mr.index.min()), min(ur.index.max(), hpi.index.max())
    m = pd.DataFrame(index=pd.RangeIndex(lo, hi + 1, name="mi"))
    m["ur"] = ur.reindex(m.index)
    m["hpi"] = hpi.reindex(m.index)
    m["mtg_rate"] = mr.reindex(m.index).ffill()
    return add_features(m)


def add_features(m: pd.DataFrame) -> pd.DataFrame:
    m = m.copy()
    m["dur12"] = m["ur"] - m["ur"].shift(12)
    m["hpa12"] = 100 * np.log(m["hpi"] / m["hpi"].shift(12))
    return m


def asat_cutoffs(reporting_date: str, cfg: dict) -> dict:
    """Last month of each series that was published by the reporting date."""
    rd = date_to_mi(reporting_date)
    return {
        "ur": rd - cfg["macro"]["ur_publication_lag_months"],
        "hpi": rd - cfg["macro"]["hpi_publication_lag_months"],
        "mtg_rate": rd,  # weekly survey, available in real time
    }
