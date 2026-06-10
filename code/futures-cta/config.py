"""Public configuration anchor for the futures CTA archive.

The original local research used a credentialed data layer for Chinese
commodity futures. This public version keeps only the static universe metadata
needed to inspect the signal, pooling, robustness, and capital-ladder scripts.
No token, API key, or local cache path is included here.
"""
from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
DATA_CACHE = PROJECT_ROOT / "data_cache"

UNIVERSE = [
    ("M0", "Soybean meal", "Agriculture", "DCE", 10),
    ("C0", "Corn", "Agriculture", "DCE", 10),
    ("P0", "Palm oil", "Agriculture", "DCE", 10),
    ("Y0", "Soybean oil", "Agriculture", "DCE", 10),
    ("SR0", "Sugar", "Agriculture", "CZCE", 10),
    ("CF0", "Cotton", "Agriculture", "CZCE", 5),
    ("RB0", "Rebar", "Ferrous", "SHFE", 10),
    ("I0", "Iron ore", "Ferrous", "DCE", 100),
    ("J0", "Coke", "Ferrous", "DCE", 100),
    ("HC0", "Hot-rolled coil", "Ferrous", "SHFE", 10),
    ("CU0", "Copper", "Non-ferrous", "SHFE", 5),
    ("ZN0", "Zinc", "Non-ferrous", "SHFE", 5),
    ("AL0", "Aluminum", "Non-ferrous", "SHFE", 5),
    ("TA0", "PTA", "Energy/Chemical", "CZCE", 5),
    ("MA0", "Methanol", "Energy/Chemical", "CZCE", 10),
    ("RU0", "Rubber", "Energy/Chemical", "SHFE", 10),
    ("SC0", "Crude oil", "Energy/Chemical", "INE", 1000),
    ("AU0", "Gold", "Precious metals", "SHFE", 1000),
    ("AG0", "Silver", "Precious metals", "SHFE", 15),
]

UNIVERSE_COLS = ["symbol", "name", "sector", "exchange", "multiplier"]

MAIN_MONTHS = {
    "M": [1, 5, 9],
    "C": [1, 5, 9],
    "P": [1, 5, 9],
    "Y": [1, 5, 9],
    "SR": [1, 5, 9],
    "CF": [1, 5, 9],
    "RB": [1, 5, 10],
    "I": [1, 5, 9],
    "J": [1, 5, 9],
    "HC": [1, 5, 10],
    "CU": list(range(1, 13)),
    "ZN": list(range(1, 13)),
    "AL": list(range(1, 13)),
    "TA": [1, 5, 9],
    "MA": [1, 5, 9],
    "RU": [1, 5, 9],
    "SC": list(range(1, 13)),
    "AU": [6, 12],
    "AG": [6, 12],
}

CONTRACT_START_YEAR = 2017
CONTRACT_END_YEAR = 2027


def get_universe_df():
    import pandas as pd

    return pd.DataFrame(UNIVERSE, columns=UNIVERSE_COLS)


def get_symbol_meta(symbol: str) -> dict | None:
    for row in UNIVERSE:
        if row[0] == symbol:
            return dict(zip(UNIVERSE_COLS, row))
    return None
