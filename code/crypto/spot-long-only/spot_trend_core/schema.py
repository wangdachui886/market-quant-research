from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class SignalSnapshot:
    symbol: str
    signal_date: str
    close: Optional[float]
    upper: Optional[float]
    ema: Optional[float]
    atr: Optional[float]
    rvol: Optional[float]
    position: int
    previous_position: int
    stop: Optional[float]
    weight: float
    action: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OrderPlan:
    symbol: str
    signal_date: str
    execute_timing: str
    side: str
    target_weight: float
    target_notional: float
    order_notional: float
    estimated_units: Optional[float]
    max_notional_by_adv: Optional[float]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SymbolState:
    symbol: str
    units: float = 0.0
    cash: float = 0.0
    last_signal_date: Optional[str] = None
    last_action: str = "WAIT"
    last_order_id: Optional[str] = None
    highest_close: Optional[float] = None
    stop: Optional[float] = None
    notes: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
