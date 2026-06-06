from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

from .config import OHLCV_COLUMNS, POOL12
from .indicators import validate_ohlcv


LOWER_TO_STANDARD = {
    "open": "Open",
    "high": "High",
    "low": "Low",
    "close": "Close",
    "volume": "Volume",
    "quote_volume": "QuoteVolume",
}


def load_ohlcv_csv(path: str | Path) -> pd.DataFrame:
    csv_path = Path(path)
    df = pd.read_csv(csv_path)

    if "date" in df.columns:
        date_col = "date"
    else:
        date_col = df.columns[0]

    df = df.rename(columns=LOWER_TO_STANDARD)
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce").dt.tz_localize(None)
    df = df.dropna(subset=[date_col]).set_index(date_col)

    keep = [col for col in OHLCV_COLUMNS if col in df.columns]
    return validate_ohlcv(df[keep])


def cache_file(data_dir: str | Path, symbol: str) -> Path:
    return Path(data_dir) / f"{symbol.lower()}_spot_daily.csv"


def load_cache_dir(
    data_dir: str | Path,
    symbols: Iterable[str] = POOL12,
    skip_missing: bool = False,
) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    missing: list[str] = []

    for symbol in symbols:
        path = cache_file(data_dir, symbol)
        if not path.exists():
            missing.append(symbol)
            if skip_missing:
                continue
            raise FileNotFoundError(path)
        out[symbol] = load_ohlcv_csv(path)

    if missing and not skip_missing:
        raise FileNotFoundError(f"Missing cache files for: {missing}")
    return out
