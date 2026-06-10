from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
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
    Paths,
    draw_bar_chart,
    load_pre_research_panel,
    log,
    markdown_table,
    num,
    pct,
    safe_annualized_return,
)
from run_pre_research_v2_stateful_portfolio import max_drawdown, worst_rolling_return  # noqa: E402


FACTOR_NAME = "rpe_score"
MAIN_UNIVERSE_NAME = "size_10_50"
ROLLING_WINDOW = 756
MIN_HISTORY = 252
MAX_VALID_PE = 300.0


def annualized_spread(high: pd.Series, low: pd.Series) -> float:
    aligned = pd.concat([high.rename("high"), low.rename("low")], axis=1).dropna()
    if aligned.empty:
        return np.nan
    return safe_annualized_return(aligned["high"] - aligned["low"])


def rank_corr(group: pd.DataFrame, x: str, y: str) -> float:
    subset = group[[x, y]].replace([np.inf, -np.inf], np.nan).dropna()
    if len(subset) < 20:
        return np.nan
    if subset[x].nunique(dropna=True) < 3 or subset[y].nunique(dropna=True) < 3:
        return np.nan
    return float(subset[x].rank(method="average").corr(subset[y].rank(method="average")))


def rank_ic_by_date(frame: pd.DataFrame, ret_col: str = "fwd_cc_ret_1d") -> pd.Series:
    subset = frame[frame["valid_rpe_flag"] & frame[ret_col].notna()].copy()
    if subset.empty:
        return pd.Series(dtype=float)
    return subset.groupby("feature_date", sort=True).apply(lambda group: rank_corr(group, FACTOR_NAME, ret_col))


def assign_quintiles(frame: pd.DataFrame) -> pd.DataFrame:
    valid = frame[frame["valid_rpe_flag"]].copy()

    def qcut_rank(series: pd.Series) -> pd.Series:
        if series.notna().sum() < 50:
            return pd.Series(pd.NA, index=series.index, dtype="object")
        ranked = series.rank(method="first")
        return pd.qcut(ranked, 5, labels=["Q1_low", "Q2", "Q3", "Q4", "Q5_high"]).astype("object")

    valid["rpe_quintile"] = valid.groupby("feature_date", sort=False)[FACTOR_NAME].transform(qcut_rank)
    return valid[valid["rpe_quintile"].notna()].copy()


def regime_for_date(date: str) -> str:
    for name, start, end in REGIMES:
        if start <= date <= end:
            return name
    return "out_of_sample"


def read_finance_pit(path: Path) -> pd.DataFrame:
    finance = pd.read_csv(
        path,
        dtype={"code": str, "report_period": str, "effective_trade_date": str},
        usecols=[
            "code",
            "report_period",
            "report_year",
            "net_profit_parent",
            "net_profit",
            "effective_trade_date",
        ],
    )
    finance["net_profit_parent"] = pd.to_numeric(finance["net_profit_parent"], errors="coerce")
    finance["net_profit"] = pd.to_numeric(finance["net_profit"], errors="coerce")
    finance["earning_base"] = finance["net_profit_parent"]
    missing_parent = finance["earning_base"].isna()
    finance.loc[missing_parent, "earning_base"] = finance.loc[missing_parent, "net_profit"]
    finance = finance[finance["effective_trade_date"].notna()].copy()
    finance = finance.sort_values(["effective_trade_date", "code", "report_period"])
    finance = finance.drop_duplicates(["code", "effective_trade_date"], keep="last")
    return finance[
        [
            "code",
            "effective_trade_date",
            "report_period",
            "report_year",
            "earning_base",
        ]
    ].copy()


def attach_finance_asof(panel: pd.DataFrame, finance: pd.DataFrame) -> pd.DataFrame:
    left_cols = [
        "feature_date",
        "code",
        "market_cap",
        "float_market_cap",
        "pe_ttm_vendor",
        "pb_vendor",
        "ps_ttm_vendor",
        "amount_20d_mean",
        "size_score",
        "base_universe",
        "size_pct",
        "return_available",
        "fwd_cc_ret_1d",
        "exec_tradable_buy",
        "exec_tradable_sell",
        "exec_has_bar",
    ]
    market = panel[left_cols].copy()
    market["feature_dt"] = pd.to_datetime(market["feature_date"], errors="coerce")
    finance = finance.copy()
    finance["effective_dt"] = pd.to_datetime(finance["effective_trade_date"], errors="coerce")
    market = market.sort_values(["feature_dt", "code"]).reset_index(drop=True)
    finance_sorted = finance.sort_values(["effective_dt", "code"]).reset_index(drop=True)
    try:
        merged = pd.merge_asof(
            market,
            finance_sorted,
            left_on="feature_dt",
            right_on="effective_dt",
            by="code",
            direction="backward",
        )
    except Exception:
        pieces = []
        finance_groups = {code: group.sort_values("effective_dt") for code, group in finance.groupby("code")}
        for code, group in market.groupby("code", sort=False):
            fin = finance_groups.get(code)
            if fin is None:
                out = group.copy()
                out["effective_trade_date"] = np.nan
                out["report_period"] = np.nan
                out["report_year"] = np.nan
                out["earning_base"] = np.nan
            else:
                out = pd.merge_asof(
                    group.sort_values("feature_dt"),
                    fin,
                    left_on="feature_dt",
                    right_on="effective_dt",
                    by="code",
                    direction="backward",
                )
            pieces.append(out)
        merged = pd.concat(pieces, ignore_index=True)
    merged = merged.drop(columns=[col for col in ["feature_dt", "effective_dt"] if col in merged.columns])
    return merged


def build_rpe_factor(panel: pd.DataFrame, finance: pd.DataFrame) -> pd.DataFrame:
    log("attach annual finance PIT to market panel")
    factor = attach_finance_asof(panel, finance)
    for col in ["market_cap", "float_market_cap", "pe_ttm_vendor", "pb_vendor", "ps_ttm_vendor", "amount_20d_mean"]:
        factor[col] = pd.to_numeric(factor[col], errors="coerce")

    factor["coverage_flag"] = factor["effective_trade_date"].notna()
    factor["positive_earning_flag"] = factor["earning_base"].gt(0)
    factor["current_pe"] = factor["market_cap"] / factor["earning_base"]
    factor["extreme_pe_flag"] = factor["current_pe"].gt(MAX_VALID_PE)
    factor["valid_pe_flag"] = (
        factor["coverage_flag"]
        & factor["positive_earning_flag"]
        & factor["market_cap"].gt(0)
        & factor["current_pe"].gt(0)
        & factor["current_pe"].le(MAX_VALID_PE)
    )
    factor = factor.sort_values(["code", "feature_date"]).reset_index(drop=True)
    factor["pe_for_reference"] = factor["current_pe"].where(factor["valid_pe_flag"])
    log("compute rolling reference PE")
    factor["reference_pe"] = factor.groupby("code", sort=False)["pe_for_reference"].transform(
        lambda series: series.rolling(ROLLING_WINDOW, min_periods=MIN_HISTORY).median()
    )
    factor["rpe_raw"] = np.nan
    factor["rpe_score"] = np.nan
    score_mask = factor["valid_pe_flag"] & factor["reference_pe"].gt(0)
    factor.loc[score_mask, "rpe_raw"] = factor.loc[score_mask, "current_pe"] / factor.loc[score_mask, "reference_pe"]
    score_mask = score_mask & factor["rpe_raw"].gt(0)
    factor.loc[score_mask, "rpe_score"] = -np.log(factor.loc[score_mask, "rpe_raw"])
    factor["valid_rpe_flag"] = (
        factor["valid_pe_flag"]
        & factor["reference_pe"].gt(0)
        & factor["rpe_raw"].gt(0)
        & np.isfinite(factor["rpe_score"])
    )
    factor = factor.rename(columns={"report_period": "source_report_period"})
    return factor


def write_factor_port(factor: pd.DataFrame, output_root: Path, force: bool) -> dict[str, Any]:
    if output_root.exists() and force:
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    port_cols = [
        "feature_date",
        "code",
        "rpe_raw",
        "rpe_score",
        "current_pe",
        "reference_pe",
        "earning_base",
        "source_report_period",
        "effective_trade_date",
        "coverage_flag",
        "valid_pe_flag",
        "valid_rpe_flag",
        "positive_earning_flag",
        "extreme_pe_flag",
    ]
    files = []
    rows = 0
    valid_rows = 0
    for year, frame in factor.groupby(factor["feature_date"].str.slice(0, 4), sort=True):
        year_dir = output_root / f"year={year}"
        year_dir.mkdir(parents=True, exist_ok=True)
        file = year_dir / f"rpe_factor_pit_{year}.csv.gz"
        frame[port_cols].to_csv(
            file,
            index=False,
            encoding="utf-8",
            compression={"method": "gzip", "compresslevel": 1},
        )
        files.append(str(file.relative_to(output_root)))
        rows += int(len(frame))
        valid_rows += int(frame["valid_rpe_flag"].sum())
    manifest = {
        "factor": "rpe_factor_v1",
        "definition": "rpe_score = -log(current_pe / rolling_3y_median_current_pe)",
        "current_pe": "market_cap / latest_visible_annual_net_profit_parent_or_net_profit",
        "rolling_window": ROLLING_WINDOW,
        "min_history": MIN_HISTORY,
        "max_valid_pe": MAX_VALID_PE,
        "row_count": rows,
        "valid_rpe_rows": valid_rows,
        "file_count": len(files),
        "files": files,
        "build_time": datetime.now().isoformat(timespec="seconds"),
    }
    (output_root / "build_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main_universe_frame(factor: pd.DataFrame) -> pd.DataFrame:
    universe = factor[
        factor["base_universe"]
        & factor["size_pct"].gt(0.10)
        & factor["size_pct"].le(0.50)
        & factor["feature_date"].between(RESEARCH_START, RESEARCH_END)
    ].copy()
    universe["year"] = universe["feature_date"].str.slice(0, 4)
    universe["regime"] = universe["feature_date"].map(regime_for_date)
    universe["log_float_market_cap"] = np.log(universe["float_market_cap"].where(universe["float_market_cap"].gt(0)))
    universe["log_amount_20d"] = np.log(universe["amount_20d_mean"].where(universe["amount_20d_mean"].gt(0)))
    return universe


def coverage_tables(universe: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    full = pd.DataFrame(
        [
            {
                "scope": "full_sample",
                "universe_count": int(len(universe)),
                "rpe_valid_count": int(universe["valid_rpe_flag"].sum()),
                "coverage_rate": float(universe["valid_rpe_flag"].mean()) if len(universe) else np.nan,
            }
        ]
    )
    by_year = (
        universe.groupby("year", sort=True)
        .agg(universe_count=("code", "size"), rpe_valid_count=("valid_rpe_flag", "sum"))
        .reset_index()
    )
    by_year["coverage_rate"] = by_year["rpe_valid_count"] / by_year["universe_count"].replace(0, np.nan)
    by_regime = (
        universe.groupby("regime", sort=False)
        .agg(universe_count=("code", "size"), rpe_valid_count=("valid_rpe_flag", "sum"))
        .reset_index()
    )
    by_regime["coverage_rate"] = by_regime["rpe_valid_count"] / by_regime["universe_count"].replace(0, np.nan)
    return full, by_year, by_regime


def exposure_correlation(universe: pd.DataFrame) -> pd.DataFrame:
    variables = {
        "size_score": "size_score",
        "log_float_market_cap": "log_float_market_cap",
        "log_amount_20d": "log_amount_20d",
        "pb_vendor": "pb_vendor",
        "pe_ttm_vendor": "pe_ttm_vendor",
        "ps_ttm_vendor": "ps_ttm_vendor",
    }
    subset = universe[universe["valid_rpe_flag"]].copy()
    rows = []
    for label, col in variables.items():
        daily = subset.groupby("feature_date", sort=True).apply(lambda group: rank_corr(group, FACTOR_NAME, col))
        rows.append(
            {
                "exposure": label,
                "daily_rank_corr_mean": float(daily.mean()) if not daily.empty else np.nan,
                "daily_rank_corr_median": float(daily.median()) if not daily.empty else np.nan,
                "observations": int(daily.notna().sum()),
            }
        )
    return pd.DataFrame(rows)


def ic_tables(universe: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.Series]:
    ic = rank_ic_by_date(universe)
    full = pd.DataFrame(
        [
            {
                "scope": "full_sample",
                "rank_ic_mean": float(ic.mean()) if not ic.empty else np.nan,
                "rank_ic_median": float(ic.median()) if not ic.empty else np.nan,
                "rank_ic_positive_rate": float((ic > 0).mean()) if not ic.empty else np.nan,
                "observations": int(ic.notna().sum()) if not ic.empty else 0,
            }
        ]
    )
    yearly = ic.rename("rank_ic").reset_index()
    yearly["year"] = yearly["feature_date"].str.slice(0, 4)
    by_year = (
        yearly.groupby("year", sort=True)["rank_ic"]
        .agg(rank_ic_mean="mean", rank_ic_median="median", rank_ic_positive_rate=lambda s: float((s > 0).mean()), observations="count")
        .reset_index()
    )
    yearly["regime"] = yearly["feature_date"].map(regime_for_date)
    by_regime = (
        yearly.groupby("regime", sort=False)["rank_ic"]
        .agg(rank_ic_mean="mean", rank_ic_median="median", rank_ic_positive_rate=lambda s: float((s > 0).mean()), observations="count")
        .reset_index()
    )
    return full, by_year, by_regime, ic


def quintile_daily_returns(quintiles: pd.DataFrame) -> pd.DataFrame:
    subset = quintiles[quintiles["return_available"] & quintiles["fwd_cc_ret_1d"].notna()].copy()
    daily = subset.groupby(["feature_date", "rpe_quintile"], sort=True, observed=True)["fwd_cc_ret_1d"].mean().unstack()
    return daily.reindex(columns=["Q1_low", "Q2", "Q3", "Q4", "Q5_high"])


def summarize_quintile_returns(daily_returns: pd.DataFrame) -> pd.DataFrame:
    rows = []
    periods = [("full_sample", RESEARCH_START, RESEARCH_END), *REGIMES]
    for period, start, end in periods:
        window = daily_returns[(daily_returns.index >= start) & (daily_returns.index <= end)]
        row: dict[str, Any] = {"period": period, "start_date": start, "end_date": end}
        for col in daily_returns.columns:
            row[f"{col}_ann_return"] = safe_annualized_return(window[col])
        row["Q5_minus_Q1_ann_spread"] = annualized_spread(window["Q5_high"], window["Q1_low"])
        row["observations"] = int(window.notna().any(axis=1).sum())
        rows.append(row)
    return pd.DataFrame(rows)


def quintile_exposure_summary(quintiles: pd.DataFrame) -> pd.DataFrame:
    grouped = quintiles.groupby(["feature_date", "rpe_quintile"], sort=True, observed=True)
    daily = grouped.agg(
        names=("code", "count"),
        median_rpe_score=("rpe_score", "median"),
        median_current_pe=("current_pe", "median"),
        median_reference_pe=("reference_pe", "median"),
        median_float_market_cap=("float_market_cap", "median"),
        median_amount_20d=("amount_20d_mean", "median"),
        median_pb=("pb_vendor", "median"),
        median_ps=("ps_ttm_vendor", "median"),
        next_buy_fail_rate=("exec_tradable_buy", lambda s: float((~s.astype(bool)).mean())),
        next_sell_blocked_rate=("exec_tradable_sell", lambda s: float((~s.astype(bool)).mean())),
        next_no_bar_rate=("exec_has_bar", lambda s: float((~s.astype(bool)).mean())),
    ).reset_index()
    summary = (
        daily.groupby("rpe_quintile", sort=True)
        .agg(
            avg_names=("names", "mean"),
            median_rpe_score=("median_rpe_score", "median"),
            median_current_pe=("median_current_pe", "median"),
            median_reference_pe=("median_reference_pe", "median"),
            median_float_market_cap=("median_float_market_cap", "median"),
            median_amount_20d=("median_amount_20d", "median"),
            median_pb=("median_pb", "median"),
            median_ps=("median_ps", "median"),
            next_buy_fail_rate=("next_buy_fail_rate", "mean"),
            next_sell_blocked_rate=("next_sell_blocked_rate", "mean"),
            next_no_bar_rate=("next_no_bar_rate", "mean"),
        )
        .reset_index()
    )
    return summary


def make_figures(
    paths: Paths,
    coverage_by_year: pd.DataFrame,
    ic_by_year: pd.DataFrame,
    ic_by_regime: pd.DataFrame,
    qret_summary: pd.DataFrame,
    qexposure: pd.DataFrame,
    corr: pd.DataFrame,
) -> dict[str, str]:
    figures: dict[str, str] = {}
    path = paths.figures_root / "rpe_coverage_by_year.png"
    draw_bar_chart(coverage_by_year["year"].tolist(), coverage_by_year["coverage_rate"].tolist(), path, "RPE Coverage by Year", "valid RPE rows / size 10%-50% universe rows")
    figures["coverage_by_year"] = str(path.relative_to(paths.output_root))

    path = paths.figures_root / "rpe_rank_ic_by_year.png"
    draw_bar_chart(ic_by_year["year"].tolist(), ic_by_year["rank_ic_mean"].tolist(), path, "RPE Rank IC by Year", "mean daily rank IC")
    figures["rank_ic_by_year"] = str(path.relative_to(paths.output_root))

    path = paths.figures_root / "rpe_rank_ic_by_regime.png"
    draw_bar_chart(ic_by_regime["regime"].tolist(), ic_by_regime["rank_ic_mean"].tolist(), path, "RPE Rank IC by Regime", "mean daily rank IC")
    figures["rank_ic_by_regime"] = str(path.relative_to(paths.output_root))

    full = qret_summary[qret_summary["period"].eq("full_sample")].iloc[0]
    labels = ["Q1_low", "Q2", "Q3", "Q4", "Q5_high"]
    path = paths.figures_root / "rpe_quintile_ann_return_full.png"
    draw_bar_chart(labels, [full[f"{label}_ann_return"] for label in labels], path, "RPE Quintile Annualized Return - Full Sample", "Q5 is highest RPE score")
    figures["quintile_return_full"] = str(path.relative_to(paths.output_root))

    row_2016 = qret_summary[qret_summary["period"].eq("2016-2018")].iloc[0]
    path = paths.figures_root / "rpe_quintile_ann_return_2016_2018.png"
    draw_bar_chart(labels, [row_2016[f"{label}_ann_return"] for label in labels], path, "RPE Quintile Annualized Return - 2016-2018", "Q5 is highest RPE score")
    figures["quintile_return_2016_2018"] = str(path.relative_to(paths.output_root))

    path = paths.figures_root / "rpe_quintile_median_amount_20d.png"
    draw_bar_chart(qexposure["rpe_quintile"].tolist(), qexposure["median_amount_20d"].tolist(), path, "RPE Quintile Median 20D Amount", "Liquidity exposure")
    figures["quintile_amount_20d"] = str(path.relative_to(paths.output_root))

    path = paths.figures_root / "rpe_quintile_median_float_mcap.png"
    draw_bar_chart(qexposure["rpe_quintile"].tolist(), qexposure["median_float_market_cap"].tolist(), path, "RPE Quintile Median Float Market Cap", "Size exposure")
    figures["quintile_float_mcap"] = str(path.relative_to(paths.output_root))

    path = paths.figures_root / "rpe_exposure_rank_corr.png"
    draw_bar_chart(corr["exposure"].tolist(), corr["daily_rank_corr_mean"].tolist(), path, "RPE Exposure Rank Correlation", "mean daily rank correlation")
    figures["exposure_corr"] = str(path.relative_to(paths.output_root))
    return figures


def format_coverage(frame: pd.DataFrame, label_col: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            label_col: frame[label_col],
            "universe_count": frame["universe_count"],
            "rpe_valid_count": frame["rpe_valid_count"],
            "coverage_rate": frame["coverage_rate"].map(pct),
        }
    )


def format_ic(frame: pd.DataFrame, label_col: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            label_col: frame[label_col],
            "rank_ic_mean": frame["rank_ic_mean"].map(num),
            "rank_ic_median": frame["rank_ic_median"].map(num),
            "positive_rate": frame["rank_ic_positive_rate"].map(pct),
            "observations": frame["observations"],
        }
    )


def format_qret(frame: pd.DataFrame) -> pd.DataFrame:
    cols = ["Q1_low", "Q2", "Q3", "Q4", "Q5_high"]
    out = pd.DataFrame({"period": frame["period"]})
    for col in cols:
        out[col] = frame[f"{col}_ann_return"].map(pct)
    out["Q5_minus_Q1_ann_spread"] = frame["Q5_minus_Q1_ann_spread"].map(pct)
    out["observations"] = frame["observations"]
    return out


def format_qexposure(frame: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "rpe_quintile": frame["rpe_quintile"],
            "avg_names": frame["avg_names"].map(num),
            "median_rpe_score": frame["median_rpe_score"].map(num),
            "median_current_pe": frame["median_current_pe"].map(num),
            "median_float_market_cap": frame["median_float_market_cap"].map(lambda x: "n/a" if pd.isna(x) else f"{x:,.0f}"),
            "median_amount_20d": frame["median_amount_20d"].map(lambda x: "n/a" if pd.isna(x) else f"{x:,.0f}"),
            "next_buy_fail_rate": frame["next_buy_fail_rate"].map(pct),
            "next_sell_blocked_rate": frame["next_sell_blocked_rate"].map(pct),
            "next_no_bar_rate": frame["next_no_bar_rate"].map(pct),
        }
    )


def render_report_zh(
    manifest: dict[str, Any],
    coverage_full: pd.DataFrame,
    coverage_by_year: pd.DataFrame,
    coverage_by_regime: pd.DataFrame,
    corr: pd.DataFrame,
    ic_full: pd.DataFrame,
    ic_by_year: pd.DataFrame,
    ic_by_regime: pd.DataFrame,
    qret_summary: pd.DataFrame,
    qexposure: pd.DataFrame,
    figures: dict[str, str],
) -> str:
    coverage_rate = float(coverage_full["coverage_rate"].iloc[0])
    full_ic = float(ic_full["rank_ic_mean"].iloc[0])
    qfull = qret_summary[qret_summary["period"].eq("full_sample")].iloc[0]
    q2016 = qret_summary[qret_summary["period"].eq("2016-2018")].iloc[0]

    lines = [
        "# A股小盘 RPE factor v1 诊断报告",
        "",
        "本报告只做 RPE 因子端口、覆盖率、暴露、IC 和理论分组收益诊断，不跑状态机组合，不做参数优化。",
        "",
        "## 因子定义",
        "",
        "- 主 universe：`size 10%-50%`。",
        "- 当前 PE：`market_cap / latest_visible_annual_net_profit_parent_or_net_profit`。",
        f"- 参考 PE：个股过去 `{ROLLING_WINDOW}` 个交易观察的 PE 滚动中位数，最少 `{MIN_HISTORY}` 个有效观察。",
        "- RPE：`rpe_score = -log(current_pe / reference_pe)`，score 越高越好。",
        f"- PE 有效范围：`0 < PE <= {MAX_VALID_PE:g}`；负盈利、零盈利、极端 PE 只标记，不填补。",
        "- 财务字段来自 `annual_finance_pit`，按 `effective_trade_date <= feature_date` 做 PIT as-of。",
        "",
        "## 端口输出",
        "",
        f"- 输出目录：`processed/rpe_factor_pit`。",
        f"- 行数：`{manifest['row_count']:,}`；有效 RPE 行数：`{manifest['valid_rpe_rows']:,}`。",
        "",
        "## 初步结论",
        "",
        f"- size 10%-50% 主池 RPE 覆盖率：`{pct(coverage_rate)}`。",
        f"- full sample 日度 rank IC 均值：`{num(full_ic)}`。",
        f"- full sample Q5-Q1 年化 spread：`{pct(qfull['Q5_minus_Q1_ann_spread'])}`。",
        f"- 2016-2018 Q5-Q1 年化 spread：`{pct(q2016['Q5_minus_Q1_ann_spread'])}`。",
        "- 这一轮判断重点是：RPE 是否有方向性、是否偷了更小市值/更低流动性暴露、是否在 2016-2018 有帮助。",
        "",
        "## 覆盖率",
        "",
        markdown_table(format_coverage(coverage_full.rename(columns={"scope": "scope"}), "scope")),
        "",
        "### 按年度",
        "",
        markdown_table(format_coverage(coverage_by_year, "year")),
        "",
        "### 按 regime",
        "",
        markdown_table(format_coverage(coverage_by_regime, "regime")),
        "",
        "## 暴露相关性",
        "",
        markdown_table(corr),
        "",
        "## Rank IC",
        "",
        markdown_table(format_ic(ic_full.rename(columns={"scope": "scope"}), "scope")),
        "",
        "### 按年度",
        "",
        markdown_table(format_ic(ic_by_year, "year")),
        "",
        "### 按 regime",
        "",
        markdown_table(format_ic(ic_by_regime, "regime")),
        "",
        "## RPE Q1-Q5 理论分组收益",
        "",
        markdown_table(format_qret(qret_summary)),
        "",
        "## RPE Q1-Q5 暴露与交易状态",
        "",
        markdown_table(format_qexposure(qexposure)),
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
            "- 这里的分组收益是理论 close-to-close 诊断，不是可部署回测。",
            "- `next_sell_blocked_rate` 和 `next_no_bar_rate` 是下一执行日状态暴露，不等于真实组合卖出失败率；真实卖出失败要等 v2 状态机组合。",
            "- 如果 RPE 高分组流动性明显更差，下一步 stateful portfolio 即使收益高也要谨慎。",
        ]
    )
    return "\n".join(lines) + "\n"


def save_outputs(
    paths: Paths,
    manifest: dict[str, Any],
    coverage_full: pd.DataFrame,
    coverage_by_year: pd.DataFrame,
    coverage_by_regime: pd.DataFrame,
    corr: pd.DataFrame,
    ic_full: pd.DataFrame,
    ic_by_year: pd.DataFrame,
    ic_by_regime: pd.DataFrame,
    ic_daily: pd.Series,
    qret_daily: pd.DataFrame,
    qret_summary: pd.DataFrame,
    qexposure: pd.DataFrame,
    figures: dict[str, str],
) -> None:
    paths.tables_root.mkdir(parents=True, exist_ok=True)
    coverage_full.to_csv(paths.tables_root / "rpe_coverage_full.csv", index=False, encoding="utf-8")
    coverage_by_year.to_csv(paths.tables_root / "rpe_coverage_by_year.csv", index=False, encoding="utf-8")
    coverage_by_regime.to_csv(paths.tables_root / "rpe_coverage_by_regime.csv", index=False, encoding="utf-8")
    corr.to_csv(paths.tables_root / "rpe_exposure_rank_corr.csv", index=False, encoding="utf-8")
    ic_full.to_csv(paths.tables_root / "rpe_ic_full.csv", index=False, encoding="utf-8")
    ic_by_year.to_csv(paths.tables_root / "rpe_ic_by_year.csv", index=False, encoding="utf-8")
    ic_by_regime.to_csv(paths.tables_root / "rpe_ic_by_regime.csv", index=False, encoding="utf-8")
    ic_daily.rename("rank_ic").to_csv(paths.tables_root / "rpe_ic_daily.csv", encoding="utf-8")
    qret_daily.to_csv(paths.tables_root / "rpe_quintile_returns_daily.csv", encoding="utf-8")
    qret_summary.to_csv(paths.tables_root / "rpe_quintile_return_summary.csv", index=False, encoding="utf-8")
    qexposure.to_csv(paths.tables_root / "rpe_quintile_exposure_summary.csv", index=False, encoding="utf-8")
    (paths.tables_root / "rpe_factor_manifest_snapshot.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    report = render_report_zh(
        manifest,
        coverage_full,
        coverage_by_year,
        coverage_by_regime,
        corr,
        ic_full,
        ic_by_year,
        ic_by_regime,
        qret_summary,
        qexposure,
        figures,
    )
    report_path = paths.output_root / "rpe_factor_v1_diagnostics_zh.md"
    report_path.write_text(report, encoding="utf-8")
    log(f"wrote {report_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and diagnose RPE factor v1.")
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--processed-root", default="processed")
    parser.add_argument("--output-root", default="outputs/rpe_factor_v1_diagnostics")
    parser.add_argument("--factor-output-root", default="processed/rpe_factor_pit")
    parser.add_argument("--force-factor", action="store_true")
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

    log("load pre-research panel")
    panel, panel_stats = load_pre_research_panel(paths)
    log(f"panel rows: {panel_stats['rows']:,}")
    log("load annual finance PIT")
    finance = read_finance_pit(paths.processed_root / "annual_finance_pit.csv.gz")
    factor = build_rpe_factor(panel, finance)
    factor_output_root = (PROJECT_ROOT / args.factor_output_root).resolve()
    log("write RPE factor PIT port")
    manifest = write_factor_port(factor, factor_output_root, force=args.force_factor)

    log("run RPE diagnostics")
    universe = main_universe_frame(factor)
    coverage_full, coverage_by_year, coverage_by_regime = coverage_tables(universe)
    corr = exposure_correlation(universe)
    ic_full, ic_by_year, ic_by_regime, ic_daily = ic_tables(universe)
    quintiles = assign_quintiles(universe)
    qret_daily = quintile_daily_returns(quintiles)
    qret_summary = summarize_quintile_returns(qret_daily)
    qexposure = quintile_exposure_summary(quintiles)
    figures = make_figures(paths, coverage_by_year, ic_by_year, ic_by_regime, qret_summary, qexposure, corr)
    save_outputs(
        paths,
        manifest,
        coverage_full,
        coverage_by_year,
        coverage_by_regime,
        corr,
        ic_full,
        ic_by_year,
        ic_by_regime,
        ic_daily,
        qret_daily,
        qret_summary,
        qexposure,
        figures,
    )


if __name__ == "__main__":
    main()
