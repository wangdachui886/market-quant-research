from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd

from .config import DEFAULT_CONFIG, StrategyConfig
from .indicators import add_indicators
from .schema import SignalSnapshot


def _optional_float(value) -> Optional[float]:
    if value is None or pd.isna(value):
        return None
    return float(value)


def generate_signal_frame(df: pd.DataFrame, config: StrategyConfig = DEFAULT_CONFIG) -> pd.DataFrame:
    out = add_indicators(df, config=config)

    position: list[int] = []
    stop: list[float] = []
    weight: list[float] = []
    highest: list[float] = []

    current_pos = 0
    current_stop = 0.0
    current_weight = 0.0
    highest_close = 0.0

    for _, row in out.iterrows():
        ready = (
            pd.notna(row["Upper"])
            and pd.notna(row["EMA"])
            and pd.notna(row["ATR"])
            and pd.notna(row["RVol"])
        )
        if not ready:
            position.append(0)
            stop.append(np.nan)
            weight.append(0.0)
            highest.append(np.nan)
            continue

        close = float(row["Close"])
        if current_pos == 0:
            if close > float(row["Upper"]) and close > float(row["EMA"]):
                current_pos = 1
                highest_close = close
                current_stop = highest_close - config.atr_mult * float(row["ATR"])
                current_weight = min(1.0, config.target_vol / max(float(row["RVol"]), config.vol_floor))
        else:
            highest_close = max(highest_close, close)
            current_stop = max(current_stop, highest_close - config.atr_mult * float(row["ATR"]))
            if close < current_stop:
                current_pos = 0
                current_stop = 0.0
                current_weight = 0.0

        position.append(current_pos)
        stop.append(current_stop if current_pos else np.nan)
        weight.append(current_weight)
        highest.append(highest_close if current_pos else np.nan)

    out["Position"] = position
    out["Stop"] = stop
    out["Weight"] = weight
    out["HighestClose"] = highest
    return out


def latest_snapshot(symbol: str, signal_frame: pd.DataFrame) -> SignalSnapshot:
    if signal_frame.empty:
        raise ValueError(f"No signal rows for {symbol}")

    frame = signal_frame.dropna(subset=["Close"])
    if frame.empty:
        raise ValueError(f"No valid close rows for {symbol}")

    row = frame.iloc[-1]
    prev_position = int(frame["Position"].iloc[-2]) if len(frame) >= 2 else 0
    position = int(row["Position"])

    if position == 1 and prev_position == 0:
        action = "ENTER"
        reason = "close_breaks_prior_high_and_above_ema"
    elif position == 0 and prev_position == 1:
        action = "EXIT"
        reason = "close_confirmed_below_atr_trailing_stop"
    elif position == 1:
        action = "HOLD"
        reason = "position_active_no_exit"
    else:
        action = "WAIT"
        reason = "no_valid_long_signal"

    signal_date = pd.Timestamp(frame.index[-1]).date().isoformat()
    return SignalSnapshot(
        symbol=symbol,
        signal_date=signal_date,
        close=_optional_float(row.get("Close")),
        upper=_optional_float(row.get("Upper")),
        ema=_optional_float(row.get("EMA")),
        atr=_optional_float(row.get("ATR")),
        rvol=_optional_float(row.get("RVol")),
        position=position,
        previous_position=prev_position,
        stop=_optional_float(row.get("Stop")),
        weight=0.0 if math.isnan(float(row.get("Weight", 0.0))) else float(row.get("Weight", 0.0)),
        action=action,
        reason=reason,
    )


def generate_latest_snapshot(
    symbol: str,
    df: pd.DataFrame,
    config: StrategyConfig = DEFAULT_CONFIG,
) -> SignalSnapshot:
    return latest_snapshot(symbol, generate_signal_frame(df, config=config))
