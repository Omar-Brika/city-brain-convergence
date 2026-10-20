"""Load the YAML files of brain/config/. Paths in them are relative to brain/."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

BRAIN_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = Path(os.environ.get("BRAIN_CONFIG_DIR", BRAIN_ROOT / "config"))


@lru_cache(maxsize=None)
def load(name: str) -> dict[str, Any]:
    """Return the content of config/<name>.yaml as a dict."""
    with open(CONFIG_DIR / f"{name}.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def resolve(path: str | os.PathLike[str]) -> Path:
    """Make a config path absolute (relative paths start at brain/)."""
    p = Path(path)
    return p if p.is_absolute() else BRAIN_ROOT / p


def read_secret(path: str | None) -> str | None:
    """Read a secret file as stripped text; None if the path is empty or missing."""
    if not path:
        return None
    p = resolve(path)
    if not p.is_file():
        return None
    return p.read_text(encoding="utf-8").strip()
