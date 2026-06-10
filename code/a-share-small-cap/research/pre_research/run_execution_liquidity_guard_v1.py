from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PRE_RESEARCH_ROOT = PROJECT_ROOT / "research" / "pre_research"
if str(PRE_RESEARCH_ROOT) not in sys.path:
    sys.path.append(str(PRE_RESEARCH_ROOT))

from run_pre_research_v1 import (  # noqa: E402
    RESEARCH_END,
    RESEARCH_START,
    WARMUP_START,
    Paths,
    cumulative_return,
    draw_bar_chart,
    draw_multi_line_chart,
    load_pre_research_panel,
    load_yearly_csv,
    log,
    markdown_table,
    num,
    parse_bool_series,
    pct,
    safe_annualized_return,
)
from run_pre_research_v2_stateful_portfolio import (  # noqa: E402
    COST_STRESS_RATES,
    MAX_NAMES,
    bool_get,
    float_get,
    load_state_data,
    make_series_map,
    max_drawdown,
    worst_rolling_return,
)


BASELINE_STRATEGY = "baseline_size_10_50_top100"
BASELINE_LABEL = "baseline"
PERIODS = [
    ("full_sample", RESEARCH_START, RESEARCH_END),
    ("ex_2008", RESEARCH_START, RESEARCH_END),
    ("2008", "2008-01-01", "2008-12-31"),
    ("2014-2015", "2014-01-01", "2015-12-31"),
    ("2016-2018", "2016-01-01", "2018-12-31"),
    ("2022-2025", "2022-01-01", "2025-12-31"),
]


Condition = Callable[[pd.DataFrame], pd.Series]


def normalized_nav(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").fillna(0.0)
    if values.empty:
        return pd.Series(dtype=float)
    return (1.0 + values).cumprod()


def drawdown_series(series: pd.Series) -> pd.Series:
    nav = normalized_nav(series)
    if nav.empty:
        return pd.Series(dtype=float)
    return nav / nav.cummax() - 1.0


def annualized_vol(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return np.nan
    return float(values.std() * np.sqrt(252))


def window_series(series: pd.Series, start: str, end: str, name: str = "") -> pd.Series:
    if series.empty:
        return series
    idx = series.index.astype(str)
    if name == "ex_2008":
        return series.loc[(idx < "2008-01-01") | (idx > "2008-12-31")]
    return series.loc[(idx >= start) & (idx <= end)]


def cost_stressed_return(daily: pd.DataFrame, bps: str = "30bps") -> pd.Series:
    returns = daily.set_index("date")["daily_return"]
    turnover = daily.set_index("date")["turnover_rate"]
    return returns - turnover * COST_STRESS_RATES[bps]


def load_status_features(paths: Paths) -> pd.DataFrame:
    years = [str(year) for year in range(2004, 2026)]
    status = load_yearly_csv(
        paths.processed_root / "market_trading_status",
        "market_trading_status_{year}.csv.gz",
        years,
        [
            "trade_date",
            "code",
            "has_bar",
            "can_sell_on_bar",
            "is_limit_down_est",
            "one_price_limit_est",
        ],
        dtype={"trade_date": str, "code": str},
    )
    status = status[(status["trade_date"] >= WARMUP_START) & (status["trade_date"] <= RESEARCH_END)].copy()
    for col in ["has_bar", "can_sell_on_bar", "is_limit_down_est", "one_price_limit_est"]:
        status[col] = parse_bool_series(status[col])
    status = status.sort_values(["code", "trade_date"])
    status["no_bar"] = (~status["has_bar"].fillna(False)).astype("int8")
    status["cant_sell"] = ((~status["has_bar"].fillna(False)) | (~status["can_sell_on_bar"].fillna(False))).astype(
        "int8"
    )
    status["limit_down"] = status["is_limit_down_est"].fillna(False).astype("int8")
    status["one_price_limit"] = status["one_price_limit_est"].fillna(False).astype("int8")
    for col in ["no_bar", "cant_sell", "limit_down", "one_price_limit"]:
        grouped = status.groupby("code", sort=False)[col]
        status[f"{col}_20d"] = grouped.rolling(20, min_periods=1).sum().reset_index(level=0, drop=True)
        status[f"{col}_60d"] = grouped.rolling(60, min_periods=1).sum().reset_index(level=0, drop=True)
    keep_cols = [
        "trade_date",
        "code",
        "no_bar_20d",
        "no_bar_60d",
        "cant_sell_20d",
        "cant_sell_60d",
        "limit_down_20d",
        "limit_down_60d",
        "one_price_limit_20d",
        "one_price_limit_60d",
    ]
    return status[keep_cols].rename(columns={"trade_date": "feature_date"})


def enrich_guard_features(panel: pd.DataFrame, paths: Paths) -> pd.DataFrame:
    frame = panel.copy()
    frame = frame.sort_values(["code", "feature_date"])
    frame["amount_60d_mean"] = (
        frame.groupby("code", sort=False)["amount_yuan"]
        .rolling(60, min_periods=40)
        .mean()
        .reset_index(level=0, drop=True)
    )
    frame["amount_20d_to_60d"] = frame["amount_20d_mean"] / frame["amount_60d_mean"].replace(0, np.nan)

    log("load current-day status rolling features")
    status = load_status_features(paths)
    frame = frame.merge(status, on=["feature_date", "code"], how="left")
    for col in [
        "no_bar_20d",
        "no_bar_60d",
        "cant_sell_20d",
        "cant_sell_60d",
        "limit_down_20d",
        "limit_down_60d",
        "one_price_limit_20d",
        "one_price_limit_60d",
    ]:
        frame[col] = pd.to_numeric(frame[col], errors="coerce").fillna(0.0)
    return frame


def build_guard_specs() -> list[dict[str, Any]]:
    def all_pass(frame: pd.DataFrame) -> pd.Series:
        return pd.Series(True, index=frame.index)

    specs: list[dict[str, Any]] = [
        {
            "strategy": BASELINE_STRATEGY,
            "label": BASELINE_LABEL,
            "family": "baseline",
            "description": "No extra execution/liquidity guard.",
            "condition": all_pass,
        },
        {
            "strategy": "amount20_ge_20m",
            "label": "amount20 >= 20m",
            "family": "amount",
            "description": "20-day average turnover must be at least CNY 20m.",
            "condition": lambda x: x["amount_20d_mean"].ge(20_000_000),
        },
        {
            "strategy": "amount20_ge_50m",
            "label": "amount20 >= 50m",
            "family": "amount",
            "description": "20-day average turnover must be at least CNY 50m.",
            "condition": lambda x: x["amount_20d_mean"].ge(50_000_000),
        },
        {
            "strategy": "amount20_ge_100m",
            "label": "amount20 >= 100m",
            "family": "amount",
            "description": "20-day average turnover must be at least CNY 100m.",
            "condition": lambda x: x["amount_20d_mean"].ge(100_000_000),
        },
        {
            "strategy": "amount60_ge_50m",
            "label": "amount60 >= 50m",
            "family": "amount",
            "description": "60-day average turnover must be at least CNY 50m.",
            "condition": lambda x: x["amount_60d_mean"].ge(50_000_000),
        },
        {
            "strategy": "amount20_to_60_ge_050",
            "label": "amount20/60 >= 0.50",
            "family": "decay",
            "description": "20-day turnover must retain at least 50% of 60-day turnover.",
            "condition": lambda x: x["amount_20d_to_60d"].ge(0.50),
        },
        {
            "strategy": "amount20_to_60_ge_070",
            "label": "amount20/60 >= 0.70",
            "family": "decay",
            "description": "20-day turnover must retain at least 70% of 60-day turnover.",
            "condition": lambda x: x["amount_20d_to_60d"].ge(0.70),
        },
        {
            "strategy": "no_bar20_eq0",
            "label": "no-bar20 = 0",
            "family": "state",
            "description": "No no-bar day in the past 20 trading days.",
            "condition": lambda x: x["no_bar_20d"].le(0),
        },
        {
            "strategy": "no_bar60_le1",
            "label": "no-bar60 <= 1",
            "family": "state",
            "description": "At most one no-bar day in the past 60 trading days.",
            "condition": lambda x: x["no_bar_60d"].le(1),
        },
        {
            "strategy": "cant_sell20_eq0",
            "label": "cant-sell20 = 0",
            "family": "state",
            "description": "No non-sellable day in the past 20 trading days.",
            "condition": lambda x: x["cant_sell_20d"].le(0),
        },
        {
            "strategy": "limit_down20_eq0",
            "label": "limit-down20 = 0",
            "family": "state",
            "description": "No estimated limit-down day in the past 20 trading days.",
            "condition": lambda x: x["limit_down_20d"].le(0),
        },
        {
            "strategy": "one_price20_eq0",
            "label": "one-price20 = 0",
            "family": "state",
            "description": "No one-price limit day in the past 20 trading days.",
            "condition": lambda x: x["one_price_limit_20d"].le(0),
        },
        {
            "strategy": "guard_loose_v1",
            "label": "guard loose",
            "family": "composite",
            "description": "amount20>=20m, amount20/60>=0.50, no-bar20=0, limit-down20<=1.",
            "condition": lambda x: x["amount_20d_mean"].ge(20_000_000)
            & x["amount_20d_to_60d"].ge(0.50)
            & x["no_bar_20d"].le(0)
            & x["limit_down_20d"].le(1),
        },
        {
            "strategy": "guard_balanced_v1",
            "label": "guard balanced",
            "family": "composite",
            "description": "amount20>=50m, amount20/60>=0.60, no-bar20=0, one-price20=0.",
            "condition": lambda x: x["amount_20d_mean"].ge(50_000_000)
            & x["amount_20d_to_60d"].ge(0.60)
            & x["no_bar_20d"].le(0)
            & x["one_price_limit_20d"].le(0),
        },
        {
            "strategy": "guard_strict_v1",
            "label": "guard strict",
            "family": "composite",
            "description": "amount20>=100m, amount20/60>=0.70, no-bar60<=1, limit-down20=0, one-price20=0.",
            "condition": lambda x: x["amount_20d_mean"].ge(100_000_000)
            & x["amount_20d_to_60d"].ge(0.70)
            & x["no_bar_60d"].le(1)
            & x["limit_down_20d"].le(0)
            & x["one_price_limit_20d"].le(0),
        },
    ]
    return specs


def condition_series(frame: pd.DataFrame, spec: dict[str, Any]) -> pd.Series:
    result = spec["condition"](frame)
    if not isinstance(result, pd.Series):
        result = pd.Series(result, index=frame.index)
    return result.fillna(False).astype(bool)


def monthly_signal_dates(panel: pd.DataFrame) -> list[str]:
    signal_dates = pd.Series(sorted(panel["feature_date"].dropna().unique()))
    signal_dates = signal_dates[(signal_dates >= RESEARCH_START) & (signal_dates <= RESEARCH_END)]
    return signal_dates.groupby(signal_dates.str.slice(0, 7)).tail(1).tolist()


def build_monthly_candidates(panel: pd.DataFrame) -> dict[str, dict[str, Any]]:
    signal_dates = monthly_signal_dates(panel)
    signal_set = set(signal_dates)
    monthly_panel = panel[panel["feature_date"].isin(signal_set)].copy()
    monthly: dict[str, dict[str, Any]] = {}
    for signal_date, date_frame in monthly_panel.groupby("feature_date", sort=True):
        exec_dates = date_frame["exec_date"].dropna().unique().tolist()
        exec_date = sorted(exec_dates)[0] if exec_dates else ""
        candidates = date_frame[
            date_frame["base_universe"] & date_frame["size_pct"].gt(0.10) & date_frame["size_pct"].le(0.50)
        ].copy()
        candidates = candidates.sort_values("float_market_cap")
        monthly[str(signal_date)] = {
            "signal_date": str(signal_date),
            "exec_date": exec_date,
            "candidates": candidates,
            "baseline_target": candidates.head(MAX_NAMES).copy(),
        }
    return monthly


def build_plans(monthly_candidates: dict[str, dict[str, Any]], spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    plans: dict[str, dict[str, Any]] = {}
    for signal_date, bundle in monthly_candidates.items():
        exec_date = str(bundle["exec_date"])
        if not exec_date:
            continue
        if exec_date > RESEARCH_END:
            continue
        base_candidates = bundle["candidates"]
        if base_candidates.empty:
            target = base_candidates
            pass_count = 0
            fail_count = 0
        else:
            passes = condition_series(base_candidates, spec)
            pass_count = int(passes.sum())
            fail_count = int((~passes).sum())
            target = base_candidates.loc[passes].nsmallest(MAX_NAMES, "float_market_cap")
        plans[exec_date] = {
            "signal_date": signal_date,
            "exec_date": exec_date,
            "target": target["code"].tolist(),
            "candidate_count": int(len(base_candidates)),
            "guard_pass_count": pass_count,
            "guard_fail_count": fail_count,
            "median_amount_20d": float(target["amount_20d_mean"].median()) if not target.empty else np.nan,
            "median_float_market_cap": float(target["float_market_cap"].median()) if not target.empty else np.nan,
        }
    return plans


def target_removal_diagnostic(
    panel: pd.DataFrame,
    monthly_candidates: dict[str, dict[str, Any]],
    specs: list[dict[str, Any]],
) -> pd.DataFrame:
    targets = {key: value["baseline_target"] for key, value in monthly_candidates.items()}
    rows: list[dict[str, Any]] = []
    monthly_dates = list(targets.keys())
    panel_returns = panel.set_index(["feature_date", "code"])["fwd_cc_ret_1d"]
    trade_dates = sorted(panel["feature_date"].dropna().unique().tolist())

    for spec in specs:
        removed_counts: list[int] = []
        kept_counts: list[int] = []
        removed_daily_returns: list[tuple[str, float]] = []
        kept_daily_returns: list[tuple[str, float]] = []
        for idx, signal_date in enumerate(monthly_dates):
            target = targets[signal_date]
            if target.empty:
                continue
            passes = condition_series(target, spec)
            removed_codes = target.loc[~passes, "code"].tolist()
            kept_codes = target.loc[passes, "code"].tolist()
            removed_counts.append(len(removed_codes))
            kept_counts.append(len(kept_codes))
            next_signal = monthly_dates[idx + 1] if idx + 1 < len(monthly_dates) else RESEARCH_END
            hold_dates = [date for date in trade_dates if signal_date < date <= next_signal]
            for date in hold_dates:
                if removed_codes:
                    idxer = pd.MultiIndex.from_product([[date], removed_codes], names=["feature_date", "code"])
                    values = panel_returns.reindex(idxer)
                    if values.notna().any():
                        removed_daily_returns.append((date, float(values.mean(skipna=True))))
                if kept_codes:
                    idxer = pd.MultiIndex.from_product([[date], kept_codes], names=["feature_date", "code"])
                    values = panel_returns.reindex(idxer)
                    if values.notna().any():
                        kept_daily_returns.append((date, float(values.mean(skipna=True))))

        removed_series = pd.Series(
            [value for _, value in removed_daily_returns],
            index=[date for date, _ in removed_daily_returns],
            dtype=float,
        )
        kept_series = pd.Series(
            [value for _, value in kept_daily_returns],
            index=[date for date, _ in kept_daily_returns],
            dtype=float,
        )
        rows.append(
            {
                "strategy": spec["strategy"],
                "label": spec["label"],
                "family": spec["family"],
                "avg_removed_names_pct": float(np.mean(removed_counts) / MAX_NAMES) if removed_counts else np.nan,
                "median_removed_names": float(np.median(removed_counts)) if removed_counts else np.nan,
                "median_kept_names": float(np.median(kept_counts)) if kept_counts else np.nan,
                "removed_basket_ann_return": safe_annualized_return(removed_series),
                "removed_basket_max_drawdown": max_drawdown(removed_series),
                "kept_basket_ann_return": safe_annualized_return(kept_series),
                "kept_basket_max_drawdown": max_drawdown(kept_series),
                "removed_minus_kept_ann": safe_annualized_return(removed_series)
                - safe_annualized_return(kept_series),
                "description": spec["description"],
            }
        )
    return pd.DataFrame(rows)


def summarize_daily(strategy: str, label: str, family: str, daily: pd.DataFrame, rebalance: pd.DataFrame) -> dict[str, Any]:
    returns = daily.set_index("date")["daily_return"] if not daily.empty else pd.Series(dtype=float)
    stressed = cost_stressed_return(daily, "30bps") if not daily.empty else pd.Series(dtype=float)
    buy_attempts = int(rebalance["bought"].sum() + rebalance["buy_failed"].sum()) if not rebalance.empty else 0
    sell_attempts = int(rebalance["sold"].sum() + rebalance["sell_failed"].sum()) if not rebalance.empty else 0
    total_pnl = float(returns.sum()) if not returns.empty else np.nan
    forced_state_pnl = (
        float(daily["sell_failed_holding_pnl"].sum() + daily["suspended_holding_pnl"].sum())
        if not daily.empty
        else np.nan
    )
    ex2008 = window_series(returns, RESEARCH_START, RESEARCH_END, "ex_2008")
    y2016 = window_series(returns, "2016-01-01", "2018-12-31")
    y2014 = window_series(returns, "2014-01-01", "2015-12-31")
    y2008 = window_series(returns, "2008-01-01", "2008-12-31")
    return {
        "strategy": strategy,
        "label": label,
        "family": family,
        "ann_return": safe_annualized_return(returns),
        "cagr": safe_annualized_return(returns),
        "cumulative_return": cumulative_return(returns),
        "cost_30bps_ann_return": safe_annualized_return(stressed),
        "max_drawdown": max_drawdown(returns),
        "max_drawdown_ex_2008": max_drawdown(ex2008),
        "worst_12m": worst_rolling_return(returns),
        "worst_12m_ex_2008": worst_rolling_return(ex2008),
        "ann_vol": annualized_vol(returns),
        "2008_ann_return": safe_annualized_return(y2008),
        "2008_max_drawdown": max_drawdown(y2008),
        "2014_2015_ann_return": safe_annualized_return(y2014),
        "2014_2015_max_drawdown": max_drawdown(y2014),
        "2016_2018_ann_return": safe_annualized_return(y2016),
        "2016_2018_max_drawdown": max_drawdown(y2016),
        "turnover": float(daily["turnover_rate"].mean()) if not daily.empty else np.nan,
        "buy_fail_rate": int(rebalance["buy_failed"].sum()) / buy_attempts if buy_attempts else np.nan,
        "sell_fail_rate": int(rebalance["sell_failed"].sum()) / sell_attempts if sell_attempts else np.nan,
        "sell_failed": int(rebalance["sell_failed"].sum()) if not rebalance.empty else 0,
        "sell_attempts": sell_attempts,
        "forced_state_pnl": forced_state_pnl,
        "forced_state_pnl_share": forced_state_pnl / total_pnl if total_pnl and np.isfinite(total_pnl) else np.nan,
        "suspended_position_days": int(daily["suspended_positions"].sum()) if not daily.empty else 0,
        "median_holdings": float(daily["holdings"].median()) if not daily.empty else np.nan,
        "median_cash_slots": float(daily["cash_slots"].median()) if not daily.empty else np.nan,
        "median_amount_20d": float(rebalance["median_amount_20d"].median()) if not rebalance.empty else np.nan,
        "median_float_mcap": float(rebalance["median_float_market_cap"].median()) if not rebalance.empty else np.nan,
    }


def summarize_periods(daily_returns: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for strategy, group in daily_returns.groupby("strategy", sort=False):
        label = str(group["label"].iloc[0])
        family = str(group["family"].iloc[0])
        returns = group.set_index("date")["daily_return"]
        for period, start, end in PERIODS:
            window = window_series(returns, start, end, period)
            rows.append(
                {
                    "strategy": strategy,
                    "label": label,
                    "family": family,
                    "period": period,
                    "ann_return": safe_annualized_return(window),
                    "cumulative_return": cumulative_return(window),
                    "max_drawdown": max_drawdown(window),
                    "worst_12m": worst_rolling_return(window),
                    "observations": int(window.notna().sum()),
                }
            )
    return pd.DataFrame(rows)


def run_all_guards(
    monthly_candidates: dict[str, dict[str, Any]],
    specs: list[dict[str, Any]],
    dates: list[str],
    maps: dict[str, pd.Series],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    daily_parts: list[pd.DataFrame] = []
    rebalance_parts: list[pd.DataFrame] = []
    summary_rows: list[dict[str, Any]] = []
    for spec in specs:
        log(f"simulate {spec['strategy']}")
        plans = build_plans(monthly_candidates, spec)
        daily, rebalance = simulate_stateful_portfolio_fast(dates, plans, maps, spec["strategy"])
        daily["label"] = spec["label"]
        daily["family"] = spec["family"]
        rebalance["label"] = spec["label"]
        rebalance["family"] = spec["family"]
        daily_parts.append(daily)
        rebalance_parts.append(rebalance)
        summary_rows.append(summarize_daily(spec["strategy"], spec["label"], spec["family"], daily, rebalance))
    daily_all = pd.concat(daily_parts, ignore_index=True) if daily_parts else pd.DataFrame()
    rebalance_all = pd.concat(rebalance_parts, ignore_index=True) if rebalance_parts else pd.DataFrame()
    summary = pd.DataFrame(summary_rows)
    return daily_all, rebalance_all, summary


def build_execution_maps(returns: pd.DataFrame, status: pd.DataFrame) -> dict[str, pd.Series]:
    return {
        "has_bar": make_series_map(status, "has_bar"),
        "can_buy": make_series_map(status, "can_buy_on_bar"),
        "can_sell": make_series_map(status, "can_sell_on_bar"),
        "holding_ret": make_series_map(returns, "holding_cc_ret_on_bar"),
        "entry_ret": make_series_map(returns, "entry_oc_ret_on_bar"),
        "sell_open_ret": make_series_map(returns, "sell_open_ret"),
    }


def simulate_stateful_portfolio_fast(
    dates: list[str],
    plans: dict[str, dict[str, Any]],
    maps: dict[str, pd.Series],
    strategy: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    has_bar = maps["has_bar"]
    can_buy = maps["can_buy"]
    can_sell = maps["can_sell"]
    holding_ret = maps["holding_ret"]
    entry_ret = maps["entry_ret"]
    sell_open_ret = maps["sell_open_ret"]

    holdings: set[str] = set()
    suspended_codes: set[str] = set()
    forced_hold_codes: set[str] = set()
    daily_rows: list[dict[str, Any]] = []
    rebalance_rows: list[dict[str, Any]] = []

    for date in dates:
        if date < RESEARCH_START or date > RESEARCH_END:
            continue
        plan = plans.get(date)
        sold: set[str] = set()
        sell_failed: set[str] = set()
        bought: set[str] = set()
        buy_failed: set[str] = set()
        target: list[str] = []
        target_set: set[str] = set()

        if plan is not None:
            target = list(plan["target"])
            target_set = set(target)
            forced_hold_codes.difference_update(target_set)
            for code in sorted(holdings - target_set):
                if bool_get(can_sell, date, code, False):
                    sold.add(code)
                else:
                    sell_failed.add(code)
            forced_hold_codes.update(sell_failed)

            holdings_after_sells = set(holdings - sold)
            available_slots = max(MAX_NAMES - len(holdings_after_sells), 0)
            for code in target:
                if available_slots <= 0:
                    break
                if code in holdings_after_sells:
                    continue
                if bool_get(can_buy, date, code, False):
                    bought.add(code)
                    available_slots -= 1
                else:
                    buy_failed.add(code)

            rebalance_rows.append(
                {
                    "strategy": strategy,
                    "exec_date": date,
                    "signal_date": plan["signal_date"],
                    "target_count": len(target),
                    "candidate_count": plan["candidate_count"],
                    "guard_pass_count": plan.get("guard_pass_count", np.nan),
                    "guard_fail_count": plan.get("guard_fail_count", np.nan),
                    "pre_holdings": len(holdings),
                    "sold": len(sold),
                    "sell_failed": len(sell_failed),
                    "bought": len(bought),
                    "buy_failed": len(buy_failed),
                    "post_holdings": len(holdings_after_sells | bought),
                    "cash_slots": MAX_NAMES - len(holdings_after_sells | bought),
                    "median_amount_20d": plan["median_amount_20d"],
                    "median_float_market_cap": plan["median_float_market_cap"],
                }
            )
        else:
            holdings_after_sells = set(holdings)

        entry_sum = 0.0
        sell_open_sum = 0.0
        normal_holding_sum = 0.0
        sell_failed_holding_sum = 0.0
        suspended_holding_sum = 0.0
        ret_events = 0
        suspended_positions = 0

        for code in sold:
            sell_open_sum += float_get(sell_open_ret, date, code, 0.0)
            ret_events += 1
            suspended_codes.discard(code)

        post_holdings = holdings_after_sells | bought
        for code in sorted(post_holdings):
            if code in bought:
                entry_sum += float_get(entry_ret, date, code, 0.0)
                ret_events += 1
                suspended_codes.discard(code)
            elif bool_get(has_bar, date, code, False):
                value = float_get(holding_ret, date, code, 0.0)
                if code in suspended_codes:
                    suspended_holding_sum += value
                    suspended_codes.discard(code)
                elif code in forced_hold_codes:
                    sell_failed_holding_sum += value
                else:
                    normal_holding_sum += value
                ret_events += 1
            else:
                suspended_positions += 1
                suspended_codes.add(code)

        entry_pnl = entry_sum / MAX_NAMES
        sell_open_pnl = sell_open_sum / MAX_NAMES
        normal_holding_pnl = normal_holding_sum / MAX_NAMES
        sell_failed_holding_pnl = sell_failed_holding_sum / MAX_NAMES
        suspended_holding_pnl = suspended_holding_sum / MAX_NAMES
        turnover_rate = (len(bought) + len(sold)) / MAX_NAMES
        portfolio_return = (
            entry_pnl
            + sell_open_pnl
            + normal_holding_pnl
            + sell_failed_holding_pnl
            + suspended_holding_pnl
        )
        holdings = post_holdings
        forced_hold_codes.intersection_update(holdings)
        suspended_codes.intersection_update(holdings)
        daily_rows.append(
            {
                "date": date,
                "strategy": strategy,
                "daily_return": portfolio_return,
                "entry_pnl": entry_pnl,
                "sell_open_pnl": sell_open_pnl,
                "normal_holding_pnl": normal_holding_pnl,
                "sell_failed_holding_pnl": sell_failed_holding_pnl,
                "suspended_holding_pnl": suspended_holding_pnl,
                "turnover_rate": turnover_rate,
                "holdings": len(holdings),
                "cash_slots": MAX_NAMES - len(holdings),
                "return_events": ret_events,
                "suspended_positions": suspended_positions,
                "is_rebalance": plan is not None,
                "bought": len(bought),
                "buy_failed": len(buy_failed),
                "sold": len(sold),
                "sell_failed": len(sell_failed),
            }
        )

    return pd.DataFrame(daily_rows), pd.DataFrame(rebalance_rows)


def add_deltas(summary: pd.DataFrame) -> pd.DataFrame:
    frame = summary.copy()
    base = frame[frame["strategy"].eq(BASELINE_STRATEGY)].iloc[0]
    for col in [
        "ann_return",
        "cost_30bps_ann_return",
        "max_drawdown",
        "max_drawdown_ex_2008",
        "worst_12m_ex_2008",
        "2016_2018_ann_return",
        "2016_2018_max_drawdown",
        "sell_fail_rate",
        "forced_state_pnl",
        "suspended_position_days",
    ]:
        frame[f"delta_{col}"] = frame[col] - base[col]
    frame["mdd_improvement"] = frame["max_drawdown"] - base["max_drawdown"]
    frame["mdd_ex2008_improvement"] = frame["max_drawdown_ex_2008"] - base["max_drawdown_ex_2008"]
    frame["sell_fail_reduction"] = base["sell_fail_rate"] - frame["sell_fail_rate"]
    frame["forced_pnl_improvement"] = frame["forced_state_pnl"] - base["forced_state_pnl"]
    return frame


def make_figures(paths: Paths, daily: pd.DataFrame, summary: pd.DataFrame, removal: pd.DataFrame) -> dict[str, str]:
    figures: dict[str, str] = {}
    focus = summary[
        summary["strategy"].isin(
            [
                BASELINE_STRATEGY,
                "amount20_ge_50m",
                "amount20_to_60_ge_070",
                "no_bar20_eq0",
                "guard_loose_v1",
                "guard_balanced_v1",
                "guard_strict_v1",
            ]
        )
    ].copy()
    nav_parts: list[pd.Series] = []
    dd_parts: list[pd.Series] = []
    for strategy in focus["strategy"].tolist():
        group = daily[daily["strategy"].eq(strategy)]
        if group.empty:
            continue
        label = str(group["label"].iloc[0])
        series = group.set_index("date")["daily_return"].fillna(0.0)
        nav_parts.append(normalized_nav(series).rename(label))
        dd_parts.append(drawdown_series(series).rename(label))
    nav = pd.concat(nav_parts, axis=1) if nav_parts else pd.DataFrame()
    dd = pd.concat(dd_parts, axis=1) if dd_parts else pd.DataFrame()

    path = paths.figures_root / "execution_liquidity_guard_v1_nav.png"
    draw_multi_line_chart(nav, path, "Execution/Liquidity Guard v1 NAV", "Stateful baseline vs hard guards")
    figures["nav"] = str(path.relative_to(paths.output_root))

    path = paths.figures_root / "execution_liquidity_guard_v1_drawdown.png"
    draw_multi_line_chart(dd, path, "Execution/Liquidity Guard v1 Drawdown", "Drawdown from running peak")
    figures["drawdown"] = str(path.relative_to(paths.output_root))

    ordered = summary[~summary["strategy"].eq(BASELINE_STRATEGY)].copy()
    ordered = ordered.sort_values(["family", "strategy"])
    labels = ordered["label"].tolist()

    path = paths.figures_root / "guard_v1_ann_return.png"
    draw_bar_chart(labels, ordered["ann_return"].tolist(), path, "Annualized Return", "stateful")
    figures["ann_return"] = str(path.relative_to(paths.output_root))

    path = paths.figures_root / "guard_v1_max_drawdown.png"
    draw_bar_chart(labels, ordered["max_drawdown"].tolist(), path, "Max Drawdown", "stateful")
    figures["max_drawdown"] = str(path.relative_to(paths.output_root))

    path = paths.figures_root / "guard_v1_2016_2018_mdd.png"
    draw_bar_chart(labels, ordered["2016_2018_max_drawdown"].tolist(), path, "2016-2018 Max Drawdown", "stateful")
    figures["mdd_2016_2018"] = str(path.relative_to(paths.output_root))

    path = paths.figures_root / "guard_v1_sell_fail_rate.png"
    draw_bar_chart(labels, ordered["sell_fail_rate"].tolist(), path, "Sell Fail Rate", "failed sells / sell attempts")
    figures["sell_fail_rate"] = str(path.relative_to(paths.output_root))

    path = paths.figures_root / "guard_v1_forced_state_pnl.png"
    draw_bar_chart(labels, ordered["forced_state_pnl"].tolist(), path, "Forced-state PnL", "sell-failed + suspended")
    figures["forced_state_pnl"] = str(path.relative_to(paths.output_root))

    removal_ordered = removal[~removal["strategy"].eq(BASELINE_STRATEGY)].copy()
    removal_ordered = removal_ordered.set_index("strategy").reindex(ordered["strategy"]).reset_index()
    path = paths.figures_root / "guard_v1_removed_pct.png"
    draw_bar_chart(
        labels,
        removal_ordered["avg_removed_names_pct"].tolist(),
        path,
        "Baseline Target Removed by Guard",
        "average removed names / 100",
    )
    figures["removed_pct"] = str(path.relative_to(paths.output_root))

    path = paths.figures_root / "guard_v1_removed_minus_kept.png"
    draw_bar_chart(
        labels,
        removal_ordered["removed_minus_kept_ann"].tolist(),
        path,
        "Removed Basket Ann Return minus Kept Basket",
        "monthly theoretical hold diagnostic",
    )
    figures["removed_minus_kept"] = str(path.relative_to(paths.output_root))
    return figures


def format_summary(frame: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "rule": frame["label"],
            "family": frame["family"],
            "ann": frame["ann_return"].map(pct),
            "30bps_ann": frame["cost_30bps_ann_return"].map(pct),
            "mdd": frame["max_drawdown"].map(pct),
            "ex08_mdd": frame["max_drawdown_ex_2008"].map(pct),
            "2016_18_ann": frame["2016_2018_ann_return"].map(pct),
            "2016_18_mdd": frame["2016_2018_max_drawdown"].map(pct),
            "sell_fail": frame["sell_fail_rate"].map(pct),
            "forced_pnl": frame["forced_state_pnl"].map(num),
            "median_hold": frame["median_holdings"].map(num),
            "median_amt20": frame["median_amount_20d"].map(num),
        }
    )


def format_removal(frame: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "rule": frame["label"],
            "removed_pct": frame["avg_removed_names_pct"].map(pct),
            "removed_ann": frame["removed_basket_ann_return"].map(pct),
            "kept_ann": frame["kept_basket_ann_return"].map(pct),
            "removed-kept": frame["removed_minus_kept_ann"].map(pct),
            "removed_mdd": frame["removed_basket_max_drawdown"].map(pct),
            "kept_mdd": frame["kept_basket_max_drawdown"].map(pct),
        }
    )


def format_periods(frame: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "rule": frame["label"],
            "period": frame["period"],
            "ann": frame["ann_return"].map(pct),
            "cum_ret": frame["cumulative_return"].map(pct),
            "mdd": frame["max_drawdown"].map(pct),
            "worst12m": frame["worst_12m"].map(pct),
        }
    )


def render_report(
    summary: pd.DataFrame,
    removal: pd.DataFrame,
    periods: pd.DataFrame,
    figures: dict[str, str],
) -> str:
    base = summary[summary["strategy"].eq(BASELINE_STRATEGY)].iloc[0]
    non_base = summary[~summary["strategy"].eq(BASELINE_STRATEGY)].copy()
    risk_first = non_base.sort_values(
        ["mdd_ex2008_improvement", "sell_fail_reduction", "delta_2016_2018_max_drawdown"],
        ascending=False,
    ).head(6)
    composite = summary[summary["family"].eq("composite")].copy()
    removal_focus = removal[~removal["strategy"].eq(BASELINE_STRATEGY)].copy()
    removal_focus = removal_focus.sort_values("avg_removed_names_pct", ascending=False)
    period_focus = periods[periods["strategy"].isin([BASELINE_STRATEGY, "guard_loose_v1", "guard_balanced_v1", "guard_strict_v1"])]

    lines: list[str] = [
        "# A股小盘 Execution / Liquidity Guard v1",
        "",
        "本报告只测试硬规则，不把规则解释成 alpha。目标是看 baseline gross engine 在成交、状态、卖出失败约束后，还剩多少可用收益。",
        "",
        "## 研究问题",
        "",
        "- 被 veto 的 baseline 名单是否本身风险更差？",
        "- hard guard 是否降低 `sell fail`、`forced-state PnL`、`2016-2018` 回撤和 ex-2008 回撤？",
        "- 如果收益下降，下降是不是换来了足够明确的风险改善？",
        "",
        "## Baseline 参照",
        "",
        f"- 年化：`{pct(base['ann_return'])}`",
        f"- 30bps 年化：`{pct(base['cost_30bps_ann_return'])}`",
        f"- 最大回撤：`{pct(base['max_drawdown'])}`",
        f"- ex-2008 最大回撤：`{pct(base['max_drawdown_ex_2008'])}`",
        f"- 2016-2018 年化 / MDD：`{pct(base['2016_2018_ann_return'])}` / `{pct(base['2016_2018_max_drawdown'])}`",
        f"- 卖出失败率：`{pct(base['sell_fail_rate'])}`",
        f"- forced-state PnL：`{num(base['forced_state_pnl'])}`",
        "",
        "## 图表",
        "",
    ]
    for key, rel in figures.items():
        lines.append(f"- {key}: `{rel}`")
    lines.extend(
        [
            "",
            "## 单规则与组合规则总表",
            "",
            markdown_table(format_summary(summary), max_rows=None),
            "",
            "## 被删 baseline 名单诊断",
            "",
            "这里看的是每月 baseline top100 中被规则删掉的股票，随后一个持有月至下次调仓的理论日均篮子表现。它不是部署回测，只用于判断 veto 有没有删到明显更脏的篮子。",
            "",
            markdown_table(format_removal(removal_focus), max_rows=None),
            "",
            "## 风险优先排序",
            "",
            "排序口径优先看 ex-2008 MDD 改善、卖出失败率下降、2016-2018 MDD 改善，不优先看年化提高。",
            "",
            markdown_table(format_summary(risk_first), max_rows=None),
            "",
            "## Composite Guard 阶段表现",
            "",
            markdown_table(format_summary(composite), max_rows=None),
            "",
            "## 关键阶段复核",
            "",
            markdown_table(format_periods(period_focus), max_rows=None),
            "",
            "## 初步解释",
            "",
            "1. 这一步不是为了找更高年化，而是为了确认哪些硬规则真的在减少 forced-state 风险。",
            "2. 如果单一流动性门槛显著降低 sell fail / 2016-2018 MDD，但大幅牺牲年化，它更适合做部署底线，不适合作为 alpha 排序。",
            "3. 如果 no-bar / limit-down 类状态规则收益损伤小、风险改善明确，它们优先级高于财务类 hard negative screen。",
            "4. 如果 strict composite 把回撤改善做出来但把 median holdings 或 gross return 打穿，下一步应该退回 loose/balanced，而不是继续加规则。",
            "",
            "## 输出文件",
            "",
            "- `tables/guard_summary.csv`",
            "- `tables/guard_removal_diagnostic.csv`",
            "- `tables/guard_period_summary.csv`",
            "- `tables/guard_daily_returns.csv`",
            "- `tables/guard_rebalance_audit.csv`",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run execution/liquidity hard guard v1.")
    parser.add_argument("--processed-root", default="processed")
    parser.add_argument("--output-root", default="outputs/execution_liquidity_guard_v1")
    args = parser.parse_args()

    paths = Paths(
        data_root=(PROJECT_ROOT / "data").resolve(),
        processed_root=(PROJECT_ROOT / args.processed_root).resolve(),
        output_root=(PROJECT_ROOT / args.output_root).resolve(),
        figures_root=(PROJECT_ROOT / args.output_root / "figures").resolve(),
        tables_root=(PROJECT_ROOT / args.output_root / "tables").resolve(),
    )
    paths.output_root.mkdir(parents=True, exist_ok=True)
    paths.figures_root.mkdir(parents=True, exist_ok=True)
    paths.tables_root.mkdir(parents=True, exist_ok=True)

    log("load pre-research panel")
    panel, _ = load_pre_research_panel(paths)
    panel = enrich_guard_features(panel, paths)
    log("cache monthly baseline candidate pools")
    monthly_candidates = build_monthly_candidates(panel)
    specs = build_guard_specs()

    log("load state execution data")
    returns, status = load_state_data(paths)
    log("build reusable execution maps")
    maps = build_execution_maps(returns, status)
    del returns, status
    calendar = pd.read_csv(paths.processed_root / "market_calendar.csv", dtype=str)
    dates = calendar[(calendar["trade_date"] >= WARMUP_START) & (calendar["trade_date"] <= RESEARCH_END)][
        "trade_date"
    ].tolist()

    log("run target removal diagnostic")
    removal = target_removal_diagnostic(panel, monthly_candidates, specs)

    log("run guarded stateful simulations")
    daily, rebalance, summary = run_all_guards(monthly_candidates, specs, dates, maps)
    summary = add_deltas(summary)
    periods = summarize_periods(daily)

    figures = make_figures(paths, daily, summary, removal)
    report = render_report(summary, removal, periods, figures)

    log("write outputs")
    summary.to_csv(paths.tables_root / "guard_summary.csv", index=False, encoding="utf-8")
    removal.to_csv(paths.tables_root / "guard_removal_diagnostic.csv", index=False, encoding="utf-8")
    periods.to_csv(paths.tables_root / "guard_period_summary.csv", index=False, encoding="utf-8")
    daily.to_csv(paths.tables_root / "guard_daily_returns.csv", index=False, encoding="utf-8")
    rebalance.to_csv(paths.tables_root / "guard_rebalance_audit.csv", index=False, encoding="utf-8")
    report_path = paths.output_root / "execution_liquidity_guard_v1_zh.md"
    report_path.write_text(report, encoding="utf-8")
    log(f"wrote {report_path}")


if __name__ == "__main__":
    main()
