import numpy as np
import pytest

from stagecraft import dashboard, scenarios


@pytest.mark.skipif(not dashboard.available_dates(), reason="run the pipeline first")
def test_dashboard_reproduces_pipeline(cfg):
    rd = dashboard.available_dates()[-1]
    b = dashboard.bundle(rd)
    res = dashboard.compute(rd, scenarios.weights(cfg), cfg["staging"]["sicr_relative_multiple"], cfg["staging"]["sicr_absolute_bp"])
    assert np.isclose(res["ecl_w"].sum(), b["res"]["ecl_w"].sum())
    # Re-projecting the base scenario with its own path reproduces the saved numbers.
    sc = scenarios.spec(cfg, rd, "base")
    o = dashboard.reproject(rd, "base", tuple(sc["unemployment"]), tuple(sc["hpi_growth"]))
    assert np.allclose(o["ecl_life_base"], b["res"]["ecl_life_base"])
    # A harsher downside raises ECL.
    sd = scenarios.spec(cfg, rd, "downside")
    worse = dashboard.reproject(rd, "downside", tuple(u + 2 for u in sd["unemployment"]), tuple(g - 5 for g in sd["hpi_growth"]))
    r2 = dashboard.compute(rd, scenarios.weights(cfg), 2.0, 50, overrides={"downside": worse})
    assert r2["ecl_w"].sum() > res["ecl_w"].sum()
