from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

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
    draw_bar_chart,
    draw_multi_line_chart,
    load_yearly_csv,
    log,
    markdown_table,
    num,
    parse_bool_series,
    pct,
    safe_annualized_return,
)
from run_pre_research_v2_stateful_portfolio import (  # noqa: E402
    MAX_NAMES,
    bool_get,
    cumulative_return,
    load_state_data,
    make_series_map,
    max_drawdown,
    simulate_stateful_portfolio,
    worst_rolling_return,
)
from run_rpe_stateful_portfolio_v1 import (  # noqa: E402
    SIZE_CONTROL_BINS,
    STRATEGY_LABELS,
    build_rebalance_plans,
    load_monthly_selection_frame,
)


MAIN_STRATEGIES = [
    "baseline_size_10_50_top100",
    "rpe_top100",
    "size_controlled_rpe_top100",
]
RPE_STRATEGIES = ["rpe_top100", "size_controlled_rpe_top100"]
FAILURE_OUTPUT_ROOT = "outputs/rpe_failure_anatomy_v1"
SIZE_SELECTORS = ["smallest", "rpe_high", "rpe_low"]
FINANCE_COLS = [
    "code",
    "report_year",
    "effective_trade_date",
    "total_operating_revenue",
    "operating_revenue",
    "net_profit_parent",
    "net_profit",
    "operating_cash_flow_direct",
    "operating_cash_flow_indirect",
    "asset_liability_ratio_vendor",
    "roe_parent_ttm_vendor",
    "roe_ttm_vendor",
    "goodwill",
    "parent_equity",
    "total_equity",
]


def year_from_date(series: pd.Series) -> pd.Series:
    return series.astype(str).str.slice(0, 4)


def strategy_daily_returns(paths: Paths) -> pd.DataFrame:
    file = paths.output_root.parent / "rpe_stateful_portfolio_v1" / "tables" / "rpe_stateful_daily_returns.csv"
    if not file.exists():
        raise FileNotFoundError(f"Missing RPE stateful output: {file}")
    daily = pd.read_csv(file, dtype={"date": str, "strategy": str})
    daily["daily_return"] = pd.to_numeric(daily["daily_return"], errors="coerce")
    return daily[daily["strategy"].isin(MAIN_STRATEGIES)].copy()


def strategy_rebalance_audit(paths: Paths) -> pd.DataFrame:
    file = paths.output_root.parent / "rpe_stateful_portfolio_v1" / "tables" / "rpe_stateful_rebalance_audit.csv"
    if not file.exists():
        raise FileNotFoundError(f"Missing RPE stateful rebalance audit: {file}")
    rebalance = pd.read_csv(file, dtype={"exec_date": str, "signal_date": str, "strategy": str, "code": str})
    return rebalance[rebalance["strategy"].isin(MAIN_STRATEGIES)].copy()


def annual_return_tables(daily: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = daily.copy()
    frame["year"] = year_from_date(frame["date"])
    rows = []
    for (strategy, year), group in frame.groupby(["strategy", "year"], sort=True):
        returns = group.set_index("date")["daily_return"].sort_index()
        rows.append(
            {
                "strategy": strategy,
                "year": year,
                "ann_return": safe_annualized_return(returns),
                "cumulative_return": cumulative_return(returns),
                "max_drawdown": max_drawdown(returns),
                "worst_12m": worst_rolling_return(returns),
                "observations": int(returns.notna().sum()),
            }
        )
    annual = pd.DataFrame(rows)
    base = annual[annual["strategy"].eq("baseline_size_10_50_top100")][["year", "ann_return"]].rename(
        columns={"ann_return": "baseline_ann_return"}
    )
    excess = annual.merge(base, on="year", how="left")
    excess["excess_vs_baseline"] = excess["ann_return"] - excess["baseline_ann_return"]
    excess = excess[excess["strategy"].isin(RPE_STRATEGIES)].copy()
    return annual, excess


def build_size_bucket_plans(monthly: pd.DataFrame, bucket: tuple[str, float, float], selector: str) -> dict[str, dict[str, Any]]:
    label, lower, upper = bucket
    plans: dict[str, dict[str, Any]] = {}
    for signal_date, date_frame in monthly.groupby("feature_date", sort=True):
        exec_dates = date_frame["exec_date"].dropna().unique().tolist()
        if not exec_dates:
            continue
        exec_date = sorted(exec_dates)[0]
        if exec_date > RESEARCH_END:
            continue
        candidates = date_frame[
            date_frame["base_universe"] & date_frame["size_pct"].gt(lower) & date_frame["size_pct"].le(upper)
        ].copy()
        if selector == "smallest":
            selected = candidates.nsmallest(MAX_NAMES, "float_market_cap")
        else:
            valid = candidates[candidates["valid_rpe_flag"] & candidates["rpe_score"].notna()].copy()
            selected = valid.nlargest(MAX_NAMES, "rpe_score") if selector == "rpe_high" else valid.nsmallest(MAX_NAMES, "rpe_score")
        plans[exec_date] = {
            "signal_date": signal_date,
            "exec_date": exec_date,
            "target": selected["code"].tolist(),
            "candidate_count": int(len(candidates)),
            "target_count": int(len(selected)),
            "median_rpe_score": float(selected["rpe_score"].median()) if not selected.empty else np.nan,
            "median_amount_20d": float(selected["amount_20d_mean"].median()) if not selected.empty else np.nan,
            "median_float_market_cap": float(selected["float_market_cap"].median()) if not selected.empty else np.nan,
        }
    return plans


def summarize_stateful(strategy: str, daily: pd.DataFrame, rebalance: pd.DataFrame) -> dict[str, Any]:
    returns = daily.set_index("date")["daily_return"].sort_index() if not daily.empty else pd.Series(dtype=float)
    buy_attempts = float(rebalance["bought"].sum() + rebalance["buy_failed"].sum()) if not rebalance.empty else np.nan
    sell_attempts = float(rebalance["sold"].sum() + rebalance["sell_failed"].sum()) if not rebalance.empty else np.nan
    return {
        "strategy": strategy,
        "ann_return": safe_annualized_return(returns),
        "cumulative_return": cumulative_return(returns),
        "max_drawdown": max_drawdown(returns),
        "worst_12m": worst_rolling_return(returns),
        "buy_fail_rate": float(rebalance["buy_failed"].sum() / buy_attempts) if buy_attempts else np.nan,
        "sell_fail_rate": float(rebalance["sell_failed"].sum() / sell_attempts) if sell_attempts else np.nan,
        "suspended_position_days": int(daily["suspended_positions"].sum()) if not daily.empty else 0,
        "median_target_count": float(rebalance["target_count"].median()) if "target_count" in rebalance else np.nan,
        "median_amount_20d": float(rebalance["median_amount_20d"].median()) if "median_amount_20d" in rebalance else np.nan,
        "median_float_market_cap": float(rebalance["median_float_market_cap"].median())
        if "median_float_market_cap" in rebalance
        else np.nan,
    }


def run_size_bucket_anatomy(
    monthly: pd.DataFrame,
    dates: list[str],
    returns: pd.DataFrame,
    status: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    summary_rows = []
    annual_rows = []
    for bucket in SIZE_CONTROL_BINS:
        bucket_label = bucket[0]
        for selector in SIZE_SELECTORS:
            strategy = f"{bucket_label}_{selector}"
            log(f"simulate size-bucket anatomy {strategy}")
            plans = build_size_bucket_plans(monthly, bucket, selector)
            _, daily, rebalance = simulate_stateful_portfolio(dates, plans, returns, status, strategy)
            summary = summarize_stateful(strategy, daily, rebalance)
            summary.update({"size_bucket": bucket_label, "selector": selector})
            summary_rows.append(summary)
            daily["year"] = year_from_date(daily["date"])
            for year, group in daily.groupby("year", sort=True):
                series = group.set_index("date")["daily_return"].sort_index()
                annual_rows.append(
                    {
                        "size_bucket": bucket_label,
                        "selector": selector,
                        "strategy": strategy,
                        "year": year,
                        "ann_return": safe_annualized_return(series),
                        "max_drawdown": max_drawdown(series),
                    }
                )
    summary = pd.DataFrame(summary_rows)
    annual = pd.DataFrame(annual_rows)
    high = summary[summary["selector"].eq("rpe_high")][["size_bucket", "ann_return"]].rename(
        columns={"ann_return": "rpe_high_ann_return"}
    )
    low = summary[summary["selector"].eq("rpe_low")][["size_bucket", "ann_return"]].rename(
        columns={"ann_return": "rpe_low_ann_return"}
    )
    smallest = summary[summary["selector"].eq("smallest")][["size_bucket", "ann_return"]].rename(
        columns={"ann_return": "smallest_ann_return"}
    )
    spread = high.merge(low, on="size_bucket", how="outer").merge(smallest, on="size_bucket", how="outer")
    spread["rpe_high_minus_low"] = spread["rpe_high_ann_return"] - spread["rpe_low_ann_return"]
    spread["rpe_high_minus_smallest"] = spread["rpe_high_ann_return"] - spread["smallest_ann_return"]
    summary = summary.merge(spread, on="size_bucket", how="left")
    return summary, annual


def collect_target_rows(plans_by_strategy: dict[str, dict[str, dict[str, Any]]]) -> pd.DataFrame:
    rows = []
    for strategy, plans in plans_by_strategy.items():
        for exec_date, plan in plans.items():
            for rank, code in enumerate(plan["target"], 1):
                rows.append(
                    {
                        "strategy": strategy,
                        "signal_date": plan["signal_date"],
                        "exec_date": exec_date,
                        "code": code,
                        "target_rank": rank,
                    }
                )
    return pd.DataFrame(rows)


def collect_sell_fail_events(
    dates: list[str],
    plans_by_strategy: dict[str, dict[str, dict[str, Any]]],
    status: pd.DataFrame,
) -> pd.DataFrame:
    has_bar = make_series_map(status, "has_bar")
    can_buy = make_series_map(status, "can_buy_on_bar")
    can_sell = make_series_map(status, "can_sell_on_bar")
    rows = []
    for strategy, plans in plans_by_strategy.items():
        holdings: set[str] = set()
        for date in dates:
            if date < RESEARCH_START or date > RESEARCH_END:
                continue
            plan = plans.get(date)
            if plan is None:
                continue
            target = list(plan["target"])
            target_set = set(target)
            sold: set[str] = set()
            sell_failed: set[str] = set()
            for code in sorted(holdings - target_set):
                if bool_get(can_sell, date, code, False):
                    sold.add(code)
                else:
                    sell_failed.add(code)
                    rows.append(
                        {
                            "strategy": strategy,
                            "exec_date": date,
                            "signal_date": plan["signal_date"],
                            "code": code,
                            "has_bar_on_exec": bool_get(has_bar, date, code, False),
                            "can_sell_on_exec": bool_get(can_sell, date, code, False),
                        }
                    )
            holdings_after_sells = set(holdings - sold)
            available_slots = max(MAX_NAMES - len(holdings_after_sells), 0)
            bought: set[str] = set()
            for code in target:
                if available_slots <= 0:
                    break
                if code in holdings_after_sells:
                    continue
                if bool_get(can_buy, date, code, False):
                    bought.add(code)
                    available_slots -= 1
            holdings = holdings_after_sells | bought
    return pd.DataFrame(rows)


def load_event_market_features(paths: Paths) -> pd.DataFrame:
    cols = [
        "trade_date",
        "code",
        "amount_yuan",
        "turnover",
        "pct_chg",
        "return_10d",
        "return_25d",
        "is_limit_down_est",
        "one_price_limit_est",
    ]
    market = load_yearly_csv(
        paths.processed_root / "market_daily_raw",
        "market_daily_raw_{year}.csv.gz",
        [str(year) for year in range(2004, 2026)],
        cols,
        dtype={"trade_date": str, "code": str},
    )
    for col in ["amount_yuan", "turnover", "pct_chg", "return_10d", "return_25d"]:
        market[col] = pd.to_numeric(market[col], errors="coerce")
    for col in ["pct_chg", "return_10d", "return_25d"]:
        market[col] = market[col] / 100.0
    for col in ["is_limit_down_est", "one_price_limit_est"]:
        market[col] = parse_bool_series(market[col]).astype(float)
    market = market.sort_values(["code", "trade_date"])
    grouped = market.groupby("code", sort=False)
    market["amount_20d_mean"] = grouped["amount_yuan"].rolling(20, min_periods=10).mean().reset_index(level=0, drop=True)
    market["amount_60d_mean"] = grouped["amount_yuan"].rolling(60, min_periods=20).mean().reset_index(level=0, drop=True)
    market["amount_20d_vs_60d"] = market["amount_20d_mean"] / market["amount_60d_mean"] - 1.0
    market["limit_down_20d"] = grouped["is_limit_down_est"].rolling(20, min_periods=1).sum().reset_index(level=0, drop=True)
    market["one_price_limit_20d"] = grouped["one_price_limit_est"].rolling(20, min_periods=1).sum().reset_index(level=0, drop=True)
    return market


def merge_asof_by_code(
    left: pd.DataFrame,
    right: pd.DataFrame,
    left_date_col: str,
    right_date_col: str,
    suffix: str = "",
) -> pd.DataFrame:
    if left.empty:
        return left.copy()
    pieces = []
    right_groups = {code: group.sort_values(right_date_col) for code, group in right.groupby("code", sort=False)}
    for code, group in left.groupby("code", sort=False):
        right_group = right_groups.get(code)
        if right_group is None:
            out = group.copy()
            for col in right.columns:
                if col not in out.columns and col not in {"code", right_date_col}:
                    out[col + suffix] = np.nan
            pieces.append(out)
            continue
        out = pd.merge_asof(
            group.sort_values(left_date_col),
            right_group,
            left_on=left_date_col,
            right_on=right_date_col,
            by="code",
            direction="backward",
            suffixes=("", suffix),
        )
        pieces.append(out)
    return pd.concat(pieces, ignore_index=True)


def attach_sell_fail_features(paths: Paths, events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return events
    log("load market features for sell-fail events")
    market = load_event_market_features(paths)
    left = events.copy()
    left["exec_dt"] = pd.to_datetime(left["exec_date"], errors="coerce")
    market = market.rename(columns={"trade_date": "last_bar_date"})
    market["last_bar_dt"] = pd.to_datetime(market["last_bar_date"], errors="coerce")
    out = merge_asof_by_code(left, market, "exec_dt", "last_bar_dt")
    out["days_since_last_bar"] = (out["exec_dt"] - out["last_bar_dt"]).dt.days
    out["year"] = year_from_date(out["exec_date"])
    return out


def summarize_sell_fail(events: pd.DataFrame, rebalance: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if events.empty:
        return pd.DataFrame(), pd.DataFrame()
    attempts = rebalance.copy()
    attempts["year"] = year_from_date(attempts["exec_date"])
    attempts_by_year = (
        attempts.groupby(["strategy", "year"], sort=True)
        .agg(sell_attempts=("sold", "sum"), sell_failed=("sell_failed", "sum"))
        .reset_index()
    )
    attempts_by_year["sell_attempts"] = attempts_by_year["sell_attempts"] + attempts_by_year["sell_failed"]
    attempts_by_year["sell_fail_rate"] = attempts_by_year["sell_failed"] / attempts_by_year["sell_attempts"].replace(0, np.nan)

    by_year = (
        events.groupby(["strategy", "year"], sort=True)
        .agg(
            sell_fail_events=("code", "size"),
            unique_codes=("code", "nunique"),
            no_bar_rate=("has_bar_on_exec", lambda s: float((~s.astype(bool)).mean())),
            median_amount_20d=("amount_20d_mean", "median"),
            median_amount_20d_vs_60d=("amount_20d_vs_60d", "median"),
            median_return_10d=("return_10d", "median"),
            median_return_25d=("return_25d", "median"),
            mean_limit_down_20d=("limit_down_20d", "mean"),
            mean_one_price_limit_20d=("one_price_limit_20d", "mean"),
            median_days_since_last_bar=("days_since_last_bar", "median"),
        )
        .reset_index()
        .merge(attempts_by_year[["strategy", "year", "sell_attempts", "sell_fail_rate"]], on=["strategy", "year"], how="left")
    )
    by_strategy = (
        events.groupby("strategy", sort=True)
        .agg(
            sell_fail_events=("code", "size"),
            unique_codes=("code", "nunique"),
            no_bar_rate=("has_bar_on_exec", lambda s: float((~s.astype(bool)).mean())),
            median_amount_20d=("amount_20d_mean", "median"),
            median_amount_20d_vs_60d=("amount_20d_vs_60d", "median"),
            median_return_10d=("return_10d", "median"),
            median_return_25d=("return_25d", "median"),
            mean_limit_down_20d=("limit_down_20d", "mean"),
            mean_one_price_limit_20d=("one_price_limit_20d", "mean"),
            median_days_since_last_bar=("days_since_last_bar", "median"),
        )
        .reset_index()
    )
    attempts_total = (
        attempts.groupby("strategy", sort=True)
        .agg(sell_attempts=("sold", "sum"), sell_failed=("sell_failed", "sum"))
        .reset_index()
    )
    attempts_total["sell_attempts"] = attempts_total["sell_attempts"] + attempts_total["sell_failed"]
    attempts_total["sell_fail_rate"] = attempts_total["sell_failed"] / attempts_total["sell_attempts"].replace(0, np.nan)
    by_strategy = by_strategy.merge(attempts_total[["strategy", "sell_attempts", "sell_fail_rate"]], on="strategy", how="left")
    return by_year, by_strategy


def load_finance() -> pd.DataFrame:
    finance = pd.read_csv(PROJECT_ROOT / "processed" / "annual_finance_pit.csv.gz", usecols=FINANCE_COLS, dtype={"code": str})
    for col in FINANCE_COLS:
        if col not in {"code", "effective_trade_date"}:
            finance[col] = pd.to_numeric(finance[col], errors="coerce")
    finance["revenue_base"] = finance["operating_revenue"]
    finance.loc[finance["revenue_base"].isna(), "revenue_base"] = finance.loc[
        finance["revenue_base"].isna(), "total_operating_revenue"
    ]
    finance["profit_base"] = finance["net_profit_parent"]
    finance.loc[finance["profit_base"].isna(), "profit_base"] = finance.loc[finance["profit_base"].isna(), "net_profit"]
    finance["cash_flow_base"] = finance["operating_cash_flow_direct"]
    finance.loc[finance["cash_flow_base"].isna(), "cash_flow_base"] = finance.loc[
        finance["cash_flow_base"].isna(), "operating_cash_flow_indirect"
    ]
    finance["equity_base"] = finance["parent_equity"]
    finance.loc[finance["equity_base"].isna(), "equity_base"] = finance.loc[finance["equity_base"].isna(), "total_equity"]
    finance["effective_dt"] = pd.to_datetime(finance["effective_trade_date"], errors="coerce")
    return finance.sort_values(["code", "effective_dt", "report_year"])


def attach_future_fundamentals(targets: pd.DataFrame) -> pd.DataFrame:
    if targets.empty:
        return targets
    log("attach ex-post future annual fundamentals")
    finance = load_finance()
    current_cols = [
        "code",
        "effective_dt",
        "report_year",
        "profit_base",
        "revenue_base",
        "roe_parent_ttm_vendor",
        "roe_ttm_vendor",
        "cash_flow_base",
        "asset_liability_ratio_vendor",
        "goodwill",
        "equity_base",
    ]
    left = targets.copy()
    left["signal_dt"] = pd.to_datetime(left["signal_date"], errors="coerce")
    current = merge_asof_by_code(left, finance[current_cols], "signal_dt", "effective_dt", suffix="_current")
    current = current.rename(
        columns={
            "report_year": "current_report_year",
            "profit_base": "current_profit",
            "revenue_base": "current_revenue",
            "roe_parent_ttm_vendor": "current_roe_parent",
            "roe_ttm_vendor": "current_roe",
            "cash_flow_base": "current_cash_flow",
            "asset_liability_ratio_vendor": "current_debt_ratio",
            "goodwill": "current_goodwill",
            "equity_base": "current_equity",
        }
    )
    current["future_report_year"] = current["current_report_year"] + 1
    future = finance[
        [
            "code",
            "report_year",
            "profit_base",
            "revenue_base",
            "roe_parent_ttm_vendor",
            "roe_ttm_vendor",
            "cash_flow_base",
            "asset_liability_ratio_vendor",
            "goodwill",
            "equity_base",
        ]
    ].rename(
        columns={
            "report_year": "future_report_year",
            "profit_base": "future_profit",
            "revenue_base": "future_revenue",
            "roe_parent_ttm_vendor": "future_roe_parent",
            "roe_ttm_vendor": "future_roe",
            "cash_flow_base": "future_cash_flow",
            "asset_liability_ratio_vendor": "future_debt_ratio",
            "goodwill": "future_goodwill",
            "equity_base": "future_equity",
        }
    )
    out = current.merge(future, on=["code", "future_report_year"], how="left")
    out["future_profit_yoy"] = out["future_profit"] / out["current_profit"] - 1.0
    out.loc[out["current_profit"].le(0), "future_profit_yoy"] = np.nan
    out["future_revenue_yoy"] = out["future_revenue"] / out["current_revenue"] - 1.0
    out.loc[out["current_revenue"].le(0), "future_revenue_yoy"] = np.nan
    out["future_cfo_to_profit"] = out["future_cash_flow"] / out["future_profit"]
    out["future_goodwill_to_equity"] = out["future_goodwill"] / out["future_equity"]
    out["selection_year"] = year_from_date(out["signal_date"])
    return out


def summarize_future_fundamentals(fund: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if fund.empty:
        return pd.DataFrame(), pd.DataFrame()

    def agg(group: pd.DataFrame) -> pd.Series:
        covered = group["future_profit"].notna()
        return pd.Series(
            {
                "rows": len(group),
                "future_coverage": float(covered.mean()),
                "median_future_profit_yoy": group["future_profit_yoy"].median(),
                "median_future_revenue_yoy": group["future_revenue_yoy"].median(),
                "median_future_roe_parent": group["future_roe_parent"].median(),
                "median_future_cfo_to_profit": group["future_cfo_to_profit"].replace([np.inf, -np.inf], np.nan).median(),
                "median_future_debt_ratio": group["future_debt_ratio"].median(),
                "median_future_goodwill_to_equity": group["future_goodwill_to_equity"].replace([np.inf, -np.inf], np.nan).median(),
                "share_profit_down_30": float((group["future_profit_yoy"] <= -0.30).mean()),
                "share_future_profit_negative": float((group["future_profit"] <= 0).mean()),
                "share_revenue_negative": float((group["future_revenue_yoy"] < 0).mean()),
            }
        )

    by_strategy = fund.groupby("strategy", sort=True).apply(agg).reset_index()
    by_year = fund.groupby(["strategy", "selection_year"], sort=True).apply(agg).reset_index()
    return by_strategy, by_year


def regime_anatomy(annual_excess: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    file = PROJECT_ROOT / "outputs" / "pre_research_v1_fresh_entry_diagnostic" / "tables" / "size_bucket_returns_theoretical_daily.csv"
    buckets = pd.read_csv(file, dtype={"feature_date": str})
    buckets["year"] = year_from_date(buckets["feature_date"])
    rows = []
    for year, group in buckets.groupby("year", sort=True):
        small_10_50 = group[["p10_20", "p20_30", "p30_50"]].mean(axis=1)
        small_10_20 = group["p10_20"]
        large = group["p50_100"]
        market = group[["p00_05", "p05_10", "p10_20", "p20_30", "p30_50", "p50_100"]].mean(axis=1)
        rows.append(
            {
                "year": year,
                "small_10_50_ann_return": safe_annualized_return(small_10_50),
                "small_10_20_ann_return": safe_annualized_return(small_10_20),
                "large_50_100_ann_return": safe_annualized_return(large),
                "market_bucket_avg_ann_return": safe_annualized_return(market),
                "small_minus_large_ann_spread": safe_annualized_return(small_10_20 - large),
            }
        )
    regime = pd.DataFrame(rows)
    regime["small_trend"] = np.where(regime["small_10_50_ann_return"] > 0, "small_up", "small_down")
    regime["risk_appetite"] = np.where(regime["small_minus_large_ann_spread"] > 0, "small_beats_large", "small_lags_large")
    regime["market_strength"] = np.where(regime["market_bucket_avg_ann_return"] > 0.15, "market_strong", "market_weak")
    joined = annual_excess[["strategy", "year", "excess_vs_baseline"]].merge(regime, on="year", how="left")
    summary = (
        joined.groupby(["strategy", "small_trend", "risk_appetite", "market_strength"], sort=True)
        .agg(mean_excess_vs_baseline=("excess_vs_baseline", "mean"), years=("year", "count"))
        .reset_index()
    )
    return joined, summary


def make_figures(
    paths: Paths,
    annual_excess: pd.DataFrame,
    size_summary: pd.DataFrame,
    sell_fail_by_year: pd.DataFrame,
    future_by_strategy: pd.DataFrame,
    regime_by_year: pd.DataFrame,
) -> dict[str, str]:
    figures: dict[str, str] = {}
    pivot = annual_excess.pivot(index="year", columns="strategy", values="excess_vs_baseline")
    path = paths.figures_root / "annual_excess_vs_baseline.png"
    draw_multi_line_chart(pivot, path, "Annual Excess vs Baseline", "RPE strategy annual return minus baseline")
    figures["annual_excess"] = str(path.relative_to(paths.output_root))

    spread = size_summary.drop_duplicates("size_bucket").sort_values("size_bucket")
    path = paths.figures_root / "size_bucket_rpe_high_minus_low.png"
    draw_bar_chart(
        spread["size_bucket"].tolist(),
        spread["rpe_high_minus_low"].tolist(),
        path,
        "RPE High Minus Low by Size Bucket",
        "Stateful annualized return spread",
    )
    figures["size_bucket_high_low"] = str(path.relative_to(paths.output_root))

    path = paths.figures_root / "size_bucket_rpe_high_minus_smallest.png"
    draw_bar_chart(
        spread["size_bucket"].tolist(),
        spread["rpe_high_minus_smallest"].tolist(),
        path,
        "RPE High Minus Smallest by Size Bucket",
        "Does RPE beat baseline-like smallest names inside each bucket?",
    )
    figures["size_bucket_high_smallest"] = str(path.relative_to(paths.output_root))

    sell_pivot = sell_fail_by_year.pivot(index="year", columns="strategy", values="sell_fail_rate") if not sell_fail_by_year.empty else pd.DataFrame()
    path = paths.figures_root / "sell_fail_rate_by_year.png"
    draw_multi_line_chart(sell_pivot, path, "Sell Failure Rate by Year", "Failed sells / sell attempts")
    figures["sell_fail_rate_by_year"] = str(path.relative_to(paths.output_root))

    path = paths.figures_root / "future_profit_yoy_by_strategy.png"
    draw_bar_chart(
        future_by_strategy["strategy"].tolist(),
        future_by_strategy["median_future_profit_yoy"].tolist(),
        path,
        "Future Profit YoY by Selected Basket",
        "Ex-post diagnostic, not tradable signal",
    )
    figures["future_profit_yoy"] = str(path.relative_to(paths.output_root))

    regime_pivot = regime_by_year.pivot(index="year", columns="strategy", values="excess_vs_baseline")
    path = paths.figures_root / "regime_annual_excess.png"
    draw_multi_line_chart(regime_pivot, path, "RPE Annual Excess with Market Regime", "Excess return by year")
    figures["regime_annual_excess"] = str(path.relative_to(paths.output_root))
    return figures


def fmt_percent_frame(frame: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = frame.copy()
    for col in cols:
        if col in out:
            out[col] = out[col].map(pct)
    return out


def render_report(
    annual_excess: pd.DataFrame,
    size_summary: pd.DataFrame,
    sell_fail_by_strategy: pd.DataFrame,
    future_by_strategy: pd.DataFrame,
    regime_summary: pd.DataFrame,
    figures: dict[str, str],
) -> str:
    focus_years = annual_excess.sort_values(["strategy", "excess_vs_baseline"]).groupby("strategy").head(5)
    best_years = annual_excess.sort_values(["strategy", "excess_vs_baseline"], ascending=[True, False]).groupby("strategy").head(5)
    size_view = size_summary[
        [
            "size_bucket",
            "selector",
            "ann_return",
            "max_drawdown",
            "sell_fail_rate",
            "median_amount_20d",
            "rpe_high_minus_low",
            "rpe_high_minus_smallest",
        ]
    ].copy()
    future_view = future_by_strategy.copy()
    lines = [
        "# A股小盘 RPE Failure Anatomy v1",
        "",
        "本报告只做失败归因，不改 RPE 公式，不改窗口，不把 top100 改成 top50/top150，也不引入 composite。",
        "",
        "## A. 年度归因",
        "",
        "RPE 相对 baseline 最差的年份：",
        "",
        markdown_table(fmt_percent_frame(focus_years, ["ann_return", "baseline_ann_return", "excess_vs_baseline"])),
        "",
        "RPE 相对 baseline 最好的年份：",
        "",
        markdown_table(fmt_percent_frame(best_years, ["ann_return", "baseline_ann_return", "excess_vs_baseline"])),
        "",
        "## B. Size 桶内归因",
        "",
        markdown_table(fmt_percent_frame(size_view, ["ann_return", "max_drawdown", "sell_fail_rate", "rpe_high_minus_low", "rpe_high_minus_smallest"])),
        "",
        "## C. 卖出失败归因",
        "",
        markdown_table(
            fmt_percent_frame(
                sell_fail_by_strategy,
                [
                    "sell_fail_rate",
                    "no_bar_rate",
                    "median_amount_20d_vs_60d",
                    "median_return_10d",
                    "median_return_25d",
                ],
            )
        ),
        "",
        "## D. 价值陷阱事后归因",
        "",
        "下面是未来一年财务表现的事后诊断，不是可交易信号。",
        "",
        markdown_table(
            fmt_percent_frame(
                future_view,
                [
                    "future_coverage",
                    "median_future_profit_yoy",
                    "median_future_revenue_yoy",
                    "median_future_roe_parent",
                    "median_future_cfo_to_profit",
                    "median_future_debt_ratio",
                    "median_future_goodwill_to_equity",
                    "share_profit_down_30",
                    "share_future_profit_negative",
                    "share_revenue_negative",
                ],
            )
        ),
        "",
        "## E. Regime 归因",
        "",
        markdown_table(fmt_percent_frame(regime_summary, ["mean_excess_vs_baseline"])),
        "",
        "## PNG 图",
        "",
    ]
    for key, rel in figures.items():
        lines.append(f"![{key}](figures/{Path(rel).name})")
        lines.append("")
    lines.extend(
        [
            "## 解读边界",
            "",
            "- 本报告只决定 RPE 失败机制，不决定新策略。",
            "- D 部分使用未来财务，只能解释价值陷阱，不能作为当时可见信号。",
            "- 如果 RPE 只在部分 size bucket 或部分 regime 有用，下一步应降级为 overlay / filter / observation，而不是晋升为 core alpha。",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run RPE failure anatomy v1.")
    parser.add_argument("--processed-root", default="processed")
    parser.add_argument("--output-root", default=FAILURE_OUTPUT_ROOT)
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

    log("A: annual return anatomy")
    daily = strategy_daily_returns(paths)
    annual_returns, annual_excess = annual_return_tables(daily)
    rebalance = strategy_rebalance_audit(paths)

    log("load monthly selection frame")
    monthly, _ = load_monthly_selection_frame(paths)
    log("load state data")
    returns, status = load_state_data(paths)
    calendar = pd.read_csv(paths.processed_root / "market_calendar.csv", dtype=str)
    dates = calendar[(calendar["trade_date"] >= WARMUP_START) & (calendar["trade_date"] <= RESEARCH_END)][
        "trade_date"
    ].tolist()

    log("B: size bucket anatomy")
    size_summary, size_annual = run_size_bucket_anatomy(monthly, dates, returns, status)

    log("C: sell failure anatomy")
    plans_by_strategy = {strategy: build_rebalance_plans(monthly, strategy) for strategy in MAIN_STRATEGIES}
    sell_events = collect_sell_fail_events(dates, plans_by_strategy, status)
    sell_events = attach_sell_fail_features(paths, sell_events)
    sell_by_year, sell_by_strategy = summarize_sell_fail(sell_events, rebalance)

    log("D: future fundamental anatomy")
    targets = collect_target_rows(plans_by_strategy)
    future_fundamentals = attach_future_fundamentals(targets)
    future_by_strategy, future_by_year = summarize_future_fundamentals(future_fundamentals)

    log("E: regime anatomy")
    regime_by_year, regime_summary = regime_anatomy(annual_excess)

    log("make figures and report")
    figures = make_figures(paths, annual_excess, size_summary, sell_by_year, future_by_strategy, regime_by_year)

    annual_returns.to_csv(paths.tables_root / "annual_return_by_strategy.csv", index=False, encoding="utf-8")
    annual_excess.to_csv(paths.tables_root / "annual_excess_vs_baseline.csv", index=False, encoding="utf-8")
    size_summary.to_csv(paths.tables_root / "size_bucket_selector_summary.csv", index=False, encoding="utf-8")
    size_annual.to_csv(paths.tables_root / "size_bucket_selector_annual.csv", index=False, encoding="utf-8")
    sell_events.to_csv(paths.tables_root / "sell_fail_pre_event_features.csv", index=False, encoding="utf-8")
    sell_by_year.to_csv(paths.tables_root / "sell_fail_events_by_year.csv", index=False, encoding="utf-8")
    sell_by_strategy.to_csv(paths.tables_root / "sell_fail_events_by_strategy.csv", index=False, encoding="utf-8")
    future_fundamentals.to_csv(paths.tables_root / "future_fundamental_target_rows.csv", index=False, encoding="utf-8")
    future_by_strategy.to_csv(paths.tables_root / "future_fundamental_by_strategy.csv", index=False, encoding="utf-8")
    future_by_year.to_csv(paths.tables_root / "future_fundamental_by_year_strategy.csv", index=False, encoding="utf-8")
    regime_by_year.to_csv(paths.tables_root / "regime_condition_by_year.csv", index=False, encoding="utf-8")
    regime_summary.to_csv(paths.tables_root / "regime_condition_summary.csv", index=False, encoding="utf-8")

    report = render_report(
        annual_excess,
        size_summary,
        sell_by_strategy,
        future_by_strategy,
        regime_summary,
        figures,
    )
    report_path = paths.output_root / "rpe_failure_anatomy_v1_zh.md"
    report_path.write_text(report, encoding="utf-8")
    log(f"wrote {report_path}")


if __name__ == "__main__":
    main()
