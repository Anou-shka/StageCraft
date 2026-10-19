"""Risk segments: credit-score band x current-LTV band."""

from __future__ import annotations

import numpy as np


def fico_band(fico, cfg: dict) -> np.ndarray:
    a, b = cfg["segments"]["fico_cuts"]
    f = np.asarray(fico, dtype=float)
    return np.where(np.isnan(f), "FICO n/a", np.where(f < a, f"FICO <{a}", np.where(f < b, f"FICO {a}-{b - 1}", f"FICO {b}+")))


def ltv_band(cltv, cfg: dict) -> np.ndarray:
    a, b = cfg["segments"]["ltv_cuts"]
    x = np.asarray(cltv, dtype=float)
    return np.where(x <= a, f"LTV <={a}", np.where(x <= b, f"LTV {a}-{b}", f"LTV >{b}"))


def segment(fico, cltv, cfg: dict) -> np.ndarray:
    fb = fico_band(fico, cfg)
    # Missing scores join the lowest band (conservative).
    a = cfg["segments"]["fico_cuts"][0]
    fb = np.where(fb == "FICO n/a", f"FICO <{a}", fb)
    return np.char.add(np.char.add(fb.astype(str), " | "), ltv_band(cltv, cfg).astype(str))


def all_segments(cfg: dict) -> list[str]:
    a, b = cfg["segments"]["fico_cuts"]
    la, lb = cfg["segments"]["ltv_cuts"]
    fbs = [f"FICO <{a}", f"FICO {a}-{b - 1}", f"FICO {b}+"]
    lbs = [f"LTV <={la}", f"LTV {la}-{lb}", f"LTV >{lb}"]
    return [f"{f} | {l}" for f in fbs for l in lbs]
