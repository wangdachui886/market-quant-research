"""Workspace-local proxy for root config.

This file exists so chat @-reference can resolve `config.py` inside the
Phase_2_0_universe workspace. Runtime config remains the project-root file.
"""

from pathlib import Path
import runpy

_ROOT_CONFIG = Path(__file__).resolve().parent.parent / "config.py"
_NAMESPACE = runpy.run_path(str(_ROOT_CONFIG))

# Re-export root config symbols for local imports and inspection.
globals().update(
    {
        key: value
        for key, value in _NAMESPACE.items()
        if not key.startswith("__")
    }
)
