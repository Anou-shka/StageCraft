"""Load config/assumptions.yaml and resolve repository paths."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "assumptions.yaml"


@lru_cache(maxsize=4)
def load_config(path: str | None = None) -> dict:
    with open(path or CONFIG_PATH) as f:
        return yaml.safe_load(f)


def path(cfg: dict, key: str) -> Path:
    """Absolute path for a key under `paths:`."""
    p = Path(cfg["paths"][key])
    return p if p.is_absolute() else ROOT / p
