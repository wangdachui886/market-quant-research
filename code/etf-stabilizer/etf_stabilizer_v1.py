"""
ETF Stabilizer V1.1

Purpose
-------
This module keeps only the executable logic needed for future integration with
the convertible-bond live framework. It does not fetch data and does not run a
full backtest. Feed it daily close prices, optional NAV data, and a month-end
signal date; it returns the target ETF sleeve weights.

Default role
------------
Use as a 30% stabilizer sleeve with the sealed convertible-bond
top12_keep37 strategy as the 70% core.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import pandas as pd


ETF_300 = "510300.SH"
ETF_SP500 = "513500.SH"
ETF_BOND = "511010.SH"
ETF_GOLD = "518880.SH"
ETF_SHORT_FINANCING = "511360.SH"


@dataclass(frozen=True)
class ETFStabilizerConfig:
    lookback_days: int = 252
    premium_abs_cap: float = 0.05
    a_share_weight: float = 0.20
    cross_border_weight: float = 0.20
    bond_base_weight: float = 0.40
    gold_weight: float = 0.20
    failed_equity_gold_share: float = 0.20
    fallback_code: str = ETF_BOND


DEFAULT_CONFIG = ETFStabilizerConfig()


def _history(series: pd.Series, signal_date: pd.Timestamp) -> pd.Series:
    history = series.loc[:signal_date].dropna()
    return history[~history.index.duplicated(keep="last")]


def trailing_return(series: pd.Series, signal_date: pd.Timestamp, lookback_days: int) -> float:
    history = _history(series, signal_date)
    if len(history) <= lookback_days:
        return float("nan")
    return float(history.iloc[-1] / history.iloc[-lookback_days - 1] - 1)


def above_moving_average(series: pd.Series, signal_date: pd.Timestamp, lookback_days: int) -> bool:
    history = _history(series, signal_date)
    if len(history) <= lookback_days:
        return False
    return bool(history.iloc[-1] > history.tail(lookback_days).mean())


def equity_trend_gate(price_series: pd.Series, signal_date: pd.Timestamp, lookback_days: int) -> bool:
    """Return True when the equity ETF is allowed to be held."""
    mom = trailing_return(price_series, signal_date, lookback_days)
    return pd.notna(mom) and mom > 0 and above_moving_average(price_series, signal_date, lookback_days)


def premium_gate(
    close_series: pd.Series,
    nav_series: pd.Series | None,
    signal_date: pd.Timestamp,
    premium_abs_cap: float,
) -> bool:
    """Conservative QDII premium filter.

    If NAV is unavailable we do not block the trade here; production integration
    can choose to fail closed instead if NAV quality is a hard requirement.
    """
    if nav_series is None:
        return True
    close_history = _history(close_series, signal_date)
    nav_history = _history(nav_series, signal_date)
    if close_history.empty or nav_history.empty:
        return True
    close = close_history.iloc[-1]
    nav = nav_history.iloc[-1]
    if pd.isna(close) or pd.isna(nav) or nav <= 0:
        return True
    premium = close / nav - 1
    return abs(float(premium)) <= premium_abs_cap


def allocate_failed_equity(weights: dict[str, float], failed_weight: float, config: ETFStabilizerConfig) -> None:
    """Move failed equity weight into fallback plus a small gold sleeve."""
    gold_weight = failed_weight * config.failed_equity_gold_share
    fallback_weight = failed_weight - gold_weight
    weights[ETF_GOLD] = weights.get(ETF_GOLD, 0.0) + gold_weight
    weights[config.fallback_code] = weights.get(config.fallback_code, 0.0) + fallback_weight


def target_weights(
    close_prices: pd.DataFrame,
    signal_date: str | pd.Timestamp,
    nav_prices: pd.DataFrame | None = None,
    config: ETFStabilizerConfig = DEFAULT_CONFIG,
) -> dict[str, float]:
    """Calculate ETF sleeve target weights on a signal date.

    Parameters
    ----------
    close_prices:
        DataFrame indexed by date, columns include 510300.SH, 513500.SH,
        511010.SH, and 518880.SH.
    signal_date:
        Month-end decision date. The returned weights should be executed on the
        next tradable day.
    nav_prices:
        Optional NAV DataFrame used for the cross-border premium filter.
    config:
        Strategy parameters.
    """
    signal_date = pd.Timestamp(signal_date)
    weights = {
        ETF_300: 0.0,
        ETF_SP500: 0.0,
        ETF_BOND: config.bond_base_weight,
        ETF_GOLD: config.gold_weight,
    }

    if equity_trend_gate(close_prices[ETF_300], signal_date, config.lookback_days):
        weights[ETF_300] += config.a_share_weight
    else:
        allocate_failed_equity(weights, config.a_share_weight, config)

    sp500_nav = nav_prices[ETF_SP500] if nav_prices is not None and ETF_SP500 in nav_prices else None
    sp500_allowed = equity_trend_gate(close_prices[ETF_SP500], signal_date, config.lookback_days)
    sp500_allowed = sp500_allowed and premium_gate(
        close_prices[ETF_SP500],
        sp500_nav,
        signal_date,
        config.premium_abs_cap,
    )
    if sp500_allowed:
        weights[ETF_SP500] += config.cross_border_weight
    else:
        allocate_failed_equity(weights, config.cross_border_weight, config)

    total = sum(weights.values())
    if total <= 0:
        raise ValueError("ETF Stabilizer produced zero total weight.")
    return {code: weight / total for code, weight in weights.items() if weight > 0}


def portfolio_overlay_weights(etf_sleeve_weight: float = 0.30) -> Mapping[str, float]:
    """Return top-level module weights for portfolio integration."""
    if not 0 <= etf_sleeve_weight <= 1:
        raise ValueError("etf_sleeve_weight must be in [0, 1].")
    return {
        "convertible_bond_top12_keep37": 1 - etf_sleeve_weight,
        "etf_stabilizer_v1": etf_sleeve_weight,
    }
