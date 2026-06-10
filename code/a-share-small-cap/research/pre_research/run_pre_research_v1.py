from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.append(str(SCRIPTS_ROOT))

from build_processed_data import MARKET_COLUMN_MAP, clean_date_series  # noqa: E402
from data_audit import normalize_code  # noqa: E402


RESEARCH_START = "2005-01-01"
RESEARCH_END = "2025-12-31"
WARMUP_START = "2004-01-01"
SIZE_BUCKET_EDGES = [0.0, 0.05, 0.10, 0.20, 0.30, 0.50, 1.0]
SIZE_BUCKET_LABELS = ["p00_05", "p05_10", "p10_20", "p20_30", "p30_50", "p50_100"]
REGIMES = [
    ("2005-2013", "2005-01-01", "2013-12-31"),
    ("2014-2015", "2014-01-01", "2015-12-31"),
    ("2016-2018", "2016-01-01", "2018-12-31"),
    ("2019-2021", "2019-01-01", "2021-12-31"),
    ("2022-2025", "2022-01-01", "2025-12-31"),
]


@dataclass
class Paths:
    data_root: Path
    processed_root: Path
    output_root: Path
    figures_root: Path
    tables_root: Path


def log(message: str) -> None:
    print(f"[pre_research] {message}", flush=True)


def parse_bool_series(series: pd.Series) -> pd.Series:
    if series.dtype == "bool":
        return series
    text = series.astype(str).str.strip().str.lower()
    return text.isin(["true", "1", "yes", "y"])


def safe_annualized_return(daily_returns: pd.Series) -> float:
    values = pd.to_numeric(daily_returns, errors="coerce").dropna()
    if values.empty:
        return np.nan
    values = values[(values > -0.95) & (values < 5.0)]
    if values.empty:
        return np.nan
    return float((1.0 + values.mean()) ** 252 - 1.0)


def cumulative_return(daily_returns: pd.Series) -> float:
    values = pd.to_numeric(daily_returns, errors="coerce").dropna()
    if values.empty:
        return np.nan
    values = values[(values > -0.95) & (values < 5.0)]
    if values.empty:
        return np.nan
    return float((1.0 + values).prod() - 1.0)


def status_color(status: str) -> str:
    return {"Green": "#1b8f3a", "Yellow": "#b7791f", "Red": "#b42318"}.get(status, "#333333")


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
    ]
    for path in candidates:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                continue
    return ImageFont.load_default()


def draw_multi_line_chart(
    frame: pd.DataFrame,
    path: Path,
    title: str,
    y_label: str = "",
    max_points: int = 900,
) -> None:
    data = frame.copy()
    data = data.replace([np.inf, -np.inf], np.nan).dropna(how="all")
    if data.empty:
        draw_placeholder(path, title, "No data")
        return
    if len(data) > max_points:
        step = math.ceil(len(data) / max_points)
        data = data.iloc[::step].copy()

    width, height = 1280, 760
    left, right, top, bottom = 90, 40, 80, 90
    plot_w = width - left - right
    plot_h = height - top - bottom
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font_title = load_font(28, True)
    font = load_font(18)
    small_font = load_font(15)
    draw.text((left, 24), title, fill="#111111", font=font_title)
    if y_label:
        draw.text((left, 56), y_label, fill="#555555", font=small_font)

    values = data.to_numpy(dtype=float)
    y_min = np.nanmin(values)
    y_max = np.nanmax(values)
    if not np.isfinite(y_min) or not np.isfinite(y_max):
        draw_placeholder(path, title, "No finite data")
        return
    if abs(y_max - y_min) < 1e-12:
        y_max += 1.0
        y_min -= 1.0
    pad = (y_max - y_min) * 0.08
    y_min -= pad
    y_max += pad

    for i in range(6):
        y = top + plot_h * i / 5
        draw.line((left, y, width - right, y), fill="#e8e8e8", width=1)
        value = y_max - (y_max - y_min) * i / 5
        draw.text((12, y - 10), f"{value:.2f}", fill="#555555", font=small_font)
    draw.rectangle((left, top, width - right, height - bottom), outline="#333333", width=1)

    palette = [
        "#1f77b4",
        "#d62728",
        "#2ca02c",
        "#9467bd",
        "#ff7f0e",
        "#17becf",
        "#8c564b",
        "#7f7f7f",
    ]

    n = len(data)
    xs = [left + (plot_w * i / max(n - 1, 1)) for i in range(n)]
    for col_idx, col in enumerate(data.columns):
        series = pd.to_numeric(data[col], errors="coerce")
        points = []
        for x, value in zip(xs, series):
            if not np.isfinite(value):
                points.append(None)
                continue
            y = top + (y_max - value) / (y_max - y_min) * plot_h
            points.append((x, y))
        color = palette[col_idx % len(palette)]
        segment: list[tuple[float, float]] = []
        for point in points:
            if point is None:
                if len(segment) >= 2:
                    draw.line(segment, fill=color, width=3)
                segment = []
            else:
                segment.append(point)
        if len(segment) >= 2:
            draw.line(segment, fill=color, width=3)

    legend_x = left
    legend_y = height - 64
    for col_idx, col in enumerate(data.columns):
        color = palette[col_idx % len(palette)]
        draw.line((legend_x, legend_y + 10, legend_x + 34, legend_y + 10), fill=color, width=4)
        draw.text((legend_x + 42, legend_y), str(col), fill="#222222", font=small_font)
        legend_x += 170
        if legend_x > width - 220:
            legend_x = left
            legend_y += 24

    x_labels = [str(data.index[0])[:10], str(data.index[len(data) // 2])[:10], str(data.index[-1])[:10]]
    x_positions = [left, left + plot_w / 2 - 45, width - right - 90]
    for x, label in zip(x_positions, x_labels):
        draw.text((x, height - bottom + 20), label, fill="#555555", font=small_font)

    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def draw_bar_chart(labels: list[str], values: list[float], path: Path, title: str, y_label: str = "") -> None:
    clean_values = [float(v) if pd.notna(v) and np.isfinite(v) else 0.0 for v in values]
    width, height = 1280, 760
    left, right, top, bottom = 90, 40, 90, 150
    plot_w = width - left - right
    plot_h = height - top - bottom
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font_title = load_font(28, True)
    font = load_font(17)
    small_font = load_font(14)
    draw.text((left, 26), title, fill="#111111", font=font_title)
    if y_label:
        draw.text((left, 60), y_label, fill="#555555", font=small_font)

    y_min = min(min(clean_values), 0.0)
    y_max = max(max(clean_values), 0.0)
    if abs(y_max - y_min) < 1e-12:
        y_max, y_min = 1.0, -1.0
    pad = (y_max - y_min) * 0.12
    y_min -= pad
    y_max += pad
    zero_y = top + (y_max - 0.0) / (y_max - y_min) * plot_h

    for i in range(6):
        y = top + plot_h * i / 5
        draw.line((left, y, width - right, y), fill="#e8e8e8", width=1)
        value = y_max - (y_max - y_min) * i / 5
        draw.text((12, y - 10), f"{value:.2f}", fill="#555555", font=small_font)
    draw.line((left, zero_y, width - right, zero_y), fill="#333333", width=2)

    n = max(len(labels), 1)
    bar_gap = 8
    bar_w = max(12, (plot_w - bar_gap * (n + 1)) / n)
    for idx, (label, value) in enumerate(zip(labels, clean_values)):
        x0 = left + bar_gap + idx * (bar_w + bar_gap)
        x1 = x0 + bar_w
        y = top + (y_max - value) / (y_max - y_min) * plot_h
        color = "#1b8f3a" if value >= 0 else "#b42318"
        draw.rectangle((x0, min(y, zero_y), x1, max(y, zero_y)), fill=color)
        if idx % max(1, len(labels) // 18) == 0:
            draw.text((x0 - 8, height - bottom + 18), str(label), fill="#555555", font=small_font)
    draw.rectangle((left, top, width - right, height - bottom), outline="#333333", width=1)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def draw_placeholder(path: Path, title: str, message: str) -> None:
    image = Image.new("RGB", (1000, 520), "white")
    draw = ImageDraw.Draw(image)
    draw.text((50, 40), title, fill="#111111", font=load_font(28, True))
    draw.text((50, 120), message, fill="#555555", font=load_font(20))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def market_daily_adjusted_dir(data_root: Path, adjust_name: str) -> Path:
    market_root = data_root / "更新到5.14号" / "每天一个文件" / adjust_name
    if not market_root.exists():
        raise FileNotFoundError(f"Cannot find adjusted daily directory: {market_root}")
    return market_root


def adjusted_daily_files(data_root: Path, adjust_name: str, market_end: str) -> list[Path]:
    root = market_daily_adjusted_dir(data_root, adjust_name)
    files = []
    for file in sorted(root.glob("*/*.csv")):
        date = file.name.split("_")[0]
        if date <= market_end:
            files.append(file)
    if not files:
        raise FileNotFoundError(f"No adjusted daily files found under {root}")
    return files


def build_adjusted_returns(paths: Paths, market_end: str, force: bool = False) -> dict[str, Any]:
    output_root = paths.processed_root / "market_daily_adj_returns"
    manifest_path = output_root / "build_manifest.json"
    existing = sorted(output_root.glob("year=*/market_daily_adj_returns_*.csv.gz"))
    source_dir = market_daily_adjusted_dir(paths.data_root, "前复权")
    source_files = adjusted_daily_files(paths.data_root, "前复权", market_end)
    expected_manifest = {
        "adjust_name": "前复权",
        "market_end": market_end,
        "source_dir": str(source_dir),
        "source_file_count": len(source_files),
    }
    if existing and manifest_path.exists() and not force:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if all(manifest.get(key) == value for key, value in expected_manifest.items()):
            return {
                "rebuilt": False,
                "files": len(existing),
                "rows": manifest.get("row_count"),
                "missing_fwd_cc_ret_1d": manifest.get("missing_fwd_cc_ret_1d"),
                "source_file_count": manifest.get("source_file_count"),
                "output_root": str(output_root),
            }
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    reverse_map = {standard: raw for raw, standard in MARKET_COLUMN_MAP.items()}
    read_cols = [reverse_map["trade_date"], reverse_map["code"], reverse_map["open"], reverse_map["close"]]
    pieces = []
    for idx, file in enumerate(source_files, 1):
        if idx % 500 == 0:
            log(f"read adjusted daily files: {idx}/{len(source_files)}")
        raw = pd.read_csv(file, encoding="utf-8-sig", usecols=read_cols, dtype=str)
        raw = raw.rename(
            columns={
                reverse_map["trade_date"]: "trade_date",
                reverse_map["code"]: "code",
                reverse_map["open"]: "adj_open",
                reverse_map["close"]: "adj_close",
            }
        )
        raw["trade_date"] = clean_date_series(raw["trade_date"])
        raw["code"] = raw["code"].map(normalize_code)
        raw["adj_open"] = pd.to_numeric(raw["adj_open"], errors="coerce").astype("float32")
        raw["adj_close"] = pd.to_numeric(raw["adj_close"], errors="coerce").astype("float32")
        pieces.append(raw)
    prices = pd.concat(pieces, ignore_index=True)
    prices = prices.dropna(subset=["trade_date", "code"]).sort_values(["trade_date", "code"])

    calendar = pd.read_csv(paths.processed_root / "market_calendar.csv", dtype=str)
    calendar = calendar[calendar["trade_date"] <= market_end].copy()
    next_map = {
        date: calendar["trade_date"].iloc[idx + 1] if idx + 1 < len(calendar) else pd.NA
        for idx, date in enumerate(calendar["trade_date"].tolist())
    }
    prices["exec_date"] = prices["trade_date"].map(next_map)
    next_prices = prices[["trade_date", "code", "adj_open", "adj_close"]].rename(
        columns={
            "trade_date": "exec_date",
            "adj_open": "exec_adj_open",
            "adj_close": "exec_adj_close",
        }
    )
    returns = prices.merge(next_prices, on=["exec_date", "code"], how="left")
    returns["fwd_cc_ret_1d"] = returns["exec_adj_close"] / returns["adj_close"] - 1.0
    returns["exec_oc_ret_1d"] = returns["exec_adj_close"] / returns["exec_adj_open"] - 1.0
    returns = returns[
        [
            "trade_date",
            "exec_date",
            "code",
            "adj_open",
            "adj_close",
            "exec_adj_open",
            "exec_adj_close",
            "fwd_cc_ret_1d",
            "exec_oc_ret_1d",
        ]
    ].sort_values(["trade_date", "code"])

    output_files = []
    for year, frame in returns.groupby(returns["trade_date"].str.slice(0, 4), sort=True):
        year_dir = output_root / f"year={year}"
        year_dir.mkdir(parents=True, exist_ok=True)
        output_file = year_dir / f"market_daily_adj_returns_{year}.csv.gz"
        frame.to_csv(
            output_file,
            index=False,
            encoding="utf-8",
            compression={"method": "gzip", "compresslevel": 1},
        )
        output_files.append(str(output_file.relative_to(paths.processed_root)))
    manifest = {
        **expected_manifest,
        "file_count": len(output_files),
        "row_count": int(len(returns)),
        "missing_fwd_cc_ret_1d": int(returns["fwd_cc_ret_1d"].isna().sum()),
        "missing_exec_oc_ret_1d": int(returns["exec_oc_ret_1d"].isna().sum()),
        "build_time": datetime.now().isoformat(timespec="seconds"),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "rebuilt": True,
        "files": len(output_files),
        "rows": int(len(returns)),
        "missing_fwd_cc_ret_1d": int(returns["fwd_cc_ret_1d"].isna().sum()),
        "missing_exec_oc_ret_1d": int(returns["exec_oc_ret_1d"].isna().sum()),
        "source_file_count": len(source_files),
        "output_root": str(output_root),
    }


def load_yearly_csv(root: Path, pattern: str, years: list[str], usecols: list[str], dtype: dict[str, Any] | None = None) -> pd.DataFrame:
    frames = []
    for year in years:
        file = root / f"year={year}" / pattern.format(year=year)
        if not file.exists():
            continue
        frames.append(pd.read_csv(file, usecols=usecols, dtype=dtype))
    if not frames:
        raise FileNotFoundError(f"No files loaded from {root}")
    return pd.concat(frames, ignore_index=True)


def load_pre_research_panel(paths: Paths) -> tuple[pd.DataFrame, dict[str, Any]]:
    years = [str(year) for year in range(2004, 2026)]
    market_cols = [
        "trade_date",
        "feature_date",
        "exec_date",
        "code",
        "board",
        "name",
        "is_st",
        "amount_yuan",
        "volume_shares",
        "float_market_cap",
        "market_cap",
        "pe_ttm_vendor",
        "pb_vendor",
        "ps_ttm_vendor",
    ]
    return_cols = ["trade_date", "code", "fwd_cc_ret_1d", "exec_oc_ret_1d"]
    status_cols = [
        "trade_date",
        "code",
        "has_bar",
        "can_buy_on_bar",
        "can_sell_on_bar",
        "is_limit_up",
        "is_limit_down_est",
        "one_price_limit_est",
    ]
    log("load market panel")
    market = load_yearly_csv(
        paths.processed_root / "market_daily_raw",
        "market_daily_raw_{year}.csv.gz",
        years,
        market_cols,
        dtype={"trade_date": str, "feature_date": str, "exec_date": str, "code": str, "board": str, "name": str},
    )
    log(f"market rows loaded: {len(market):,}")
    market = market[(market["feature_date"] >= WARMUP_START) & (market["feature_date"] <= RESEARCH_END)].copy()
    for col in ["amount_yuan", "volume_shares", "float_market_cap", "market_cap", "pe_ttm_vendor", "pb_vendor", "ps_ttm_vendor"]:
        market[col] = pd.to_numeric(market[col], errors="coerce").astype("float64")
    market["is_st"] = parse_bool_series(market["is_st"])
    market["name_contains_st"] = market["name"].fillna("").str.upper().str.contains("ST", regex=False)
    market = market.sort_values(["code", "feature_date"])
    market["list_age_trade_days"] = market.groupby("code", sort=False).cumcount() + 1
    market["amount_20d_mean"] = (
        market.groupby("code", sort=False)["amount_yuan"]
        .rolling(20, min_periods=20)
        .mean()
        .reset_index(level=0, drop=True)
    )

    log("load adjusted returns")
    returns = load_yearly_csv(
        paths.processed_root / "market_daily_adj_returns",
        "market_daily_adj_returns_{year}.csv.gz",
        years,
        return_cols,
        dtype={"trade_date": str, "code": str},
    )
    returns = returns.rename(columns={"trade_date": "feature_date"})
    for col in ["fwd_cc_ret_1d", "exec_oc_ret_1d"]:
        returns[col] = pd.to_numeric(returns[col], errors="coerce").astype("float64")
    market = market.merge(returns, on=["feature_date", "code"], how="left")

    log("load execution status")
    status_years = [str(year) for year in range(2005, 2027)]
    status = load_yearly_csv(
        paths.processed_root / "market_trading_status",
        "market_trading_status_{year}.csv.gz",
        status_years,
        status_cols,
        dtype={"trade_date": str, "code": str},
    )
    status = status.rename(
        columns={
            "trade_date": "exec_date",
            "has_bar": "exec_has_bar",
            "can_buy_on_bar": "exec_can_buy_on_bar",
            "can_sell_on_bar": "exec_can_sell_on_bar",
            "is_limit_up": "exec_is_limit_up",
            "is_limit_down_est": "exec_is_limit_down_est",
            "one_price_limit_est": "exec_one_price_limit_est",
        }
    )
    for col in [
        "exec_has_bar",
        "exec_can_buy_on_bar",
        "exec_can_sell_on_bar",
        "exec_is_limit_up",
        "exec_is_limit_down_est",
        "exec_one_price_limit_est",
    ]:
        status[col] = parse_bool_series(status[col])
    market = market.merge(status, on=["exec_date", "code"], how="left")
    log(f"panel rows after joins: {len(market):,}")

    sample = market[(market["feature_date"] >= RESEARCH_START) & (market["feature_date"] <= RESEARCH_END)].copy()
    sample["base_universe"] = (
        sample["board"].isin(["main", "chinext"])
        & sample["is_st"].eq(False)
        & sample["name_contains_st"].eq(False)
        & sample["list_age_trade_days"].ge(120)
        & sample["amount_20d_mean"].notna()
        & sample["amount_20d_mean"].gt(0)
        & sample["float_market_cap"].notna()
        & sample["float_market_cap"].gt(0)
        & sample["exec_date"].notna()
    )
    sample["exec_status_missing"] = sample["base_universe"] & sample["exec_has_bar"].isna()
    sample["exec_tradable_buy"] = sample["base_universe"] & sample["exec_has_bar"].eq(True) & sample["exec_can_buy_on_bar"].eq(True)
    sample["exec_tradable_sell"] = sample["base_universe"] & sample["exec_has_bar"].eq(True) & sample["exec_can_sell_on_bar"].eq(True)
    sample["return_available"] = sample["fwd_cc_ret_1d"].notna()

    eligible_for_bucket = sample["base_universe"]
    sample.loc[eligible_for_bucket, "size_pct"] = sample.loc[eligible_for_bucket].groupby("feature_date")[
        "float_market_cap"
    ].rank(pct=True, method="first", ascending=True)
    sample["size_bucket"] = pd.cut(
        sample["size_pct"],
        bins=SIZE_BUCKET_EDGES,
        labels=SIZE_BUCKET_LABELS,
        include_lowest=True,
    )
    sample["size_score"] = np.nan
    sample.loc[sample["float_market_cap"].gt(0), "size_score"] = -np.log(
        sample.loc[sample["float_market_cap"].gt(0), "float_market_cap"]
    )
    sample["value_pb_score"] = np.nan
    sample.loc[sample["pb_vendor"].gt(0), "value_pb_score"] = -np.log(
        sample.loc[sample["pb_vendor"].gt(0), "pb_vendor"]
    )
    sample["value_pe_score"] = np.nan
    sample.loc[sample["pe_ttm_vendor"].gt(0), "value_pe_score"] = -np.log(
        sample.loc[sample["pe_ttm_vendor"].gt(0), "pe_ttm_vendor"]
    )
    sample["value_ps_score"] = np.nan
    sample.loc[sample["ps_ttm_vendor"].gt(0), "value_ps_score"] = -np.log(
        sample.loc[sample["ps_ttm_vendor"].gt(0), "ps_ttm_vendor"]
    )

    stats = {
        "rows": int(len(sample)),
        "base_universe_rows": int(sample["base_universe"].sum()),
        "exec_status_missing_rows": int(sample["exec_status_missing"].sum()),
        "return_available_rows": int((sample["base_universe"] & sample["return_available"]).sum()),
        "exec_tradable_buy_rows": int(sample["exec_tradable_buy"].sum()),
        "start": RESEARCH_START,
        "end": RESEARCH_END,
    }
    return sample, stats


def rank_ic_by_date(panel: pd.DataFrame, factor: str, ret_col: str = "fwd_cc_ret_1d") -> pd.Series:
    subset = panel[panel["base_universe"] & panel[ret_col].notna() & panel[factor].notna()].copy()
    if subset.empty:
        return pd.Series(dtype=float)
    def corr_func(group: pd.DataFrame) -> float:
        if group[factor].nunique(dropna=True) < 3 or group[ret_col].nunique(dropna=True) < 3:
            return np.nan
        return group[factor].rank().corr(group[ret_col].rank())
    return subset.groupby("feature_date", sort=True).apply(corr_func)


def bucket_return_table(panel: pd.DataFrame, tradable: bool = False) -> pd.DataFrame:
    if tradable:
        mask = panel["base_universe"] & panel["size_bucket"].notna()
        subset = panel.loc[mask, ["feature_date", "size_bucket", "exec_oc_ret_1d", "exec_tradable_buy"]].copy()
        subset["fresh_entry_ret"] = np.where(
            subset["exec_tradable_buy"] & subset["exec_oc_ret_1d"].notna(),
            subset["exec_oc_ret_1d"],
            0.0,
        )
        grouped = subset.groupby(["feature_date", "size_bucket"], observed=True)["fresh_entry_ret"].mean().unstack()
    else:
        mask = panel["base_universe"] & panel["return_available"] & panel["size_bucket"].notna()
        subset = panel.loc[mask, ["feature_date", "size_bucket", "fwd_cc_ret_1d"]].copy()
        grouped = subset.groupby(["feature_date", "size_bucket"], observed=True)["fwd_cc_ret_1d"].mean().unstack()
    return grouped.reindex(columns=SIZE_BUCKET_LABELS)


def combine_buckets(bucket_returns: pd.DataFrame, columns: list[str], name: str) -> pd.Series:
    existing = [col for col in columns if col in bucket_returns.columns]
    if not existing:
        return pd.Series(dtype=float, name=name)
    return bucket_returns[existing].mean(axis=1).rename(name)


def compute_universe_diagnostics(panel: pd.DataFrame) -> pd.DataFrame:
    grouped = panel.groupby("feature_date", sort=True)
    diag = pd.DataFrame(
        {
            "rows": grouped.size(),
            "base_universe": grouped["base_universe"].sum(),
            "exec_tradable_buy": grouped["exec_tradable_buy"].sum(),
            "exec_tradable_sell": grouped["exec_tradable_sell"].sum(),
            "exec_status_missing": grouped["exec_status_missing"].sum(),
        }
    )
    diag["tradable_buy_coverage"] = diag["exec_tradable_buy"] / diag["base_universe"].replace(0, np.nan)
    diag["exec_status_missing_rate"] = diag["exec_status_missing"] / diag["base_universe"].replace(0, np.nan)
    return diag


def annual_ic_table(ic: pd.Series) -> pd.DataFrame:
    if ic.empty:
        return pd.DataFrame(columns=["year", "rank_ic_mean", "rank_ic_median", "rank_ic_positive_rate", "observations"])
    frame = ic.rename("rank_ic").reset_index()
    frame["year"] = frame["feature_date"].astype(str).str.slice(0, 4)
    return (
        frame.groupby("year")["rank_ic"]
        .agg(rank_ic_mean="mean", rank_ic_median="median", rank_ic_positive_rate=lambda x: float((x > 0).mean()), observations="count")
        .reset_index()
    )


def factor_ic_summary(panel: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, pd.Series]]:
    factors = {
        "size_score": "Size -log(float mcap)",
        "value_pb_score": "Value -log(PB)",
        "value_pe_score": "Value -log(PE positive)",
        "value_ps_score": "Value -log(PS)",
    }
    rows = []
    series_map = {}
    for factor, label in factors.items():
        ic = rank_ic_by_date(panel, factor)
        series_map[factor] = ic
        rows.append(
            {
                "factor": factor,
                "label": label,
                "rank_ic_mean": float(ic.mean()) if not ic.empty else np.nan,
                "rank_ic_median": float(ic.median()) if not ic.empty else np.nan,
                "rank_ic_positive_rate": float((ic > 0).mean()) if not ic.empty else np.nan,
                "observations": int(ic.notna().sum()) if not ic.empty else 0,
                "coverage_rows": int((panel["base_universe"] & panel[factor].notna()).sum()),
            }
        )
    return pd.DataFrame(rows), series_map


def return_summary_table(bucket_returns: pd.DataFrame, label: str) -> pd.DataFrame:
    rows = []
    for col in bucket_returns.columns:
        rows.append(
            {
                "scope": label,
                "bucket": col,
                "ann_return_mean_based": safe_annualized_return(bucket_returns[col]),
                "cumulative_return": cumulative_return(bucket_returns[col]),
                "daily_mean": float(bucket_returns[col].mean()),
                "daily_std": float(bucket_returns[col].std()),
                "observations": int(bucket_returns[col].notna().sum()),
            }
        )
    return pd.DataFrame(rows)


def regime_table(bucket_returns: pd.DataFrame) -> pd.DataFrame:
    rows = []
    small_10_30 = combine_buckets(bucket_returns, ["p10_20", "p20_30"], "small_10_30")
    small_20_50 = combine_buckets(bucket_returns, ["p20_30", "p30_50"], "small_20_50")
    large = bucket_returns["p50_100"] if "p50_100" in bucket_returns.columns else pd.Series(dtype=float)
    frame = pd.concat([small_10_30, small_20_50, large.rename("large_50_100")], axis=1)
    for name, start, end in REGIMES:
        window = frame[(frame.index >= start) & (frame.index <= end)]
        rows.append(
            {
                "regime": name,
                "small_10_30_ann_return": safe_annualized_return(window["small_10_30"]),
                "small_20_50_ann_return": safe_annualized_return(window["small_20_50"]),
                "large_50_100_ann_return": safe_annualized_return(window["large_50_100"]),
                "spread_10_30_minus_large": safe_annualized_return(window["small_10_30"] - window["large_50_100"]),
                "spread_20_50_minus_large": safe_annualized_return(window["small_20_50"] - window["large_50_100"]),
                "observations": int(window.notna().any(axis=1).sum()),
            }
        )
    return pd.DataFrame(rows)


def monthly_smoke_baseline(panel: pd.DataFrame, max_names: int = 100) -> tuple[pd.Series, pd.DataFrame]:
    candidates = panel[
        panel["base_universe"]
        & panel["return_available"]
        & panel["exec_tradable_buy"]
        & panel["size_pct"].gt(0.05)
        & panel["size_pct"].le(0.30)
    ].copy()
    if candidates.empty:
        return pd.Series(dtype=float), pd.DataFrame()
    dates = pd.Series(sorted(candidates["feature_date"].unique()))
    month_end_dates = dates.groupby(dates.str.slice(0, 7)).tail(1).tolist()
    daily_returns = panel[panel["return_available"]][["feature_date", "code", "fwd_cc_ret_1d"]].copy()
    daily_returns = daily_returns.set_index(["feature_date", "code"])["fwd_cc_ret_1d"]
    nav_returns: list[tuple[str, float]] = []
    selections = []
    for idx, rebalance_date in enumerate(month_end_dates[:-1]):
        next_rebalance_date = month_end_dates[idx + 1]
        selection = candidates[candidates["feature_date"].eq(rebalance_date)].nsmallest(max_names, "float_market_cap")
        holdings = selection["code"].tolist()
        selections.append(
            {
                "rebalance_date": rebalance_date,
                "next_rebalance_date": next_rebalance_date,
                "selected": len(holdings),
                "median_amount_20d": float(selection["amount_20d_mean"].median()) if holdings else np.nan,
                "median_float_market_cap": float(selection["float_market_cap"].median()) if holdings else np.nan,
            }
        )
        if not holdings:
            continue
        trade_dates = dates[(dates > rebalance_date) & (dates <= next_rebalance_date)].tolist()
        for trade_date in trade_dates:
            idxer = pd.MultiIndex.from_product([[trade_date], holdings], names=["feature_date", "code"])
            values = daily_returns.reindex(idxer).fillna(0.0)
            nav_returns.append((trade_date, float(values.mean())))
    if not nav_returns:
        return pd.Series(dtype=float), pd.DataFrame(selections)
    series = pd.Series([value for _, value in nav_returns], index=[date for date, _ in nav_returns], name="smoke_top100_ex_bottom5")
    return series, pd.DataFrame(selections)


def determine_gates(
    panel_stats: dict[str, Any],
    bucket_theory: pd.DataFrame,
    bucket_tradable: pd.DataFrame,
    factor_summary: pd.DataFrame,
    regimes: pd.DataFrame,
    smoke_returns: pd.Series,
    smoke_selections: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    metrics: dict[str, Any] = {}
    data_status = "Green"
    if panel_stats["base_universe_rows"] == 0 or panel_stats["return_available_rows"] == 0:
        data_status = "Red"
    elif panel_stats["exec_status_missing_rows"] / max(panel_stats["base_universe_rows"], 1) > 0.01:
        data_status = "Yellow"

    theory_summary = return_summary_table(bucket_theory, "theoretical")
    tradable_summary = return_summary_table(bucket_tradable, "fresh_entry")
    def bucket_ann(summary: pd.DataFrame, bucket: str) -> float:
        row = summary[summary["bucket"].eq(bucket)]
        return float(row["ann_return_mean_based"].iloc[0]) if not row.empty else np.nan

    large_theory = bucket_ann(theory_summary, "p50_100")
    large_tradable = bucket_ann(tradable_summary, "p50_100")
    small_0_30_theory = safe_annualized_return(
        pd.concat(
            [
                combine_buckets(bucket_theory, ["p00_05", "p05_10", "p10_20", "p20_30"], "small_0_30"),
            ],
            axis=1,
        )["small_0_30"]
    )
    small_10_30_theory = safe_annualized_return(combine_buckets(bucket_theory, ["p10_20", "p20_30"], "small_10_30"))
    small_20_50_theory = safe_annualized_return(combine_buckets(bucket_theory, ["p20_30", "p30_50"], "small_20_50"))
    small_10_30_tradable = safe_annualized_return(combine_buckets(bucket_tradable, ["p10_20", "p20_30"], "small_10_30"))
    small_20_50_tradable = safe_annualized_return(combine_buckets(bucket_tradable, ["p20_30", "p30_50"], "small_20_50"))

    size_ic = factor_summary[factor_summary["factor"].eq("size_score")]
    size_ic_mean = float(size_ic["rank_ic_mean"].iloc[0]) if not size_ic.empty else np.nan
    size_conditions = [
        np.isfinite(small_0_30_theory) and np.isfinite(large_theory) and small_0_30_theory > large_theory,
        np.isfinite(size_ic_mean) and size_ic_mean > 0,
    ]
    if all(size_conditions):
        size_status = "Green"
    elif any(size_conditions):
        size_status = "Yellow"
    else:
        size_status = "Red"

    tail_conditions = [
        np.isfinite(small_10_30_theory) and np.isfinite(large_theory) and small_10_30_theory > large_theory,
        np.isfinite(small_20_50_theory) and np.isfinite(large_theory) and small_20_50_theory > large_theory,
    ]
    if all(tail_conditions):
        tail_status = "Green"
    elif any(tail_conditions):
        tail_status = "Yellow"
    else:
        tail_status = "Red"

    theoretical_spread = small_10_30_theory - large_theory
    tradable_spread = small_10_30_tradable - large_tradable
    if np.isfinite(tradable_spread) and tradable_spread > 0 and (
        not np.isfinite(theoretical_spread) or theoretical_spread <= 0 or tradable_spread / theoretical_spread >= 0.5
    ):
        tradability_status = "Green"
    elif np.isfinite(tradable_spread) and tradable_spread > 0:
        tradability_status = "Yellow"
    else:
        tradability_status = "Red"

    positive_regimes = int((regimes["spread_10_30_minus_large"] > 0).sum()) if not regimes.empty else 0
    hot_only = False
    if not regimes.empty:
        positive_names = set(regimes.loc[regimes["spread_10_30_minus_large"] > 0, "regime"].tolist())
        hot_only = positive_names and positive_names.issubset({"2014-2015", "2019-2021"})
    if positive_regimes >= 3 and not hot_only:
        regime_status = "Green"
    elif positive_regimes >= 2:
        regime_status = "Yellow"
    else:
        regime_status = "Red"

    if smoke_returns.empty or smoke_selections.empty:
        smoke_status = "Red"
    elif smoke_selections["selected"].median() >= 80:
        smoke_status = "Green"
    else:
        smoke_status = "Yellow"

    metrics.update(
        {
            "large_theory_ann": large_theory,
            "small_0_30_theory_ann": small_0_30_theory,
            "small_10_30_theory_ann": small_10_30_theory,
            "small_20_50_theory_ann": small_20_50_theory,
            "large_tradable_ann": large_tradable,
            "small_10_30_tradable_ann": small_10_30_tradable,
            "small_20_50_tradable_ann": small_20_50_tradable,
            "theoretical_spread_10_30_minus_large": theoretical_spread,
            "tradable_spread_10_30_minus_large": tradable_spread,
            "size_rank_ic_mean": size_ic_mean,
            "positive_regimes": positive_regimes,
            "smoke_median_selected": float(smoke_selections["selected"].median()) if not smoke_selections.empty else np.nan,
            "smoke_ann_return": safe_annualized_return(smoke_returns) if not smoke_returns.empty else np.nan,
        }
    )
    gates = pd.DataFrame(
        [
            {"gate": "Data Gate", "status": data_status, "detail": "Data ports, returns, exec-status joins, and fixed sample."},
            {"gate": "Size Monotonicity Gate", "status": size_status, "detail": "Small-cap bucket direction and size rank IC."},
            {"gate": "Bottom Tail Robustness Gate", "status": tail_status, "detail": "Edge after excluding bottom 5% tail."},
            {"gate": "Fresh-entry Failed-buy Penalty Gate", "status": tradability_status, "detail": "Daily fresh-entry basket; failed T+1 buys are cash."},
            {"gate": "Regime Stability Gate", "status": regime_status, "detail": "Spread stability across major market regimes."},
            {"gate": "Smoke Baseline Gate", "status": smoke_status, "detail": "Minimal monthly top-100 diagnostic loop coverage."},
        ]
    )
    return gates, metrics


def make_figures(
    paths: Paths,
    universe_diag: pd.DataFrame,
    bucket_theory: pd.DataFrame,
    bucket_tradable: pd.DataFrame,
    factor_ics: dict[str, pd.Series],
    regimes: pd.DataFrame,
    smoke_returns: pd.Series,
) -> dict[str, str]:
    figures: dict[str, str] = {}
    monthly_diag = universe_diag.copy()
    monthly_diag["month"] = monthly_diag.index.astype(str).str.slice(0, 7)
    monthly_counts = monthly_diag.groupby("month")[["base_universe", "exec_tradable_buy"]].mean()
    path = paths.figures_root / "universe_counts.png"
    draw_multi_line_chart(monthly_counts, path, "Universe Counts", "Monthly average stock count")
    figures["universe_counts"] = str(path.relative_to(paths.output_root))

    nav_theory = (1.0 + bucket_theory.fillna(0.0)).cumprod()
    path = paths.figures_root / "size_bucket_nav_theoretical.png"
    draw_multi_line_chart(nav_theory, path, "Size Bucket NAV - Theoretical", "Equal-weight daily close-to-close NAV")
    figures["size_bucket_nav_theoretical"] = str(path.relative_to(paths.output_root))

    nav_tradable = (1.0 + bucket_tradable.fillna(0.0)).cumprod()
    path = paths.figures_root / "size_bucket_nav_tradable.png"
    draw_multi_line_chart(nav_tradable, path, "Size Bucket NAV - Fresh-entry Failed Buys as Cash", "T+1 open-to-close if bought; failed buys return 0")
    figures["size_bucket_nav_fresh_entry"] = str(path.relative_to(paths.output_root))

    tail = pd.concat(
        [
            combine_buckets(bucket_theory, ["p00_05"], "bottom_0_5"),
            combine_buckets(bucket_theory, ["p05_10", "p10_20", "p20_30"], "bottom_5_30"),
            combine_buckets(bucket_theory, ["p20_30", "p30_50"], "bottom_20_50"),
            combine_buckets(bucket_theory, ["p50_100"], "large_50_100"),
        ],
        axis=1,
    )
    path = paths.figures_root / "bottom_tail_robustness.png"
    draw_multi_line_chart((1.0 + tail.fillna(0.0)).cumprod(), path, "Bottom Tail Robustness", "NAV by tail-exclusion bucket")
    figures["bottom_tail_robustness"] = str(path.relative_to(paths.output_root))

    annual_ics = []
    for factor, ic in factor_ics.items():
        table = annual_ic_table(ic)
        table["factor"] = factor
        annual_ics.append(table)
    if annual_ics:
        all_annual_ics = pd.concat(annual_ics, ignore_index=True)
        size_ic = all_annual_ics[all_annual_ics["factor"].eq("size_score")]
        path = paths.figures_root / "size_rank_ic_by_year.png"
        draw_bar_chart(size_ic["year"].tolist(), size_ic["rank_ic_mean"].tolist(), path, "Size Rank IC by Year", "Annual mean daily rank IC")
        figures["size_rank_ic_by_year"] = str(path.relative_to(paths.output_root))

    if not regimes.empty:
        path = paths.figures_root / "regime_spread_10_30_minus_large.png"
        draw_bar_chart(
            regimes["regime"].tolist(),
            regimes["spread_10_30_minus_large"].tolist(),
            path,
            "Regime Spread: Small 10-30% minus Large 50-100%",
            "Annualized mean daily spread",
        )
        figures["regime_spread"] = str(path.relative_to(paths.output_root))

    if not smoke_returns.empty:
        smoke_nav = (1.0 + smoke_returns.fillna(0.0)).cumprod().to_frame("smoke_top100_ex_bottom5")
        path = paths.figures_root / "smoke_baseline_nav.png"
        draw_multi_line_chart(smoke_nav, path, "Smoke Baseline NAV", "Monthly selected top100 ex bottom5 diagnostic")
        figures["smoke_baseline_nav"] = str(path.relative_to(paths.output_root))
    return figures


def pct(value: float | int | np.floating | None) -> str:
    if value is None or pd.isna(value) or not np.isfinite(float(value)):
        return "n/a"
    return f"{float(value):.2%}"


def num(value: float | int | np.floating | None) -> str:
    if value is None or pd.isna(value) or not np.isfinite(float(value)):
        return "n/a"
    return f"{float(value):,.4f}"


def markdown_table(frame: pd.DataFrame, max_rows: int | None = None) -> str:
    if frame.empty:
        return "_No rows._"
    view = frame.copy()
    if max_rows is not None:
        view = view.head(max_rows)
    formatted = view.copy()
    for col in formatted.columns:
        if pd.api.types.is_float_dtype(formatted[col]):
            formatted[col] = formatted[col].map(lambda value: "" if pd.isna(value) else f"{value:.6g}")
        else:
            formatted[col] = formatted[col].map(lambda value: "" if pd.isna(value) else str(value))
    columns = [str(col) for col in formatted.columns]
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    for _, row in formatted.iterrows():
        values = [str(row[col]).replace("|", "\\|") for col in formatted.columns]
        lines.append("| " + " | ".join(values) + " |")
    if max_rows is not None and len(frame) > max_rows:
        lines.append("")
        lines.append(f"_Showing first {max_rows} of {len(frame)} rows._")
    return "\n".join(lines)


def render_report(
    paths: Paths,
    returns_info: dict[str, Any],
    panel_stats: dict[str, Any],
    universe_diag: pd.DataFrame,
    factor_summary: pd.DataFrame,
    return_summary: pd.DataFrame,
    regimes: pd.DataFrame,
    smoke_selections: pd.DataFrame,
    gates: pd.DataFrame,
    gate_metrics: dict[str, Any],
    figures: dict[str, str],
) -> str:
    lines: list[str] = [
        "# A-share Small-cap Pre Research v1 - Fresh-entry Diagnostic",
        "",
        "This report is a pre-research diagnostic. It is not a formal strategy conclusion.",
        "",
        "## Fixed Sample",
        "",
        f"- Research sample: `{RESEARCH_START}` to `{RESEARCH_END}`",
        f"- Warmup starts: `{WARMUP_START}`",
        "- 2026 data is excluded from formal conclusions.",
        "",
        "## Data Ports",
        "",
        f"- Adjusted return port rebuilt: `{returns_info.get('rebuilt')}`",
        f"- Adjusted return files: `{returns_info.get('files')}`",
        f"- Panel rows: `{panel_stats['rows']:,}`",
        f"- Base universe rows: `{panel_stats['base_universe_rows']:,}`",
        f"- Return-available base rows: `{panel_stats['return_available_rows']:,}`",
        f"- Exec-status missing rows: `{panel_stats['exec_status_missing_rows']:,}`",
        f"- Exec-tradable buy rows: `{panel_stats['exec_tradable_buy_rows']:,}`",
        "",
        "## Gate Summary",
        "",
    ]
    for _, row in gates.iterrows():
        lines.append(f"- **{row['gate']}**: `{row['status']}` - {row['detail']}")
    lines.extend(
        [
            "",
            "## Key Metrics",
            "",
            f"- Size rank IC mean: `{num(gate_metrics.get('size_rank_ic_mean'))}`",
            f"- Small 0-30% theoretical annualized return: `{pct(gate_metrics.get('small_0_30_theory_ann'))}`",
            f"- Small 10-30% theoretical annualized return: `{pct(gate_metrics.get('small_10_30_theory_ann'))}`",
            f"- Small 20-50% theoretical annualized return: `{pct(gate_metrics.get('small_20_50_theory_ann'))}`",
            f"- Large 50-100% theoretical annualized return: `{pct(gate_metrics.get('large_theory_ann'))}`",
            f"- Small 10-30% fresh-entry annualized return: `{pct(gate_metrics.get('small_10_30_tradable_ann'))}`",
            f"- Large 50-100% fresh-entry annualized return: `{pct(gate_metrics.get('large_tradable_ann'))}`",
            f"- Regimes with positive 10-30 minus large spread: `{gate_metrics.get('positive_regimes')}` / `{len(REGIMES)}`",
            f"- Smoke median selected names: `{num(gate_metrics.get('smoke_median_selected'))}`",
            f"- Smoke annualized diagnostic return: `{pct(gate_metrics.get('smoke_ann_return'))}`",
            "",
            "## Figures",
            "",
        ]
    )
    for key, rel in figures.items():
        lines.append(f"![{key}](figures/{Path(rel).name})")
        lines.append("")

    lines.extend(
        [
            "## Factor IC Summary",
            "",
            markdown_table(factor_summary),
            "",
            "## Size Bucket Return Summary",
            "",
            markdown_table(return_summary),
            "",
            "## Regime Table",
            "",
            markdown_table(regimes),
            "",
            "## Universe Diagnostics",
            "",
            f"- Median daily base universe count: `{universe_diag['base_universe'].median():,.0f}`",
            f"- Median T+1 buy-tradable count: `{universe_diag['exec_tradable_buy'].median():,.0f}`",
            f"- Median T+1 buy-tradable coverage: `{pct(universe_diag['tradable_buy_coverage'].median())}`",
            f"- Median exec-status missing rate: `{pct(universe_diag['exec_status_missing_rate'].median())}`",
            "",
            "## Notes",
            "",
            "- `security_master_latest_snapshot` is not used for historical filtering.",
            "- `market_trading_status.trade_date` is joined from signal `exec_date`, not signal `feature_date`.",
            "- `quality` factors are intentionally not mixed into the first size gate. The annual PIT port is ready, but quality should be introduced after the size/valuation sanity pass is interpreted.",
            "- The fresh-entry bucket test keeps the same intended basket, uses T+1 open-to-close return for successful buys, and assigns 0 return to failed T+1 buys.",
            "- The smoke baseline is a diagnostic loop, not a deployable backtest.",
        ]
    )
    return "\n".join(lines) + "\n"


def render_report_zh(
    paths: Paths,
    returns_info: dict[str, Any],
    panel_stats: dict[str, Any],
    universe_diag: pd.DataFrame,
    factor_summary: pd.DataFrame,
    return_summary: pd.DataFrame,
    regimes: pd.DataFrame,
    gates: pd.DataFrame,
    gate_metrics: dict[str, Any],
    figures: dict[str, str],
) -> str:
    zh_gates = {
        "Data Gate": "数据门槛",
        "Size Monotonicity Gate": "小盘单调性门槛",
        "Bottom Tail Robustness Gate": "尾部剔除稳健性门槛",
        "Fresh-entry Failed-buy Penalty Gate": "新买入失败惩罚门槛",
        "Regime Stability Gate": "阶段稳定性门槛",
        "Smoke Baseline Gate": "最小闭环 smoke 门槛",
    }
    zh_detail = {
        "Data Gate": "数据端口、复权收益、执行日状态连接和固定样本。",
        "Size Monotonicity Gate": "小市值方向和 size rank IC。",
        "Bottom Tail Robustness Gate": "剔除 bottom 0%-5% 后 edge 是否还存在。",
        "Fresh-entry Failed-buy Penalty Gate": "每天新买入 bucket，T+1 买不到则当现金。",
        "Regime Stability Gate": "主要市场阶段里的 small-minus-large spread。",
        "Smoke Baseline Gate": "月度 top100 最小闭环是否能跑通。",
    }
    lines: list[str] = [
        "# A股小盘 Pre Research v1：新买入诊断",
        "",
        "这份报告是 pre research 诊断，不是正式策略收益结论。",
        "",
        "## 固定样本",
        "",
        f"- 正式样本：`{RESEARCH_START}` 到 `{RESEARCH_END}`",
        f"- warmup 起点：`{WARMUP_START}`",
        "- 2026 数据不进入正式结论。",
        "",
        "## 数据端口",
        "",
        f"- 复权收益端口本次是否重建：`{returns_info.get('rebuilt')}`",
        f"- 复权收益文件数：`{returns_info.get('files')}`",
        f"- 复权源文件数：`{returns_info.get('source_file_count', 'n/a')}`",
        f"- panel 行数：`{panel_stats['rows']:,}`",
        f"- base universe 行数：`{panel_stats['base_universe_rows']:,}`",
        f"- 有收益的 base 行数：`{panel_stats['return_available_rows']:,}`",
        f"- 执行日 status 缺失行数：`{panel_stats['exec_status_missing_rows']:,}`",
        f"- 执行日可买行数：`{panel_stats['exec_tradable_buy_rows']:,}`",
        "",
        "## Gate 摘要",
        "",
    ]
    for _, row in gates.iterrows():
        gate = str(row["gate"])
        lines.append(f"- **{zh_gates.get(gate, gate)}**：`{row['status']}` - {zh_detail.get(gate, row['detail'])}")
    lines.extend(
        [
            "",
            "## 关键指标",
            "",
            f"- Size rank IC 均值：`{num(gate_metrics.get('size_rank_ic_mean'))}`",
            f"- 小盘 0%-30% 理论年化：`{pct(gate_metrics.get('small_0_30_theory_ann'))}`",
            f"- 小盘 10%-30% 理论年化：`{pct(gate_metrics.get('small_10_30_theory_ann'))}`",
            f"- 小盘 20%-50% 理论年化：`{pct(gate_metrics.get('small_20_50_theory_ann'))}`",
            f"- 大盘 50%-100% 理论年化：`{pct(gate_metrics.get('large_theory_ann'))}`",
            f"- 小盘 10%-30% 新买入诊断年化：`{pct(gate_metrics.get('small_10_30_tradable_ann'))}`",
            f"- 大盘 50%-100% 新买入诊断年化：`{pct(gate_metrics.get('large_tradable_ann'))}`",
            f"- 10%-30% 小盘相对大盘的新买入 spread：`{pct(gate_metrics.get('tradable_spread_10_30_minus_large'))}`",
            f"- small 10%-30% minus large 为正的阶段数：`{gate_metrics.get('positive_regimes')}` / `{len(REGIMES)}`",
            f"- smoke 中位选股数：`{num(gate_metrics.get('smoke_median_selected'))}`",
            f"- smoke 诊断年化：`{pct(gate_metrics.get('smoke_ann_return'))}`",
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
            "## 单因子 IC 摘要",
            "",
            markdown_table(factor_summary),
            "",
            "## size 分桶收益摘要",
            "",
            markdown_table(return_summary),
            "",
            "## 阶段稳定性",
            "",
            markdown_table(regimes),
            "",
            "## Universe 诊断",
            "",
            f"- 每日 base universe 中位数：`{universe_diag['base_universe'].median():,.0f}`",
            f"- 每日 T+1 可买中位数：`{universe_diag['exec_tradable_buy'].median():,.0f}`",
            f"- T+1 可买覆盖率中位数：`{pct(universe_diag['tradable_buy_coverage'].median())}`",
            f"- 执行日 status 缺失率中位数：`{pct(universe_diag['exec_status_missing_rate'].median())}`",
            "",
            "## 解释边界",
            "",
            "- 这个 v1 不是“真实组合回测”，而是 fresh-entry 诊断。",
            "- fresh-entry 诊断的含义是：每天都想新买入这个 bucket，T+1 买不到的股票当现金。",
            "- 成功买入时使用 `exec_oc_ret_1d`，即 T+1 open-to-close；理论分桶仍使用 T close-to-T+1 close。",
            "- `security_master_latest_snapshot` 不参与历史过滤。",
            "- `market_trading_status.trade_date` 由信号侧 `exec_date` 去匹配，不用 `feature_date` 偷看执行状态。",
            "- smoke baseline 只说明闭环能跑，不是可部署回测。",
        ]
    )
    return "\n".join(lines) + "\n"


def save_outputs(
    paths: Paths,
    universe_diag: pd.DataFrame,
    factor_summary: pd.DataFrame,
    factor_ics: dict[str, pd.Series],
    bucket_theory: pd.DataFrame,
    bucket_tradable: pd.DataFrame,
    return_summary: pd.DataFrame,
    regimes: pd.DataFrame,
    smoke_returns: pd.Series,
    smoke_selections: pd.DataFrame,
    gates: pd.DataFrame,
    gate_metrics: dict[str, Any],
) -> None:
    paths.tables_root.mkdir(parents=True, exist_ok=True)
    universe_diag.to_csv(paths.tables_root / "universe_diagnostics_daily.csv", encoding="utf-8")
    factor_summary.to_csv(paths.tables_root / "factor_ic_summary.csv", index=False, encoding="utf-8")
    for factor, ic in factor_ics.items():
        ic.rename("rank_ic").to_csv(paths.tables_root / f"{factor}_rank_ic_daily.csv", encoding="utf-8")
    bucket_theory.to_csv(paths.tables_root / "size_bucket_returns_theoretical_daily.csv", encoding="utf-8")
    bucket_tradable.to_csv(paths.tables_root / "size_bucket_returns_tradable_daily.csv", encoding="utf-8")
    return_summary.to_csv(paths.tables_root / "size_bucket_return_summary.csv", index=False, encoding="utf-8")
    regimes.to_csv(paths.tables_root / "regime_spread_summary.csv", index=False, encoding="utf-8")
    smoke_returns.rename("smoke_return").to_csv(paths.tables_root / "smoke_baseline_returns_daily.csv", encoding="utf-8")
    smoke_selections.to_csv(paths.tables_root / "smoke_baseline_selections.csv", index=False, encoding="utf-8")
    gates.to_csv(paths.tables_root / "gate_summary.csv", index=False, encoding="utf-8")
    (paths.tables_root / "gate_metrics.json").write_text(json.dumps(gate_metrics, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run A-share small-cap pre research v1 diagnostics.")
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--processed-root", default="processed")
    parser.add_argument("--output-root", default="outputs/pre_research_v1_fresh_entry_diagnostic")
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
    log(f"market_end={market_end}")
    returns_info = build_adjusted_returns(paths, market_end=market_end, force=args.force_returns)
    log(f"adjusted returns info: {returns_info}")

    panel, panel_stats = load_pre_research_panel(paths)
    log(f"panel stats: {panel_stats}")
    universe_diag = compute_universe_diagnostics(panel)
    factor_summary, factor_ics = factor_ic_summary(panel)
    bucket_theory = bucket_return_table(panel, tradable=False)
    bucket_tradable = bucket_return_table(panel, tradable=True)
    return_summary = pd.concat(
        [return_summary_table(bucket_theory, "theoretical"), return_summary_table(bucket_tradable, "tradable")],
        ignore_index=True,
    )
    regimes = regime_table(bucket_theory)
    smoke_returns, smoke_selections = monthly_smoke_baseline(panel)
    gates, gate_metrics = determine_gates(
        panel_stats,
        bucket_theory,
        bucket_tradable,
        factor_summary,
        regimes,
        smoke_returns,
        smoke_selections,
    )
    figures = make_figures(paths, universe_diag, bucket_theory, bucket_tradable, factor_ics, regimes, smoke_returns)
    save_outputs(
        paths,
        universe_diag,
        factor_summary,
        factor_ics,
        bucket_theory,
        bucket_tradable,
        return_summary,
        regimes,
        smoke_returns,
        smoke_selections,
        gates,
        gate_metrics,
    )
    report = render_report(
        paths,
        returns_info,
        panel_stats,
        universe_diag,
        factor_summary,
        return_summary,
        regimes,
        smoke_selections,
        gates,
        gate_metrics,
        figures,
    )
    report_path = paths.output_root / "pre_research_report.md"
    report_path.write_text(report, encoding="utf-8")
    report_zh = render_report_zh(
        paths,
        returns_info,
        panel_stats,
        universe_diag,
        factor_summary,
        return_summary,
        regimes,
        gates,
        gate_metrics,
        figures,
    )
    report_zh_path = paths.output_root / "pre_research_report_zh.md"
    report_zh_path.write_text(report_zh, encoding="utf-8")
    log(f"wrote {report_path}")
    log(f"wrote {report_zh_path}")


if __name__ == "__main__":
    main()
