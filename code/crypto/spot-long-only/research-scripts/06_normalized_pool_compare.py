from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
BASELINE_SCRIPT = ROOT / "02_spot_universe_baseline.py"
OUTPUT_DIR = ROOT / "outputs_normalized_compare"
REPORT_PATH = ROOT / "06_normalized_pool_compare_report.md"

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

MODE_LABELS = {
    "raw": "Raw",
    "same_exposure": "Same exposure",
    "same_vol": "Same vol",
}


def load_baseline_module():
    spec = importlib.util.spec_from_file_location("spot_normalized_compare_baseline", BASELINE_SCRIPT)
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
    return {
        BTC_ONLY: ["BTCUSDT"],
        CORE4: ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"],
        POOL12: [s for s in selected_symbols if s not in {"LTCUSDT", "AAVEUSDT"}],
    }


def portfolio_series(backtests: dict[str, pd.DataFrame], symbols: list[str], column: str) -> pd.Series:
    panel = pd.concat([backtests[s][column].rename(s) for s in symbols], axis=1).fillna(0.0)
    return panel.mean(axis=1)


def portfolio_exposure(backtests: dict[str, pd.DataFrame], symbols: list[str]) -> pd.Series:
    panel = pd.concat([backtests[s]["Exposure"].rename(s) for s in symbols], axis=1).fillna(0.0)
    return panel.abs().mean(axis=1)


def compute_raw_inputs(baseline, backtests: dict[str, pd.DataFrame], pools: dict[str, list[str]]) -> pd.DataFrame:
    rows = []
    for pool, symbols in pools.items():
        ret = portfolio_series(backtests, symbols, "GrossReturn")
        net_ret = portfolio_series(backtests, symbols, "NetReturn")
        exp = portfolio_exposure(backtests, symbols)
        gross_m = baseline.metrics(ret)
        net_m = baseline.metrics(net_ret)
        rows.append(
            dict(
                pool=pool,
                label=POOL_LABELS[pool],
                n_symbols=len(symbols),
                symbols=", ".join(symbols),
                raw_avg_exposure=float(exp.mean()),
                raw_vol=gross_m["vol"],
                raw_gross_cagr=gross_m["cagr"],
                raw_gross_sharpe=gross_m["sharpe"],
                raw_gross_mdd=gross_m["mdd"],
                raw_gross_calmar=gross_m["calmar"],
                raw_gross_final=gross_m["final"],
                raw_net_cagr=net_m["cagr"],
                raw_net_sharpe=net_m["sharpe"],
                raw_net_mdd=net_m["mdd"],
                raw_net_calmar=net_m["calmar"],
                raw_net_final=net_m["final"],
            )
        )
    return pd.DataFrame(rows)


def scale_inputs(raw_df: pd.DataFrame) -> pd.DataFrame:
    pool12 = raw_df.set_index("pool").loc[POOL12]
    target_exposure = float(pool12["raw_avg_exposure"])
    target_vol = float(pool12["raw_vol"])
    rows = []
    for row in raw_df.itertuples():
        exposure_scale = min(1.0, target_exposure / float(row.raw_avg_exposure)) if row.raw_avg_exposure > 0 else 0.0
        vol_scale = min(1.0, target_vol / float(row.raw_vol)) if row.raw_vol > 0 else 0.0
        rows.append(
            dict(
                pool=row.pool,
                label=row.label,
                n_symbols=int(row.n_symbols),
                symbols=row.symbols,
                target_exposure=target_exposure,
                target_vol=target_vol,
                raw_avg_exposure=float(row.raw_avg_exposure),
                raw_vol=float(row.raw_vol),
                raw_scale=1.0,
                same_exposure_scale=exposure_scale,
                same_vol_scale=vol_scale,
            )
        )
    return pd.DataFrame(rows)


def compute_scaled_metrics(baseline, backtests: dict[str, pd.DataFrame], pools: dict[str, list[str]], scale_df: pd.DataFrame):
    rows = []
    equity_map: dict[str, dict[str, pd.Series]] = {mode: {} for mode in MODE_LABELS}
    return_map: dict[str, dict[str, pd.Series]] = {mode: {} for mode in MODE_LABELS}
    scale_lookup = scale_df.set_index("pool")

    for pool, symbols in pools.items():
        gross_ret = portfolio_series(backtests, symbols, "GrossReturn")
        net_ret = portfolio_series(backtests, symbols, "NetReturn")
        exposure = portfolio_exposure(backtests, symbols)
        scales = {
            "raw": 1.0,
            "same_exposure": float(scale_lookup.loc[pool, "same_exposure_scale"]),
            "same_vol": float(scale_lookup.loc[pool, "same_vol_scale"]),
        }
        for norm_mode, scale in scales.items():
            for mode, base_ret in [("gross", gross_ret), ("net_cost_model", net_ret)]:
                ret = base_ret * scale
                m = baseline.metrics(ret)
                rows.append(
                    dict(
                        pool=pool,
                        label=POOL_LABELS[pool],
                        normalization=norm_mode,
                        normalization_label=MODE_LABELS[norm_mode],
                        return_mode=mode,
                        scale=scale,
                        n_symbols=len(symbols),
                        avg_exposure=float(exposure.mean() * scale),
                        symbols=", ".join(symbols),
                        **m,
                    )
                )
                if mode == "gross":
                    return_map[norm_mode][pool] = ret
                    equity_map[norm_mode][pool] = (1.0 + ret).cumprod()
    return pd.DataFrame(rows), return_map, equity_map


def rolling_normalized(baseline, return_map: dict[str, dict[str, pd.Series]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    base_index = next(iter(next(iter(return_map.values())).values())).index
    first = base_index[0]
    last_start = base_index[-1] - pd.DateOffset(years=2) + pd.Timedelta(days=1)
    starts = pd.date_range(first, last_start, freq="MS")
    if starts.empty or starts[0] != first:
        starts = pd.DatetimeIndex([first]).append(starts)

    rows = []
    for norm_mode, pool_returns in return_map.items():
        for start in starts:
            end = start + pd.DateOffset(years=2) - pd.Timedelta(days=1)
            for pool, ret in pool_returns.items():
                seg = ret.loc[start:end]
                if len(seg) < 365:
                    continue
                row = dict(
                    normalization=norm_mode,
                    normalization_label=MODE_LABELS[norm_mode],
                    pool=pool,
                    label=POOL_LABELS[pool],
                    window_start=start.date().isoformat(),
                    window_end=end.date().isoformat(),
                )
                row.update(baseline.metrics(seg))
                rows.append(row)
    rolling_df = pd.DataFrame(rows)

    summary_rows = []
    for norm_mode, seg in rolling_df.groupby("normalization"):
        pivots = {metric: seg.pivot(index="window_start", columns="pool", values=metric) for metric in ["cagr", "sharpe", "mdd", "calmar"]}
        for challenger in [CORE4, POOL12]:
            common = pivots["cagr"][[challenger, BTC_ONLY]].dropna().index
            cagr = pivots["cagr"].loc[common]
            sharpe = pivots["sharpe"].loc[common]
            mdd = pivots["mdd"].loc[common]
            calmar = pivots["calmar"].loc[common]
            summary_rows.append(
                dict(
                    normalization=norm_mode,
                    normalization_label=MODE_LABELS[norm_mode],
                    challenger=challenger,
                    label=POOL_LABELS[challenger],
                    benchmark=BTC_ONLY,
                    windows=len(common),
                    cagr_win_rate=float((cagr[challenger] > cagr[BTC_ONLY]).mean()),
                    sharpe_win_rate=float((sharpe[challenger] > sharpe[BTC_ONLY]).mean()),
                    mdd_win_rate=float((mdd[challenger] > mdd[BTC_ONLY]).mean()),
                    calmar_win_rate=float((calmar[challenger] > calmar[BTC_ONLY]).mean()),
                    avg_cagr_diff=float((cagr[challenger] - cagr[BTC_ONLY]).mean()),
                    avg_sharpe_diff=float((sharpe[challenger] - sharpe[BTC_ONLY]).mean()),
                    avg_mdd_diff=float((mdd[challenger] - mdd[BTC_ONLY]).mean()),
                    avg_calmar_diff=float((calmar[challenger] - calmar[BTC_ONLY]).mean()),
                )
            )
    return rolling_df, pd.DataFrame(summary_rows)


def draw_normalized_equity(equity_map: dict[str, dict[str, pd.Series]], out_path: Path) -> None:
    width, height = 1750, 1250
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (70, 28), "同暴露 / 同波动归一化后的权益曲线", 30, bold=True)
    draw_text(draw, (70, 64), "只做现金降仓，不使用杠杆；12 币池作为目标风险/暴露水平。", 18, fill=(90, 95, 105))

    panels = [("raw", 115), ("same_exposure", 480), ("same_vol", 845)]
    x0, x1 = 110, width - 80
    panel_h = 270
    for norm_mode, y0 in panels:
        aligned = pd.concat(equity_map[norm_mode], axis=1).dropna()
        log_values = np.log(aligned.clip(lower=1e-8))
        ymin, ymax = float(log_values.min().min()), float(log_values.max().max())
        pad = max((ymax - ymin) * 0.08, 0.01)
        ymin -= pad
        ymax += pad
        y1 = y0 + panel_h
        draw_text(draw, (x0, y0 - 36), MODE_LABELS[norm_mode], 24, bold=True)
        draw.rectangle((x0, y0, x1, y1), outline=(220, 224, 230))
        for i in range(5):
            y = y1 - int((y1 - y0) * i / 4)
            value = np.exp(ymin + (ymax - ymin) * i / 4)
            draw.line((x0, y, x1, y), fill=(238, 241, 245))
            draw_text(draw, (35, y - 10), f"{value:.1f}x", 15, fill=(95, 100, 110))
        for pool in [BTC_ONLY, CORE4, POOL12]:
            vals = log_values[pool].values
            pts = []
            for i, value in enumerate(vals):
                x = x0 + int((x1 - x0) * i / (len(vals) - 1))
                y = y1 - int((y1 - y0) * (float(value) - ymin) / (ymax - ymin))
                pts.append((x, y))
            draw.line(pts, fill=COLORS[pool], width=4)
    for i, pool in enumerate([BTC_ONLY, CORE4, POOL12]):
        lx = x0 + 60 + i * 410
        draw.rectangle((lx, height - 80, lx + 28, height - 63), fill=COLORS[pool])
        draw_text(draw, (lx + 38, height - 85), POOL_LABELS[pool], 18, fill=(50, 55, 65))
    img.save(out_path)


def draw_normalized_metrics(metrics_df: pd.DataFrame, out_path: Path) -> None:
    width, height = 1800, 1120
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (70, 28), "归一化指标对比", 30, bold=True)
    draw_text(draw, (70, 64), "Gross 口径；MDD 展示绝对值，越低越好。", 18, fill=(90, 95, 105))

    df = metrics_df[metrics_df["return_mode"] == "gross"].copy()
    metrics = [("CAGR", "cagr", False), ("Sharpe", "sharpe", False), ("MDD", "mdd", True), ("Calmar", "calmar", False)]
    origins = [(80, 145), (940, 145), (80, 610), (940, 610)]
    panel_w, panel_h = 770, 340
    pool_order = [BTC_ONLY, CORE4, POOL12]
    norm_order = ["raw", "same_exposure", "same_vol"]
    for (title, col, abs_mode), (ox, oy) in zip(metrics, origins):
        draw_text(draw, (ox, oy - 34), title, 23, bold=True)
        draw.rectangle((ox, oy, ox + panel_w, oy + panel_h), outline=(220, 224, 230))
        vals = []
        for norm_mode in norm_order:
            for pool in pool_order:
                value = float(df[(df["normalization"] == norm_mode) & (df["pool"] == pool)][col].iloc[0])
                vals.append(abs(value) if abs_mode else value)
        max_v = max(vals + [1e-9]) * 1.18
        baseline_y = oy + panel_h - 55
        draw.line((ox + 45, baseline_y, ox + panel_w - 30, baseline_y), fill=(190, 195, 205), width=2)
        group_w = (panel_w - 90) / len(norm_order)
        bar_w = 46
        for i, norm_mode in enumerate(norm_order):
            gx = ox + 55 + int(i * group_w)
            draw_text(draw, (gx + 18, oy + panel_h - 33), MODE_LABELS[norm_mode], 13, fill=(55, 60, 70), bold=True)
            for j, pool in enumerate(pool_order):
                raw_value = float(df[(df["normalization"] == norm_mode) & (df["pool"] == pool)][col].iloc[0])
                value = abs(raw_value) if abs_mode else raw_value
                bar_h = int((panel_h - 100) * value / max_v)
                x = gx + j * (bar_w + 12)
                draw.rectangle((x, baseline_y - bar_h, x + bar_w, baseline_y), fill=COLORS[pool])
                label = f"{value:.2f}" if col in {"sharpe", "calmar"} else pct(value)
                draw_text(draw, (x - 10, baseline_y - bar_h - 24), label, 13, fill=(45, 50, 60))
    for i, pool in enumerate(pool_order):
        lx = 120 + i * 440
        draw.rectangle((lx, height - 70, lx + 28, height - 53), fill=COLORS[pool])
        draw_text(draw, (lx + 38, height - 75), POOL_LABELS[pool], 18, fill=(50, 55, 65))
    img.save(out_path)


def draw_scaling_factors(scale_df: pd.DataFrame, out_path: Path) -> None:
    width, height = 1500, 820
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (70, 28), "归一化降仓比例", 30, bold=True)
    draw_text(draw, (70, 64), "目标为 12 币池水平；比例小于 1 表示把其余资金放现金。", 18, fill=(90, 95, 105))

    df = scale_df.set_index("pool").loc[[BTC_ONLY, CORE4, POOL12]].reset_index()
    x0, y0, x1, y1 = 110, 130, width - 90, height - 150
    draw.rectangle((x0, y0, x1, y1), outline=(220, 224, 230))
    for i in range(6):
        y = y1 - int((y1 - y0) * i / 5)
        draw.line((x0, y, x1, y), fill=(238, 241, 245))
        draw_text(draw, (50, y - 10), pct(i / 5), 15, fill=(95, 100, 110))
    group_w = (x1 - x0 - 90) / len(df)
    bar_w = 100
    for i, row in enumerate(df.itertuples()):
        gx = x0 + 70 + int(i * group_w)
        for j, (label, col) in enumerate([("Same exposure", "same_exposure_scale"), ("Same vol", "same_vol_scale")]):
            value = float(getattr(row, col))
            bar_h = int((y1 - y0) * value)
            x = gx + j * (bar_w + 24)
            draw.rectangle((x, y1 - bar_h, x + bar_w, y1), fill=COLORS[row.pool] if j == 0 else "#6B7280")
            draw_text(draw, (x + 12, y1 - bar_h - 26), pct(value), 16, fill=(45, 50, 60), bold=True)
            draw_text(draw, (x - 4, y1 + 12), label, 14, fill=(55, 60, 70))
        draw_text(draw, (gx + 7, y1 + 48), POOL_LABELS[row.pool], 17, fill=(45, 50, 60), bold=True)
    img.save(out_path)


def draw_rolling_winrates(rolling_summary: pd.DataFrame, out_path: Path) -> None:
    width, height = 1550, 920
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (70, 28), "2 年滚动窗口：归一化后相对 BTC 胜率", 30, bold=True)
    draw_text(draw, (70, 64), "每组内比较 Core4 / 12池 是否优于 BTC only。", 18, fill=(90, 95, 105))

    metrics = [("CAGR", "cagr_win_rate"), ("Sharpe", "sharpe_win_rate"), ("MDD", "mdd_win_rate"), ("Calmar", "calmar_win_rate")]
    norm_order = ["raw", "same_exposure", "same_vol"]
    challenger_order = [CORE4, POOL12]
    x0, y0, x1, y1 = 110, 135, width - 80, height - 150
    draw.rectangle((x0, y0, x1, y1), outline=(220, 224, 230))
    for i in range(6):
        y = y1 - int((y1 - y0) * i / 5)
        draw.line((x0, y, x1, y), fill=(238, 241, 245))
        draw_text(draw, (50, y - 10), pct(i / 5), 15, fill=(95, 100, 110))

    group_w = (x1 - x0 - 80) / len(norm_order)
    bar_w = 36
    for i, norm_mode in enumerate(norm_order):
        gx = x0 + 55 + int(i * group_w)
        draw_text(draw, (gx + 120, y1 + 22), MODE_LABELS[norm_mode], 18, fill=(55, 60, 70), bold=True)
        for j, (metric_label, col) in enumerate(metrics):
            mx = gx + j * 82
            draw_text(draw, (mx, y1 + 50), metric_label, 12, fill=(80, 85, 95))
            for k, challenger in enumerate(challenger_order):
                row = rolling_summary[(rolling_summary["normalization"] == norm_mode) & (rolling_summary["challenger"] == challenger)].iloc[0]
                value = float(row[col])
                bar_h = int((y1 - y0) * value)
                x = mx + k * (bar_w + 5)
                draw.rectangle((x, y1 - bar_h, x + bar_w, y1), fill=COLORS[challenger])
    for i, challenger in enumerate(challenger_order):
        lx = x0 + 60 + i * 400
        draw.rectangle((lx, height - 70, lx + 28, height - 53), fill=COLORS[challenger])
        draw_text(draw, (lx + 38, height - 75), POOL_LABELS[challenger], 18, fill=(50, 55, 65))
    img.save(out_path)


def table_for_metrics(metrics_df: pd.DataFrame, normalization: str, return_mode: str = "gross") -> str:
    df = metrics_df[(metrics_df["normalization"] == normalization) & (metrics_df["return_mode"] == return_mode)].set_index("pool")
    rows = []
    for pool in [BTC_ONLY, CORE4, POOL12]:
        r = df.loc[pool]
        rows.append(
            f"| {POOL_LABELS[pool]} | {pct(r.scale)} | {pct(r.cagr)} | {num(r.sharpe)} | {pct(r.mdd)} | {num(r.calmar)} | {num(r.final)}x | {pct(r.avg_exposure)} |"
        )
    return "\n".join(rows)


def make_report(context: dict, scale_df: pd.DataFrame, metrics_df: pd.DataFrame, rolling_summary: pd.DataFrame) -> str:
    gross = metrics_df[(metrics_df["return_mode"] == "gross")].set_index(["normalization", "pool"])
    raw_pool12 = gross.loc[("raw", POOL12)]
    exp_btc = gross.loc[("same_exposure", BTC_ONLY)]
    exp_core4 = gross.loc[("same_exposure", CORE4)]
    exp_pool12 = gross.loc[("same_exposure", POOL12)]
    vol_btc = gross.loc[("same_vol", BTC_ONLY)]
    vol_core4 = gross.loc[("same_vol", CORE4)]
    vol_pool12 = gross.loc[("same_vol", POOL12)]

    scale_rows = []
    for row in scale_df.set_index("pool").loc[[BTC_ONLY, CORE4, POOL12]].itertuples():
        scale_rows.append(
            f"| {POOL_LABELS[row.Index]} | {pct(row.raw_avg_exposure)} | {pct(row.raw_vol)} | {pct(row.same_exposure_scale)} | {pct(row.same_vol_scale)} |"
        )
    roll_rows = []
    for norm_mode in ["raw", "same_exposure", "same_vol"]:
        for challenger in [CORE4, POOL12]:
            r = rolling_summary[(rolling_summary["normalization"] == norm_mode) & (rolling_summary["challenger"] == challenger)].iloc[0]
            roll_rows.append(
                f"| {MODE_LABELS[norm_mode]} | {POOL_LABELS[challenger]} | {int(r.windows)} | {pct(r.cagr_win_rate)} | {pct(r.sharpe_win_rate)} | {pct(r.mdd_win_rate)} | {pct(r.calmar_win_rate)} | {pct(r.avg_cagr_diff)} | {num(r.avg_calmar_diff)} |"
            )

    return f"""# 右侧现货动量：同风险 / 同暴露归一化对比

生成时间：{pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")}

## 1. 验证目标

本轮只做归一化验证，不改信号、不改参数、不新增过滤器。

核心问题：

> 12 coin pool 的优势，是否只是因为暴露/波动更低，或者在同风险、同暴露下仍然成立？

样本窗口：{context["common_start"]} 至 {context["common_end"]}。

归一化规则：

- Same exposure：把 BTC only 和 Core4 现金降仓到 12 coin pool 的平均暴露水平。
- Same vol：把 BTC only 和 Core4 现金降仓到 12 coin pool 的年化波动水平。
- 不使用杠杆；如果某组合本来低于目标水平，也不放大。
- 这一步是诊断口径，不是交易参数。

## 2. 降仓比例

![归一化降仓比例]({md_img(OUTPUT_DIR / "03_scaling_factors.png")})

| Pool | Raw avg exposure | Raw vol | Same exposure scale | Same vol scale |
|---|---:|---:|---:|---:|
{chr(10).join(scale_rows)}

12 coin pool 原始平均暴露 {pct(raw_pool12.avg_exposure)}，原始波动 {pct(raw_pool12.vol)}；因此它是本轮归一化目标。

## 3. 全样本权益与指标

![归一化权益曲线]({md_img(OUTPUT_DIR / "01_normalized_equity.png")})

![归一化指标对比]({md_img(OUTPUT_DIR / "02_normalized_metrics.png")})

Raw：

| Pool | Scale | CAGR | Sharpe | MDD | Calmar | Final | Avg exposure |
|---|---:|---:|---:|---:|---:|---:|---:|
{table_for_metrics(metrics_df, "raw")}

Same exposure：

| Pool | Scale | CAGR | Sharpe | MDD | Calmar | Final | Avg exposure |
|---|---:|---:|---:|---:|---:|---:|---:|
{table_for_metrics(metrics_df, "same_exposure")}

Same vol：

| Pool | Scale | CAGR | Sharpe | MDD | Calmar | Final | Avg exposure |
|---|---:|---:|---:|---:|---:|---:|---:|
{table_for_metrics(metrics_df, "same_vol")}

## 4. 结果解读

同暴露口径：

- BTC only 降仓后 CAGR {pct(exp_btc.cagr)}，Calmar {num(exp_btc.calmar)}。
- Core4 降仓后 CAGR {pct(exp_core4.cagr)}，Calmar {num(exp_core4.calmar)}。
- 12 coin pool 保持原始仓位，CAGR {pct(exp_pool12.cagr)}，Calmar {num(exp_pool12.calmar)}。

同波动口径：

- BTC only 降仓后 CAGR {pct(vol_btc.cagr)}，Calmar {num(vol_btc.calmar)}。
- Core4 降仓后 CAGR {pct(vol_core4.cagr)}，Calmar {num(vol_core4.calmar)}。
- 12 coin pool 保持原始仓位，CAGR {pct(vol_pool12.cagr)}，Calmar {num(vol_pool12.calmar)}。

因此当前证据更偏向：

> 12 coin pool 的优势不是靠更高暴露获得，而是在较低暴露和较低波动下保持了更好的风险调整收益。

## 5. 2 年滚动窗口

![滚动胜率]({md_img(OUTPUT_DIR / "04_rolling_winrates.png")})

相对 BTC only 的滚动胜率：

| Normalization | Challenger | Windows | CAGR win | Sharpe win | MDD win | Calmar win | Avg CAGR diff | Avg Calmar diff |
|---|---|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(roll_rows)}

注意：归一化后 BTC only 本身也被现金降仓，所以它的滚动 MDD 会机械性改善；MDD win rate 下降不等于 12 coin pool 变差。这个表里更应关注 CAGR、Sharpe、Calmar 三项是否仍然占优。

## 6. 当前判断

这一步支持 12 coin pool 继续作为候选 baseline：

1. 原始口径下，12 coin pool 已经优于 BTC only。
2. 同暴露和同波动后，BTC only 与 Core4 被降仓，12 coin pool 的全样本优势更清楚。
3. 但这不是说 12 coin pool 一定优于 Core4 的收益能力；Core4 原始收益仍更强，只是风险集中度更高。

下一步建议：

> 不再删币，不再调参数。下一轮应做 walk-forward / 时间切片验证，确认 12 coin pool 在不同起点、不同阶段下是否仍能稳定压过 BTC only，并与 Core4 保持可接受差距。
"""


def main() -> None:
    baseline = load_baseline_module()
    _, _, _, _, _, backtests, context = baseline.build_results(refresh=False)
    pools = build_pools(context["selected_symbols"])

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    raw_df = compute_raw_inputs(baseline, backtests, pools)
    scale_df = scale_inputs(raw_df)
    metrics_df, return_map, equity_map = compute_scaled_metrics(baseline, backtests, pools, scale_df)
    rolling_df, rolling_summary_df = rolling_normalized(baseline, return_map)

    raw_df.to_csv(OUTPUT_DIR / "normalized_raw_inputs.csv", index=False, encoding="utf-8-sig")
    scale_df.to_csv(OUTPUT_DIR / "normalized_scaling_factors.csv", index=False, encoding="utf-8-sig")
    metrics_df.to_csv(OUTPUT_DIR / "normalized_metrics.csv", index=False, encoding="utf-8-sig")
    rolling_df.to_csv(OUTPUT_DIR / "normalized_rolling_2y.csv", index=False, encoding="utf-8-sig")
    rolling_summary_df.to_csv(OUTPUT_DIR / "normalized_rolling_summary.csv", index=False, encoding="utf-8-sig")

    draw_normalized_equity(equity_map, OUTPUT_DIR / "01_normalized_equity.png")
    draw_normalized_metrics(metrics_df, OUTPUT_DIR / "02_normalized_metrics.png")
    draw_scaling_factors(scale_df, OUTPUT_DIR / "03_scaling_factors.png")
    draw_rolling_winrates(rolling_summary_df, OUTPUT_DIR / "04_rolling_winrates.png")

    REPORT_PATH.write_text(make_report(context, scale_df, metrics_df, rolling_summary_df), encoding="utf-8-sig")

    print(metrics_df[(metrics_df["return_mode"] == "gross")][["label", "normalization_label", "scale", "cagr", "sharpe", "mdd", "calmar", "vol", "avg_exposure", "final"]].to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print("\nScaling factors")
    print(scale_df[["label", "raw_avg_exposure", "raw_vol", "same_exposure_scale", "same_vol_scale"]].to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print("\nRolling summary")
    print(rolling_summary_df.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print(f"\nSaved outputs to: {OUTPUT_DIR}")
    print(f"Saved report to: {REPORT_PATH}")


if __name__ == "__main__":
    main()
