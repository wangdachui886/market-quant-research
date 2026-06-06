from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Optional

from .config import DEFAULT_CONFIG, StrategyConfig
from .schema import OrderPlan, SignalSnapshot


def sleeve_equity(total_equity: float, config: StrategyConfig = DEFAULT_CONFIG) -> float:
    if total_equity < 0:
        raise ValueError("total_equity must be non-negative.")
    if not config.symbols:
        raise ValueError("config.symbols cannot be empty.")
    return float(total_equity) / len(config.symbols)


def _adv_cap(quote_volume: Optional[float], config: StrategyConfig) -> Optional[float]:
    if quote_volume is None:
        return None
    if quote_volume <= 0:
        return 0.0
    return float(quote_volume) * config.adv_participation


def build_order_plan(
    snapshot: SignalSnapshot,
    total_equity: float,
    current_units: float = 0.0,
    execution_price: Optional[float] = None,
    quote_volume: Optional[float] = None,
    config: StrategyConfig = DEFAULT_CONFIG,
) -> OrderPlan:
    sleeve = sleeve_equity(total_equity, config=config)
    max_by_adv = _adv_cap(quote_volume, config=config)

    side = "HOLD"
    target_weight = 0.0
    target_notional = 0.0
    order_notional = 0.0
    estimated_units: Optional[float] = None
    reason = snapshot.reason

    if snapshot.action == "ENTER":
        side = "BUY"
        target_weight = float(snapshot.weight)
        target_notional = sleeve * target_weight
        order_notional = target_notional
        if max_by_adv is not None and order_notional > max_by_adv:
            order_notional = max_by_adv
            reason = f"{reason}; capped_by_adv"
        if execution_price and execution_price > 0:
            estimated_units = order_notional / execution_price
    elif snapshot.action == "EXIT":
        side = "SELL"
        target_weight = 0.0
        target_notional = 0.0
        estimated_units = max(float(current_units), 0.0)
        if execution_price and execution_price > 0:
            order_notional = estimated_units * execution_price
    elif snapshot.action == "HOLD":
        side = "HOLD"
        target_weight = float(snapshot.weight)
        target_notional = sleeve * target_weight

    return OrderPlan(
        symbol=snapshot.symbol,
        signal_date=snapshot.signal_date,
        execute_timing=config.execution_timing,
        side=side,
        target_weight=target_weight,
        target_notional=target_notional,
        order_notional=order_notional,
        estimated_units=estimated_units,
        max_notional_by_adv=max_by_adv,
        reason=reason,
    )


def build_portfolio_order_plan(
    snapshots: Iterable[SignalSnapshot],
    total_equity: float,
    current_units_by_symbol: Optional[Mapping[str, float]] = None,
    execution_price_by_symbol: Optional[Mapping[str, float]] = None,
    quote_volume_by_symbol: Optional[Mapping[str, float]] = None,
    config: StrategyConfig = DEFAULT_CONFIG,
) -> list[OrderPlan]:
    units = current_units_by_symbol or {}
    prices = execution_price_by_symbol or {}
    volumes = quote_volume_by_symbol or {}

    return [
        build_order_plan(
            snapshot=snapshot,
            total_equity=total_equity,
            current_units=float(units.get(snapshot.symbol, 0.0)),
            execution_price=prices.get(snapshot.symbol),
            quote_volume=volumes.get(snapshot.symbol),
            config=config,
        )
        for snapshot in snapshots
    ]
