import numpy as np
import pandas as pd

from stagecraft import staging


def test_stage_assignment(cfg):
    snap = pd.DataFrame({
        "status": [0, 1, 0, 0, 0, 0],
        "modified": [False, False, False, False, True, False],
        "assisted": [False] * 6, "deferred": [False] * 6,
    })
    s3 = np.array([False, False, False, False, False, True])
    pd_orig = np.array([0.02, 0.02, 0.0010, 0.02, 0.02, 0.02])
    pd_life = np.array([0.03, 0.03, 0.0030, 0.05, 0.02, 0.02])
    out = staging.assign(snap, s3, pd_life, pd_orig, cfg)
    # 1.5x -> stage 1; 30 DPD -> 2; 3x but only +20bp -> 1; 2.5x and +300bp -> 2; modified -> 2; default -> 3
    assert out["stage"].tolist() == [1, 2, 1, 2, 2, 3]
    assert out["trigger"].tolist()[1] == "30+ DPD" and out["trigger"].tolist()[3] == "relative PD"
    # Lower multiple moves the first loan to stage 2 (cliff effect).
    assert staging.assign(snap, s3, pd_life, pd_orig, cfg, multiple=1.5)["stage"].iloc[0] == 2
