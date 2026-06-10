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
    load_yearly_csv,
    log,
    markdown_table,
    num,
    parse_bool_series,
    pct,
    safe_annualized_return,
)


MAX_NAMES = 100
COST_STRESS_RATES = {
    "10bps": 0.001,
    "30bps": 0.003,
}
STRATEGY_SPECS = [
    {
        "strategy": "size_05_30_top100",
        "label": "size 5%-30% top100",
        "min_pct": 0.05,
        "max_pct": 0.30,
    },
    {
        "strategy": "size_10_50_top100",
        "label": "size 10%-50% top100",
        "min_pct": 0.10,
        "max_pct": 0.50,
    },
]


def max_drawdown(daily_returns: pd.Series) -> float:
    values = pd.to_numeric(daily_returns, errors="coerce").fillna(0.0)
    if values.empty:
        return np.nan
    nav = (1.0 + values).cumprod()
    peak = nav.cummax()
    dd = nav / peak - 1.0
    return float(dd.min())


def annualized_vol(daily_returns: pd.Series) -> float:
    values = pd.to_numeric(daily_returns, errors="coerce").dropna()
    if values.empty:
        return np.nan
    return float(values.std() * np.sqrt(252))


def worst_rolling_return(daily_returns: pd.Series, window: int = 252) -> float:
    values = pd.to_numeric(daily_returns, errors="coerce").fillna(0.0)
    if len(values) < window:
        return np.nan
    rolling = (1.0 + values).rolling(window).apply(np.prod, raw=True) - 1.0
    return float(rolling.min())


def load_state_data(paths: Paths) -> tuple[pd.DataFrame, pd.DataFrame]:
    years = [str(year) for year in range(2004, 2026)]
    returns = load_yearly_csv(
        paths.processed_root / "market_daily_adj_returns",
        "market_daily_adj_returns_{year}.csv.gz",
        years,
        ["trade_date", "code", "adj_open", "adj_close", "exec_oc_ret_1d"],
        dtype={"trade_date": str, "code": str},
    )
    returns["adj_open"] = pd.to_numeric(returns["adj_open"], errors="coerce")
    returns["adj_close"] = pd.to_numeric(returns["adj_close"], errors="coerce")
    returns["exec_oc_ret_1d"] = pd.to_numeric(returns["exec_oc_ret_1d"], errors="coerce")
    returns = returns.sort_values(["code", "trade_date"])
    returns["prev_bar_adj_close"] = returns.groupby("code", sort=False)["adj_close"].shift(1)
    returns["entry_oc_ret_on_bar"] = returns["adj_close"] / returns["adj_open"] - 1.0
    returns["holding_cc_ret_on_bar"] = returns["adj_close"] / returns["prev_bar_adj_close"] - 1.0
    returns["sell_open_ret"] = returns["adj_open"] / returns["prev_bar_adj_close"] - 1.0

    status = load_yearly_csv(
        paths.processed_root / "market_trading_status",
        "market_trading_status_{year}.csv.gz",
        [str(year) for year in range(2005, 2026)],
        ["trade_date", "code", "has_bar", "can_buy_on_bar", "can_sell_on_bar"],
        dtype={"trade_date": str, "code": str},
    )
    for col in ["has_bar", "can_buy_on_bar", "can_sell_on_bar"]:
        status[col] = parse_bool_series(status[col])
    return returns, status


def make_series_map(frame: pd.DataFrame, value_col: str) -> pd.Series:
    return frame.set_index(["trade_date", "code"])[value_col]


def scalar_get(series: pd.Series, date: str, code: str, default: Any = np.nan) -> Any:
    try:
        value = series.loc[(date, code)]
    except KeyError:
        return default
    if isinstance(value, pd.Series):
        if value.empty:
            return default
        return value.iloc[0]
    return value


def bool_get(series: pd.Series, date: str, code: str, default: bool = False) -> bool:
    value = scalar_get(series, date, code, default)
    if pd.isna(value):
        return default
    return bool(value)


def float_get(series: pd.Series, date: str, code: str, default: float = 0.0) -> float:
    value = scalar_get(series, date, code, default)
    if pd.isna(value) or not np.isfinite(float(value)):
        return default
    return float(value)


def build_rebalance_plans(panel: pd.DataFrame, spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    signal_dates = pd.Series(sorted(panel["feature_date"].dropna().unique()))
    signal_dates = signal_dates[(signal_dates >= RESEARCH_START) & (signal_dates <= RESEARCH_END)]
    month_end_dates = signal_dates.groupby(signal_dates.str.slice(0, 7)).tail(1).tolist()
    plans: dict[str, dict[str, Any]] = {}
    for signal_date in month_end_dates:
        date_frame = panel[panel["feature_date"].eq(signal_date)]
        exec_dates = date_frame["exec_date"].dropna().unique().tolist()
        if not exec_dates:
            continue
        exec_date = sorted(exec_dates)[0]
        if exec_date > RESEARCH_END:
            continue
        candidates = date_frame[
            date_frame["base_universe"]
            & date_frame["size_pct"].gt(float(spec["min_pct"]))
            & date_frame["size_pct"].le(float(spec["max_pct"]))
        ].copy()
        candidates = candidates.nsmallest(MAX_NAMES, "float_market_cap")
        plans[exec_date] = {
            "signal_date": signal_date,
            "exec_date": exec_date,
            "target": candidates["code"].tolist(),
            "candidate_count": int(len(candidates)),
            "median_amount_20d": float(candidates["amount_20d_mean"].median()) if not candidates.empty else np.nan,
            "median_float_market_cap": float(candidates["float_market_cap"].median()) if not candidates.empty else np.nan,
        }
    return plans


def simulate_stateful_portfolio(
    dates: list[str],
    plans: dict[str, dict[str, Any]],
    returns: pd.DataFrame,
    status: pd.DataFrame,
    strategy: str,
) -> tuple[pd.Series, pd.DataFrame, pd.DataFrame]:
    has_bar = make_series_map(status, "has_bar")
    can_buy = make_series_map(status, "can_buy_on_bar")
    can_sell = make_series_map(status, "can_sell_on_bar")
    holding_ret = make_series_map(returns, "holding_cc_ret_on_bar")
    entry_ret = make_series_map(returns, "entry_oc_ret_on_bar")
    sell_open_ret = make_series_map(returns, "sell_open_ret")

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

    daily = pd.DataFrame(daily_rows)
    returns_series = daily.set_index("date")["daily_return"] if not daily.empty else pd.Series(dtype=float)
    return returns_series, daily, pd.DataFrame(rebalance_rows)


def summarize_strategy(strategy: str, daily: pd.DataFrame, rebalance: pd.DataFrame) -> dict[str, Any]:
    returns = daily.set_index("date")["daily_return"] if not daily.empty else pd.Series(dtype=float)
    turnover = daily.set_index("date")["turnover_rate"] if "turnover_rate" in daily else pd.Series(dtype=float)
    buy_attempts = int(rebalance["bought"].sum() + rebalance["buy_failed"].sum()) if not rebalance.empty else 0
    sell_attempts = int(rebalance["sold"].sum() + rebalance["sell_failed"].sum()) if not rebalance.empty else 0
    total_pnl = float(returns.sum()) if not returns.empty else np.nan
    sell_failed_pnl = float(daily["sell_failed_holding_pnl"].sum()) if "sell_failed_holding_pnl" in daily else np.nan
    suspended_pnl = float(daily["suspended_holding_pnl"].sum()) if "suspended_holding_pnl" in daily else np.nan
    forced_state_pnl = sell_failed_pnl + suspended_pnl
    forced_state_pnl_share = forced_state_pnl / total_pnl if total_pnl and np.isfinite(total_pnl) else np.nan
    return {
        "strategy": strategy,
        "ann_return": safe_annualized_return(returns),
        "cumulative_return": cumulative_return(returns),
        "max_drawdown": max_drawdown(returns),
        "worst_12m_return": worst_rolling_return(returns),
        "ann_vol": annualized_vol(returns),
        "daily_mean": float(returns.mean()) if not returns.empty else np.nan,
        "cost_stress_10bps_ann_return": safe_annualized_return(returns - turnover * COST_STRESS_RATES["10bps"]),
        "cost_stress_30bps_ann_return": safe_annualized_return(returns - turnover * COST_STRESS_RATES["30bps"]),
        "total_simple_pnl": total_pnl,
        "entry_pnl_total": float(daily["entry_pnl"].sum()) if "entry_pnl" in daily else np.nan,
        "sell_open_pnl_total": float(daily["sell_open_pnl"].sum()) if "sell_open_pnl" in daily else np.nan,
        "normal_holding_pnl_total": float(daily["normal_holding_pnl"].sum()) if "normal_holding_pnl" in daily else np.nan,
        "sell_failed_holding_pnl_total": sell_failed_pnl,
        "suspended_holding_pnl_total": suspended_pnl,
        "forced_state_pnl_share": forced_state_pnl_share,
        "rebalance_count": int(len(rebalance)),
        "median_holdings": float(daily["holdings"].median()) if not daily.empty else np.nan,
        "median_cash_slots": float(daily["cash_slots"].median()) if not daily.empty else np.nan,
        "buy_attempts": buy_attempts,
        "buy_failed": int(rebalance["buy_failed"].sum()) if not rebalance.empty else 0,
        "buy_fail_rate": int(rebalance["buy_failed"].sum()) / buy_attempts if buy_attempts else np.nan,
        "sell_attempts": sell_attempts,
        "sell_failed": int(rebalance["sell_failed"].sum()) if not rebalance.empty else 0,
        "sell_fail_rate": int(rebalance["sell_failed"].sum()) / sell_attempts if sell_attempts else np.nan,
        "suspended_position_days": int(daily["suspended_positions"].sum()) if not daily.empty else 0,
    }


def summarize_regimes(daily_returns: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for strategy, group in daily_returns.groupby("strategy", sort=True):
        series = group.set_index("date")["daily_return"]
        for regime, start, end in REGIMES:
            window = series[(series.index >= start) & (series.index <= end)]
            rows.append(
                {
                    "strategy": strategy,
                    "regime": regime,
                    "ann_return": safe_annualized_return(window),
                    "max_drawdown": max_drawdown(window),
                    "observations": int(window.notna().sum()),
                }
            )
    return pd.DataFrame(rows)


def make_figures(paths: Paths, daily_returns: pd.DataFrame, summary: pd.DataFrame, rebalance: pd.DataFrame) -> dict[str, str]:
    figures: dict[str, str] = {}
    nav_parts = []
    dd_parts = []
    for strategy, group in daily_returns.groupby("strategy", sort=True):
        series = group.set_index("date")["daily_return"].fillna(0.0)
        nav = (1.0 + series).cumprod().rename(strategy)
        nav_parts.append(nav)
        dd = (nav / nav.cummax() - 1.0).rename(strategy)
        dd_parts.append(dd)
    nav_frame = pd.concat(nav_parts, axis=1) if nav_parts else pd.DataFrame()
    dd_frame = pd.concat(dd_parts, axis=1) if dd_parts else pd.DataFrame()

    path = paths.figures_root / "stateful_portfolio_nav.png"
    draw_multi_line_chart(nav_frame, path, "Stateful Monthly Portfolio NAV", "Monthly rebalance, stateful execution")
    figures["stateful_nav"] = str(path.relative_to(paths.output_root))

    path = paths.figures_root / "stateful_portfolio_drawdown.png"
    draw_multi_line_chart(dd_frame, path, "Stateful Monthly Portfolio Drawdown", "Drawdown from running peak")
    figures["stateful_drawdown"] = str(path.relative_to(paths.output_root))

    path = paths.figures_root / "stateful_buy_fail_rate.png"
    draw_bar_chart(summary["strategy"].tolist(), summary["buy_fail_rate"].tolist(), path, "Buy Failure Rate", "Failed buys / buy attempts")
    figures["buy_fail_rate"] = str(path.relative_to(paths.output_root))

    path = paths.figures_root / "stateful_worst_12m_return.png"
    draw_bar_chart(
        summary["strategy"].tolist(),
        summary["worst_12m_return"].tolist(),
        path,
        "Worst Rolling 12-month Return",
        "252-trading-day compounded return",
    )
    figures["worst_12m_return"] = str(path.relative_to(paths.output_root))

    path = paths.figures_root / "stateful_cost_stress_30bps.png"
    draw_bar_chart(
        summary["strategy"].tolist(),
        summary["cost_stress_30bps_ann_return"].tolist(),
        path,
        "Cost Stress: 30bps per Traded Slot",
        "Annualized return after simple turnover cost",
    )
    figures["cost_stress_30bps"] = str(path.relative_to(paths.output_root))

    attribution_labels: list[str] = []
    attribution_values: list[float] = []
    for _, row in summary.iterrows():
        short_name = str(row["strategy"]).replace("size_", "").replace("_top100", "")
        attribution_labels.extend([f"{short_name} sell-failed", f"{short_name} suspended"])
        attribution_values.extend(
            [
                float(row["sell_failed_holding_pnl_total"]),
                float(row["suspended_holding_pnl_total"]),
            ]
        )
    path = paths.figures_root / "stateful_forced_state_pnl.png"
    draw_bar_chart(
        attribution_labels,
        attribution_values,
        path,
        "Forced-state PnL Attribution",
        "Sum of daily portfolio-return contributions",
    )
    figures["forced_state_pnl"] = str(path.relative_to(paths.output_root))

    if not rebalance.empty:
        monthly = rebalance.copy()
        monthly["month"] = monthly["exec_date"].str.slice(0, 7)
        holding_parts = []
        for strategy, group in monthly.groupby("strategy", sort=True):
            holding_parts.append(group.set_index("month")["post_holdings"].rename(strategy))
        holding_frame = pd.concat(holding_parts, axis=1) if holding_parts else pd.DataFrame()
        path = paths.figures_root / "stateful_post_rebalance_holdings.png"
        draw_multi_line_chart(holding_frame, path, "Post-rebalance Holdings", "Holdings after rebalance execution")
        figures["post_rebalance_holdings"] = str(path.relative_to(paths.output_root))
    return figures


def gate_table(summary: pd.DataFrame, regime_summary: pd.DataFrame) -> pd.DataFrame:
    positive_strategies = int((summary["ann_return"] > 0).sum()) if not summary.empty else 0
    buy_fail_ok = bool((summary["buy_fail_rate"].fillna(1.0) < 0.25).all()) if not summary.empty else False
    holdings_ok = bool((summary["median_holdings"].fillna(0.0) >= 80).all()) if not summary.empty else False
    regime_positive = 0
    if not regime_summary.empty:
        regime_positive = int((regime_summary["ann_return"] > 0).sum())
    regime_total = int(len(regime_summary)) if not regime_summary.empty else 0

    if positive_strategies == len(summary) and buy_fail_ok and holdings_ok:
        execution_status = "Green"
    elif positive_strategies >= 1 and holdings_ok:
        execution_status = "Yellow"
    else:
        execution_status = "Red"

    if regime_total and regime_positive >= max(1, regime_total // 2):
        regime_status = "Green"
    elif regime_positive > 0:
        regime_status = "Yellow"
    else:
        regime_status = "Red"

    returns_positive = bool((summary["ann_return"] > 0).all()) if not summary.empty else False
    cost_10_positive = (
        bool((summary["cost_stress_10bps_ann_return"] > 0).all())
        if "cost_stress_10bps_ann_return" in summary
        else False
    )
    cost_30_positive = (
        bool((summary["cost_stress_30bps_ann_return"] > 0).all())
        if "cost_stress_30bps_ann_return" in summary
        else False
    )
    forced_share = summary["forced_state_pnl_share"].abs().replace([np.inf, -np.inf], np.nan)
    forced_main_source = bool((forced_share.fillna(0.0) > 0.50).any()) if not summary.empty else False
    forced_material = bool((forced_share.fillna(0.0) > 0.25).any()) if not summary.empty else False
    large_drawdown = bool((summary["max_drawdown"].fillna(-1.0) < -0.55).any()) if not summary.empty else False
    weak_12m = bool((summary["worst_12m_return"].fillna(-1.0) < -0.35).any()) if not summary.empty else False
    if (not returns_positive) or (not cost_10_positive) or forced_main_source:
        risk_status = "Red"
    elif large_drawdown or weak_12m or (not cost_30_positive) or forced_material:
        risk_status = "Yellow"
    else:
        risk_status = "Green"

    return pd.DataFrame(
        [
            {
                "gate": "Stateful Execution Gate",
                "status": execution_status,
                "detail": "Monthly portfolio with failed buys as cash, failed sells held, and suspension days frozen.",
            },
            {
                "gate": "Stateful Regime Gate",
                "status": regime_status,
                "detail": f"Positive regime-strategy cells: {regime_positive}/{regime_total}.",
            },
            {
                "gate": "Risk Realism Gate",
                "status": risk_status,
                "detail": (
                    "Checks max drawdown, worst 12-month return, forced-state PnL attribution, "
                    "and simple 10/30bps turnover cost stress."
                ),
            },
        ]
    )


def render_report_zh(
    paths: Paths,
    summary: pd.DataFrame,
    regime_summary: pd.DataFrame,
    gates: pd.DataFrame,
    figures: dict[str, str],
) -> str:
    summary_view = pd.DataFrame(
        {
            "组合": summary["strategy"],
            "年化收益": summary["ann_return"].map(pct),
            "累计收益": summary["cumulative_return"].map(pct),
            "最大回撤": summary["max_drawdown"].map(pct),
            "最差12个月": summary["worst_12m_return"].map(pct),
            "30bps成本压力后年化": summary["cost_stress_30bps_ann_return"].map(pct),
            "买入失败率": summary["buy_fail_rate"].map(pct),
            "卖出失败率": summary["sell_fail_rate"].map(pct),
            "停牌持仓日": summary["suspended_position_days"],
        }
    )
    attribution_view = pd.DataFrame(
        {
            "组合": summary["strategy"],
            "正常持仓贡献": summary["normal_holding_pnl_total"].map(num),
            "买入日贡献": summary["entry_pnl_total"].map(num),
            "卖出开盘贡献": summary["sell_open_pnl_total"].map(num),
            "卖不出持仓贡献": summary["sell_failed_holding_pnl_total"].map(num),
            "停牌复牌贡献": summary["suspended_holding_pnl_total"].map(num),
            "强制状态贡献占比": summary["forced_state_pnl_share"].map(pct),
        }
    )
    cost_view = pd.DataFrame(
        {
            "组合": summary["strategy"],
            "裸年化": summary["ann_return"].map(pct),
            "10bps成本压力后年化": summary["cost_stress_10bps_ann_return"].map(pct),
            "30bps成本压力后年化": summary["cost_stress_30bps_ann_return"].map(pct),
        }
    )
    regime_view = regime_summary.copy()
    if not regime_view.empty:
        regime_view["ann_return"] = regime_view["ann_return"].map(pct)
        regime_view["max_drawdown"] = regime_view["max_drawdown"].map(pct)

    lines = [
        "# A股小盘 Pre Research v2：真实持仓状态机",
        "",
        "这份报告只做 execution realism 诊断，不做 RPE、多因子或参数优化。",
        "",
        "## 本次修正",
        "",
        "- v2 状态机的循环日期已经是实际执行日 D，因此新买入收益改为 D 日 `adj_close / adj_open - 1`。",
        "- `exec_oc_ret_1d` 仍适合 v1 fresh-entry 诊断：在 T 日特征行上看 T+1 open-to-close。",
        "- 新增 Risk Realism Gate：最大回撤、最差 12 个月、分阶段回撤、卖不出/停牌持仓归因、基础成本压力。",
        "",
        "## 组合设定",
        "",
        "- 样本：`2005-01-01` 到 `2025-12-31`。",
        "- 月度调仓：T 日收盘生成目标名单，T+1 执行。",
        "- 目标池只看两组：`size 5%-30% top100` 和 `size 10%-50% top100`。",
        "- T+1 买得到才进入，买不到留现金；调仓卖出遇到跌停或无 bar，卖不出则继续持有。",
        "- 停牌无 bar 日收益记 0，复牌日把停牌前最后一个复权 close 到复牌 close 的跳空收益/损失归到复牌日。",
        "- 单日组合收益按 100 个目标槽位计算，空仓槽位收益为 0。",
        "",
        "## Gate 摘要",
        "",
    ]
    for _, row in gates.iterrows():
        lines.append(f"- **{row['gate']}**：`{row['status']}` - {row['detail']}")
    lines.extend(
        [
            "",
            "## 关键结果",
            "",
            markdown_table(summary_view),
            "",
            "## 强制状态收益归因",
            "",
            markdown_table(attribution_view),
            "",
            "## 成本压力",
            "",
            markdown_table(cost_view),
            "",
            "## 分阶段结果",
            "",
            markdown_table(regime_view),
            "",
            "## PNG 图",
            "",
        ]
    )
    for key, rel in figures.items():
        lines.append(f"![{key}](figures/{Path(rel).name})")
        lines.append("")
    lines.extend(
        [
            "## 解读边界",
            "",
            "- 这仍然不是最终可部署策略，因为还没有纳入真实撮合、滑点、冲击成本和更细的复牌交易限制。",
            "- 这一版用于判断：小盘 gross edge 在最小真实状态机下是否还活着，以及风险是不是主要来自无法处理状态。",
            "- 如果 Risk Realism Gate 变红，就不应继续堆 RPE/quality；如果是黄灯，可以继续研究，但必须把 execution realism 和风险控制并行推进。",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run stateful monthly portfolio diagnostics.")
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--processed-root", default="processed")
    parser.add_argument("--output-root", default="outputs/pre_research_v2_stateful_portfolio")
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
    market_end = manifest["market"]["market_end_date"]
    build_adjusted_returns(paths, market_end=market_end, force=args.force_returns)

    log("load pre-research panel for monthly targets")
    panel, _ = load_pre_research_panel(paths)
    log("load state returns and status")
    returns, status = load_state_data(paths)
    calendar = pd.read_csv(paths.processed_root / "market_calendar.csv", dtype=str)
    dates = calendar[(calendar["trade_date"] >= WARMUP_START) & (calendar["trade_date"] <= RESEARCH_END)][
        "trade_date"
    ].tolist()

    all_daily = []
    all_rebalance = []
    all_summary = []
    for spec in STRATEGY_SPECS:
        log(f"simulate {spec['strategy']}")
        plans = build_rebalance_plans(panel, spec)
        _, daily, rebalance = simulate_stateful_portfolio(dates, plans, returns, status, spec["strategy"])
        all_daily.append(daily)
        all_rebalance.append(rebalance)
        all_summary.append(summarize_strategy(spec["strategy"], daily, rebalance))

    daily_returns = pd.concat(all_daily, ignore_index=True)
    rebalance_audit = pd.concat(all_rebalance, ignore_index=True)
    summary = pd.DataFrame(all_summary)
    regime_summary = summarize_regimes(daily_returns)
    gates = gate_table(summary, regime_summary)
    figures = make_figures(paths, daily_returns, summary, rebalance_audit)

    summary.to_csv(paths.tables_root / "stateful_summary.csv", index=False, encoding="utf-8")
    regime_summary.to_csv(paths.tables_root / "stateful_regime_summary.csv", index=False, encoding="utf-8")
    daily_returns.to_csv(paths.tables_root / "stateful_daily_returns.csv", index=False, encoding="utf-8")
    rebalance_audit.to_csv(paths.tables_root / "stateful_rebalance_audit.csv", index=False, encoding="utf-8")
    gates.to_csv(paths.tables_root / "stateful_gate_summary.csv", index=False, encoding="utf-8")

    report = render_report_zh(paths, summary, regime_summary, gates, figures)
    report_path = paths.output_root / "pre_research_v2_stateful_portfolio_zh.md"
    report_path.write_text(report, encoding="utf-8")
    log(f"wrote {report_path}")


if __name__ == "__main__":
    main()
