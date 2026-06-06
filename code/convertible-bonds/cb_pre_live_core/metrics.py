"""Performance metrics."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


def calc_metrics(r: pd.Series, rf_annual: float = 0.025) -> dict[str, float]:
    r = pd.Series(r).dropna().astype(float)
    if len(r) < 20:
        return {k: np.nan for k in ["CAGR", "Vol", "Sharpe", "MDD", "Calmar", "WinW"]}
    nav = (1.0 + r).cumprod()
    years = len(r) / 252.0
    cagr = nav.iloc[-1] ** (1.0 / years) - 1.0
    vol = r.std() * math.sqrt(252.0)
    sharpe = (cagr - rf_annual) / vol if vol > 0 else np.nan
    dd = nav / nav.cummax() - 1.0
    mdd = float(dd.min())
    calmar = cagr / abs(mdd) if mdd != 0 else np.nan
    win_w = float((r.resample("W").sum() > 0).mean()) if isinstance(r.index, pd.DatetimeIndex) else np.nan
    return {"CAGR": float(cagr), "Vol": float(vol), "Sharpe": float(sharpe), "MDD": mdd, "Calmar": float(calmar), "WinW": win_w}
