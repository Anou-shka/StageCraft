"""Month arithmetic.

Months are carried as integers (`year * 12 + month - 1`) so that loan-month
panels can be joined and shifted with integer arithmetic instead of dates.
"""

from __future__ import annotations

import datetime as dt

import numpy as np


def ym_to_mi(ym):
    """YYYYMM (int, str or array) -> month index."""
    ym = np.asarray(ym, dtype=np.int64)
    return (ym // 100) * 12 + (ym % 100) - 1


def mi_to_ym(mi):
    mi = np.asarray(mi, dtype=np.int64)
    return (mi // 12) * 100 + (mi % 12) + 1


def date_to_mi(d) -> int:
    """'2018-12-31' or a date -> month index of that calendar month."""
    if isinstance(d, str):
        d = dt.date.fromisoformat(d[:10])
    return d.year * 12 + d.month - 1


def mi_to_date(mi: int) -> dt.date:
    return dt.date(int(mi) // 12, int(mi) % 12 + 1, 1)


def mi_label(mi: int) -> str:
    return f"{int(mi) // 12}-{int(mi) % 12 + 1:02d}"
