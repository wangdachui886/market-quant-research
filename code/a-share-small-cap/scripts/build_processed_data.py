from __future__ import annotations

import argparse
import bisect
import json
import shutil
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from pandas.io.stata import StataReader

from data_audit import (
    find_data_dirs,
    find_market_roots,
    normalize_code,
    parse_csv_line,
    read_first_line,
)


MARKET_COLUMN_MAP = {
    "日期": "trade_date",
    "代码": "code",
    "名称": "name",
    "所属行业": "industry_vendor",
    "开盘价": "open",
    "最高价": "high",
    "最低价": "low",
    "收盘价": "close",
    "前收盘价": "prev_close",
    "成交量（股）": "volume_shares",
    "成交额（元）": "amount_yuan",
    "换手率": "turnover",
    "涨幅%": "pct_chg",
    "振幅%": "amplitude",
    "是否ST": "is_st",
    "量比": "volume_ratio",
    "3日涨幅%": "return_3d",
    "6日涨幅%": "return_6d",
    "10日涨幅%": "return_10d",
    "25日涨幅%": "return_25d",
    "是否涨停": "is_limit_up",
    "总股本（股）": "total_shares",
    "流通股本（股）": "float_shares",
    "总市值（元）": "market_cap",
    "流通市值（元）": "float_market_cap",
    "滚动市盈率": "pe_ttm_vendor",
    "市净率": "pb_vendor",
    "滚动市销率": "ps_ttm_vendor",
    "5日线": "ma_5_vendor",
    "10日线": "ma_10_vendor",
    "20日线": "ma_20_vendor",
    "30日线": "ma_30_vendor",
    "60日线": "ma_60_vendor",
    "120日线": "ma_120_vendor",
    "250日线": "ma_250_vendor",
    "上市时间": "list_date",
    "退市时间": "delist_date",
    "是否融资融券": "is_marginable",
}

MARKET_OUTPUT_COLUMNS = [
    "trade_date",
    "feature_date",
    "exec_date",
    "code",
    "board",
    "name",
    "industry_vendor",
    "open",
    "high",
    "low",
    "close",
    "prev_close",
    "volume_shares",
    "amount_yuan",
    "turnover",
    "pct_chg",
    "amplitude",
    "is_st",
    "volume_ratio",
    "return_3d",
    "return_6d",
    "return_10d",
    "return_25d",
    "is_limit_up",
    "is_limit_down_est",
    "one_price_limit_est",
    "total_shares",
    "float_shares",
    "market_cap",
    "float_market_cap",
    "pe_ttm_vendor",
    "pb_vendor",
    "ps_ttm_vendor",
    "ma_5_vendor",
    "ma_10_vendor",
    "ma_20_vendor",
    "ma_30_vendor",
    "ma_60_vendor",
    "ma_120_vendor",
    "ma_250_vendor",
    "list_date",
    "delist_date",
    "is_marginable",
]

REQUIRED_MARKET_COLUMNS = [
    "日期",
    "代码",
    "名称",
    "开盘价",
    "最高价",
    "最低价",
    "收盘价",
    "前收盘价",
    "成交量（股）",
    "成交额（元）",
    "是否ST",
    "是否涨停",
    "总市值（元）",
    "流通市值（元）",
    "上市时间",
    "退市时间",
]

REQUIRED_ANNUAL_COLUMNS = ["Stkcd", "Accper", "Typrep", "IfCorrect", "DeclareDate"]
REQUIRED_FAR_COLUMNS = ["Stkcd", "Accper", "Annodt"]

NUMERIC_COLUMNS = [
    "open",
    "high",
    "low",
    "close",
    "prev_close",
    "volume_shares",
    "amount_yuan",
    "turnover",
    "pct_chg",
    "amplitude",
    "volume_ratio",
    "return_3d",
    "return_6d",
    "return_10d",
    "return_25d",
    "total_shares",
    "float_shares",
    "market_cap",
    "float_market_cap",
    "pe_ttm_vendor",
    "pb_vendor",
    "ps_ttm_vendor",
    "ma_5_vendor",
    "ma_10_vendor",
    "ma_20_vendor",
    "ma_30_vendor",
    "ma_60_vendor",
    "ma_120_vendor",
    "ma_250_vendor",
]

ANNUAL_FIELD_MAP = {
    "Stkcd": "code",
    "ShortName": "finance_name",
    "Accper": "report_period",
    "Typrep": "report_type",
    "IfCorrect": "if_correct",
    "DeclareDate": "correction_disclosure_date",
    "A001000000": "total_assets",
    "A002000000": "total_liabilities",
    "A003000000": "total_equity",
    "A003100000": "parent_equity",
    "A001220000": "goodwill",
    "B001100000": "total_operating_revenue",
    "B001101000": "operating_revenue",
    "B002000000": "net_profit",
    "B002000101": "net_profit_parent",
    "C001000000": "operating_cash_flow_direct",
    "D000100000": "operating_cash_flow_indirect",
    "F011201A": "asset_liability_ratio_vendor",
    "F050504C": "roe_ttm_vendor",
    "F053004C": "roe_parent_ttm_vendor",
    "F053301C": "gross_margin_ttm_vendor",
    "F060101C": "net_profit_cash_content_ttm_vendor",
}

FAR_FIELD_MAP = {
    "Stkcd": "code",
    "Accper": "report_period",
    "Annodt": "ann_date",
    "A100000": "far_total_assets",
    "A300000": "far_total_equity",
    "B110101": "far_main_revenue",
    "D100000": "far_operating_cash_flow",
    "T30100": "far_asset_liability_ratio",
    "T40100": "far_gross_margin",
    "T40803": "far_roe_c",
    "T60200": "far_eps",
    "T60300": "far_bps",
    "Capexp": "far_capex",
    "Etaxrt": "far_effective_tax_rate",
    "Speitem": "far_special_item_profit",
    "Nstaff": "far_staff_count",
}


@dataclass
class MarketBuildStats:
    market_end_date: str
    modal_header_columns: int
    years: dict[str, dict[str, Any]]
    total_rows: int
    total_dates: int
    trading_status: dict[str, Any]
    output_files: list[str]


@dataclass
class FinanceBuildStats:
    raw_rows: int
    rows_with_ann_date: int
    corrected_rows: int
    corrected_rows_adjusted_to_correction_date: int
    corrected_rows_missing_correction_date: int
    multi_correction_date_rows: int
    rows_with_effective_trade_date: int
    dropped_missing_ann_date: int
    dropped_missing_correction_date: int
    dropped_missing_effective_trade_date: int
    report_period_min: str | None
    report_period_max: str | None
    ann_date_min: str | None
    ann_date_max: str | None
    output_file: str


def board_from_code(code: str) -> str:
    if code.startswith(("688", "689")):
        return "star"
    if code.startswith("920") or code.startswith("8"):
        return "beijing"
    if code.startswith(("300", "301", "302")):
        return "chinext"
    if code.startswith(("000", "001", "002", "003", "600", "601", "603", "605")):
        return "main"
    if code.startswith(("200", "900")):
        return "b_share"
    return "unknown"


def bool_from_yes_no(value: Any) -> Any:
    text = str(value).strip()
    if text == "是":
        return True
    if text == "否":
        return False
    return pd.NA


def estimate_limit_threshold(frame: pd.DataFrame) -> pd.Series:
    trade_date = pd.to_datetime(frame["trade_date"], errors="coerce")
    threshold = pd.Series(0.10, index=frame.index, dtype="float64")
    threshold.loc[frame["board"].eq("star")] = 0.20
    threshold.loc[frame["board"].eq("beijing")] = 0.30
    threshold.loc[frame["board"].eq("chinext") & (trade_date >= pd.Timestamp("2020-08-24"))] = 0.20
    threshold.loc[frame["is_st"].fillna(False)] = 0.05
    return threshold


def clean_date_series(series: pd.Series) -> pd.Series:
    dates = pd.to_datetime(series.replace("-", pd.NA), errors="coerce")
    return dates.dt.strftime("%Y-%m-%d")


def standardize_market_frame(raw: pd.DataFrame) -> pd.DataFrame:
    for raw_col in MARKET_COLUMN_MAP:
        if raw_col not in raw.columns:
            raw[raw_col] = pd.NA
    frame = raw[list(MARKET_COLUMN_MAP)].rename(columns=MARKET_COLUMN_MAP)
    frame["code"] = frame["code"].map(normalize_code)
    frame["board"] = frame["code"].map(board_from_code)
    frame["trade_date"] = clean_date_series(frame["trade_date"])
    frame["feature_date"] = frame["trade_date"]
    frame["exec_date"] = pd.NA
    frame["list_date"] = clean_date_series(frame["list_date"])
    frame["delist_date"] = clean_date_series(frame["delist_date"])
    for col in NUMERIC_COLUMNS:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    for col in ["is_st", "is_limit_up", "is_marginable"]:
        frame[col] = frame[col].map(bool_from_yes_no).astype("boolean")
    ret = frame["close"] / frame["prev_close"] - 1.0
    threshold = estimate_limit_threshold(frame)
    valid_prices = frame["prev_close"].gt(0) & frame[["open", "high", "low", "close"]].notna().all(axis=1)
    frame["is_limit_down_est"] = (
        valid_prices
        & ret.le(-threshold + 0.0025)
        & (frame["low"].sub(frame["close"]).abs() <= 0.01)
    ).astype("boolean")
    one_price = (
        valid_prices
        & (frame["open"].sub(frame["high"]).abs() <= 0.01)
        & (frame["open"].sub(frame["low"]).abs() <= 0.01)
        & (frame["open"].sub(frame["close"]).abs() <= 0.01)
    )
    frame["one_price_limit_est"] = (
        one_price & (frame["is_limit_up"].fillna(False) | frame["is_limit_down_est"].fillna(False))
    ).astype("boolean")
    return frame[MARKET_OUTPUT_COLUMNS]


def discover_unadjusted_daily_dir(data_root: Path) -> Path:
    market_dir, _ = find_data_dirs(data_root)
    _, daily_root = find_market_roots(market_dir)
    raw_dirs = [path for path in daily_root.iterdir() if path.is_dir() and path.name == "不复权"]
    if raw_dirs:
        return raw_dirs[0]
    return sorted([path for path in daily_root.iterdir() if path.is_dir()], key=lambda p: p.name)[0]


def infer_stable_market_end_date(raw_daily_dir: Path) -> tuple[str, int]:
    header_counts: Counter[int] = Counter()
    dated_headers: list[tuple[str, int]] = []
    for file in sorted(raw_daily_dir.glob("*/*.csv")):
        date = file.name.split("_")[0]
        ncols = len(parse_csv_line(read_first_line(file)))
        header_counts[ncols] += 1
        dated_headers.append((date, ncols))
    if not dated_headers:
        raise FileNotFoundError(f"No daily csv files found under {raw_daily_dir}")
    modal_ncols = header_counts.most_common(1)[0][0]
    stable_dates = [date for date, ncols in dated_headers if ncols == modal_ncols]
    return max(stable_dates), modal_ncols


def collect_daily_files(raw_daily_dir: Path, end_date: str, modal_header_columns: int) -> dict[str, list[Path]]:
    by_year: dict[str, list[Path]] = {}
    for file in sorted(raw_daily_dir.glob("*/*.csv")):
        date = file.name.split("_")[0]
        if date > end_date:
            continue
        ncols = len(parse_csv_line(read_first_line(file)))
        if ncols != modal_header_columns:
            raise ValueError(f"Unexpected header width before end date: {file} has {ncols} columns")
        header = parse_csv_line(read_first_line(file))
        missing = [col for col in REQUIRED_MARKET_COLUMNS if col not in header]
        if missing:
            raise ValueError(f"Required market columns missing in {file}: {missing}")
        by_year.setdefault(date[:4], []).append(file)
    return by_year


def next_trade_date_map(dates: list[str]) -> dict[str, str | pd.NA]:
    ordered = sorted(dates)
    mapping: dict[str, str | pd.NA] = {}
    for idx, date in enumerate(ordered):
        mapping[date] = ordered[idx + 1] if idx + 1 < len(ordered) else pd.NA
    return mapping


def year_security_summary(year_df: pd.DataFrame) -> pd.DataFrame:
    sorted_df = year_df.sort_values(["code", "trade_date"])
    grouped = sorted_df.groupby("code", sort=False)
    first = grouped.head(1).set_index("code")
    last = grouped.tail(1).set_index("code")
    summary = pd.DataFrame(index=last.index)
    summary["first_seen_date"] = grouped["trade_date"].min()
    summary["last_seen_date"] = grouped["trade_date"].max()
    summary["list_date"] = grouped["list_date"].min()
    summary["delist_date"] = grouped["delist_date"].max()
    summary["latest_name"] = last["name"]
    summary["first_name"] = first["name"]
    summary["latest_industry_vendor"] = last["industry_vendor"]
    summary["latest_board"] = last["board"]
    summary["latest_is_st"] = last["is_st"].astype("boolean")
    summary["latest_market_cap"] = last["market_cap"]
    summary["latest_float_market_cap"] = last["float_market_cap"]
    summary["latest_amount_yuan"] = last["amount_yuan"]
    return summary.reset_index()


def merge_security_summaries(parts: list[pd.DataFrame]) -> pd.DataFrame:
    combined = pd.concat(parts, ignore_index=True)
    combined = combined.sort_values(["code", "last_seen_date"])
    grouped = combined.groupby("code", sort=False)
    first = grouped.head(1).set_index("code")
    last = grouped.tail(1).set_index("code")
    master = pd.DataFrame(index=last.index)
    master["first_seen_date"] = grouped["first_seen_date"].min()
    master["last_seen_date"] = grouped["last_seen_date"].max()
    master["list_date"] = grouped["list_date"].min()
    master["delist_date"] = grouped["delist_date"].max()
    master["first_name"] = first["first_name"]
    master["latest_name"] = last["latest_name"]
    master["latest_industry_vendor"] = last["latest_industry_vendor"]
    master["board"] = last["latest_board"]
    master["eligible_board_v1"] = master["board"].isin(["main", "chinext"])
    master["has_delist_date"] = master["delist_date"].notna()
    master["latest_is_st"] = last["latest_is_st"].astype("boolean")
    master["latest_market_cap"] = last["latest_market_cap"]
    master["latest_float_market_cap"] = last["latest_float_market_cap"]
    master["latest_amount_yuan"] = last["latest_amount_yuan"]
    return master.reset_index().sort_values("code")


def add_security_lifecycle_flags(security: pd.DataFrame, market_end: str) -> pd.DataFrame:
    security = security.copy()
    last_seen = pd.to_datetime(security["last_seen_date"], errors="coerce")
    delist = pd.to_datetime(security["delist_date"], errors="coerce")
    security["missing_delist_but_ended_before_market_end"] = (
        delist.isna() & last_seen.notna() & last_seen.lt(pd.Timestamp(market_end))
    )
    return security


def build_trading_status_ports(processed_root: Path) -> tuple[list[str], dict[str, Any]]:
    calendar_path = processed_root / "market_calendar.csv"
    security_path = processed_root / "security_master_latest_snapshot.csv"
    market_root = processed_root / "market_daily_raw"
    status_root = processed_root / "market_trading_status"
    if status_root.exists():
        shutil.rmtree(status_root)
    status_root.mkdir(parents=True, exist_ok=True)

    calendar = pd.read_csv(calendar_path, dtype=str)
    security = pd.read_csv(security_path, dtype={"code": str})
    market_end = calendar["trade_date"].max()
    security = add_security_lifecycle_flags(security, market_end)
    security.to_csv(security_path, index=False, encoding="utf-8")
    security["active_start"] = security["first_seen_date"].fillna(security["list_date"])
    security["active_end"] = security["delist_date"].fillna(security["last_seen_date"])
    security["active_end"] = security["active_end"].fillna(market_end)
    security.loc[security["active_end"] > market_end, "active_end"] = market_end
    security = security[security["active_start"].notna() & security["active_end"].notna()].copy()

    output_files: list[str] = []
    status_stats: dict[str, Any] = {
        "total_status_rows": 0,
        "has_bar_rows": 0,
        "no_bar_rows": 0,
        "can_buy_rows": 0,
        "can_sell_rows": 0,
        "missing_delist_but_ended_before_market_end": int(
            security["missing_delist_but_ended_before_market_end"].fillna(False).sum()
        ),
        "years": {},
    }
    calendar_by_year = {
        year: group["trade_date"].tolist()
        for year, group in calendar.groupby(calendar["trade_date"].str.slice(0, 4), sort=True)
    }
    status_columns = [
        "trade_date",
        "code",
        "board",
        "eligible_board_v1",
        "has_bar",
        "trading_status",
        "is_st",
        "is_limit_up",
        "is_limit_down_est",
        "one_price_limit_est",
        "can_buy_on_bar",
        "can_sell_on_bar",
        "amount_yuan",
        "volume_shares",
        "close",
        "prev_close",
    ]
    bar_columns = [
        "trade_date",
        "code",
        "is_st",
        "is_limit_up",
        "is_limit_down_est",
        "one_price_limit_est",
        "amount_yuan",
        "volume_shares",
        "close",
        "prev_close",
    ]

    for year, dates in calendar_by_year.items():
        year_start, year_end = dates[0], dates[-1]
        active = security[(security["active_start"] <= year_end) & (security["active_end"] >= year_start)].copy()
        frames: list[pd.DataFrame] = []
        for row in active.itertuples(index=False):
            start = max(row.active_start, year_start)
            end = min(row.active_end, year_end)
            code_dates = [date for date in dates if start <= date <= end]
            if not code_dates:
                continue
            frames.append(
                pd.DataFrame(
                    {
                        "trade_date": code_dates,
                        "code": row.code,
                        "board": row.board,
                        "eligible_board_v1": str(row.eligible_board_v1).strip().lower() == "true",
                    }
                )
            )
        if frames:
            status = pd.concat(frames, ignore_index=True)
        else:
            status = pd.DataFrame(
                columns=["trade_date", "code", "board", "eligible_board_v1"]
            )

        market_file = market_root / f"year={year}" / f"market_daily_raw_{year}.csv.gz"
        bars = pd.read_csv(market_file, usecols=bar_columns, dtype={"trade_date": str, "code": str}) if market_file.exists() else pd.DataFrame(columns=bar_columns)
        status = status.merge(bars, on=["trade_date", "code"], how="left", suffixes=("", "_bar"))
        status["has_bar"] = status["close"].notna()
        status["trading_status"] = status["has_bar"].map({True: "has_bar", False: "no_bar_suspended_or_missing"})
        for col in ["is_st", "is_limit_up", "is_limit_down_est", "one_price_limit_est"]:
            status[col] = status[col].astype("boolean")
        valid_bar = (
            status["has_bar"]
            & pd.to_numeric(status["volume_shares"], errors="coerce").fillna(0).gt(0)
            & pd.to_numeric(status["amount_yuan"], errors="coerce").fillna(0).gt(0)
        )
        status["can_buy_on_bar"] = (valid_bar & ~status["is_limit_up"].fillna(False)).astype("boolean")
        status["can_sell_on_bar"] = (valid_bar & ~status["is_limit_down_est"].fillna(False)).astype("boolean")
        status = status[status_columns].sort_values(["trade_date", "code"])

        duplicate_rows = int(status.duplicated(["trade_date", "code"]).sum())
        if duplicate_rows:
            raise ValueError(f"Duplicate trading status rows in {year}: {duplicate_rows}")

        year_stats = {
            "rows": int(len(status)),
            "has_bar_rows": int(status["has_bar"].sum()),
            "no_bar_rows": int(status["trading_status"].eq("no_bar_suspended_or_missing").sum()),
            "can_buy_rows": int(status["can_buy_on_bar"].fillna(False).sum()),
            "can_sell_rows": int(status["can_sell_on_bar"].fillna(False).sum()),
        }
        status_stats["years"][year] = year_stats
        status_stats["total_status_rows"] += year_stats["rows"]
        status_stats["has_bar_rows"] += year_stats["has_bar_rows"]
        status_stats["no_bar_rows"] += year_stats["no_bar_rows"]
        status_stats["can_buy_rows"] += year_stats["can_buy_rows"]
        status_stats["can_sell_rows"] += year_stats["can_sell_rows"]

        year_dir = status_root / f"year={year}"
        year_dir.mkdir(parents=True, exist_ok=True)
        output_file = year_dir / f"market_trading_status_{year}.csv.gz"
        status.to_csv(
            output_file,
            index=False,
            encoding="utf-8",
            compression={"method": "gzip", "compresslevel": 1},
        )
        output_files.append(str(output_file.relative_to(processed_root)))
    return output_files, status_stats


def build_market_ports(data_root: Path, processed_root: Path, market_end_date: str | None) -> tuple[MarketBuildStats, list[pd.Timestamp]]:
    raw_daily_dir = discover_unadjusted_daily_dir(data_root)
    inferred_end, modal_header_columns = infer_stable_market_end_date(raw_daily_dir)
    end_date = market_end_date or inferred_end
    files_by_year = collect_daily_files(raw_daily_dir, end_date, modal_header_columns)
    included_dates = sorted(file.name.split("_")[0] for files in files_by_year.values() for file in files)
    exec_map = next_trade_date_map(included_dates)

    output_root = processed_root / "market_daily_raw"
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    years: dict[str, dict[str, Any]] = {}
    output_files: list[str] = []
    total_rows = 0
    all_dates: set[str] = set()
    security_parts: list[pd.DataFrame] = []

    for year, files in sorted(files_by_year.items()):
        frames = []
        for file in files:
            raw = pd.read_csv(file, encoding="utf-8-sig", dtype=str)
            frames.append(standardize_market_frame(raw))
        year_df = pd.concat(frames, ignore_index=True)
        year_df["exec_date"] = year_df["feature_date"].map(exec_map)
        year_df = year_df.sort_values(["trade_date", "code"])
        duplicate_rows = int(year_df.duplicated(["trade_date", "code"]).sum())
        if duplicate_rows:
            raise ValueError(f"Duplicate trade_date+code rows in {year}: {duplicate_rows}")
        bad_exec = pd.to_datetime(year_df["exec_date"], errors="coerce") <= pd.to_datetime(
            year_df["feature_date"], errors="coerce"
        )
        if int(bad_exec.fillna(False).sum()):
            raise ValueError(f"Non-forward exec_date rows in {year}")
        year_dir = output_root / f"year={year}"
        year_dir.mkdir(parents=True, exist_ok=True)
        output_file = year_dir / f"market_daily_raw_{year}.csv.gz"
        year_df.to_csv(
            output_file,
            index=False,
            encoding="utf-8",
            compression={"method": "gzip", "compresslevel": 1},
        )
        output_files.append(str(output_file.relative_to(processed_root)))
        total_rows += len(year_df)
        all_dates.update(year_df["trade_date"].dropna().unique().tolist())
        security_parts.append(year_security_summary(year_df))
        years[year] = {
            "files": len(files),
            "rows": int(len(year_df)),
            "date_min": str(year_df["trade_date"].min()),
            "date_max": str(year_df["trade_date"].max()),
            "unique_dates": int(year_df["trade_date"].nunique()),
            "unique_codes": int(year_df["code"].nunique()),
            "price_null_rows": int(year_df[["open", "high", "low", "close"]].isna().any(axis=1).sum()),
            "zero_volume_rows": int((year_df["volume_shares"].fillna(0) == 0).sum()),
            "board_counts": {str(k): int(v) for k, v in year_df["board"].value_counts(dropna=False).items()},
            "st_rows": int(year_df["is_st"].fillna(False).sum()),
        }

    calendar = pd.DataFrame({"trade_date": sorted(all_dates)})
    calendar["year"] = calendar["trade_date"].str.slice(0, 4)
    calendar_path = processed_root / "market_calendar.csv"
    calendar.to_csv(calendar_path, index=False, encoding="utf-8")

    security_master = add_security_lifecycle_flags(merge_security_summaries(security_parts), end_date)
    old_security_path = processed_root / "security_master.csv"
    if old_security_path.exists():
        old_security_path.unlink()
    security_path = processed_root / "security_master_latest_snapshot.csv"
    security_master.to_csv(security_path, index=False, encoding="utf-8")

    trade_dates = [pd.Timestamp(date) for date in calendar["trade_date"].tolist()]
    trading_status_files, trading_status_stats = build_trading_status_ports(processed_root)
    return (
        MarketBuildStats(
            market_end_date=end_date,
            modal_header_columns=modal_header_columns,
            years=years,
            total_rows=total_rows,
            total_dates=len(all_dates),
            trading_status=trading_status_stats,
            output_files=output_files + ["market_calendar.csv", "security_master_latest_snapshot.csv"] + trading_status_files,
        ),
        trade_dates,
    )


def load_existing_market_ports(processed_root: Path) -> tuple[MarketBuildStats, list[pd.Timestamp]]:
    calendar_path = processed_root / "market_calendar.csv"
    market_root = processed_root / "market_daily_raw"
    security_path = processed_root / "security_master_latest_snapshot.csv"
    if not calendar_path.exists() or not market_root.exists():
        raise FileNotFoundError("Existing market ports are incomplete; run without --reuse-market first.")
    if not security_path.exists():
        old_security_path = processed_root / "security_master.csv"
        if old_security_path.exists():
            old_security_path.replace(security_path)
        else:
            raise FileNotFoundError("Missing security_master_latest_snapshot.csv.")

    calendar = pd.read_csv(calendar_path, dtype=str)
    trade_dates = [pd.Timestamp(value) for value in calendar["trade_date"].tolist()]
    years: dict[str, dict[str, Any]] = {}
    output_files: list[str] = []
    total_rows = 0

    for file in sorted(market_root.glob("year=*/market_daily_raw_*.csv.gz")):
        year = file.parent.name.split("=", 1)[-1]
        cols = ["trade_date", "code", "open", "high", "low", "close", "volume_shares", "board", "is_st"]
        frame = pd.read_csv(file, usecols=cols, dtype={"trade_date": str, "code": str})
        total_rows += len(frame)
        output_files.append(str(file.relative_to(processed_root)))
        years[year] = {
            "files": None,
            "rows": int(len(frame)),
            "date_min": str(frame["trade_date"].min()),
            "date_max": str(frame["trade_date"].max()),
            "unique_dates": int(frame["trade_date"].nunique()),
            "unique_codes": int(frame["code"].nunique()),
            "price_null_rows": int(frame[["open", "high", "low", "close"]].isna().any(axis=1).sum()),
            "zero_volume_rows": int((pd.to_numeric(frame["volume_shares"], errors="coerce").fillna(0) == 0).sum()),
            "board_counts": {str(k): int(v) for k, v in frame["board"].value_counts(dropna=False).items()},
            "st_rows": int(frame["is_st"].astype(str).str.lower().eq("true").sum()),
        }

    status_files, status_stats = build_trading_status_ports(processed_root)
    output_files.extend(["market_calendar.csv", "security_master_latest_snapshot.csv"] + status_files)
    return (
        MarketBuildStats(
            market_end_date=str(calendar["trade_date"].max()),
            modal_header_columns=38,
            years=years,
            total_rows=total_rows,
            total_dates=int(calendar["trade_date"].nunique()),
            trading_status=status_stats,
            output_files=output_files,
        ),
        trade_dates,
    )


def stata_available_columns(path: Path) -> set[str]:
    return set(StataReader(str(path)).variable_labels().keys())


def find_finance_file(finance_dir: Path, name: str) -> Path:
    matches = list(finance_dir.rglob(name))
    if not matches:
        raise FileNotFoundError(f"Cannot find {name} under {finance_dir}")
    return matches[0]


def read_stata_selected(path: Path, mapping: dict[str, str]) -> pd.DataFrame:
    available = stata_available_columns(path)
    columns = [col for col in mapping if col in available]
    frame = pd.read_stata(str(path), columns=columns, convert_categoricals=False)
    return frame.rename(columns={col: mapping[col] for col in columns})


def require_stata_columns(path: Path, required_columns: list[str]) -> None:
    available = stata_available_columns(path)
    missing = [col for col in required_columns if col not in available]
    if missing:
        raise ValueError(f"Required Stata columns missing in {path}: {missing}")


def next_trade_date_after(ann_date: pd.Timestamp, trade_dates: list[pd.Timestamp]) -> pd.Timestamp | pd.NaT:
    if pd.isna(ann_date):
        return pd.NaT
    idx = bisect.bisect_right(trade_dates, ann_date)
    if idx >= len(trade_dates):
        return pd.NaT
    return trade_dates[idx]


def latest_correction_date(value: Any) -> pd.Timestamp | pd.NaT:
    if pd.isna(value):
        return pd.NaT
    parts = [part.strip() for part in str(value).split(",") if part.strip()]
    dates = pd.to_datetime(parts, errors="coerce")
    dates = [date for date in dates if pd.notna(date)]
    return max(dates) if dates else pd.NaT


def build_annual_finance_pit(data_root: Path, processed_root: Path, trade_dates: list[pd.Timestamp]) -> FinanceBuildStats:
    _, finance_dir = find_data_dirs(data_root)
    annual_file = next(path for path in finance_dir.glob("*.dta") if "年度数据合并" in path.name)
    far_file = find_finance_file(finance_dir, "FAR_Finidx.dta")
    require_stata_columns(annual_file, REQUIRED_ANNUAL_COLUMNS)
    require_stata_columns(far_file, REQUIRED_FAR_COLUMNS)

    annual = read_stata_selected(annual_file, ANNUAL_FIELD_MAP)
    far = read_stata_selected(far_file, FAR_FIELD_MAP)

    for frame in [annual, far]:
        frame["code"] = frame["code"].map(normalize_code)
        frame["report_period"] = clean_date_series(frame["report_period"])

    raw_rows = len(annual)
    finance = annual.merge(far, on=["code", "report_period"], how="left")
    finance = finance[finance["report_period"].str.endswith("-12-31", na=False)].copy()
    finance["report_year"] = finance["report_period"].str.slice(0, 4).astype("Int64")
    finance["ann_date"] = clean_date_series(finance["ann_date"])
    rows_with_ann_date = int(finance["ann_date"].notna().sum())
    finance = finance[finance["ann_date"].notna()].copy()
    ann_ts = pd.to_datetime(finance["ann_date"], errors="coerce")
    finance["correction_latest_date"] = finance["correction_disclosure_date"].map(latest_correction_date)
    correction_ts = pd.to_datetime(finance["correction_latest_date"], errors="coerce")
    if_correct = pd.to_numeric(finance["if_correct"], errors="coerce").eq(1)
    corrected_rows = int(if_correct.sum())
    multi_correction_date_rows = int(
        finance["correction_disclosure_date"].astype(str).str.contains(",", regex=False, na=False).sum()
    )
    corrected_rows_missing_correction_date = int((if_correct & correction_ts.isna()).sum())
    if corrected_rows_missing_correction_date:
        finance = finance[~(if_correct & correction_ts.isna())].copy()
        ann_ts = pd.to_datetime(finance["ann_date"], errors="coerce")
        correction_ts = pd.to_datetime(finance["correction_latest_date"], errors="coerce")
        if_correct = pd.to_numeric(finance["if_correct"], errors="coerce").eq(1)
    use_correction_anchor = if_correct & correction_ts.notna() & correction_ts.gt(ann_ts)
    corrected_rows_adjusted = int(use_correction_anchor.sum())
    finance["pit_anchor_date"] = ann_ts
    finance.loc[use_correction_anchor, "pit_anchor_date"] = correction_ts.loc[use_correction_anchor]
    finance["pit_anchor_reason"] = "original_announcement"
    finance.loc[use_correction_anchor, "pit_anchor_reason"] = "correction_disclosure"
    finance["pit_anchor_date"] = pd.to_datetime(finance["pit_anchor_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    finance["correction_latest_date"] = pd.to_datetime(
        finance["correction_latest_date"], errors="coerce"
    ).dt.strftime("%Y-%m-%d")
    pit_anchor_ts = pd.to_datetime(finance["pit_anchor_date"], errors="coerce")
    finance["effective_trade_date"] = [next_trade_date_after(value, trade_dates) for value in pit_anchor_ts]
    finance["effective_trade_date"] = pd.to_datetime(finance["effective_trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    rows_with_effective = int(finance["effective_trade_date"].notna().sum())
    finance = finance[finance["effective_trade_date"].notna()].copy()
    bad_pit = pd.to_datetime(finance["effective_trade_date"], errors="coerce") <= pd.to_datetime(
        finance["pit_anchor_date"], errors="coerce"
    )
    if int(bad_pit.fillna(False).sum()):
        raise ValueError("Annual finance PIT effective date is not after PIT anchor date.")

    text_columns = {
        "code",
        "finance_name",
        "report_period",
        "report_type",
        "correction_disclosure_date",
        "correction_latest_date",
        "ann_date",
        "pit_anchor_date",
        "pit_anchor_reason",
        "effective_trade_date",
    }
    for col in finance.columns:
        if col in text_columns or col == "report_year":
            continue
        finance[col] = pd.to_numeric(finance[col], errors="coerce")

    output_file = processed_root / "annual_finance_pit.csv.gz"
    finance = finance.sort_values(["effective_trade_date", "code", "report_period"])
    finance.to_csv(
        output_file,
        index=False,
        encoding="utf-8",
        compression={"method": "gzip", "compresslevel": 1},
    )

    report_dates = pd.to_datetime(finance["report_period"], errors="coerce")
    ann_dates = pd.to_datetime(finance["ann_date"], errors="coerce")
    return FinanceBuildStats(
        raw_rows=raw_rows,
        rows_with_ann_date=rows_with_ann_date,
        corrected_rows=corrected_rows,
        corrected_rows_adjusted_to_correction_date=corrected_rows_adjusted,
        corrected_rows_missing_correction_date=corrected_rows_missing_correction_date,
        multi_correction_date_rows=multi_correction_date_rows,
        rows_with_effective_trade_date=rows_with_effective,
        dropped_missing_ann_date=raw_rows - rows_with_ann_date,
        dropped_missing_correction_date=corrected_rows_missing_correction_date,
        dropped_missing_effective_trade_date=rows_with_ann_date
        - corrected_rows_missing_correction_date
        - rows_with_effective,
        report_period_min=str(report_dates.min().date()) if report_dates.notna().any() else None,
        report_period_max=str(report_dates.max().date()) if report_dates.notna().any() else None,
        ann_date_min=str(ann_dates.min().date()) if ann_dates.notna().any() else None,
        ann_date_max=str(ann_dates.max().date()) if ann_dates.notna().any() else None,
        output_file=str(output_file.relative_to(processed_root)),
    )


def render_validation(manifest: dict[str, Any]) -> str:
    market = manifest["market"]
    status = market["trading_status"]
    finance = manifest["annual_finance_pit"]
    lines = [
        "# Processed Data Validation",
        "",
        "## Market",
        "",
        f"- Stable market end date: `{market['market_end_date']}`",
        f"- Modal daily header width: `{market['modal_header_columns']}`",
        f"- Total rows: `{market['total_rows']}`",
        f"- Total trade dates: `{market['total_dates']}`",
        "",
        "Yearly partitions:",
        "",
    ]
    for year, stats in market["years"].items():
        lines.append(
            f"- `{year}`: rows={stats['rows']}, dates={stats['date_min']}..{stats['date_max']}, "
            f"unique_codes={stats['unique_codes']}, price_null_rows={stats['price_null_rows']}, "
            f"zero_volume_rows={stats['zero_volume_rows']}"
        )
    lines.extend(
        [
            "",
            "## Market Trading Status",
            "",
            f"- Total status rows: `{status['total_status_rows']}`",
            f"- Has-bar rows: `{status['has_bar_rows']}`",
            f"- No-bar active rows: `{status['no_bar_rows']}`",
            f"- Can-buy rows: `{status['can_buy_rows']}`",
            f"- Can-sell rows: `{status['can_sell_rows']}`",
            f"- Missing delist date but ended before market end: `{status['missing_delist_but_ended_before_market_end']}`",
            "",
            "## Annual Finance PIT",
            "",
            f"- Raw annual rows: `{finance['raw_rows']}`",
            f"- Rows with announcement date: `{finance['rows_with_ann_date']}`",
            f"- Corrected annual rows: `{finance['corrected_rows']}`",
            f"- Corrected rows anchored to correction disclosure date: `{finance['corrected_rows_adjusted_to_correction_date']}`",
            f"- Corrected rows missing correction disclosure date: `{finance['corrected_rows_missing_correction_date']}`",
            f"- Rows with multiple correction disclosure dates: `{finance['multi_correction_date_rows']}`",
            f"- Rows with effective trade date: `{finance['rows_with_effective_trade_date']}`",
            f"- Dropped missing announcement date: `{finance['dropped_missing_ann_date']}`",
            f"- Dropped missing correction disclosure date: `{finance['dropped_missing_correction_date']}`",
            f"- Dropped missing effective trade date: `{finance['dropped_missing_effective_trade_date']}`",
            f"- Report periods: `{finance['report_period_min']}` to `{finance['report_period_max']}`",
            f"- Announcement dates: `{finance['ann_date_min']}` to `{finance['ann_date_max']}`",
            "",
            "## Verdict",
            "",
            "- Processed market data is cut at the stable daily schema end date.",
            "- `security_master_latest_snapshot` is only a latest audit snapshot, not a historical universe.",
            "- `market_trading_status` describes whether the `trade_date` bar itself can execute buy/sell orders.",
            "- EOD market fields are labeled with `feature_date`; trading can only occur on `exec_date`.",
            "- Annual finance uses next trading day after the later of `Annodt` and correction disclosure date as the conservative PIT effective date.",
            "- Quarterly finance is intentionally not built into a tradable port yet.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build cleaned data ports for A-share small-cap research.")
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--processed-root", default="processed")
    parser.add_argument("--output-dir", default="outputs/processed_validation")
    parser.add_argument("--market-end-date", default=None, help="Override stable market end date, YYYY-MM-DD.")
    parser.add_argument("--reuse-market", action="store_true", help="Reuse existing processed market ports.")
    args = parser.parse_args()

    data_root = Path(args.data_root).resolve()
    processed_root = Path(args.processed_root).resolve()
    output_dir = Path(args.output_dir).resolve()
    processed_root.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.reuse_market:
        market_stats, trade_dates = load_existing_market_ports(processed_root)
    else:
        market_stats, trade_dates = build_market_ports(data_root, processed_root, args.market_end_date)
    finance_stats = build_annual_finance_pit(data_root, processed_root, trade_dates)

    manifest = {
        "data_root": str(data_root),
        "processed_root": str(processed_root),
        "market": asdict(market_stats),
        "annual_finance_pit": asdict(finance_stats),
    }
    manifest_path = processed_root / "build_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    validation_path = output_dir / "processed_data_validation.md"
    validation_path.write_text(render_validation(manifest), encoding="utf-8")

    print(f"Wrote {manifest_path}")
    print(f"Wrote {validation_path}")


if __name__ == "__main__":
    main()
