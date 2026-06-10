from __future__ import annotations

import argparse
import json
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
    REGIMES,
    RESEARCH_END,
    RESEARCH_START,
    WARMUP_START,
    Paths,
    build_adjusted_returns,
    cumulative_return,
    draw_bar_chart,
    draw_multi_line_chart,
    load_pre_research_panel,
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
    annualized_vol,
    load_state_data,
    max_drawdown,
    simulate_stateful_portfolio,
    worst_rolling_return,
)


RPE_FACTOR_ROOT = "processed/rpe_factor_pit"
MAIN_MIN_SIZE_PCT = 0.10
MAIN_MAX_SIZE_PCT = 0.50
SIZE_CONTROL_BINS = [
    ("p10_20", 0.10, 0.20),
    ("p20_30", 0.20, 0.30),
    ("p30_40", 0.30, 0.40),
    ("p40_50", 0.40, 0.50),
]
SIZE_CONTROL_QUOTA = MAX_NAMES // len(SIZE_CONTROL_BINS)
WINDOWS = [
    ("full_sample", RESEARCH_START, RESEARCH_END),
    ("max_drawdown_window", "2008-01-15", "2008-11-04"),
    ("worst_12m_window", "2007-10-17", "2008-10-27"),
    ("ex_2008", RESEARCH_START, RESEARCH_END),
    ("2016-2018", "2016-01-01", "2018-12-31"),
    ("2022-2025", "2022-01-01", "2025-12-31"),
]
STRATEGY_LABELS = {
    "baseline_size_10_50_top100": "baseline: size 10%-50% smallest float mcap top100",
    "rpe_top100": "RPE top100 inside size 10%-50%",
    "size_controlled_rpe_top100": "size-controlled RPE top100, 25 names per size bucket",
}


def annual_turnover(daily: pd.DataFrame) -> float:
    if daily.empty or "turnover_rate" not in daily:
        return np.nan
    years = max(len(daily) / 252.0, 1e-12)
    return float(pd.to_numeric(daily["turnover_rate"], errors="coerce").fillna(0.0).sum() / years)


def month_end_signal_dates(panel: pd.DataFrame) -> list[str]:
    signal_dates = pd.Series(sorted(panel["feature_date"].dropna().unique()))
    signal_dates = signal_dates[(signal_dates >= RESEARCH_START) & (signal_dates <= RESEARCH_END)]
    return signal_dates.groupby(signal_dates.str.slice(0, 7)).tail(1).tolist()


def load_month_end_rpe(paths: Paths, signal_dates: set[str]) -> pd.DataFrame:
    frames = []
    usecols = ["feature_date", "code", "rpe_score", "valid_rpe_flag"]
    for year in range(2005, 2026):
        file = paths.processed_root / "rpe_factor_pit" / f"year={year}" / f"rpe_factor_pit_{year}.csv.gz"
        if not file.exists():
            continue
        frame = pd.read_csv(file, usecols=usecols, dtype={"feature_date": str, "code": str})
        frame = frame[frame["feature_date"].isin(signal_dates)].copy()
        frames.append(frame)
    if not frames:
        raise FileNotFoundError(f"No RPE factor files loaded from {paths.processed_root / 'rpe_factor_pit'}")
    rpe = pd.concat(frames, ignore_index=True)
    rpe["rpe_score"] = pd.to_numeric(rpe["rpe_score"], errors="coerce")
    rpe["valid_rpe_flag"] = parse_bool_series(rpe["valid_rpe_flag"])
    return rpe


def load_monthly_selection_frame(paths: Paths) -> tuple[pd.DataFrame, dict[str, Any]]:
    log("load pre-research panel for monthly RPE stateful targets")
    panel, panel_stats = load_pre_research_panel(paths)
    signal_dates = month_end_signal_dates(panel)
    selection_cols = [
        "feature_date",
        "exec_date",
        "code",
        "base_universe",
        "size_pct",
        "float_market_cap",
        "amount_20d_mean",
    ]
    monthly = panel.loc[panel["feature_date"].isin(signal_dates), selection_cols].copy()
    del panel

    log("load month-end RPE factor port")
    rpe = load_month_end_rpe(paths, set(signal_dates))
    monthly = monthly.merge(rpe, on=["feature_date", "code"], how="left")
    monthly["valid_rpe_flag"] = monthly["valid_rpe_flag"].fillna(False).astype(bool)
    monthly["rpe_score"] = pd.to_numeric(monthly["rpe_score"], errors="coerce")
    monthly["float_market_cap"] = pd.to_numeric(monthly["float_market_cap"], errors="coerce")
    monthly["amount_20d_mean"] = pd.to_numeric(monthly["amount_20d_mean"], errors="coerce")
    return monthly, panel_stats


def main_universe(frame: pd.DataFrame) -> pd.DataFrame:
    return frame[
        frame["base_universe"]
        & frame["size_pct"].gt(MAIN_MIN_SIZE_PCT)
        & frame["size_pct"].le(MAIN_MAX_SIZE_PCT)
    ].copy()


def select_baseline(candidates: pd.DataFrame) -> pd.DataFrame:
    return candidates.nsmallest(MAX_NAMES, "float_market_cap")


def select_rpe_top100(candidates: pd.DataFrame) -> pd.DataFrame:
    valid = candidates[candidates["valid_rpe_flag"] & candidates["rpe_score"].notna()].copy()
    return valid.nlargest(MAX_NAMES, "rpe_score")


def select_size_controlled_rpe(candidates: pd.DataFrame) -> pd.DataFrame:
    valid = candidates[candidates["valid_rpe_flag"] & candidates["rpe_score"].notna()].copy()
    selected_parts = []
    selected_codes: set[str] = set()
    for _, lower, upper in SIZE_CONTROL_BINS:
        bucket = valid[valid["size_pct"].gt(lower) & valid["size_pct"].le(upper)].copy()
        pick = bucket.nlargest(SIZE_CONTROL_QUOTA, "rpe_score")
        selected_parts.append(pick)
        selected_codes.update(pick["code"].tolist())
    selected = pd.concat(selected_parts, ignore_index=True) if selected_parts else pd.DataFrame()
    if len(selected) < MAX_NAMES:
        remaining = valid[~valid["code"].isin(selected_codes)].copy()
        fill = remaining.nlargest(MAX_NAMES - len(selected), "rpe_score")
        selected = pd.concat([selected, fill], ignore_index=True)
    return selected.head(MAX_NAMES)


def size_bucket_counts(selected: pd.DataFrame) -> dict[str, int]:
    counts: dict[str, int] = {}
    for label, lower, upper in SIZE_CONTROL_BINS:
        in_bucket = selected["size_pct"].gt(lower) & selected["size_pct"].le(upper)
        counts[label] = int(in_bucket.sum())
    return counts


def select_targets(candidates: pd.DataFrame, strategy: str) -> pd.DataFrame:
    if strategy == "baseline_size_10_50_top100":
        return select_baseline(candidates)
    if strategy == "rpe_top100":
        return select_rpe_top100(candidates)
    if strategy == "size_controlled_rpe_top100":
        return select_size_controlled_rpe(candidates)
    raise ValueError(f"Unknown strategy: {strategy}")


def build_rebalance_plans(monthly: pd.DataFrame, strategy: str) -> dict[str, dict[str, Any]]:
    plans: dict[str, dict[str, Any]] = {}
    for signal_date, date_frame in monthly.groupby("feature_date", sort=True):
        exec_dates = date_frame["exec_date"].dropna().unique().tolist()
        if not exec_dates:
            continue
        exec_date = sorted(exec_dates)[0]
        if exec_date > RESEARCH_END:
            continue
        candidates = main_universe(date_frame)
        selected = select_targets(candidates, strategy)
        bucket_counts = size_bucket_counts(selected) if not selected.empty else {label: 0 for label, _, _ in SIZE_CONTROL_BINS}
        plans[exec_date] = {
            "signal_date": signal_date,
            "exec_date": exec_date,
            "target": selected["code"].tolist(),
            "candidate_count": int(len(candidates)),
            "valid_rpe_candidate_count": int((candidates["valid_rpe_flag"] & candidates["rpe_score"].notna()).sum()),
            "target_count": int(len(selected)),
            "median_rpe_score": float(selected["rpe_score"].median()) if "rpe_score" in selected and not selected.empty else np.nan,
            "median_amount_20d": float(selected["amount_20d_mean"].median()) if not selected.empty else np.nan,
            "median_float_market_cap": float(selected["float_market_cap"].median()) if not selected.empty else np.nan,
            **{f"selected_{key}": value for key, value in bucket_counts.items()},
        }
    return plans


def plan_metadata_frame(plans: dict[str, dict[str, Any]], strategy: str) -> pd.DataFrame:
    rows = []
    extra_cols = ["valid_rpe_candidate_count", "median_rpe_score"]
    extra_cols.extend([f"selected_{label}" for label, _, _ in SIZE_CONTROL_BINS])
    for exec_date, plan in plans.items():
        row = {"strategy": strategy, "exec_date": exec_date}
        for col in extra_cols:
            row[col] = plan.get(col, np.nan)
        rows.append(row)
    return pd.DataFrame(rows)


def strategy_returns(daily: pd.DataFrame) -> pd.Series:
    if daily.empty:
        return pd.Series(dtype=float)
    return daily.set_index("date")["daily_return"].sort_index()


def split_ex_2008(series: pd.Series) -> list[pd.Series]:
    before = series[series.index < "2008-01-01"]
    after = series[series.index > "2008-12-31"]
    return [part for part in [before, after] if not part.empty]


def max_drawdown_ex_2008(series: pd.Series) -> float:
    parts = split_ex_2008(series)
    values = [max_drawdown(part) for part in parts if not part.empty]
    values = [value for value in values if pd.notna(value)]
    return float(min(values)) if values else np.nan


def worst_12m_ex_2008(series: pd.Series) -> float:
    parts = split_ex_2008(series)
    values = [worst_rolling_return(part) for part in parts if len(part) >= 252]
    values = [value for value in values if pd.notna(value)]
    return float(min(values)) if values else np.nan


def window_series(series: pd.Series, start: str, end: str, name: str) -> pd.Series:
    if name == "ex_2008":
        return series[(series.index < "2008-01-01") | (series.index > "2008-12-31")]
    return series[(series.index >= start) & (series.index <= end)]


def summarize_one_strategy(strategy: str, daily: pd.DataFrame, rebalance: pd.DataFrame) -> dict[str, Any]:
    returns = strategy_returns(daily)
    turnover = daily.set_index("date")["turnover_rate"] if "turnover_rate" in daily else pd.Series(dtype=float)
    buy_attempts = int(rebalance["bought"].sum() + rebalance["buy_failed"].sum()) if not rebalance.empty else 0
    sell_attempts = int(rebalance["sold"].sum() + rebalance["sell_failed"].sum()) if not rebalance.empty else 0
    sell_failed_pnl = float(daily["sell_failed_holding_pnl"].sum()) if "sell_failed_holding_pnl" in daily else np.nan
    suspended_pnl = float(daily["suspended_holding_pnl"].sum()) if "suspended_holding_pnl" in daily else np.nan
    forced_state_pnl = sell_failed_pnl + suspended_pnl
    total_simple_pnl = float(returns.sum()) if not returns.empty else np.nan
    forced_state_pnl_share = forced_state_pnl / total_simple_pnl if total_simple_pnl and np.isfinite(total_simple_pnl) else np.nan
    r2016 = returns[(returns.index >= "2016-01-01") & (returns.index <= "2018-12-31")]
    r2022 = returns[(returns.index >= "2022-01-01") & (returns.index <= "2025-12-31")]
    return {
        "strategy": strategy,
        "label": STRATEGY_LABELS[strategy],
        "ann_return": safe_annualized_return(returns),
        "cost_stress_10bps_ann_return": safe_annualized_return(returns - turnover * COST_STRESS_RATES["10bps"]),
        "cost_stress_30bps_ann_return": safe_annualized_return(returns - turnover * COST_STRESS_RATES["30bps"]),
        "cumulative_return": cumulative_return(returns),
        "max_drawdown": max_drawdown(returns),
        "worst_12m": worst_rolling_return(returns),
        "worst_12m_ex_2008": worst_12m_ex_2008(returns),
        "max_drawdown_ex_2008": max_drawdown_ex_2008(returns),
        "2016_2018_ann_return": safe_annualized_return(r2016),
        "2016_2018_max_drawdown": max_drawdown(r2016),
        "2022_2025_ann_return": safe_annualized_return(r2022),
        "ann_vol": annualized_vol(returns),
        "buy_attempts": buy_attempts,
        "buy_failed": int(rebalance["buy_failed"].sum()) if not rebalance.empty else 0,
        "buy_fail_rate": int(rebalance["buy_failed"].sum()) / buy_attempts if buy_attempts else np.nan,
        "sell_attempts": sell_attempts,
        "sell_failed": int(rebalance["sell_failed"].sum()) if not rebalance.empty else 0,
        "sell_fail_rate": int(rebalance["sell_failed"].sum()) / sell_attempts if sell_attempts else np.nan,
        "suspended_position_days": int(daily["suspended_positions"].sum()) if not daily.empty else 0,
        "forced_state_pnl": forced_state_pnl,
        "forced_state_pnl_share": forced_state_pnl_share,
        "median_amount_20d": float(rebalance["median_amount_20d"].median()) if not rebalance.empty else np.nan,
        "median_float_market_cap": float(rebalance["median_float_market_cap"].median()) if not rebalance.empty else np.nan,
        "turnover": annual_turnover(daily),
        "avg_rebalance_turnover": float(rebalance.eval("(bought + sold) / @MAX_NAMES").mean()) if not rebalance.empty else np.nan,
        "median_target_count": float(rebalance["target_count"].median()) if "target_count" in rebalance else np.nan,
        "median_valid_rpe_candidates": float(rebalance["valid_rpe_candidate_count"].median())
        if "valid_rpe_candidate_count" in rebalance
        else np.nan,
        "median_holdings": float(daily["holdings"].median()) if not daily.empty else np.nan,
        "median_cash_slots": float(daily["cash_slots"].median()) if not daily.empty else np.nan,
    }


def summarize_windows(daily_returns: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for strategy, group in daily_returns.groupby("strategy", sort=True):
        series = group.set_index("date")["daily_return"].sort_index()
        daily = group.set_index("date").sort_index()
        for name, start, end in WINDOWS:
            returns = window_series(series, start, end, name)
            window_daily = daily.loc[returns.index] if not returns.empty else daily.iloc[0:0]
            total_pnl = float(returns.sum()) if not returns.empty else np.nan
            forced_pnl = (
                float(window_daily["sell_failed_holding_pnl"].sum() + window_daily["suspended_holding_pnl"].sum())
                if not window_daily.empty
                else np.nan
            )
            rows.append(
                {
                    "strategy": strategy,
                    "window": name,
                    "start_date": start,
                    "end_date": end,
                    "ann_return": safe_annualized_return(returns),
                    "cumulative_return": cumulative_return(returns),
                    "max_drawdown": max_drawdown(returns),
                    "worst_12m": worst_rolling_return(returns),
                    "observations": int(returns.notna().sum()),
                    "sell_failed_holding_pnl": float(window_daily["sell_failed_holding_pnl"].sum())
                    if not window_daily.empty
                    else np.nan,
                    "suspended_holding_pnl": float(window_daily["suspended_holding_pnl"].sum())
                    if not window_daily.empty
                    else np.nan,
                    "forced_state_pnl": forced_pnl,
                    "forced_state_pnl_share": forced_pnl / total_pnl if total_pnl and np.isfinite(total_pnl) else np.nan,
                    "suspended_position_days": int(window_daily["suspended_positions"].sum()) if not window_daily.empty else 0,
                }
            )
    return pd.DataFrame(rows)


def summarize_size_bucket_mix(rebalance: pd.DataFrame) -> pd.DataFrame:
    rows = []
    bucket_cols = [f"selected_{label}" for label, _, _ in SIZE_CONTROL_BINS]
    for strategy, group in rebalance.groupby("strategy", sort=True):
        row: dict[str, Any] = {"strategy": strategy}
        for col in bucket_cols:
            row[col] = float(group[col].median()) if col in group else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def pass_fail_table(summary: pd.DataFrame) -> pd.DataFrame:
    base = summary[summary["strategy"].eq("baseline_size_10_50_top100")].iloc[0]
    rows = []
    for strategy in ["rpe_top100", "size_controlled_rpe_top100"]:
        row = summary[summary["strategy"].eq(strategy)].iloc[0]
        checks = [
            (
                "30bps cost remains positive",
                row["cost_stress_30bps_ann_return"] > 0,
                row["cost_stress_30bps_ann_return"],
                0.0,
            ),
            (
                "ann_return not materially below baseline",
                row["ann_return"] >= base["ann_return"] - 0.05,
                row["ann_return"],
                base["ann_return"],
            ),
            (
                "2016-2018 not worse than baseline",
                row["2016_2018_ann_return"] >= base["2016_2018_ann_return"],
                row["2016_2018_ann_return"],
                base["2016_2018_ann_return"],
            ),
            (
                "worst_12m_ex_2008 not worse than baseline",
                row["worst_12m_ex_2008"] >= base["worst_12m_ex_2008"],
                row["worst_12m_ex_2008"],
                base["worst_12m_ex_2008"],
            ),
            (
                "max_drawdown not materially worse",
                row["max_drawdown"] >= base["max_drawdown"] - 0.03,
                row["max_drawdown"],
                base["max_drawdown"],
            ),
            (
                "sell_fail_rate not materially worse",
                row["sell_fail_rate"] <= base["sell_fail_rate"] + 0.03,
                row["sell_fail_rate"],
                base["sell_fail_rate"],
            ),
            (
                "suspended days not materially worse",
                row["suspended_position_days"] <= base["suspended_position_days"] * 1.20,
                row["suspended_position_days"],
                base["suspended_position_days"],
            ),
            (
                "forced_state_pnl not worse",
                row["forced_state_pnl"] >= base["forced_state_pnl"] - 0.03,
                row["forced_state_pnl"],
                base["forced_state_pnl"],
            ),
            (
                "median amount not much lower",
                row["median_amount_20d"] >= base["median_amount_20d"] * 0.80,
                row["median_amount_20d"],
                base["median_amount_20d"],
            ),
            (
                "median float mcap not much smaller",
                row["median_float_market_cap"] >= base["median_float_market_cap"] * 0.90,
                row["median_float_market_cap"],
                base["median_float_market_cap"],
            ),
        ]
        check_status = {name: ok for name, ok, _, _ in checks}
        passed = int(sum(check_status.values()))
        total = len(checks)
        if all(check_status.values()):
            verdict = "Pass"
        elif (
            passed >= 7
            and check_status["30bps cost remains positive"]
            and check_status["2016-2018 not worse than baseline"]
        ):
            verdict = "Borderline"
        else:
            verdict = "Fail"
        for check, ok, strategy_value, baseline_value in checks:
            rows.append(
                {
                    "strategy": strategy,
                    "check": check,
                    "status": "Pass" if ok else "Fail",
                    "strategy_value": strategy_value,
                    "baseline_or_threshold": baseline_value,
                    "verdict": verdict,
                    "passed_checks": passed,
                    "total_checks": total,
                }
            )
    return pd.DataFrame(rows)


def make_figures(paths: Paths, daily_returns: pd.DataFrame, summary: pd.DataFrame, windows: pd.DataFrame) -> dict[str, str]:
    figures: dict[str, str] = {}
    nav_parts = []
    dd_parts = []
    for strategy, group in daily_returns.groupby("strategy", sort=True):
        series = group.set_index("date")["daily_return"].fillna(0.0)
        nav = (1.0 + series).cumprod().rename(strategy)
        nav_parts.append(nav)
        dd_parts.append((nav / nav.cummax() - 1.0).rename(strategy))
    nav_frame = pd.concat(nav_parts, axis=1) if nav_parts else pd.DataFrame()
    dd_frame = pd.concat(dd_parts, axis=1) if dd_parts else pd.DataFrame()

    path = paths.figures_root / "rpe_stateful_nav.png"
    draw_multi_line_chart(nav_frame, path, "RPE Stateful Portfolio NAV", "Monthly T+1 stateful execution")
    figures["nav"] = str(path.relative_to(paths.output_root))

    path = paths.figures_root / "rpe_stateful_drawdown.png"
    draw_multi_line_chart(dd_frame, path, "RPE Stateful Portfolio Drawdown", "Drawdown from running peak")
    figures["drawdown"] = str(path.relative_to(paths.output_root))

    path = paths.figures_root / "rpe_stateful_30bps_ann_return.png"
    draw_bar_chart(
        summary["strategy"].tolist(),
        summary["cost_stress_30bps_ann_return"].tolist(),
        path,
        "30bps Cost Stress Annualized Return",
        "Turnover cost: 30bps per traded slot",
    )
    figures["cost_30bps"] = str(path.relative_to(paths.output_root))

    path = paths.figures_root / "rpe_stateful_2016_2018_ann_return.png"
    draw_bar_chart(
        summary["strategy"].tolist(),
        summary["2016_2018_ann_return"].tolist(),
        path,
        "2016-2018 Annualized Return",
        "Key non-2008 failure window",
    )
    figures["ann_2016_2018"] = str(path.relative_to(paths.output_root))

    path = paths.figures_root / "rpe_stateful_worst_12m_ex_2008.png"
    draw_bar_chart(
        summary["strategy"].tolist(),
        summary["worst_12m_ex_2008"].tolist(),
        path,
        "Worst 12M Return Ex-2008",
        "Worst rolling 252-trading-day return, excluding calendar 2008",
    )
    figures["worst_12m_ex_2008"] = str(path.relative_to(paths.output_root))

    path = paths.figures_root / "rpe_stateful_sell_fail_rate.png"
    draw_bar_chart(
        summary["strategy"].tolist(),
        summary["sell_fail_rate"].tolist(),
        path,
        "Sell Failure Rate",
        "Failed sells / sell attempts",
    )
    figures["sell_fail_rate"] = str(path.relative_to(paths.output_root))

    path = paths.figures_root / "rpe_stateful_forced_state_pnl.png"
    draw_bar_chart(
        summary["strategy"].tolist(),
        summary["forced_state_pnl"].tolist(),
        path,
        "Forced-state PnL",
        "Sell-failed holding PnL + suspension catch-up PnL",
    )
    figures["forced_state_pnl"] = str(path.relative_to(paths.output_root))

    path = paths.figures_root / "rpe_stateful_median_amount_20d.png"
    draw_bar_chart(
        summary["strategy"].tolist(),
        summary["median_amount_20d"].tolist(),
        path,
        "Selected Basket Median 20D Amount",
        "Median across rebalance selections",
    )
    figures["median_amount_20d"] = str(path.relative_to(paths.output_root))

    path = paths.figures_root / "rpe_stateful_median_float_mcap.png"
    draw_bar_chart(
        summary["strategy"].tolist(),
        summary["median_float_market_cap"].tolist(),
        path,
        "Selected Basket Median Float Market Cap",
        "Median across rebalance selections",
    )
    figures["median_float_mcap"] = str(path.relative_to(paths.output_root))

    window_2016 = windows[windows["window"].eq("2016-2018")].copy()
    path = paths.figures_root / "rpe_stateful_2016_2018_forced_state_pnl.png"
    draw_bar_chart(
        window_2016["strategy"].tolist(),
        window_2016["forced_state_pnl"].tolist(),
        path,
        "2016-2018 Forced-state PnL",
        "Execution stress contribution in the key failure window",
    )
    figures["forced_state_2016_2018"] = str(path.relative_to(paths.output_root))
    return figures


def format_summary(summary: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "组合": summary["strategy"],
            "年化": summary["ann_return"].map(pct),
            "30bps后年化": summary["cost_stress_30bps_ann_return"].map(pct),
            "累计收益": summary["cumulative_return"].map(pct),
            "最大回撤": summary["max_drawdown"].map(pct),
            "最差12个月": summary["worst_12m"].map(pct),
            "ex-2008最差12个月": summary["worst_12m_ex_2008"].map(pct),
            "ex-2008最大回撤": summary["max_drawdown_ex_2008"].map(pct),
            "2016-2018年化": summary["2016_2018_ann_return"].map(pct),
            "2016-2018最大回撤": summary["2016_2018_max_drawdown"].map(pct),
            "2022-2025年化": summary["2022_2025_ann_return"].map(pct),
            "卖出失败率": summary["sell_fail_rate"].map(pct),
            "停牌持仓日": summary["suspended_position_days"],
            "forced-state PnL": summary["forced_state_pnl"].map(num),
            "年化换手": summary["turnover"].map(num),
        }
    )


def format_exposure(summary: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "组合": summary["strategy"],
            "买入失败率": summary["buy_fail_rate"].map(pct),
            "卖出失败率": summary["sell_fail_rate"].map(pct),
            "停牌持仓日": summary["suspended_position_days"],
            "forced-state PnL": summary["forced_state_pnl"].map(num),
            "forced-state占比": summary["forced_state_pnl_share"].map(pct),
            "入选20日成交额中位数": summary["median_amount_20d"].map(lambda x: "n/a" if pd.isna(x) else f"{x:,.0f}"),
            "入选流通市值中位数": summary["median_float_market_cap"].map(lambda x: "n/a" if pd.isna(x) else f"{x:,.0f}"),
            "中位目标数": summary["median_target_count"].map(num),
            "中位持仓数": summary["median_holdings"].map(num),
            "中位现金槽位": summary["median_cash_slots"].map(num),
        }
    )


def format_windows(windows: pd.DataFrame) -> pd.DataFrame:
    out = windows.copy()
    out["ann_return"] = out["ann_return"].map(pct)
    out["cumulative_return"] = out["cumulative_return"].map(pct)
    out["max_drawdown"] = out["max_drawdown"].map(pct)
    out["worst_12m"] = out["worst_12m"].map(pct)
    out["forced_state_pnl"] = out["forced_state_pnl"].map(num)
    out["forced_state_pnl_share"] = out["forced_state_pnl_share"].map(pct)
    return out[
        [
            "strategy",
            "window",
            "ann_return",
            "cumulative_return",
            "max_drawdown",
            "worst_12m",
            "forced_state_pnl",
            "forced_state_pnl_share",
            "suspended_position_days",
            "observations",
        ]
    ]


def format_pass_fail(checks: pd.DataFrame) -> pd.DataFrame:
    compact = (
        checks.groupby("strategy", sort=False)
        .agg(verdict=("verdict", "first"), passed_checks=("passed_checks", "first"), total_checks=("total_checks", "first"))
        .reset_index()
    )
    compact["通过项"] = compact["passed_checks"].astype(str) + "/" + compact["total_checks"].astype(str)
    return compact[["strategy", "verdict", "通过项"]]


def final_interpretation(summary: pd.DataFrame, checks: pd.DataFrame) -> list[str]:
    base = summary[summary["strategy"].eq("baseline_size_10_50_top100")].iloc[0]
    rpe = summary[summary["strategy"].eq("rpe_top100")].iloc[0]
    controlled = summary[summary["strategy"].eq("size_controlled_rpe_top100")].iloc[0]
    verdicts = checks.groupby("strategy")["verdict"].first().to_dict()
    lines = [
        "## 研究解读",
        "",
        f"- `rpe_top100` 第一轮判定：`{verdicts.get('rpe_top100', 'n/a')}`；`size_controlled_rpe_top100` 第一轮判定：`{verdicts.get('size_controlled_rpe_top100', 'n/a')}`。",
        f"- baseline 年化为 `{pct(base['ann_return'])}`，30bps 后为 `{pct(base['cost_stress_30bps_ann_return'])}`；RPE top100 年化为 `{pct(rpe['ann_return'])}`，30bps 后为 `{pct(rpe['cost_stress_30bps_ann_return'])}`；size-controlled RPE 年化为 `{pct(controlled['ann_return'])}`，30bps 后为 `{pct(controlled['cost_stress_30bps_ann_return'])}`。",
        f"- 关键窗口 2016-2018：baseline `{pct(base['2016_2018_ann_return'])}`，RPE top100 `{pct(rpe['2016_2018_ann_return'])}`，size-controlled RPE `{pct(controlled['2016_2018_ann_return'])}`。",
        f"- 执行风险：baseline 卖出失败率 `{pct(base['sell_fail_rate'])}`、停牌持仓日 `{int(base['suspended_position_days']):,}`；RPE top100 为 `{pct(rpe['sell_fail_rate'])}` / `{int(rpe['suspended_position_days']):,}`；size-controlled RPE 为 `{pct(controlled['sell_fail_rate'])}` / `{int(controlled['suspended_position_days']):,}`。",
        f"- 流动性暴露：baseline 入选 20 日成交额中位数 `{base['median_amount_20d']:,.0f}`，RPE top100 `{rpe['median_amount_20d']:,.0f}`，size-controlled RPE `{controlled['median_amount_20d']:,.0f}`。",
        "",
    ]
    if verdicts.get("size_controlled_rpe_top100") == "Pass":
        lines.append("- 结论：RPE 不只是理论分组里的弱信号，在真实状态机里也通过了第一关。下一步可以进入更严格的稳健性审计，但仍不能直接晋升为可交易模块。")
    elif verdicts.get("size_controlled_rpe_top100") == "Borderline":
        lines.append("- 结论：RPE 有增量迹象，但还没有干净到可以晋升。下一步应优先查失败项，而不是调参救曲线。")
    else:
        lines.append("- 结论：RPE stateful v1 没过第一关。按当前准则，它只能保留为 observation 或进入归档，不应继续复杂化。")
    return lines


def render_report_zh(
    summary: pd.DataFrame,
    windows: pd.DataFrame,
    size_mix: pd.DataFrame,
    checks: pd.DataFrame,
    figures: dict[str, str],
) -> str:
    lines = [
        "# A股小盘 RPE Stateful Portfolio v1",
        "",
        "本报告只测试冻结的 RPE v1 端口在真实持仓状态机下是否仍有增量，不做参数优化，不改 RPE 公式。",
        "",
        "## 组合设定",
        "",
        "- 样本：`2005-01-01` 到 `2025-12-31`；2026 不进入正式结论。",
        "- 主 universe：`size 10%-50%`。",
        "- baseline：主 universe 内最小流通市值 `top100`。",
        "- RPE top100：主 universe 内 `valid_rpe_flag=True` 且 `rpe_score` 最高的 100 只。",
        "- size-controlled RPE：把 `size 10%-50%` 固定切为 `10-20 / 20-30 / 30-40 / 40-50` 四桶，每桶优先选 25 只高 RPE。",
        "- 状态机：月度调仓，T 日收盘算目标，T+1 执行；买不到留现金，卖不出继续持有，停牌冻结，复牌归因。",
        "- 成本压力：沿用 10bps / 30bps per traded slot。",
        "",
        "## 第一轮判定",
        "",
        markdown_table(format_pass_fail(checks)),
        "",
        "## 组合对比",
        "",
        markdown_table(format_summary(summary)),
        "",
        "## 执行与暴露",
        "",
        markdown_table(format_exposure(summary)),
        "",
        "## Size 桶入选结构",
        "",
        markdown_table(size_mix),
        "",
        "## 审计窗口",
        "",
        markdown_table(format_windows(windows)),
        "",
        "## PNG 图",
        "",
    ]
    for key, rel in figures.items():
        lines.append(f"![{key}](figures/{Path(rel).name})")
        lines.append("")
    lines.extend(final_interpretation(summary, checks))
    lines.extend(
        [
            "",
            "## 解读边界",
            "",
            "- 这仍是 pre-research，不是可部署策略结论。",
            "- 2008 主要是系统性 beta risk，本轮重点是 2016-2018、ex-2008 风险、执行失败和流动性暴露。",
            "- 如果结果只是年化更高，但执行风险或 2016-2018 恶化，应判为不合格。",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run RPE stateful portfolio v1.")
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--processed-root", default="processed")
    parser.add_argument("--output-root", default="outputs/rpe_stateful_portfolio_v1")
    parser.add_argument("--force-returns", action="store_true")
    args = parser.parse_args()

    paths = Paths(
        data_root=(PROJECT_ROOT / args.data_root).resolve(),
        processed_root=(PROJECT_ROOT / args.processed_root).resolve(),
        output_root=(PROJECT_ROOT / args.output_root).resolve(),
        figures_root=(PROJECT_ROOT / args.output_root / "figures").resolve(),
        tables_root=(PROJECT_ROOT / args.output_root / "tables").resolve(),
    )
    paths.output_root.mkdir(parents=True, exist_ok=True)
    paths.figures_root.mkdir(parents=True, exist_ok=True)
    paths.tables_root.mkdir(parents=True, exist_ok=True)

    manifest = json.loads((paths.processed_root / "build_manifest.json").read_text(encoding="utf-8"))
    build_adjusted_returns(paths, market_end=manifest["market"]["market_end_date"], force=args.force_returns)

    monthly, panel_stats = load_monthly_selection_frame(paths)
    log(f"panel rows: {panel_stats['rows']:,}; monthly target rows: {len(monthly):,}")
    log("load state returns and status")
    returns, status = load_state_data(paths)
    calendar = pd.read_csv(paths.processed_root / "market_calendar.csv", dtype=str)
    dates = calendar[(calendar["trade_date"] >= WARMUP_START) & (calendar["trade_date"] <= RESEARCH_END)][
        "trade_date"
    ].tolist()

    all_daily = []
    all_rebalance = []
    summaries = []
    for strategy in STRATEGY_LABELS:
        log(f"simulate {strategy}")
        plans = build_rebalance_plans(monthly, strategy)
        _, daily, rebalance = simulate_stateful_portfolio(dates, plans, returns, status, strategy)
        plan_meta = plan_metadata_frame(plans, strategy)
        if not plan_meta.empty and not rebalance.empty:
            rebalance = rebalance.merge(plan_meta, on=["strategy", "exec_date"], how="left")
        for key, value in STRATEGY_LABELS.items():
            if strategy == key:
                daily["label"] = value
                rebalance["label"] = value
        all_daily.append(daily)
        all_rebalance.append(rebalance)
        summaries.append(summarize_one_strategy(strategy, daily, rebalance))

    daily_returns = pd.concat(all_daily, ignore_index=True)
    rebalance_audit = pd.concat(all_rebalance, ignore_index=True)
    summary = pd.DataFrame(summaries)
    windows = summarize_windows(daily_returns)
    size_mix = summarize_size_bucket_mix(rebalance_audit)
    checks = pass_fail_table(summary)
    figures = make_figures(paths, daily_returns, summary, windows)

    summary.to_csv(paths.tables_root / "rpe_stateful_summary.csv", index=False, encoding="utf-8")
    windows.to_csv(paths.tables_root / "rpe_stateful_window_summary.csv", index=False, encoding="utf-8")
    daily_returns.to_csv(paths.tables_root / "rpe_stateful_daily_returns.csv", index=False, encoding="utf-8")
    rebalance_audit.to_csv(paths.tables_root / "rpe_stateful_rebalance_audit.csv", index=False, encoding="utf-8")
    size_mix.to_csv(paths.tables_root / "rpe_stateful_size_bucket_mix.csv", index=False, encoding="utf-8")
    checks.to_csv(paths.tables_root / "rpe_stateful_pass_fail_checks.csv", index=False, encoding="utf-8")

    report = render_report_zh(summary, windows, size_mix, checks, figures)
    report_path = paths.output_root / "rpe_stateful_portfolio_v1_zh.md"
    report_path.write_text(report, encoding="utf-8")
    log(f"wrote {report_path}")


if __name__ == "__main__":
    main()
