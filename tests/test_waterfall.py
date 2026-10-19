import numpy as np
import pandas as pd

from stagecraft import validation


def _res(ids, stages, rng):
    n = len(ids)
    df = pd.DataFrame({"loan_id": ids, "stage": stages, "upb": rng.uniform(1e4, 1e5, n)})
    for s in ("base", "upside", "downside"):
        df[f"ecl12_{s}"] = rng.uniform(0, 100, n)
        df[f"ecl_life_{s}"] = df[f"ecl12_{s}"] * rng.uniform(1, 10, n)
        df[f"ecl3_{s}"] = rng.uniform(1000, 5000, n)
    from stagecraft.ecl import stage_ecl
    w = {"base": 0.6, "upside": 0.2, "downside": 0.2}
    df["ecl_w"] = sum(wt * stage_ecl(df["stage"].to_numpy(), df[f"ecl12_{s}"], df[f"ecl_life_{s}"], df[f"ecl3_{s}"])
                      for s, wt in w.items())
    return df


def test_closing_equals_opening_plus_movements(cfg, monkeypatch):
    rng = np.random.default_rng(3)
    r0 = _res([f"L{i}" for i in range(0, 60)], rng.integers(1, 4, 60), rng)
    r1 = _res([f"L{i}" for i in range(20, 90)], rng.integers(1, 4, 70), rng)
    cats = ["Repaid / prepaid", "Written off", "Sold / other exit"]
    monkeypatch.setattr(validation, "exit_category",
                        lambda ids, *a: pd.Series([cats[i % 3] for i in range(len(ids))], index=ids.index))
    wf, by_stage = validation.waterfall({"rd": "2018-12-31", "res": r0}, {"rd": "2019-12-31", "res": r1}, cfg)
    amounts = wf["amount"].to_numpy()
    assert np.isclose(amounts[0] + amounts[1:-1].sum(), amounts[-1])
    assert np.isclose(amounts[0], r0["ecl_w"].sum()) and np.isclose(amounts[-1], r1["ecl_w"].sum())
    cols = ["Stage 1", "Stage 2", "Stage 3"]
    body = by_stage[cols].iloc[:-1].sum()
    assert np.allclose(body.to_numpy(), by_stage[cols].iloc[-1].to_numpy())
