from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
BASELINE_SCRIPT = ROOT / "02_spot_universe_baseline.py"
OUTPUT_DIR = ROOT / "outputs_walk_forward"
REPORT_PATH = ROOT / "08_walk_forward_time_slice_report.md"

BTC_ONLY = "BTC_ONLY"
CORE4 = "CORE4_BTC_ETH_SOL_BNB"
POOL12 = "POOL12_DROP_LTC_AAVE"

POOL_LABELS = {
    BTC_ONLY: "BTC only",
    CORE4: "BTC/ETH/SOL/BNB",
    POOL12: "12 coin pool",
}

COLORS = {
    BTC_ONLY: "#255C99",
    CORE4: "#2E7D32",
    POOL12: "#D95F02",
}

FIXED_PERIODS = {
    "FULL": ("2020-01-01", None, "2020-2026"),
    "2020": ("2020-01-01", "2020-12-31", "2020"),
    "2021": ("2021-01-01", "2021-12-31", "2021"),
    "2022_2023": ("2022-01-01", "2023-12-31", "2022-2023"),
    "2024_2026": ("2024-01-01", None, "2024-2026"),
    "POST_2021": ("2022-01-01", None, "2022-2026"),
}

EXPECTED_12 = {
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "BNBUSDT",
    "TRXUSDT",
    "ADAUSDT",
    "LINKUSDT",
    "AVAXUSDT",
    "NEARUSDT",
    "UNIUSDT",
}

EXPECTED_12_ORDER = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "BNBUSDT",
    "TRXUSDT",
    "ADAUSDT",
    "LINKUSDT",
    "AVAXUSDT",
    "NEARUSDT",
    "UNIUSDT",
]

POLICY_LABELS = {
    "cash_slots": "Cash slots",
    "common_sample": "Common sample",
    "dynamic_eligible": "Dynamic eligible",
}


def load_baseline_module():
    spec = importlib.util.spec_from_file_location("spot_walk_forward_baseline", BASELINE_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load baseline script: {BASELINE_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def get_font(size: int, bold: bool = False):
    candidates = [
        "msyhbd.ttc" if bold else "msyh.ttc",
        "simhei.ttf",
        "arial.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, size: int, fill=(30, 35, 40), bold: bool = False) -> None:
    draw.text(xy, text, font=get_font(size, bold=bold), fill=fill)


def pct(x: float) -> str:
    return "NA" if pd.isna(x) else f"{x:.2%}"


def num(x: float) -> str:
    return "NA" if pd.isna(x) else f"{x:.2f}"


def md_img(path: Path) -> str:
    return path.resolve().as_posix()


def build_pools(selected_symbols: list[str]) -> dict[str, list[str]]:
    selected = set(selected_symbols)
    missing = EXPECTED_12 - selected
    unexpected = selected - EXPECTED_12 - {"LTCUSDT", "AAVEUSDT"}
    if missing or unexpected:
        raise ValueError(
            f"Selected universe drifted. missing={sorted(missing)}, unexpected={sorted(unexpected)}"
        )
    return {
        BTC_ONLY: ["BTCUSDT"],
        CORE4: ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"],
        POOL12: EXPECTED_12_ORDER.copy(),
    }


def portfolio_return(backtests: dict[str, pd.DataFrame], symbols: list[str], policy: str = "cash_slots") -> pd.Series:
    panel = pd.concat([backtests[s]["GrossReturn"].rename(s) for s in symbols], axis=1)
    availability = pd.concat([backtests[s]["Close"].notna().rename(s) for s in symbols], axis=1)
    panel = panel.where(availability)

    if policy == "cash_slots":
        # Fixed slot model: unavailable or unlisted sleeves sit in cash and earn 0.
        return panel.fillna(0.0).mean(axis=1)

    if policy == "common_sample":
        # Strict common sample: only days with data for every symbol are compared.
        return panel.dropna().mean(axis=1)

    if policy == "dynamic_eligible":
        # Dynamic eligible model: equal-weight only among symbols with data that day.
        alive = panel.notna().sum(axis=1)
        return (panel.sum(axis=1, min_count=1) / alive.replace(0, np.nan)).dropna()

    raise ValueError(policy)


def slice_series(series: pd.Series, start: str | pd.Timestamp | None, end: str | pd.Timestamp | None) -> pd.Series:
    out = series.copy()
    if start is not None:
        out = out.loc[pd.Timestamp(start) :]
    if end is not None:
        out = out.loc[: pd.Timestamp(end)]
    return out


def compute_fixed_periods(baseline, pool_returns: dict[str, pd.Series], policy: str) -> pd.DataFrame:
    rows = []
    for period, (start, end, label) in FIXED_PERIODS.items():
        for pool, ret in pool_returns.items():
            seg = slice_series(ret, start, end)
            if len(seg) < 60:
                continue
            row = dict(
                policy=policy,
                policy_label=POLICY_LABELS[policy],
                pool=pool,
                label=POOL_LABELS[pool],
                period=period,
                period_label=label,
                start=str(seg.index[0].date()),
                end=str(seg.index[-1].date()),
                days=len(seg),
            )
            row.update(baseline.metrics(seg))
            rows.append(row)
    return pd.DataFrame(rows)


def compute_rolling_windows(baseline, pool_returns: dict[str, pd.Series], policy: str, years: int = 2) -> pd.DataFrame:
    index = next(iter(pool_returns.values())).index
    first = index[0]
    last_start = index[-1] - pd.DateOffset(years=years) + pd.Timedelta(days=1)
    starts = pd.date_range(first, last_start, freq="MS")
    if starts.empty or starts[0] != first:
        starts = pd.DatetimeIndex([first]).append(starts)

    rows = []
    min_days = int(365 * years * 0.90)
    for start in starts:
        end = start + pd.DateOffset(years=years) - pd.Timedelta(days=1)
        for pool, ret in pool_returns.items():
            seg = ret.loc[start:end]
            if len(seg) < min_days:
                continue
            row = dict(
                policy=policy,
                policy_label=POLICY_LABELS[policy],
                pool=pool,
                label=POOL_LABELS[pool],
                window_years=years,
                window_start=start.date().isoformat(),
                window_end=end.date().isoformat(),
                days=len(seg),
                min_days=min_days,
            )
            row.update(baseline.metrics(seg))
            rows.append(row)
    return pd.DataFrame(rows)


def compute_start_sensitivity(baseline, pool_returns: dict[str, pd.Series], policy: str) -> pd.DataFrame:
    index = next(iter(pool_returns.values())).index
    last_allowed_start = index[-1] - pd.DateOffset(years=2) + pd.Timedelta(days=1)
    starts = pd.date_range(index[0], last_allowed_start, freq="QS")
    if starts.empty or starts[0] != index[0]:
        starts = pd.DatetimeIndex([index[0]]).append(starts)

    rows = []
    for start in starts:
        for pool, ret in pool_returns.items():
            seg = ret.loc[start:]
            if len(seg) < 365:
                continue
            row = dict(
                policy=policy,
                policy_label=POLICY_LABELS[policy],
                pool=pool,
                label=POOL_LABELS[pool],
                start_date=start.date().isoformat(),
                end_date=seg.index[-1].date().isoformat(),
                days=len(seg),
            )
            row.update(baseline.metrics(seg))
            rows.append(row)
    return pd.DataFrame(rows)


def compare_to_benchmarks(df: pd.DataFrame, key_col: str) -> pd.DataFrame:
    rows = []
    for policy, policy_df in df.groupby("policy"):
        for challenger, benchmark in [(POOL12, BTC_ONLY), (POOL12, CORE4), (CORE4, BTC_ONLY)]:
            pivots = {metric: policy_df.pivot(index=key_col, columns="pool", values=metric) for metric in ["cagr", "sharpe", "mdd", "calmar"]}
            common = pivots["cagr"][[challenger, benchmark]].dropna().index
            cagr = pivots["cagr"].loc[common]
            sharpe = pivots["sharpe"].loc[common]
            mdd = pivots["mdd"].loc[common]
            calmar = pivots["calmar"].loc[common]
            rows.append(
                dict(
                    policy=policy,
                    policy_label=POLICY_LABELS[policy],
                    challenger=challenger,
                    challenger_label=POOL_LABELS[challenger],
                    benchmark=benchmark,
                    benchmark_label=POOL_LABELS[benchmark],
                    samples=len(common),
                    cagr_win_rate=float((cagr[challenger] > cagr[benchmark]).mean()) if len(common) else np.nan,
                    sharpe_win_rate=float((sharpe[challenger] > sharpe[benchmark]).mean()) if len(common) else np.nan,
                    mdd_win_rate=float((mdd[challenger] > mdd[benchmark]).mean()) if len(common) else np.nan,
                    calmar_win_rate=float((calmar[challenger] > calmar[benchmark]).mean()) if len(common) else np.nan,
                    avg_cagr_diff=float((cagr[challenger] - cagr[benchmark]).mean()) if len(common) else np.nan,
                    avg_sharpe_diff=float((sharpe[challenger] - sharpe[benchmark]).mean()) if len(common) else np.nan,
                    avg_mdd_diff=float((mdd[challenger] - mdd[benchmark]).mean()) if len(common) else np.nan,
                    avg_calmar_diff=float((calmar[challenger] - calmar[benchmark]).mean()) if len(common) else np.nan,
                )
            )
    return pd.DataFrame(rows)


def draw_fixed_periods(fixed_df: pd.DataFrame, out_path: Path) -> None:
    width, height = 1750, 1050
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (70, 28), "固定时间切片：CAGR 与 Calmar", 30, bold=True)
    draw_text(draw, (70, 64), "验证 12 币池是否只依赖单一阶段；每个阶段独立计算指标。", 18, fill=(90, 95, 105))

    period_order = ["2020", "2021", "2022_2023", "2024_2026", "POST_2021"]
    pool_order = [BTC_ONLY, CORE4, POOL12]
    panels = [("CAGR", "cagr", True, 135), ("Calmar", "calmar", False, 585)]
    x0, x1 = 100, width - 80
    panel_h = 330

    for title, col, is_pct, y0 in panels:
        y1 = y0 + panel_h
        draw_text(draw, (x0, y0 - 36), title, 24, bold=True)
        draw.rectangle((x0, y0, x1, y1), outline=(220, 224, 230))
        seg = fixed_df[fixed_df["period"].isin(period_order)]
        vals = seg[col].astype(float).tolist()
        max_abs = max(abs(min(vals + [0])), abs(max(vals + [0]))) * 1.18
        max_abs = max(max_abs, 1e-9)
        zero_y = y0 + int(panel_h * max_abs / (2 * max_abs))
        draw.line((x0, zero_y, x1, zero_y), fill=(145, 150, 160), width=2)
        group_w = (x1 - x0 - 95) / len(period_order)
        bar_w = 62
        for i, period in enumerate(period_order):
            gx = x0 + 55 + int(i * group_w)
            p_label = fixed_df[fixed_df["period"] == period]["period_label"].iloc[0]
            draw_text(draw, (gx + 45, y1 + 18), p_label, 16, fill=(55, 60, 70), bold=True)
            for j, pool in enumerate(pool_order):
                row = fixed_df[(fixed_df["period"] == period) & (fixed_df["pool"] == pool)].iloc[0]
                value = float(row[col])
                bar_h = int((panel_h - 75) / 2 * abs(value) / max_abs)
                x = gx + j * (bar_w + 12)
                if value >= 0:
                    y = zero_y - bar_h
                    rect = (x, y, x + bar_w, zero_y)
                    text_y = y - 25
                else:
                    y = zero_y + bar_h
                    rect = (x, zero_y, x + bar_w, y)
                    text_y = y + 5
                draw.rectangle(rect, fill=COLORS[pool])
                label = pct(value) if is_pct else f"{value:.1f}"
                draw_text(draw, (x - 4, text_y), label, 13, fill=(45, 50, 60), bold=True)

    for i, pool in enumerate(pool_order):
        lx = x0 + 65 + i * 410
        draw.rectangle((lx, height - 68, lx + 28, height - 51), fill=COLORS[pool])
        draw_text(draw, (lx + 38, height - 73), POOL_LABELS[pool], 18, fill=(50, 55, 65))
    img.save(out_path)


def draw_start_sensitivity(start_df: pd.DataFrame, out_path: Path) -> None:
    width, height = 1700, 1050
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (70, 28), "不同起点敏感性", 30, bold=True)
    draw_text(draw, (70, 64), "从不同季度开始，一直持有到样本结束；看结论是否依赖 2020-01-01 起点。", 18, fill=(90, 95, 105))

    pool_order = [BTC_ONLY, CORE4, POOL12]
    panels = [("CAGR", "cagr", True, 135), ("Calmar", "calmar", False, 585)]
    x0, x1 = 100, width - 80
    panel_h = 330

    for title, col, is_pct, y0 in panels:
        pivot = start_df.pivot(index="start_date", columns="pool", values=col)
        pivot.index = pd.to_datetime(pivot.index)
        pivot = pivot[pool_order]
        y1 = y0 + panel_h
        vals = pivot.values.flatten()
        ymin, ymax = float(np.nanmin(vals)), float(np.nanmax(vals))
        pad = max((ymax - ymin) * 0.08, 0.05)
        ymin -= pad
        ymax += pad
        draw_text(draw, (x0, y0 - 36), title, 24, bold=True)
        draw.rectangle((x0, y0, x1, y1), outline=(220, 224, 230))
        for i in range(5):
            y = y1 - int((y1 - y0) * i / 4)
            value = ymin + (ymax - ymin) * i / 4
            draw.line((x0, y, x1, y), fill=(238, 241, 245))
            label = pct(value) if is_pct else f"{value:.1f}"
            draw_text(draw, (35, y - 10), label, 14, fill=(95, 100, 110))
        for pool in pool_order:
            values = pivot[pool].astype(float).values
            pts = []
            for i, value in enumerate(values):
                x = x0 + int((x1 - x0) * i / (len(values) - 1))
                y = y1 - int((y1 - y0) * (float(value) - ymin) / (ymax - ymin))
                pts.append((x, y))
            draw.line(pts, fill=COLORS[pool], width=4)
        draw_text(draw, (x0, y1 + 18), str(pivot.index[0].date()), 15, fill=(95, 100, 110))
        draw_text(draw, (x1 - 95, y1 + 18), str(pivot.index[-1].date()), 15, fill=(95, 100, 110))

    for i, pool in enumerate(pool_order):
        lx = x0 + 65 + i * 410
        draw.rectangle((lx, height - 68, lx + 28, height - 51), fill=COLORS[pool])
        draw_text(draw, (lx + 38, height - 73), POOL_LABELS[pool], 18, fill=(50, 55, 65))
    img.save(out_path)


def draw_rolling_windows(rolling_df: pd.DataFrame, out_path: Path) -> None:
    width, height = 1700, 1050
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (70, 28), "2 年滚动窗口", 30, bold=True)
    draw_text(draw, (70, 64), "每月起点滚动 2 年；验证阶段稳定性。", 18, fill=(90, 95, 105))

    pool_order = [BTC_ONLY, CORE4, POOL12]
    panels = [("CAGR", "cagr", True, 135), ("Calmar", "calmar", False, 585)]
    x0, x1 = 100, width - 80
    panel_h = 330

    for title, col, is_pct, y0 in panels:
        pivot = rolling_df.pivot(index="window_start", columns="pool", values=col)
        pivot.index = pd.to_datetime(pivot.index)
        pivot = pivot[pool_order]
        y1 = y0 + panel_h
        vals = pivot.values.flatten()
        ymin, ymax = float(np.nanmin(vals)), float(np.nanmax(vals))
        pad = max((ymax - ymin) * 0.08, 0.05)
        ymin -= pad
        ymax += pad
        draw_text(draw, (x0, y0 - 36), title, 24, bold=True)
        draw.rectangle((x0, y0, x1, y1), outline=(220, 224, 230))
        for i in range(5):
            y = y1 - int((y1 - y0) * i / 4)
            value = ymin + (ymax - ymin) * i / 4
            draw.line((x0, y, x1, y), fill=(238, 241, 245))
            label = pct(value) if is_pct else f"{value:.1f}"
            draw_text(draw, (35, y - 10), label, 14, fill=(95, 100, 110))
        for pool in pool_order:
            values = pivot[pool].astype(float).values
            pts = []
            for i, value in enumerate(values):
                x = x0 + int((x1 - x0) * i / (len(values) - 1))
                y = y1 - int((y1 - y0) * (float(value) - ymin) / (ymax - ymin))
                pts.append((x, y))
            draw.line(pts, fill=COLORS[pool], width=4)
        draw_text(draw, (x0, y1 + 18), str(pivot.index[0].date()), 15, fill=(95, 100, 110))
        draw_text(draw, (x1 - 95, y1 + 18), str(pivot.index[-1].date()), 15, fill=(95, 100, 110))

    for i, pool in enumerate(pool_order):
        lx = x0 + 65 + i * 410
        draw.rectangle((lx, height - 68, lx + 28, height - 51), fill=COLORS[pool])
        draw_text(draw, (lx + 38, height - 73), POOL_LABELS[pool], 18, fill=(50, 55, 65))
    img.save(out_path)


def draw_winrate_summary(rolling_summary: pd.DataFrame, start_summary: pd.DataFrame, out_path: Path) -> None:
    width, height = 1650, 980
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (70, 28), "稳定性胜率摘要", 30, bold=True)
    draw_text(draw, (70, 64), "12 币池分别对比 BTC only 与 Core4；胜率为窗口内指标更优的比例。", 18, fill=(90, 95, 105))

    rows = []
    for source, df in [("Rolling 2Y", rolling_summary), ("Start date", start_summary)]:
        for benchmark in [BTC_ONLY, CORE4]:
            row = df[(df["challenger"] == POOL12) & (df["benchmark"] == benchmark)].iloc[0]
            rows.append((source, benchmark, row))

    metrics = [("CAGR", "cagr_win_rate"), ("Sharpe", "sharpe_win_rate"), ("MDD", "mdd_win_rate"), ("Calmar", "calmar_win_rate")]
    x0, y0, x1, y1 = 115, 140, width - 75, height - 150
    draw.rectangle((x0, y0, x1, y1), outline=(220, 224, 230))
    for i in range(6):
        y = y1 - int((y1 - y0) * i / 5)
        draw.line((x0, y, x1, y), fill=(238, 241, 245))
        draw_text(draw, (55, y - 10), pct(i / 5), 15, fill=(95, 100, 110))

    group_w = (x1 - x0 - 100) / len(rows)
    bar_w = 45
    for i, (source, benchmark, row) in enumerate(rows):
        gx = x0 + 55 + int(i * group_w)
        draw_text(draw, (gx - 8, y1 + 18), source, 15, fill=(55, 60, 70), bold=True)
        draw_text(draw, (gx - 8, y1 + 42), f"vs {POOL_LABELS[benchmark]}", 14, fill=(80, 85, 95))
        for j, (label, col) in enumerate(metrics):
            value = float(row[col])
            x = gx + j * (bar_w + 12)
            bar_h = int((y1 - y0) * value)
            draw.rectangle((x, y1 - bar_h, x + bar_w, y1), fill="#D95F02")
            draw_text(draw, (x - 4, y1 - bar_h - 24), pct(value), 12, fill=(45, 50, 60), bold=True)
            draw_text(draw, (x - 2, y1 + 68), label, 11, fill=(80, 85, 95))
    img.save(out_path)


def draw_policy_comparison(fixed_df: pd.DataFrame, out_path: Path) -> None:
    width, height = 1700, 980
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (70, 28), "三种组合口径：全样本对比", 30, bold=True)
    draw_text(draw, (70, 64), "Cash slots / Common sample / Dynamic eligible；用于检查未上市币现金槽位假设。", 18, fill=(90, 95, 105))

    df = fixed_df[fixed_df["period"] == "FULL"].copy()
    policy_order = ["cash_slots", "common_sample", "dynamic_eligible"]
    pool_order = [BTC_ONLY, CORE4, POOL12]
    panels = [("CAGR", "cagr", True, 135), ("Calmar", "calmar", False, 560)]
    x0, x1 = 105, width - 80
    panel_h = 300
    for title, col, is_pct, y0 in panels:
        y1 = y0 + panel_h
        draw_text(draw, (x0, y0 - 34), title, 23, bold=True)
        draw.rectangle((x0, y0, x1, y1), outline=(220, 224, 230))
        vals = df[col].astype(float).tolist()
        max_abs = max(abs(min(vals + [0])), abs(max(vals + [0]))) * 1.18
        max_abs = max(max_abs, 1e-9)
        zero_y = y0 + int(panel_h * max_abs / (2 * max_abs))
        draw.line((x0, zero_y, x1, zero_y), fill=(145, 150, 160), width=2)
        group_w = (x1 - x0 - 95) / len(policy_order)
        bar_w = 70
        for i, policy in enumerate(policy_order):
            gx = x0 + 65 + int(i * group_w)
            draw_text(draw, (gx + 45, y1 + 18), POLICY_LABELS[policy], 16, fill=(55, 60, 70), bold=True)
            for j, pool in enumerate(pool_order):
                row = df[(df["policy"] == policy) & (df["pool"] == pool)].iloc[0]
                value = float(row[col])
                bar_h = int((panel_h - 80) / 2 * abs(value) / max_abs)
                x = gx + j * (bar_w + 12)
                if value >= 0:
                    y = zero_y - bar_h
                    rect = (x, y, x + bar_w, zero_y)
                    text_y = y - 25
                else:
                    y = zero_y + bar_h
                    rect = (x, zero_y, x + bar_w, y)
                    text_y = y + 5
                draw.rectangle(rect, fill=COLORS[pool])
                label = pct(value) if is_pct else f"{value:.1f}"
                draw_text(draw, (x - 3, text_y), label, 13, fill=(45, 50, 60), bold=True)
    for i, pool in enumerate(pool_order):
        lx = x0 + 80 + i * 410
        draw.rectangle((lx, height - 68, lx + 28, height - 51), fill=COLORS[pool])
        draw_text(draw, (lx + 38, height - 73), POOL_LABELS[pool], 18, fill=(50, 55, 65))
    img.save(out_path)


def table_rows(df: pd.DataFrame, pool_order: list[str]) -> str:
    rows = []
    for row in df.itertuples():
        if row.pool not in pool_order:
            continue
        rows.append(
            f"| {row.period_label if hasattr(row, 'period_label') else row.label} | {POOL_LABELS[row.pool]} | {pct(row.cagr)} | {num(row.sharpe)} | {pct(row.mdd)} | {num(row.calmar)} | {num(row.final)}x |"
        )
    return "\n".join(rows)


def summary_rows(df: pd.DataFrame) -> str:
    rows = []
    for row in df.itertuples():
        rows.append(
            f"| {row.challenger_label} vs {row.benchmark_label} | {int(row.samples)} | {pct(row.cagr_win_rate)} | {pct(row.sharpe_win_rate)} | {pct(row.mdd_win_rate)} | {pct(row.calmar_win_rate)} | {pct(row.avg_cagr_diff)} | {num(row.avg_calmar_diff)} |"
        )
    return "\n".join(rows)


def policy_full_rows(fixed_df: pd.DataFrame) -> str:
    rows = []
    df = fixed_df[fixed_df["period"] == "FULL"].copy()
    for policy in ["cash_slots", "common_sample", "dynamic_eligible"]:
        for pool in [BTC_ONLY, CORE4, POOL12]:
            row = df[(df["policy"] == policy) & (df["pool"] == pool)].iloc[0]
            rows.append(
                f"| {POLICY_LABELS[policy]} | {POOL_LABELS[pool]} | {str(row.start)} | {str(row.end)} | {int(row.days)} | {pct(row.cagr)} | {num(row.sharpe)} | {pct(row.mdd)} | {num(row.calmar)} | {num(row.final)}x |"
            )
    return "\n".join(rows)


def policy_rolling_rows(rolling_summary: pd.DataFrame) -> str:
    rows = []
    for policy in ["cash_slots", "common_sample", "dynamic_eligible"]:
        for benchmark in [BTC_ONLY, CORE4]:
            row = rolling_summary[
                (rolling_summary["policy"] == policy)
                & (rolling_summary["challenger"] == POOL12)
                & (rolling_summary["benchmark"] == benchmark)
            ].iloc[0]
            rows.append(
                f"| {POLICY_LABELS[policy]} | 12 coin pool vs {POOL_LABELS[benchmark]} | {int(row.samples)} | {pct(row.cagr_win_rate)} | {pct(row.sharpe_win_rate)} | {pct(row.mdd_win_rate)} | {pct(row.calmar_win_rate)} | {pct(row.avg_cagr_diff)} | {num(row.avg_calmar_diff)} |"
            )
    return "\n".join(rows)


def make_report(context: dict, fixed_df: pd.DataFrame, rolling_summary: pd.DataFrame, start_summary: pd.DataFrame) -> str:
    cash_fixed = fixed_df[fixed_df["policy"] == "cash_slots"].copy()
    cash_rolling_summary = rolling_summary[rolling_summary["policy"] == "cash_slots"].copy()
    cash_start_summary = start_summary[start_summary["policy"] == "cash_slots"].copy()

    fixed_select = cash_fixed[cash_fixed["period"].isin(["FULL", "2021", "POST_2021"])].copy()
    fixed_select["period_sort"] = fixed_select["period"].map({"FULL": 0, "2021": 1, "POST_2021": 2})
    fixed_select = fixed_select.sort_values(["period_sort", "pool"])
    full = cash_fixed[cash_fixed["period"] == "FULL"].set_index("pool")
    post = cash_fixed[cash_fixed["period"] == "POST_2021"].set_index("pool")
    roll_12_btc = cash_rolling_summary[(cash_rolling_summary["challenger"] == POOL12) & (cash_rolling_summary["benchmark"] == BTC_ONLY)].iloc[0]
    roll_12_core = cash_rolling_summary[(cash_rolling_summary["challenger"] == POOL12) & (cash_rolling_summary["benchmark"] == CORE4)].iloc[0]
    start_12_btc = cash_start_summary[(cash_start_summary["challenger"] == POOL12) & (cash_start_summary["benchmark"] == BTC_ONLY)].iloc[0]
    start_12_core = cash_start_summary[(cash_start_summary["challenger"] == POOL12) & (cash_start_summary["benchmark"] == CORE4)].iloc[0]

    return f"""# 右侧现货动量：Walk-forward / 时间切片验证

生成时间：{pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")}

## 1. 验证目的

本轮不改策略、不改参数、不改币池。

这里的 walk-forward 不是训练参数后的样本外检验，因为当前 baseline 没有拟合参数；它是时间稳定性检验：

- 固定时间切片：看不同阶段是否都能解释；
- 2 年滚动窗口：看局部窗口内是否稳定；
- 不同起点敏感性：看结论是否依赖 `2020-01-01` 这个起点。

注意：滚动窗口和不同起点窗口彼此高度重叠，不能当成独立样本；胜率只用于观察稳定性，不用于显著性检验。

样本窗口：{context["common_start"]} 至 {context["common_end"]}。

## 2. 组合口径

之前报告的主口径是 `cash_slots`：

- `cash_slots`：固定槽位模型；未上市、无数据、不可交易的币，其槽位资金视为现金，收益为 0。
- `common_sample`：严格共同样本；只有所有币都有数据的日期才参与比较。
- `dynamic_eligible`：动态可交易池；当天有数据的币等权，未上市币不占槽位。

`cash_slots` 不是 bug，但它是一个强假设，尤其会影响 SOL、AVAX、NEAR、UNI 上市前的 2020/2021 早期结果。因此本版同时输出三种口径。

![三种组合口径]({md_img(OUTPUT_DIR / "05_policy_comparison.png")})

全样本三口径：

| Policy | Pool | Start | End | Days | CAGR | Sharpe | MDD | Calmar | Final |
|---|---|---|---|---:|---:|---:|---:|---:|---:|
{policy_full_rows(fixed_df)}

后续图表的主展示仍使用 `cash_slots`，因为它最接近“固定 12 个 sleeve，空槽资金留现金”的可部署口径；但结论必须同时参考三口径表。

## 3. 固定时间切片

![固定时间切片]({md_img(OUTPUT_DIR / "01_fixed_periods.png")})

关键阶段表：

| Period | Pool | CAGR | Sharpe | MDD | Calmar | Final |
|---|---|---:|---:|---:|---:|---:|
{table_rows(fixed_select, [BTC_ONLY, CORE4, POOL12])}

解读：

- 全样本：12 coin pool CAGR {pct(full.loc[POOL12, "cagr"])}，低于 Core4 的 {pct(full.loc[CORE4, "cagr"])}，但 Calmar {num(full.loc[POOL12, "calmar"])} 最高。
- 2021：Core4 明显最强，说明 Core4 全样本收益高度吃到 SOL/BNB/ETH 的强趋势。
- 2022-2026：12 coin pool CAGR {pct(post.loc[POOL12, "cagr"])}，低于 BTC only 的 {pct(post.loc[BTC_ONLY, "cagr"])}，但 Sharpe/MDD/Calmar 更好。

单年 Calmar 对局部低回撤非常敏感，只适合阶段观察，不适合作为长期目标值。

## 4. 不同起点敏感性

![不同起点敏感性]({md_img(OUTPUT_DIR / "02_start_date_sensitivity.png")})

相对胜率：

| Comparison | Samples | CAGR win | Sharpe win | MDD win | Calmar win | Avg CAGR diff | Avg Calmar diff |
|---|---:|---:|---:|---:|---:|---:|---:|
{summary_rows(cash_start_summary)}

关键点：

- 12 coin pool 相对 BTC only：不同起点下 Calmar 胜率 {pct(start_12_btc.calmar_win_rate)}，Sharpe 胜率 {pct(start_12_btc.sharpe_win_rate)}。
- 12 coin pool 相对 Core4：CAGR 胜率 {pct(start_12_core.cagr_win_rate)}，但 Calmar 胜率 {pct(start_12_core.calmar_win_rate)}。

这说明 12 池不是单一起点偶然胜出；但它相对 Core4 的优势主要体现在风险调整，而不是绝对收益。

## 5. 2 年滚动窗口

![2 年滚动窗口]({md_img(OUTPUT_DIR / "03_rolling_2y.png")})

![稳定性胜率摘要]({md_img(OUTPUT_DIR / "04_winrate_summary.png")})

滚动窗口相对胜率：

| Comparison | Samples | CAGR win | Sharpe win | MDD win | Calmar win | Avg CAGR diff | Avg Calmar diff |
|---|---:|---:|---:|---:|---:|---:|---:|
{summary_rows(cash_rolling_summary)}

关键点：

- 12 coin pool 相对 BTC only：2 年滚动 Calmar 胜率 {pct(roll_12_btc.calmar_win_rate)}，Sharpe 胜率 {pct(roll_12_btc.sharpe_win_rate)}。
- 12 coin pool 相对 Core4：2 年滚动 Calmar 胜率 {pct(roll_12_core.calmar_win_rate)}，但 CAGR 胜率 {pct(roll_12_core.cagr_win_rate)}。

三种组合口径下，12 coin pool 的 2 年滚动胜率：

| Policy | Comparison | Samples | CAGR win | Sharpe win | MDD win | Calmar win | Avg CAGR diff | Avg Calmar diff |
|---|---|---:|---:|---:|---:|---:|---:|---:|
{policy_rolling_rows(rolling_summary)}

严格 `common_sample` 口径下，12 coin pool 相对 BTC only 的 CAGR 胜率会下降；这说明不能把 12 池解释为“绝对收益稳定碾压 BTC”。但 Sharpe / MDD / Calmar 仍然更稳，这才是当前结论的核心。

## 6. 当前判断

这一步支持一个克制结论：

> 12 coin pool 不是收益爆发最强的版本，但它在不同时间切片、不同起点和滚动窗口里，风险调整表现更稳定。

具体判断：

1. 如果目标是最高全样本 CAGR，Core4 更强。
2. 如果目标是右侧现货动量的稳定 baseline，12 coin pool 更合理。
3. BTC only 仍是必要基准，但目前不是最优实现。
4. 12 coin pool 的优势主要是 Sharpe / MDD / Calmar，不是每个阶段都 CAGR 领先。
5. `cash_slots` 口径必须明确写作固定槽位现金假设；三口径结果一起看后，12 池的风险调整优势仍然成立，但 CAGR 结论要更谨慎。

下一步建议：

> 当前可以暂定 12 coin pool 为右侧现货动量 baseline 候选；下一轮不要再做筛选或参数优化，而应做最终边界检查：交易成本敏感性、成本冲击、缺失币/交易所可得性，以及部署层的资金分配规则。
"""


def main() -> None:
    baseline = load_baseline_module()
    _, _, _, _, _, backtests, context = baseline.build_results(refresh=False)
    pools = build_pools(context["selected_symbols"])
    policy_returns = {
        policy: {pool: portfolio_return(backtests, symbols, policy=policy) for pool, symbols in pools.items()}
        for policy in POLICY_LABELS
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    fixed_df = pd.concat(
        [compute_fixed_periods(baseline, returns, policy) for policy, returns in policy_returns.items()],
        ignore_index=True,
    )
    rolling_df = pd.concat(
        [compute_rolling_windows(baseline, returns, policy, years=2) for policy, returns in policy_returns.items()],
        ignore_index=True,
    )
    start_df = pd.concat(
        [compute_start_sensitivity(baseline, returns, policy) for policy, returns in policy_returns.items()],
        ignore_index=True,
    )
    rolling_summary = compare_to_benchmarks(rolling_df, "window_start")
    start_summary = compare_to_benchmarks(start_df, "start_date")
    cash_fixed = fixed_df[fixed_df["policy"] == "cash_slots"]
    cash_rolling = rolling_df[rolling_df["policy"] == "cash_slots"]
    cash_start = start_df[start_df["policy"] == "cash_slots"]
    cash_rolling_summary = rolling_summary[rolling_summary["policy"] == "cash_slots"]
    cash_start_summary = start_summary[start_summary["policy"] == "cash_slots"]

    fixed_df.to_csv(OUTPUT_DIR / "walk_fixed_period_metrics.csv", index=False, encoding="utf-8-sig")
    rolling_df.to_csv(OUTPUT_DIR / "walk_rolling_2y_metrics.csv", index=False, encoding="utf-8-sig")
    start_df.to_csv(OUTPUT_DIR / "walk_start_date_sensitivity.csv", index=False, encoding="utf-8-sig")
    rolling_summary.to_csv(OUTPUT_DIR / "walk_rolling_summary.csv", index=False, encoding="utf-8-sig")
    start_summary.to_csv(OUTPUT_DIR / "walk_start_summary.csv", index=False, encoding="utf-8-sig")

    draw_fixed_periods(cash_fixed, OUTPUT_DIR / "01_fixed_periods.png")
    draw_start_sensitivity(cash_start, OUTPUT_DIR / "02_start_date_sensitivity.png")
    draw_rolling_windows(cash_rolling, OUTPUT_DIR / "03_rolling_2y.png")
    draw_winrate_summary(cash_rolling_summary, cash_start_summary, OUTPUT_DIR / "04_winrate_summary.png")
    draw_policy_comparison(fixed_df, OUTPUT_DIR / "05_policy_comparison.png")

    REPORT_PATH.write_text(make_report(context, fixed_df, rolling_summary, start_summary), encoding="utf-8-sig")

    print("Fixed periods")
    print(fixed_df[(fixed_df["period"].isin(["FULL", "POST_2021"])) & (fixed_df["policy"] == "cash_slots")][["period_label", "label", "cagr", "sharpe", "mdd", "calmar", "final"]].to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print("\nPolicy full sample")
    print(fixed_df[fixed_df["period"] == "FULL"][["policy_label", "label", "start", "end", "days", "cagr", "sharpe", "mdd", "calmar", "final"]].to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print("\nRolling summary")
    print(rolling_summary.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print("\nStart summary")
    print(start_summary.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print(f"\nSaved outputs to: {OUTPUT_DIR}")
    print(f"Saved report to: {REPORT_PATH}")


if __name__ == "__main__":
    main()
