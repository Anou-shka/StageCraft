import numpy as np

from stagecraft import macro, scenarios
from stagecraft.dates import date_to_mi


def test_weights_sum_to_one(cfg):
    assert np.isclose(sum(scenarios.weights(cfg).values()), 1.0)


def test_path_uses_only_published_history(cfg):
    hist = macro.load_macro(cfg)
    rd = "2018-12-31"
    sc = scenarios.spec(cfg, rd, "severe")
    p = scenarios.macro_path(hist, rd, sc, cfg)
    cut = macro.asat_cutoffs(rd, cfg)
    # history identical up to the cutoff, scenario afterwards (not the realised 2019 data)
    assert np.isclose(p["ur"].loc[cut["ur"]], hist["ur"].loc[cut["ur"]])
    m = date_to_mi(rd)
    assert np.isclose(p["ur"].loc[m + 12], sc["unemployment"][0])
    assert np.isclose(p["ur"].loc[m + 24], sc["unemployment"][1])
    g1 = p["hpi"].loc[m + 12] / p["hpi"].loc[m]
    assert np.isclose(g1, 1 + sc["hpi_growth"][0] / 100, atol=1e-6)
