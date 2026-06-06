"""Data loading helpers.

The only repair here is point-in-time safe forward-fill of conversion price
within the same bond, followed by recomputing conversion value and premium.
"""

from __future__ import annotations

import pandas as pd

from .config import FinalConfig


def load_panel(cfg: FinalConfig) -> pd.DataFrame:
    raw = pd.read_csv(cfg.panel_csv, dtype={"cb_code": str, "stk_code": str, "trade_date": str})
    raw["trade_date"] = pd.to_datetime(raw["trade_date"], format="%Y%m%d")
    for col in ("is_tradable_day", "in_delisting_period"):
        if raw[col].dtype == object:
            raw[col] = raw[col].str.lower() == "true"
        else:
            raw[col] = raw[col].astype(bool)
    raw = raw.sort_values(["cb_code", "trade_date"]).copy()
    raw["conv_price"] = pd.to_numeric(raw["conv_price"], errors="coerce")
    raw["conv_price"] = raw.groupby("cb_code")["conv_price"].ffill()
    ok = raw["conv_price"].notna()
    raw.loc[ok, "conversion_value"] = 100.0 / raw.loc[ok, "conv_price"] * raw.loc[ok, "stock_close"]
    raw.loc[ok, "conversion_premium"] = raw.loc[ok, "cb_close"] / raw.loc[ok, "conversion_value"] - 1.0
    return raw.sort_values(["trade_date", "cb_code"]).reset_index(drop=True)


def load_issue_sizes(cfg: FinalConfig) -> pd.Series:
    if cfg.issue_size_csv.exists():
        df = pd.read_csv(cfg.issue_size_csv, dtype={"ts_code": str, "maturity_date": str})
        return df.set_index("ts_code")["issue_size"]
    df = pd.read_csv(cfg.fallback_issue_size_csv, dtype={"ts_code": str})
    return df.set_index("ts_code")["issue_size"]


def load_maturity_dates(cfg: FinalConfig) -> pd.Series:
    df = pd.read_csv(cfg.issue_size_csv, dtype={"ts_code": str, "maturity_date": str})
    return df.set_index("ts_code")["maturity_date"].astype(str)
