"""Signal scoring: C_rank_mom20."""

from __future__ import annotations

import pandas as pd


def add_score_and_returns(df: pd.DataFrame) -> pd.DataFrame:
    d = df.sort_values(["cb_code", "trade_date"]).copy()
    d["ret"] = d.groupby("cb_code")["cb_close"].pct_change()
    open_px = pd.to_numeric(d["cb_open"], errors="coerce")
    close_px = pd.to_numeric(d["cb_close"], errors="coerce")
    d["ret_entry"] = close_px / open_px - 1.0
    mom_col = "stock_close_adj" if "stock_close_adj" in d.columns else "stock_close"
    d["mom_20d"] = d.groupby("stk_code")[mom_col].pct_change(20)
    rank_price = d.groupby("trade_date")["cb_close"].rank(pct=True, ascending=True)
    rank_premium = d.groupby("trade_date")["conversion_premium"].rank(pct=True, ascending=True)
    rank_mom = d.groupby("trade_date")["mom_20d"].rank(pct=True, ascending=False)
    d["score"] = rank_price + rank_premium + rank_mom
    return d.loc[d["score"].notna()].copy()
