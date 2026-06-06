"""Layer1 universe construction."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import FinalConfig


def _redeem_notice_ok(raw: pd.DataFrame, cfg: FinalConfig) -> pd.Series:
    if not cfg.redeem_notice_csv.exists():
        return pd.Series(True, index=raw.index)
    notices = pd.read_csv(cfg.redeem_notice_csv, dtype={"cb_code": str})
    if notices.empty:
        return pd.Series(True, index=raw.index)
    notices["notice_date"] = pd.to_datetime(notices["notice_date"]).dt.normalize()
    left = raw[["cb_code", "trade_date"]].copy()
    left["trade_date"] = pd.to_datetime(left["trade_date"]).dt.normalize()
    joined = left.merge(notices, on="cb_code", how="left")
    return (joined["notice_date"].isna() | (joined["trade_date"] < joined["notice_date"])).fillna(True)


def build_layer1(raw: pd.DataFrame, issue_sizes: pd.Series, maturity_dates: pd.Series, cfg: FinalConfig) -> pd.DataFrame:
    r = raw.copy()
    r["issue_size"] = r["cb_code"].map(issue_sizes)
    m = (
        r["is_tradable_day"]
        & ~r["in_delisting_period"]
        & (r["issue_size"] >= cfg.min_issue_size)
        & r["conversion_premium"].notna()
        & (r["cb_close"] > 0)
        & (r["cb_close"] >= cfg.cb_close_min)
    )
    if cfg.cb_close_max is not None:
        m &= r["cb_close"] <= cfg.cb_close_max
    mat = r["cb_code"].map(maturity_dates)
    mat_dt = pd.to_datetime(mat, format="%Y%m%d", errors="coerce")
    days_left = (mat_dt - r["trade_date"]).dt.days
    m &= mat_dt.isna() | (days_left >= cfg.min_days_to_maturity)
    m &= _redeem_notice_ok(r, cfg)
    out = r.loc[m].copy()
    return out.replace([np.inf, -np.inf], np.nan)
