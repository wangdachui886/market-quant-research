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
    REGIMES,
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
    MAX_NAMES,
    bool_get,
    build_rebalance_plans,
    float_get,
    load_state_data,
    make_series_map,
    max_drawdown,
    worst_rolling_return,
)


BASELINE_STRATEGY = "size_10_50_top100"
BASELINE_SPEC = {
    "strategy": BASELINE_STRATEGY,
    "label": "size 10%-50% smallest float market cap top100",
    "min_pct": 0.10,
    "max_pct": 0.50,
}
CRITICAL_WINDOWS = [
    ("full_sample", RESEARCH_START, RESEARCH_END),
    ("max_drawdown_window", "event", "event"),
    ("worst_12m_window", "event", "event"),
    ("ex_2008", RESEARCH_START, RESEARCH_END),
    ("2008", "2008-01-01", "2008-12-31"),
    ("2016-2018", "2016-01-01", "2018-12-31"),
    ("2022-2025", "2022-01-01", "2025-12-31"),
]


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


def max_drawdown_event(series: pd.Series) -> dict[str, Any]:
    values = pd.to_numeric(series, errors="coerce").fillna(0.0)
    nav = normalized_nav(values)
    peak = nav.cummax()
    dd = nav / peak - 1.0
    trough_date = str(dd.idxmin())
    peak_date = str(nav.loc[:trough_date].idxmax())
    peak_nav = float(nav.loc[peak_date])
    trough_nav = float(nav.loc[trough_date])
    return {
        "event": "max_drawdown",
        "start_date": peak_date,
        "end_date": trough_date,
        "drawdown": trough_nav / peak_nav - 1.0 if peak_nav else np.nan,
        "days": int(values.loc[peak_date:trough_date].shape[0]),
    }


def worst_12m_event(series: pd.Series, window: int = 252) -> dict[str, Any]:
    values = pd.to_numeric(series, errors="coerce").fillna(0.0)
    if len(values) < window:
        return {"event": "worst_12m", "start_date": "", "end_date": "", "return": np.nan, "days": 0}
    rolling = (1.0 + values).rolling(window).apply(np.prod, raw=True) - 1.0
    end_date = str(rolling.idxmin())
    end_pos = values.index.get_loc(end_date)
    start_date = str(values.index[max(0, end_pos - window + 1)])
    return {
        "event": "worst_12m",
        "start_date": start_date,
        "end_date": end_date,
        "return": float(rolling.loc[end_date]),
        "days": int(window),
    }


def build_style_returns(bucket_returns: pd.DataFrame) -> pd.DataFrame:
    frame = bucket_returns.copy()
    frame.index = frame.index.astype(str)
    for col in frame.columns:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    style = pd.DataFrame(index=frame.index)
    style["market_bucket_eq_cc"] = frame.mean(axis=1)
    style["micro_00_10_cc"] = frame[["p00_05", "p05_10"]].mean(axis=1)
    style["size_10_50_cc"] = frame[["p10_20", "p20_30", "p30_50"]].mean(axis=1)
    style["core_p10_20_cc"] = frame["p10_20"]
    style["large_50_100_cc"] = frame["p50_100"]
    style["size_minus_large_cc"] = style["size_10_50_cc"] - style["large_50_100_cc"]
    style["core_minus_large_cc"] = style["core_p10_20_cc"] - style["large_50_100_cc"]
    return style


def in_window(index: pd.Index, start: str, end: str, name: str = "") -> pd.Series:
    idx = index.astype(str)
    if name == "ex_2008":
        return (idx < "2008-01-01") | (idx > "2008-12-31")
    return (idx >= start) & (idx <= end)


def series_window(series: pd.Series, start: str, end: str, name: str = "") -> pd.Series:
    if series.empty:
        return series
    mask = in_window(series.index, start, end, name)
    return series.loc[mask]


def frame_window(frame: pd.DataFrame, date_col: str, start: str, end: str, name: str = "") -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    dates = frame[date_col].astype(str)
    if name == "ex_2008":
        return frame[(dates < "2008-01-01") | (dates > "2008-12-31")].copy()
    return frame[(dates >= start) & (dates <= end)].copy()


def simulate_baseline_code_contributions(
    dates: list[str],
    plans: dict[str, dict[str, Any]],
    returns: pd.DataFrame,
    status: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
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
    event_rows: list[dict[str, Any]] = []
    sell_fail_rows: list[dict[str, Any]] = []

    for date in dates:
        if date < RESEARCH_START or date > RESEARCH_END:
            continue
        plan = plans.get(date)
        sold: set[str] = set()
        sell_failed: set[str] = set()
        bought: set[str] = set()
        buy_failed: set[str] = set()

        if plan is not None:
            target = list(plan["target"])
            target_set = set(target)
            forced_hold_codes.difference_update(target_set)
            for code in sorted(holdings - target_set):
                if bool_get(can_sell, date, code, False):
                    sold.add(code)
                else:
                    sell_failed.add(code)
                    sell_fail_rows.append(
                        {
                            "date": date,
                            "signal_date": plan["signal_date"],
                            "code": code,
                            "has_bar_on_exec": bool_get(has_bar, date, code, False),
                            "can_sell_on_exec": bool_get(can_sell, date, code, False),
                        }
                    )
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
        else:
            holdings_after_sells = set(holdings)

        entry_sum = 0.0
        sell_open_sum = 0.0
        normal_holding_sum = 0.0
        sell_failed_holding_sum = 0.0
        suspended_holding_sum = 0.0
        suspended_positions = 0

        for code in sold:
            contribution = float_get(sell_open_ret, date, code, 0.0) / MAX_NAMES
            sell_open_sum += contribution
            event_rows.append(
                {
                    "date": date,
                    "code": code,
                    "component": "sell_open",
                    "contribution": contribution,
                    "forced_state": False,
                    "is_rebalance": plan is not None,
                }
            )
            suspended_codes.discard(code)

        post_holdings = holdings_after_sells | bought
        for code in sorted(post_holdings):
            if code in bought:
                contribution = float_get(entry_ret, date, code, 0.0) / MAX_NAMES
                entry_sum += contribution
                component = "entry"
                forced = False
                suspended_codes.discard(code)
            elif bool_get(has_bar, date, code, False):
                contribution = float_get(holding_ret, date, code, 0.0) / MAX_NAMES
                if code in suspended_codes:
                    suspended_holding_sum += contribution
                    component = "suspended_reopen"
                    forced = True
                    suspended_codes.discard(code)
                elif code in forced_hold_codes:
                    sell_failed_holding_sum += contribution
                    component = "sell_failed_holding"
                    forced = True
                else:
                    normal_holding_sum += contribution
                    component = "normal_holding"
                    forced = False
            else:
                contribution = 0.0
                suspended_positions += 1
                suspended_codes.add(code)
                component = "suspended_no_bar"
                forced = True
            event_rows.append(
                {
                    "date": date,
                    "code": code,
                    "component": component,
                    "contribution": contribution,
                    "forced_state": forced,
                    "is_rebalance": plan is not None,
                }
            )

        turnover_rate = (len(bought) + len(sold)) / MAX_NAMES
        portfolio_return = entry_sum + sell_open_sum + normal_holding_sum + sell_failed_holding_sum + suspended_holding_sum
        holdings = post_holdings
        forced_hold_codes.intersection_update(holdings)
        suspended_codes.intersection_update(holdings)
        daily_rows.append(
            {
                "date": date,
                "daily_return": portfolio_return,
                "entry_pnl": entry_sum,
                "sell_open_pnl": sell_open_sum,
                "normal_holding_pnl": normal_holding_sum,
                "sell_failed_holding_pnl": sell_failed_holding_sum,
                "suspended_holding_pnl": suspended_holding_sum,
                "turnover_rate": turnover_rate,
                "holdings": len(holdings),
                "cash_slots": MAX_NAMES - len(holdings),
                "suspended_positions": suspended_positions,
                "is_rebalance": plan is not None,
                "bought": len(bought),
                "buy_failed": len(buy_failed),
                "sold": len(sold),
                "sell_failed": len(sell_failed),
            }
        )

    return pd.DataFrame(daily_rows), pd.DataFrame(event_rows), pd.DataFrame(sell_fail_rows)


def build_periods(events: pd.DataFrame) -> list[dict[str, str]]:
    max_dd = events[events["event"].eq("max_drawdown")].iloc[0].to_dict()
    worst = events[events["event"].eq("worst_12m")].iloc[0].to_dict()
    rows = []
    for name, start, end in CRITICAL_WINDOWS:
        if name == "max_drawdown_window":
            rows.append({"period": name, "start_date": str(max_dd["start_date"]), "end_date": str(max_dd["end_date"])})
        elif name == "worst_12m_window":
            rows.append({"period": name, "start_date": str(worst["start_date"]), "end_date": str(worst["end_date"])})
        else:
            rows.append({"period": name, "start_date": start, "end_date": end})
    for regime, start, end in REGIMES:
        if regime not in {row["period"] for row in rows}:
            rows.append({"period": regime, "start_date": start, "end_date": end})
    return rows


def code_concentration(event_rows: pd.DataFrame, periods: list[dict[str, str]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    top_rows = []
    pnl_events = event_rows[event_rows["component"].ne("suspended_no_bar")].copy()
    for item in periods:
        name, start, end = item["period"], item["start_date"], item["end_date"]
        window = frame_window(pnl_events, "date", start, end, name)
        code_pnl = window.groupby("code", sort=True)["contribution"].sum().sort_values()
        negatives = code_pnl[code_pnl < 0]
        gross_loss = float(-negatives.sum()) if not negatives.empty else 0.0
        top1 = float(-negatives.iloc[:1].sum()) if len(negatives) else 0.0
        top5 = float(-negatives.iloc[:5].sum()) if len(negatives) else 0.0
        top10 = float(-negatives.iloc[:10].sum()) if len(negatives) else 0.0
        rows.append(
            {
                "period": name,
                "start_date": start,
                "end_date": end,
                "total_code_contribution": float(window["contribution"].sum()) if not window.empty else np.nan,
                "gross_negative_code_contribution": -gross_loss,
                "loss_code_count": int(len(negatives)),
                "top1_loss": -top1,
                "top5_loss": -top5,
                "top10_loss": -top10,
                "top1_loss_share": top1 / gross_loss if gross_loss else np.nan,
                "top5_loss_share": top5 / gross_loss if gross_loss else np.nan,
                "top10_loss_share": top10 / gross_loss if gross_loss else np.nan,
                "worst_code": str(negatives.index[0]) if len(negatives) else "",
                "worst_code_contribution": float(negatives.iloc[0]) if len(negatives) else np.nan,
            }
        )
        for rank, (code, contribution) in enumerate(negatives.iloc[:20].items(), 1):
            top_rows.append(
                {
                    "period": name,
                    "rank": rank,
                    "code": code,
                    "contribution": float(contribution),
                }
            )
    return pd.DataFrame(rows), pd.DataFrame(top_rows)


def summarize_periods(
    daily: pd.DataFrame,
    rebalance: pd.DataFrame,
    style: pd.DataFrame,
    periods: list[dict[str, str]],
    concentration: pd.DataFrame,
    sell_fail_events: pd.DataFrame,
) -> pd.DataFrame:
    baseline = daily.set_index("date")["daily_return"].sort_index()
    rows = []
    for item in periods:
        name, start, end = item["period"], item["start_date"], item["end_date"]
        daily_window = frame_window(daily, "date", start, end, name)
        rebalance_window = frame_window(rebalance, "exec_date", start, end, name)
        sell_fail_window = frame_window(sell_fail_events, "date", start, end, name)
        base_series = series_window(baseline, start, end, name)
        style_window = style.loc[in_window(style.index, start, end, name)].copy()
        buy_attempts = int(rebalance_window["bought"].sum() + rebalance_window["buy_failed"].sum()) if not rebalance_window.empty else 0
        sell_attempts = int(rebalance_window["sold"].sum() + rebalance_window["sell_failed"].sum()) if not rebalance_window.empty else 0
        total_simple_pnl = float(daily_window["daily_return"].sum()) if not daily_window.empty else np.nan
        forced_pnl = (
            float(daily_window["sell_failed_holding_pnl"].sum() + daily_window["suspended_holding_pnl"].sum())
            if not daily_window.empty
            else np.nan
        )
        forced_loss_share = (
            (-forced_pnl) / (-total_simple_pnl)
            if pd.notna(total_simple_pnl) and total_simple_pnl < 0 and pd.notna(forced_pnl) and forced_pnl < 0
            else np.nan
        )
        conc = concentration[concentration["period"].eq(name)]
        conc_row = conc.iloc[0].to_dict() if not conc.empty else {}
        rows.append(
            {
                "period": name,
                "start_date": start,
                "end_date": end,
                "observations": int(base_series.notna().sum()),
                "baseline_ann_return": safe_annualized_return(base_series),
                "baseline_cumulative_return": cumulative_return(base_series),
                "baseline_max_drawdown": max_drawdown(base_series),
                "baseline_worst_12m": worst_rolling_return(base_series),
                "market_ann_return": safe_annualized_return(style_window["market_bucket_eq_cc"]),
                "market_cumulative_return": cumulative_return(style_window["market_bucket_eq_cc"]),
                "market_max_drawdown": max_drawdown(style_window["market_bucket_eq_cc"]),
                "large_ann_return": safe_annualized_return(style_window["large_50_100_cc"]),
                "large_cumulative_return": cumulative_return(style_window["large_50_100_cc"]),
                "large_max_drawdown": max_drawdown(style_window["large_50_100_cc"]),
                "size_10_50_ann_return": safe_annualized_return(style_window["size_10_50_cc"]),
                "size_10_50_cumulative_return": cumulative_return(style_window["size_10_50_cc"]),
                "core_p10_20_ann_return": safe_annualized_return(style_window["core_p10_20_cc"]),
                "size_minus_large_ann_spread": safe_annualized_return(style_window["size_minus_large_cc"]),
                "core_minus_large_ann_spread": safe_annualized_return(style_window["core_minus_large_cc"]),
                "baseline_minus_market_daily_sum": float((base_series - style_window["market_bucket_eq_cc"]).sum()),
                "baseline_minus_size_10_50_daily_sum": float((base_series - style_window["size_10_50_cc"]).sum()),
                "entry_pnl": float(daily_window["entry_pnl"].sum()) if not daily_window.empty else np.nan,
                "sell_open_pnl": float(daily_window["sell_open_pnl"].sum()) if not daily_window.empty else np.nan,
                "normal_holding_pnl": float(daily_window["normal_holding_pnl"].sum()) if not daily_window.empty else np.nan,
                "sell_failed_holding_pnl": float(daily_window["sell_failed_holding_pnl"].sum()) if not daily_window.empty else np.nan,
                "suspended_holding_pnl": float(daily_window["suspended_holding_pnl"].sum()) if not daily_window.empty else np.nan,
                "forced_state_pnl": forced_pnl,
                "forced_loss_share_when_losing": forced_loss_share,
                "buy_fail_rate": int(rebalance_window["buy_failed"].sum()) / buy_attempts if buy_attempts else np.nan,
                "sell_fail_rate": int(rebalance_window["sell_failed"].sum()) / sell_attempts if sell_attempts else np.nan,
                "sell_fail_no_bar_rate": float((~sell_fail_window["has_bar_on_exec"].astype(bool)).mean())
                if not sell_fail_window.empty
                else np.nan,
                "sell_fail_events": int(len(sell_fail_window)),
                "suspended_position_days": int(daily_window["suspended_positions"].sum()) if not daily_window.empty else 0,
                "avg_suspended_positions": float(daily_window["suspended_positions"].mean()) if not daily_window.empty else np.nan,
                "max_suspended_positions": int(daily_window["suspended_positions"].max()) if not daily_window.empty else 0,
                "median_amount_20d": float(rebalance_window["median_amount_20d"].median()) if not rebalance_window.empty else np.nan,
                "median_float_mcap": float(rebalance_window["median_float_market_cap"].median()) if not rebalance_window.empty else np.nan,
                "rebalance_count": int(len(rebalance_window)),
                "top10_loss_share": conc_row.get("top10_loss_share", np.nan),
                "top5_loss_share": conc_row.get("top5_loss_share", np.nan),
                "worst_code": conc_row.get("worst_code", ""),
                "worst_code_contribution": conc_row.get("worst_code_contribution", np.nan),
            }
        )
    return pd.DataFrame(rows)


def classify_risk_sources(periods: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in periods.iterrows():
        losing = bool(row["baseline_cumulative_return"] < 0 or row["baseline_max_drawdown"] < -0.25)
        market_beta = bool(row["market_cumulative_return"] < 0 and row["large_cumulative_return"] < 0)
        small_relative = bool(row["size_minus_large_ann_spread"] < 0 or row["core_minus_large_ann_spread"] < 0)
        execution = bool(
            (pd.notna(row["forced_loss_share_when_losing"]) and row["forced_loss_share_when_losing"] > 0.15)
            or row["sell_fail_rate"] > 0.15
            or row["avg_suspended_positions"] > 1.5
        )
        liquidity = bool(
            row["sell_fail_rate"] > 0.15
            or row["sell_fail_no_bar_rate"] > 0.70
            or row["max_suspended_positions"] >= 10
        )
        idio = bool(pd.notna(row["top10_loss_share"]) and row["top10_loss_share"] > 0.20)
        rows.append(
            {
                "period": row["period"],
                "losing_or_deep_drawdown": losing,
                "market_beta_drawdown": market_beta,
                "small_cap_relative_drawdown": small_relative,
                "execution_drawdown": execution,
                "liquidity_crash": liquidity,
                "idiosyncratic_concentration": idio,
                "primary_read": primary_read(row, market_beta, small_relative, execution, liquidity, idio),
            }
        )
    return pd.DataFrame(rows)


def primary_read(
    row: pd.Series,
    market_beta: bool,
    small_relative: bool,
    execution: bool,
    liquidity: bool,
    idio: bool,
) -> str:
    if row["period"] in {"max_drawdown_window", "2008"} and market_beta:
        return "systemic_beta_first"
    if row["period"] == "2016-2018" and execution:
        return "weak_market_plus_execution"
    if market_beta and not small_relative:
        return "market_beta_dominant"
    if small_relative and execution:
        return "small_relative_plus_execution"
    if execution or liquidity:
        return "execution_liquidity"
    if idio:
        return "idiosyncratic_concentration"
    return "mixed_or_not_loss"


def make_figures(paths: Paths, daily: pd.DataFrame, style: pd.DataFrame, periods: pd.DataFrame) -> dict[str, str]:
    figures: dict[str, str] = {}
    baseline = daily.set_index("date")["daily_return"].rename("baseline_stateful")
    returns_frame = pd.concat(
        [
            baseline,
            style["market_bucket_eq_cc"].rename("market_bucket_eq_cc"),
            style["size_10_50_cc"].rename("size_10_50_cc"),
            style["large_50_100_cc"].rename("large_50_100_cc"),
        ],
        axis=1,
    ).dropna(how="all")
    nav = returns_frame.fillna(0.0).apply(normalized_nav)
    dd = returns_frame.fillna(0.0).apply(drawdown_series)

    path = paths.figures_root / "baseline_v2_market_style_nav.png"
    draw_multi_line_chart(nav, path, "Baseline Anatomy 2.0: NAV", "Stateful baseline vs style proxies")
    figures["nav"] = str(path.relative_to(paths.output_root))

    path = paths.figures_root / "baseline_v2_market_style_drawdown.png"
    draw_multi_line_chart(dd, path, "Baseline Anatomy 2.0: Drawdown", "Drawdown from running peak")
    figures["drawdown"] = str(path.relative_to(paths.output_root))

    focus = periods[periods["period"].isin(["max_drawdown_window", "worst_12m_window", "2008", "2016-2018", "2022-2025"])]
    labels = focus["period"].tolist()

    path = paths.figures_root / "baseline_v2_period_cumulative_return.png"
    draw_bar_chart(labels, focus["baseline_cumulative_return"].tolist(), path, "Baseline Cumulative Return by Critical Period", "")
    figures["period_cumulative_return"] = str(path.relative_to(paths.output_root))

    path = paths.figures_root / "baseline_v2_market_beta_proxy.png"
    draw_bar_chart(labels, focus["market_cumulative_return"].tolist(), path, "Market Beta Proxy by Critical Period", "Equal-weight style bucket return")
    figures["market_beta_proxy"] = str(path.relative_to(paths.output_root))

    path = paths.figures_root / "baseline_v2_forced_loss_share.png"
    draw_bar_chart(labels, focus["forced_loss_share_when_losing"].fillna(0.0).tolist(), path, "Forced-state Loss Share", "Only meaningful for losing windows")
    figures["forced_loss_share"] = str(path.relative_to(paths.output_root))

    path = paths.figures_root / "baseline_v2_sell_fail_rate.png"
    draw_bar_chart(labels, focus["sell_fail_rate"].tolist(), path, "Sell Failure Rate by Critical Period", "")
    figures["sell_fail_rate"] = str(path.relative_to(paths.output_root))

    path = paths.figures_root / "baseline_v2_top10_loss_share.png"
    draw_bar_chart(labels, focus["top10_loss_share"].tolist(), path, "Top 10 Code Loss Concentration", "Top 10 losing code contribution / gross code loss")
    figures["top10_loss_share"] = str(path.relative_to(paths.output_root))

    path = paths.figures_root / "baseline_v2_size_minus_large.png"
    draw_bar_chart(labels, focus["size_minus_large_ann_spread"].tolist(), path, "Size 10%-50% Minus Large Spread", "Annualized daily spread")
    figures["size_minus_large"] = str(path.relative_to(paths.output_root))
    return figures


def format_periods(frame: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "period": frame["period"],
            "start": frame["start_date"],
            "end": frame["end_date"],
            "baseline_ret": frame["baseline_cumulative_return"].map(pct),
            "baseline_mdd": frame["baseline_max_drawdown"].map(pct),
            "market_ret": frame["market_cumulative_return"].map(pct),
            "large_ret": frame["large_cumulative_return"].map(pct),
            "size-large_ann": frame["size_minus_large_ann_spread"].map(pct),
            "forced_pnl": frame["forced_state_pnl"].map(num),
            "forced_loss_share": frame["forced_loss_share_when_losing"].map(pct),
            "sell_fail_rate": frame["sell_fail_rate"].map(pct),
            "sell_fail_no_bar": frame["sell_fail_no_bar_rate"].map(pct),
            "avg_suspended": frame["avg_suspended_positions"].map(num),
            "top10_loss_share": frame["top10_loss_share"].map(pct),
            "worst_code": frame["worst_code"],
            "worst_code_pnl": frame["worst_code_contribution"].map(num),
        }
    )


def format_risk_flags(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    for col in [
        "losing_or_deep_drawdown",
        "market_beta_drawdown",
        "small_cap_relative_drawdown",
        "execution_drawdown",
        "liquidity_crash",
        "idiosyncratic_concentration",
    ]:
        out[col] = out[col].map(lambda value: "Yes" if bool(value) else "No")
    return out


def render_report(
    events: pd.DataFrame,
    periods: pd.DataFrame,
    risk_flags: pd.DataFrame,
    concentration: pd.DataFrame,
    top_losses: pd.DataFrame,
    figures: dict[str, str],
) -> str:
    max_dd = events[events["event"].eq("max_drawdown")].iloc[0]
    worst = events[events["event"].eq("worst_12m")].iloc[0]
    focus_periods = periods[
        periods["period"].isin(["full_sample", "max_drawdown_window", "worst_12m_window", "ex_2008", "2016-2018", "2022-2025"])
    ].copy()
    focus_losses = top_losses[top_losses["period"].isin(["max_drawdown_window", "2016-2018", "2022-2025"]) & top_losses["rank"].le(10)]
    conc_view = concentration[
        concentration["period"].isin(["max_drawdown_window", "worst_12m_window", "ex_2008", "2016-2018", "2022-2025"])
    ].copy()
    for col in ["top1_loss_share", "top5_loss_share", "top10_loss_share"]:
        conc_view[col] = conc_view[col].map(pct)
    for col in ["top1_loss", "top5_loss", "top10_loss", "worst_code_contribution"]:
        conc_view[col] = conc_view[col].map(num)
    loss_view = top_losses[top_losses["period"].isin(["max_drawdown_window", "2016-2018"]) & top_losses["rank"].le(10)].copy()
    loss_view["contribution"] = loss_view["contribution"].map(num)

    lines = [
        "# A股小盘 baseline Drawdown Anatomy 2.0",
        "",
        "本报告不加过滤器、不改 baseline，只把 `size 10%-50% smallest top100` 的风险来源拆清楚。",
        "",
        "## 第一优先级任务",
        "",
        "这一阶段只回答一个问题：",
        "",
        "```text",
        "baseline 的 -66.97% MDD、2016-2018 亏损、ex-2008 worst 12m，到底分别来自系统性 beta、小盘相对风险、execution、liquidity crash，还是个股 blow-up？",
        "```",
        "",
        "## 核心事件",
        "",
        f"- 最大回撤窗口：`{max_dd['start_date']}` 到 `{max_dd['end_date']}`，回撤 `{pct(max_dd['drawdown'])}`。",
        f"- 最差 12 个月窗口：`{worst['start_date']}` 到 `{worst['end_date']}`，收益 `{pct(worst['return'])}`。",
        "",
        "## 风险来源分类",
        "",
        markdown_table(format_risk_flags(risk_flags)),
        "",
        "## 关键窗口分解",
        "",
        markdown_table(format_periods(focus_periods)),
        "",
        "## 个股损伤集中度",
        "",
        markdown_table(conc_view[
            [
                "period",
                "loss_code_count",
                "top1_loss",
                "top5_loss",
                "top10_loss",
                "top1_loss_share",
                "top5_loss_share",
                "top10_loss_share",
                "worst_code",
                "worst_code_contribution",
            ]
        ]),
        "",
        "## 关键窗口最大亏损代码",
        "",
        markdown_table(loss_view),
        "",
        "## PNG 图",
        "",
    ]
    for key, rel in figures.items():
        lines.append(f"![{key}](figures/{Path(rel).name})")
        lines.append("")
    lines.extend(
        [
            "## 初步解读",
            "",
            "- 2008 / 最大回撤窗口优先看作 `systemic_beta_first`，不应指望 hard stock filter 单独解决。",
            "- 2016-2018 是 `weak_market_plus_execution`，这里才是 liquidity / execution guard 和 hard negative screen 的主要战场。",
            "- 如果 ex-2008 的 worst 12m 仍显示较高 sell-fail、forced-state 或个股集中损伤，下一阶段优先测试 execution / liquidity guard。",
            "- 这一版没有引入任何新 alpha 因子；后续每个 risk guard 都必须与本报告的风险来源一一对应。",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run baseline drawdown anatomy 2.0.")
    parser.add_argument("--processed-root", default="processed")
    parser.add_argument("--v1-output-root", default="outputs/pre_research_v1_fresh_entry_diagnostic")
    parser.add_argument("--v2-output-root", default="outputs/pre_research_v2_stateful_portfolio")
    parser.add_argument("--output-root", default="outputs/baseline_drawdown_anatomy_v2")
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

    log("load v1 market/style bucket returns")
    bucket = pd.read_csv(
        PROJECT_ROOT / args.v1_output_root / "tables" / "size_bucket_returns_theoretical_daily.csv",
        dtype={"feature_date": str},
    ).set_index("feature_date")
    style = build_style_returns(bucket)

    log("build baseline monthly plans")
    panel, _ = load_pre_research_panel(paths)
    plans = build_rebalance_plans(panel, BASELINE_SPEC)
    del panel

    log("load state data")
    returns, status = load_state_data(paths)
    calendar = pd.read_csv(paths.processed_root / "market_calendar.csv", dtype=str)
    dates = calendar[(calendar["trade_date"] >= WARMUP_START) & (calendar["trade_date"] <= RESEARCH_END)][
        "trade_date"
    ].tolist()

    log("simulate baseline code-level contributions")
    daily, code_events, sell_fail_events = simulate_baseline_code_contributions(dates, plans, returns, status)
    baseline = daily.set_index("date")["daily_return"].sort_index()
    events = pd.DataFrame([max_drawdown_event(baseline), worst_12m_event(baseline)])
    periods = build_periods(events)
    concentration, top_losses = code_concentration(code_events, periods)

    rebalance = pd.read_csv(
        PROJECT_ROOT / args.v2_output_root / "tables" / "stateful_rebalance_audit.csv",
        dtype={"exec_date": str, "strategy": str},
    )
    rebalance = rebalance[rebalance["strategy"].eq(BASELINE_STRATEGY)].copy()
    for col in ["bought", "buy_failed", "sold", "sell_failed", "median_amount_20d", "median_float_market_cap"]:
        rebalance[col] = pd.to_numeric(rebalance[col], errors="coerce")

    log("summarize risk sources")
    period_summary = summarize_periods(daily, rebalance, style, periods, concentration, sell_fail_events)
    risk_flags = classify_risk_sources(period_summary)
    figures = make_figures(paths, daily, style, period_summary)

    log("write outputs")
    daily.to_csv(paths.tables_root / "baseline_daily_returns_reconstructed.csv", index=False, encoding="utf-8")
    code_events.to_csv(paths.tables_root / "baseline_code_contribution_events.csv", index=False, encoding="utf-8")
    sell_fail_events.to_csv(paths.tables_root / "baseline_sell_fail_events.csv", index=False, encoding="utf-8")
    events.to_csv(paths.tables_root / "drawdown_events.csv", index=False, encoding="utf-8")
    style.to_csv(paths.tables_root / "market_style_returns_daily.csv", encoding="utf-8")
    period_summary.to_csv(paths.tables_root / "risk_source_period_summary.csv", index=False, encoding="utf-8")
    risk_flags.to_csv(paths.tables_root / "risk_source_flags.csv", index=False, encoding="utf-8")
    concentration.to_csv(paths.tables_root / "code_loss_concentration.csv", index=False, encoding="utf-8")
    top_losses.to_csv(paths.tables_root / "top_negative_code_contributions.csv", index=False, encoding="utf-8")

    report = render_report(events, period_summary, risk_flags, concentration, top_losses, figures)
    report_path = paths.output_root / "baseline_drawdown_anatomy_v2_zh.md"
    report_path.write_text(report, encoding="utf-8")
    log(f"wrote {report_path}")


if __name__ == "__main__":
    main()
