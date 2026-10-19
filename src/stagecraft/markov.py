"""Roll-rate (Markov chain) PD model: the challenger.

Monthly transition matrices between Current, 30 DPD, 60 DPD, Default
(entry into default) and Prepaid/closed are counted from loan-months in a look-back window ending at
the reporting date, separately for each credit-score x current-LTV segment.
Default and Prepaid are absorbing. Cumulative PD over t months from state s
is (P^t)[s, Default]; it already nets off prepayment, because a loan that
prepays can no longer reach Default.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import polars as pl

from .buckets import DEFAULT, PREPAID, n_transient
from .dates import date_to_mi
from .segments import all_segments, segment


def state_names(cfg: dict) -> list[str]:
    k = n_transient(cfg)
    return ["Current"] + [f"{30 * i} DPD" for i in range(1, k)] + ["Default", "Prepaid"]


def transitions(panel: pl.LazyFrame, orig: pl.DataFrame, reporting_date: str, cfg: dict) -> pl.DataFrame:
    """Transition pairs (from_state, to_state, segment) in the window."""
    k = n_transient(cfg)
    rd = date_to_mi(reporting_date)
    w = cfg["markov"]["window_months"]
    p = (
        panel.select("loan_id", "mi", "state", "cltv")
        .filter(pl.col("mi").is_between(rd - w - 1, rd))
        .sort("loan_id", "mi")
        .with_columns(
            pl.col("state").shift(1).over("loan_id").alias("from"),
            pl.col("mi").shift(1).over("loan_id").alias("from_mi"),
            pl.col("cltv").shift(1).over("loan_id").alias("from_cltv"),
        )
        .filter((pl.col("mi") > rd - w) & (pl.col("from_mi") == pl.col("mi") - 1) & (pl.col("from") < k)
                & ((pl.col("state") < k) | pl.col("state").is_in([DEFAULT, PREPAID])))
        .join(orig.lazy().select("loan_id", "credit_score"), on="loan_id", how="left")
        .collect()
    )
    seg = segment(p["credit_score"].to_numpy(), p["from_cltv"].to_numpy(), cfg)
    to = p["state"].to_numpy().astype(int)
    to = np.where(to == DEFAULT, k, np.where(to == PREPAID, k + 1, to))
    return pl.DataFrame({"from": p["from"].to_numpy().astype(int), "to": to, "segment": seg})


@dataclass
class MarkovModel:
    k: int
    matrices: dict[str, np.ndarray]
    counts: dict[str, np.ndarray]
    names: list[str]
    _cum: dict = field(default_factory=dict, repr=False)

    def cum_pd(self, seg: str, start: int, T: int) -> np.ndarray:
        """Cumulative default probability at t = 1..T starting from `start`."""
        key = (seg, T)
        if key not in self._cum:
            P = self.matrices.get(seg, self.matrices["ALL"])
            out = np.zeros((self.k, T))
            v = np.eye(P.shape[0])[: self.k]
            for t in range(T):
                v = v @ P
                out[:, t] = v[:, self.k]
            self._cum[key] = out
        return self._cum[key][start]

    def loan_pds(self, segs: np.ndarray, states: np.ndarray, horizons: np.ndarray, T12: int = 12) -> tuple:
        """12-month and remaining-term cumulative PD for each loan."""
        Tmax = int(max(horizons.max(), T12))
        pd12 = np.zeros(len(segs))
        pdl = np.zeros(len(segs))
        for (s, st), idx in pd.DataFrame({"s": segs, "st": states}).groupby(["s", "st"]).groups.items():
            c = self.cum_pd(s, int(st), Tmax)
            idx = np.asarray(idx)
            pd12[idx] = c[T12 - 1]
            pdl[idx] = c[np.clip(horizons[idx], 1, Tmax) - 1]
        return pd12, pdl

    def matrix_frame(self, seg: str = "ALL") -> pd.DataFrame:
        P = self.matrices[seg]
        return pd.DataFrame(P[: self.k], index=self.names[: self.k], columns=self.names)


def fit(tr: pl.DataFrame, cfg: dict) -> MarkovModel:
    k = n_transient(cfg)
    n = k + 2
    min_obs = cfg["markov"]["min_obs_per_row"]

    def count(df: pl.DataFrame) -> np.ndarray:
        C = np.zeros((n, n))
        np.add.at(C, (df["from"].to_numpy(), df["to"].to_numpy()), 1)
        return C

    def normalise(C: np.ndarray, prior: np.ndarray | None) -> np.ndarray:
        """Row-normalise counts. Segment rows are credibility-weighted towards
        the pooled matrix: (counts + a * pooled) / (n + a), a = min_obs, so a
        sparse row borrows strength instead of showing zero transitions."""
        P = np.zeros_like(C)
        for i in range(k):
            if prior is None:
                P[i] = C[i] / max(C[i].sum(), 1)
            else:
                P[i] = (C[i] + min_obs * prior[i]) / (C[i].sum() + min_obs)
        P[k, k] = 1.0
        P[k + 1, k + 1] = 1.0
        return P

    pooled_C = count(tr)
    pooled = normalise(pooled_C, None)
    mats, counts = {"ALL": pooled}, {"ALL": pooled_C}
    for seg in all_segments(cfg):
        C = count(tr.filter(pl.col("segment") == seg))
        mats[seg] = normalise(C, pooled)
        counts[seg] = C
    return MarkovModel(k, mats, counts, state_names(cfg))
