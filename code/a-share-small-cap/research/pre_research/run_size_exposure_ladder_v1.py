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

from run_execution_liquidity_guard_v1 import (  # noqa: E402
    build_execution_maps,
    drawdown_series,
    simulate_stateful_portfolio_fast,
)
from run_pre_research_v1 import (  # noqa: E402
    RESEARCH_END,
    RESEARCH_START,
    WARMUP_START,
    Paths,
    cumulative_return,
    draw_bar_chart,
    draw_multi_line_chart,
    load_pre_research_panel,
    log,
    markdown_table,
    num,
    pct,
    safe_annualized_return,
)
from run_pre_research_v2_stateful_portfolio import (  # noqa: E402
    COST_STRESS_RATES,
    MAX_NAMES,
    load_state_data,
    max_drawdown,
    worst_rolling_return,
)


BASELINE_STRATEGY = "baseline_p10_50_smallest100"
PERIODS = [
    ("full_sample", RESEARCH_START, RESEARCH_END),
    ("ex_2008", RESEARCH_START, RESEARCH_END),
    ("2008", "2008-01-01", "2008-12-31"),
    ("2014-2015", "2014-01-01", "2015-12-31"),
    ("2016-2018", "2016-01-01", "2018-12-31"),
    ("2022-2025", "2022-01-01", "2025-12-31"),
]


def annualized_vol(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return np.nan
    return float(values.std() * np.sqrt(252))


def sharpe_ratio(series: pd.Series) -> float:
    ann = safe_annualized_return(series)
    vol = annualized_vol(series)
    if not vol or not np.isfinite(vol):
        return np.nan
    return ann / vol


def calmar_ratio(series: pd.Series) -> float:
    ann = safe_annualized_return(series)
    mdd = max_drawdown(series)
    if not mdd or not np.isfinite(mdd):
        return np.nan
    return ann / abs(mdd)


def normalized_nav(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").fillna(0.0)
    if values.empty:
        return pd.Series(dtype=float)
    return (1.0 + values).cumprod()


def window_series(series: pd.Series, start: str, end: str, name: str = "") -> pd.Series:
    if series.empty:
        return series
    idx = series.index.astype(str)
    if name == "ex_2008":
        return series.loc[(idx < "2008-01-01") | (idx > "2008-12-31")]
    return series.loc[(idx >= start) & (idx <= end)]


def build_size_specs() -> list[dict[str, Any]]:
    return [
        {
            "strategy": BASELINE_STRATEGY,
            "label": "current p10-50 lower-edge",
            "min_pct": 0.10,
            "max_pct": 0.50,
            "select": "smallest",
            "role": "current",
        },
        {"strategy": "p10_20_top100", "label": "p10-20", "min_pct": 0.10, "max_pct": 0.20, "select": "smallest", "role": "small"},
        {"strategy": "p20_30_top100", "label": "p20-30", "min_pct": 0.20, "max_pct": 0.30, "select": "smallest", "role": "small_mid"},
        {"strategy": "p30_40_top100", "label": "p30-40", "min_pct": 0.30, "max_pct": 0.40, "select": "smallest", "role": "mid"},
        {"strategy": "p40_50_top100", "label": "p40-50", "min_pct": 0.40, "max_pct": 0.50, "select": "smallest", "role": "mid"},
        {"strategy": "p50_70_top100", "label": "p50-70", "min_pct": 0.50, "max_pct": 0.70, "select": "smallest", "role": "mid_large"},
        {"strategy": "p70_90_top100", "label": "p70-90", "min_pct": 0.70, "max_pct": 0.90, "select": "smallest", "role": "large"},
        {"strategy": "p90_100_top100", "label": "p90-100 lower-edge", "min_pct": 0.90, "max_pct": 1.00, "select": "smallest", "role": "large"},
        {"strategy": "top100_largest", "label": "largest top100", "min_pct": 0.00, "max_pct": 1.00, "select": "largest", "role": "mega"},
        {"strategy": "p20_50_smallest100", "label": "p20-50 lower-edge", "min_pct": 0.20, "max_pct": 0.50, "select": "smallest", "role": "candidate_core"},
        {"strategy": "p30_70_smallest100", "label": "p30-70 lower-edge", "min_pct": 0.30, "max_pct": 0.70, "select": "smallest", "role": "candidate_core"},
        {"strategy": "p50_100_smallest100", "label": "p50-100 lower-edge", "min_pct": 0.50, "max_pct": 1.00, "select": "smallest", "role": "candidate_core"},
    ]


def monthly_signal_dates(panel: pd.DataFrame) -> list[str]:
    signal_dates = pd.Series(sorted(panel["feature_date"].dropna().unique()))
    signal_dates = signal_dates[(signal_dates >= RESEARCH_START) & (signal_dates <= RESEARCH_END)]
    return signal_dates.groupby(signal_dates.str.slice(0, 7)).tail(1).tolist()


def build_monthly_panel(panel: pd.DataFrame) -> dict[str, pd.DataFrame]:
    signal_dates = monthly_signal_dates(panel)
    monthly_panel = panel[panel["feature_date"].isin(set(signal_dates))].copy()
    return {str(date): group.copy() for date, group in monthly_panel.groupby("feature_date", sort=True)}


def select_candidates(frame: pd.DataFrame, spec: dict[str, Any]) -> pd.DataFrame:
    subset = frame[
        frame["base_universe"]
        & frame["size_pct"].gt(float(spec["min_pct"]))
        & frame["size_pct"].le(float(spec["max_pct"]))
    ].copy()
    if subset.empty:
        return subset
    if spec["select"] == "largest":
        return subset.nlargest(MAX_NAMES, "float_market_cap")
    return subset.nsmallest(MAX_NAMES, "float_market_cap")


def build_plans(monthly_panel: dict[str, pd.DataFrame], spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    plans: dict[str, dict[str, Any]] = {}
    for signal_date, frame in monthly_panel.items():
        exec_dates = frame["exec_date"].dropna().unique().tolist()
        if not exec_dates:
            continue
        exec_date = sorted(exec_dates)[0]
        if exec_date > RESEARCH_END:
            continue
        base_pool = frame[
            frame["base_universe"]
            & frame["size_pct"].gt(float(spec["min_pct"]))
            & frame["size_pct"].le(float(spec["max_pct"]))
        ].copy()
        target = select_candidates(frame, spec)
        plans[exec_date] = {
            "signal_date": signal_date,
            "exec_date": exec_date,
            "target": target["code"].tolist(),
            "candidate_count": int(len(base_pool)),
            "guard_pass_count": int(len(target)),
            "guard_fail_count": int(max(len(base_pool) - len(target), 0)),
            "median_amount_20d": float(target["amount_20d_mean"].median()) if not target.empty else np.nan,
            "median_float_market_cap": float(target["float_market_cap"].median()) if not target.empty else np.nan,
        }
    return plans


def cost_stressed_return(daily: pd.DataFrame, bps: str = "30bps") -> pd.Series:
    returns = daily.set_index("date")["daily_return"]
    turnover = daily.set_index("date")["turnover_rate"]
    return returns - turnover * COST_STRESS_RATES[bps]


def summarize_strategy(strategy: str, label: str, role: str, daily: pd.DataFrame, rebalance: pd.DataFrame) -> dict[str, Any]:
    returns = daily.set_index("date")["daily_return"] if not daily.empty else pd.Series(dtype=float)
    stressed = cost_stressed_return(daily, "30bps") if not daily.empty else pd.Series(dtype=float)
    ex2008 = window_series(returns, RESEARCH_START, RESEARCH_END, "ex_2008")
    y2008 = window_series(returns, "2008-01-01", "2008-12-31")
    y2014 = window_series(returns, "2014-01-01", "2015-12-31")
    y2016 = window_series(returns, "2016-01-01", "2018-12-31")
    y2022 = window_series(returns, "2022-01-01", "2025-12-31")
    buy_attempts = int(rebalance["bought"].sum() + rebalance["buy_failed"].sum()) if not rebalance.empty else 0
    sell_attempts = int(rebalance["sold"].sum() + rebalance["sell_failed"].sum()) if not rebalance.empty else 0
    forced_state_pnl = (
        float(daily["sell_failed_holding_pnl"].sum() + daily["suspended_holding_pnl"].sum())
        if not daily.empty
        else np.nan
    )
    return {
        "strategy": strategy,
        "label": label,
        "role": role,
        "ann_return": safe_annualized_return(returns),
        "cost_30bps_ann_return": safe_annualized_return(stressed),
        "cumulative_return": cumulative_return(returns),
        "max_drawdown": max_drawdown(returns),
        "max_drawdown_ex_2008": max_drawdown(ex2008),
        "worst_12m": worst_rolling_return(returns),
        "worst_12m_ex_2008": worst_rolling_return(ex2008),
        "ann_vol": annualized_vol(returns),
        "sharpe": sharpe_ratio(returns),
        "calmar": calmar_ratio(returns),
        "2008_ann_return": safe_annualized_return(y2008),
        "2008_max_drawdown": max_drawdown(y2008),
        "2014_2015_ann_return": safe_annualized_return(y2014),
        "2014_2015_max_drawdown": max_drawdown(y2014),
        "2016_2018_ann_return": safe_annualized_return(y2016),
        "2016_2018_max_drawdown": max_drawdown(y2016),
        "2022_2025_ann_return": safe_annualized_return(y2022),
        "2022_2025_max_drawdown": max_drawdown(y2022),
        "turnover": float(daily["turnover_rate"].mean()) if not daily.empty else np.nan,
        "buy_fail_rate": int(rebalance["buy_failed"].sum()) / buy_attempts if buy_attempts else np.nan,
        "sell_fail_rate": int(rebalance["sell_failed"].sum()) / sell_attempts if sell_attempts else np.nan,
        "forced_state_pnl": forced_state_pnl,
        "suspended_position_days": int(daily["suspended_positions"].sum()) if not daily.empty else 0,
        "median_holdings": float(daily["holdings"].median()) if not daily.empty else np.nan,
        "median_cash_slots": float(daily["cash_slots"].median()) if not daily.empty else np.nan,
        "median_target_count": float(rebalance["target_count"].median()) if not rebalance.empty else np.nan,
        "median_candidate_count": float(rebalance["candidate_count"].median()) if not rebalance.empty else np.nan,
        "median_amount_20d": float(rebalance["median_amount_20d"].median()) if not rebalance.empty else np.nan,
        "median_float_mcap": float(rebalance["median_float_market_cap"].median()) if not rebalance.empty else np.nan,
    }


def summarize_periods(daily: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for strategy, group in daily.groupby("strategy", sort=False):
        label = str(group["label"].iloc[0])
        role = str(group["role"].iloc[0])
        returns = group.set_index("date")["daily_return"]
        for period, start, end in PERIODS:
            window = window_series(returns, start, end, period)
            rows.append(
                {
                    "strategy": strategy,
                    "label": label,
                    "role": role,
                    "period": period,
                    "ann_return": safe_annualized_return(window),
                    "cumulative_return": cumulative_return(window),
                    "max_drawdown": max_drawdown(window),
                    "worst_12m": worst_rolling_return(window),
                    "sharpe": sharpe_ratio(window),
                    "calmar": calmar_ratio(window),
                    "observations": int(window.notna().sum()),
                }
            )
    return pd.DataFrame(rows)


def run_ladder(
    monthly_panel: dict[str, pd.DataFrame],
    specs: list[dict[str, Any]],
    dates: list[str],
    maps: dict[str, pd.Series],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    daily_parts: list[pd.DataFrame] = []
    rebalance_parts: list[pd.DataFrame] = []
    summary_rows: list[dict[str, Any]] = []
    for spec in specs:
        log(f"simulate {spec['strategy']}")
        plans = build_plans(monthly_panel, spec)
        daily, rebalance = simulate_stateful_portfolio_fast(dates, plans, maps, spec["strategy"])
        daily["label"] = spec["label"]
        daily["role"] = spec["role"]
        rebalance["label"] = spec["label"]
        rebalance["role"] = spec["role"]
        daily_parts.append(daily)
        rebalance_parts.append(rebalance)
        summary_rows.append(summarize_strategy(spec["strategy"], spec["label"], spec["role"], daily, rebalance))
    daily_all = pd.concat(daily_parts, ignore_index=True) if daily_parts else pd.DataFrame()
    rebalance_all = pd.concat(rebalance_parts, ignore_index=True) if rebalance_parts else pd.DataFrame()
    return daily_all, rebalance_all, pd.DataFrame(summary_rows)


def make_figures(paths: Paths, daily: pd.DataFrame, summary: pd.DataFrame) -> dict[str, str]:
    figures: dict[str, str] = {}
    focus_order = [
        BASELINE_STRATEGY,
        "p20_30_top100",
        "p30_40_top100",
        "p40_50_top100",
        "p50_70_top100",
        "p70_90_top100",
        "top100_largest",
    ]
    nav_parts: list[pd.Series] = []
    dd_parts: list[pd.Series] = []
    for strategy in focus_order:
        group = daily[daily["strategy"].eq(strategy)]
        if group.empty:
            continue
        label = str(group["label"].iloc[0])
        series = group.set_index("date")["daily_return"].fillna(0.0)
        nav_parts.append(normalized_nav(series).rename(label))
        dd_parts.append(drawdown_series(series).rename(label))
    nav = pd.concat(nav_parts, axis=1) if nav_parts else pd.DataFrame()
    dd = pd.concat(dd_parts, axis=1) if dd_parts else pd.DataFrame()

    path = paths.figures_root / "size_ladder_nav.png"
    draw_multi_line_chart(nav, path, "Size Exposure Ladder NAV", "Same monthly stateful engine, different size bands")
    figures["nav"] = str(path.relative_to(paths.output_root))

    path = paths.figures_root / "size_ladder_drawdown.png"
    draw_multi_line_chart(dd, path, "Size Exposure Ladder Drawdown", "Drawdown from running peak")
    figures["drawdown"] = str(path.relative_to(paths.output_root))

    ordered = summary.copy()
    labels = ordered["label"].tolist()
    chart_cols = [
        ("ann_return", "size_ladder_ann_return.png", "Annualized Return", "stateful"),
        ("cost_30bps_ann_return", "size_ladder_30bps_ann_return.png", "30bps Cost-stressed Annualized Return", "stateful"),
        ("max_drawdown", "size_ladder_max_drawdown.png", "Max Drawdown", "stateful"),
        ("sharpe", "size_ladder_sharpe.png", "Sharpe", "annual return / annual vol"),
        ("calmar", "size_ladder_calmar.png", "Calmar", "annual return / abs(MDD)"),
        ("2016_2018_max_drawdown", "size_ladder_2016_2018_mdd.png", "2016-2018 Max Drawdown", "stateful"),
        ("sell_fail_rate", "size_ladder_sell_fail_rate.png", "Sell Fail Rate", "failed sells / sell attempts"),
        ("median_amount_20d", "size_ladder_median_amount20.png", "Median 20D Amount", "CNY"),
    ]
    for col, file_name, title, subtitle in chart_cols:
        path = paths.figures_root / file_name
        draw_bar_chart(labels, ordered[col].tolist(), path, title, subtitle)
        figures[col] = str(path.relative_to(paths.output_root))
    return figures


def format_summary(frame: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "size_exposure": frame["label"],
            "ann": frame["ann_return"].map(pct),
            "30bps_ann": frame["cost_30bps_ann_return"].map(pct),
            "vol": frame["ann_vol"].map(pct),
            "sharpe": frame["sharpe"].map(num),
            "calmar": frame["calmar"].map(num),
            "mdd": frame["max_drawdown"].map(pct),
            "ex08_mdd": frame["max_drawdown_ex_2008"].map(pct),
            "worst12m_ex08": frame["worst_12m_ex_2008"].map(pct),
            "2016_18_ann": frame["2016_2018_ann_return"].map(pct),
            "2016_18_mdd": frame["2016_2018_max_drawdown"].map(pct),
            "sell_fail": frame["sell_fail_rate"].map(pct),
            "forced_pnl": frame["forced_state_pnl"].map(num),
            "median_amt20": frame["median_amount_20d"].map(num),
            "median_mcap": frame["median_float_mcap"].map(num),
        }
    )


def format_periods(frame: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "size_exposure": frame["label"],
            "period": frame["period"],
            "ann": frame["ann_return"].map(pct),
            "cum_ret": frame["cumulative_return"].map(pct),
            "mdd": frame["max_drawdown"].map(pct),
            "sharpe": frame["sharpe"].map(num),
            "calmar": frame["calmar"].map(num),
        }
    )


def render_report(summary: pd.DataFrame, periods: pd.DataFrame, figures: dict[str, str]) -> str:
    ordered = summary.copy()
    candidate = ordered[
        ordered["strategy"].isin(
            [
                BASELINE_STRATEGY,
                "p20_30_top100",
                "p30_40_top100",
                "p40_50_top100",
                "p50_70_top100",
                "p70_90_top100",
                "top100_largest",
                "p20_50_smallest100",
                "p30_70_smallest100",
                "p50_100_smallest100",
            ]
        )
    ].copy()
    calmar_rank = candidate.sort_values("calmar", ascending=False).head(5)
    sharpe_rank = candidate.sort_values("sharpe", ascending=False).head(5)
    periods_focus = periods[
        periods["strategy"].isin([BASELINE_STRATEGY, "p30_40_top100", "p50_70_top100", "p70_90_top100", "top100_largest"])
    ].copy()

    lines: list[str] = [
        "# A股 Size Exposure Ladder v1",
        "",
        "本报告不是新 alpha 策略，而是 market exposure diagnostic：在同样月频、同样最多 100 只、同样 stateful 执行口径下，只改变 size exposure。",
        "",
        "## 研究问题",
        "",
        "- 当前小盘 baseline 的高 MDD 是可通过选股过滤修复，还是 size exposure 的入场费？",
        "- 如果从小盘下沿迁移到中盘/大盘，Sharpe、Calmar、MDD、执行风险如何变化？",
        "- 对偏好高 Sharpe / 高 Calmar 的个人资金来说，哪个 size exposure 更像 core，哪个更像 satellite？",
        "",
        "## 口径说明",
        "",
        "- 当前 baseline 是 `p10-50` 区间里最小的 100 只，所以报告中称为 `current p10-50 lower-edge`。",
        "- 其他 size band 也采用每月最多 100 只、等权、T+1 stateful 执行；大多数 band 选该 band 内市值较小的 100 只，`largest top100` 单独表示全市场最大 100 只。",
        "- 指标重点不是年化最高，而是 Sharpe / Calmar / MDD / worst12m / sell fail。",
        "",
        "## 图表",
        "",
    ]
    for key, rel in figures.items():
        lines.append(f"- {key}: `{rel}`")
    lines.extend(
        [
            "",
            "## Size Exposure 总表",
            "",
            markdown_table(format_summary(ordered), max_rows=None),
            "",
            "## Calmar 前五",
            "",
            markdown_table(format_summary(calmar_rank), max_rows=None),
            "",
            "## Sharpe 前五",
            "",
            markdown_table(format_summary(sharpe_rank), max_rows=None),
            "",
            "## 关键阶段复核",
            "",
            markdown_table(format_periods(periods_focus), max_rows=None),
            "",
            "## 初步解释框架",
            "",
            "1. 如果中大市值的 Sharpe / Calmar 明显高于当前 baseline，说明小盘不是天然 core，只是高收益 satellite。",
            "2. 如果所有 size exposure 的 MDD 都高，说明主要约束不是 size，而是 long-only market beta。",
            "3. 如果中大市值执行指标明显更好但收益塌陷，说明可部署性提高，但 gross edge 不足。",
            "4. 如果中盘兼具较好 Calmar 和可接受年化，下一步才值得研究 smart beta，而不是继续修小盘 MDD。",
            "",
            "## 输出文件",
            "",
            "- `tables/size_ladder_summary.csv`",
            "- `tables/size_ladder_period_summary.csv`",
            "- `tables/size_ladder_daily_returns.csv`",
            "- `tables/size_ladder_rebalance_audit.csv`",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run size exposure ladder diagnostic v1.")
    parser.add_argument("--processed-root", default="processed")
    parser.add_argument("--output-root", default="outputs/size_exposure_ladder_v1")
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
    log("cache monthly panel")
    monthly_panel = build_monthly_panel(panel)
    specs = build_size_specs()

    log("load state execution data")
    returns, status = load_state_data(paths)
    log("build reusable execution maps")
    maps = build_execution_maps(returns, status)
    del returns, status

    calendar = pd.read_csv(paths.processed_root / "market_calendar.csv", dtype=str)
    dates = calendar[(calendar["trade_date"] >= WARMUP_START) & (calendar["trade_date"] <= RESEARCH_END)][
        "trade_date"
    ].tolist()

    daily, rebalance, summary = run_ladder(monthly_panel, specs, dates, maps)
    periods = summarize_periods(daily)
    figures = make_figures(paths, daily, summary)
    report = render_report(summary, periods, figures)

    log("write outputs")
    summary.to_csv(paths.tables_root / "size_ladder_summary.csv", index=False, encoding="utf-8")
    periods.to_csv(paths.tables_root / "size_ladder_period_summary.csv", index=False, encoding="utf-8")
    daily.to_csv(paths.tables_root / "size_ladder_daily_returns.csv", index=False, encoding="utf-8")
    rebalance.to_csv(paths.tables_root / "size_ladder_rebalance_audit.csv", index=False, encoding="utf-8")
    report_path = paths.output_root / "size_exposure_ladder_v1_zh.md"
    report_path.write_text(report, encoding="utf-8")
    log(f"wrote {report_path}")


if __name__ == "__main__":
    main()
