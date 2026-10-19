import numpy as np
import polars as pl

from stagecraft import markov


def _transitions(cfg, n=5000, seed=0):
    rng = np.random.default_rng(seed)
    k = cfg["default_definition"]["min_dpd_status"]
    fr = rng.integers(0, k, n)
    to = np.where(rng.random(n) < 0.9, fr, rng.integers(0, k + 2, n))
    seg = rng.choice(["FICO 740+ | LTV <=80", "FICO <680 | LTV >95"], n)
    return pl.DataFrame({"from": fr, "to": to, "segment": seg})


def test_rows_sum_to_one_and_absorbing(cfg):
    m = markov.fit(_transitions(cfg), cfg)
    for P in m.matrices.values():
        assert np.allclose(P.sum(axis=1), 1.0)
        assert (P >= 0).all()
        k = m.k
        assert P[k, k] == 1.0 and P[k + 1, k + 1] == 1.0  # default, prepaid absorbing


def test_cumulative_pd_monotone_and_bounded(cfg):
    m = markov.fit(_transitions(cfg), cfg)
    for s in range(m.k):
        c = m.cum_pd("FICO <680 | LTV >95", s, 360)
        assert (np.diff(c) >= -1e-12).all()
        assert c[-1] <= 1.0 + 1e-12
