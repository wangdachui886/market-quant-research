from __future__ import annotations

import math

import pandas as pd

from .config import DEFAULT_CONFIG, StrategyConfig


REQUIRED_COLUMNS = ("Open", "High", "Low", "Close")


def validate_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"Missing OHLCV columns: {missing}")

    out = df.copy().sort_index()
    if out.index.has_duplicates:
        dupes = out.index[out.index.duplicated()].unique()
        raise ValueError(f"Duplicate date index values: {list(dupes[:5])}")

    for col in [c for c in out.columns if c in ("Open", "High", "Low", "Close", "Volume", "QuoteVolume", "num_trades")]:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    if out[list(REQUIRED_COLUMNS)].isna().any().any():
        raise ValueError("OHLC columns contain NaN after numeric conversion.")

    return out


def ema(series: pd.Series, n: int) -> pd.Series:
    return series.ewm(span=n, adjust=False).mean()


def atr(df: pd.DataFrame, n: int) -> pd.Series:
    tr = pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - df["Close"].shift(1)).abs(),
            (df["Low"] - df["Close"].shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(n).mean()


def add_indicators(df: pd.DataFrame, config: StrategyConfig = DEFAULT_CONFIG) -> pd.DataFrame:
    out = validate_ohlcv(df)
    out["Upper"] = out["High"].rolling(config.entry_window).max().shift(1)
    out["EMA"] = ema(out["Close"], config.ema_window).shift(1)
    out["ATR"] = atr(out, config.atr_window).shift(1)
    out["RVol"] = (
        out["Close"].pct_change().rolling(config.vol_window).std() * math.sqrt(config.trading_days)
    ).shift(1)
    return out
