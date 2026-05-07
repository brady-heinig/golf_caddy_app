from __future__ import annotations

import importlib
import sys
from pathlib import Path


def enable_legacy_caddie_imports() -> None:
    """
    During migration from the earlier Python prototype, reuse logic from the sibling
    `caddie/` directory (course data, weather, benchmarks, etc.).

    In production images, make sure that directory is included in PYTHONPATH or copied
    into the backend container; otherwise imports will fail.
    """
    repo_root = Path(__file__).resolve().parents[2]
    legacy = repo_root / "caddie"
    if legacy.exists() and legacy.is_dir():
        p = str(legacy)
        if p not in sys.path:
            sys.path.insert(0, p)


def legacy_import(name: str):
    enable_legacy_caddie_imports()
    return importlib.import_module(name)

