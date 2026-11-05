"""Load the symbol tables produced by tools/sync_definitions.py."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"


@lru_cache(maxsize=1)
def lsl_symbols() -> dict:
    return json.loads((DATA / "lsl.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def slua_symbols() -> dict:
    return json.loads((DATA / "slua.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def manifest() -> dict:
    return json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))


def project_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "languages" / "lsl" / "pack.toml").is_file():
            return parent
    return here.parents[1]
