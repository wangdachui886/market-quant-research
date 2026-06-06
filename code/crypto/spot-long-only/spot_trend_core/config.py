from __future__ import annotations

from dataclasses import dataclass


POOL12: tuple[str, ...] = (
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "BNBUSDT",
    "TRXUSDT",
    "ADAUSDT",
    "LINKUSDT",
    "AVAXUSDT",
    "NEARUSDT",
    "UNIUSDT",
)

OHLCV_COLUMNS: tuple[str, ...] = (
    "Open",
    "High",
    "Low",
    "Close",
    "Volume",
    "QuoteVolume",
    "num_trades",
)


@dataclass(frozen=True)
class StrategyConfig:
    symbols: tuple[str, ...] = POOL12
    start_date: str = "2020-01-01"
    trading_days: int = 365
    entry_window: int = 20
    ema_window: int = 200
    atr_window: int = 14
    atr_mult: float = 3.0
    target_vol: float = 0.40
    vol_window: int = 20
    vol_floor: float = 0.20
    spot_fee: float = 0.0010
    spot_slippage: float = 0.0005
    cash_policy: str = "fixed_slots"
    execution_timing: str = "next_open_after_close_confirmation"
    adv_participation: float = 0.01

    @property
    def cost_rate(self) -> float:
        return self.spot_fee + self.spot_slippage


DEFAULT_CONFIG = StrategyConfig()
