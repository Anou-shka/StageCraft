import numpy as np

from stagecraft.ead import balance_schedule
from stagecraft.ecl import stage_ecl, survival_components


def _random(n=200, T=360, seed=1):
    rng = np.random.default_rng(seed)
    h = rng.uniform(0, 0.05, (n, T))
    smm = rng.uniform(0, 0.03, n)
    ead = rng.uniform(1e4, 3e5, (n, T))
    lgd = rng.uniform(0.05, 0.6, (n, T))
    rate = rng.uniform(2, 8, n)
    rem = rng.integers(1, T + 1, n)
    return h, smm, ead, lgd, rate, rem


def test_marginal_pd_nonnegative_and_cumulative_le_one():
    h, smm, ead, lgd, rate, rem = _random()
    h[0] = 1.0  # extreme: certain default every month
    c = survival_components(h, smm, ead, lgd, rate, rem)
    assert (c["marg"] >= 0).all()
    assert (c["pd_life"] <= 1 + 1e-12).all()
    assert np.isclose(c["pd_life"][0], 1.0)  # defaults in month 1, nothing left after
    assert (c["pd12"] <= c["pd_life"] + 1e-12).all()


def test_no_pd_after_remaining_term():
    h, smm, ead, lgd, rate, _ = _random(n=5, T=24)
    rem = np.array([1, 5, 12, 20, 24])
    c = survival_components(h, smm, ead, lgd, rate, rem)
    for i, r in enumerate(rem):
        assert np.all(c["marg"][i, r:] == 0)


def test_stage1_is_12_month_and_stage2_lifetime():
    h, smm, ead, lgd, rate, rem = _random()
    c = survival_components(h, smm, ead, lgd, rate, np.full(len(rem), 360))
    t = np.arange(1, 361)
    el = c["marg"] * ead * lgd * (1 + rate[:, None] / 1200) ** (-t)
    assert np.allclose(c["ecl12"], el[:, :12].sum(1))
    assert np.allclose(c["ecl_life"], el.sum(1))
    ecl3 = np.full(len(rem), 123.0)
    stage = np.array([1, 2, 3] * (len(rem) // 3) + [1] * (len(rem) % 3))
    e = stage_ecl(stage, c["ecl12"], c["ecl_life"], ecl3)
    assert np.allclose(e[stage == 1], c["ecl12"][stage == 1])
    assert np.allclose(e[stage == 2], c["ecl_life"][stage == 2])
    assert np.allclose(e[stage == 3], 123.0)
    assert (c["ecl_life"] >= c["ecl12"] - 1e-9).all()


def test_discounting():
    # Certain default in month 1: ECL = LGD x EAD / (1 + r/12).
    h = np.zeros((1, 24)); h[0, 0] = 1.0
    c = survival_components(h, np.zeros(1), np.full((1, 24), 1000.0), np.full((1, 24), 0.5), np.array([6.0]), np.array([24]))
    assert np.isclose(c["ecl12"][0], 500 / 1.005)
    # Certain default in month 12 (no earlier exits): discounted 12 months.
    h = np.zeros((1, 24)); h[0, 11] = 1.0
    c = survival_components(h, np.zeros(1), np.full((1, 24), 1000.0), np.full((1, 24), 0.5), np.array([6.0]), np.array([24]))
    assert np.isclose(c["ecl12"][0], 500 / 1.005 ** 12)


def test_prepayment_reduces_pd():
    h = np.full((1, 120), 0.002)
    a = survival_components(h, np.zeros(1), np.ones((1, 120)), np.ones((1, 120)), np.array([5.0]), np.array([120]))
    b = survival_components(h, np.array([0.01]), np.ones((1, 120)), np.ones((1, 120)), np.array([5.0]), np.array([120]))
    assert b["pd_life"][0] < a["pd_life"][0]


def test_balance_schedule_amortises_to_zero():
    B = balance_schedule(np.array([100_000.0, 50_000.0]), np.array([4.0, 0.0]), np.array([360, 12]), 400)
    assert np.isclose(B[0, 0], 100_000) and np.isclose(B[0, 360], 0, atol=1e-6)
    assert np.allclose(B[1, 12:], 0) and np.isclose(B[1, 6], 25_000)
    assert (np.diff(B, axis=1) <= 1e-9).all()
