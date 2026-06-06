from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from .schema import SymbolState


def load_states(path: str | Path) -> dict[str, SymbolState]:
    state_path = Path(path)
    if not state_path.exists():
        return {}

    raw = json.loads(state_path.read_text(encoding="utf-8"))
    return {symbol: SymbolState(**payload) for symbol, payload in raw.items()}


def save_states(path: str | Path, states: Mapping[str, SymbolState]) -> None:
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {symbol: state.to_dict() for symbol, state in states.items()}
    state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
