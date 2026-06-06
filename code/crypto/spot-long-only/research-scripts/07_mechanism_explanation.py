from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
BASELINE_SCRIPT = ROOT / "02_spot_universe_baseline.py"
OUTPUT_DIR = ROOT / "outputs_mechanism"
REPORT_PATH = ROOT / "07_mechanism_explanation_report.md"


def load_baseline_module():
    spec = importlib.util.spec_from_file_location("spot_mechanism_baseline", BASELINE_SCRIPT)
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


def upper_triangle_stats(matrix: pd.DataFrame) -> dict:
    mask = np.triu(np.ones(matrix.shape), 1).astype(bool)
    values = matrix.where(mask).stack()
    return dict(
        mean=float(values.mean()),
        median=float(values.median()),
        min=float(values.min()),
        max=float(values.max()),
    )


def jaccard_matrix(position: pd.DataFrame) -> pd.DataFrame:
    symbols = position.columns.tolist()
    out = pd.DataFrame(np.eye(len(symbols)), index=symbols, columns=symbols)
    for a in symbols:
        for b in symbols:
            both = ((position[a] == 1) & (position[b] == 1)).sum()
            either = ((position[a] == 1) | (position[b] == 1)).sum()
            out.loc[a, b] = float(both / either) if either else 0.0
    return out


def build_mechanism_data(backtests: dict[str, pd.DataFrame], symbols: list[str]):
    raw_return = pd.concat([backtests[s]["MarketReturn"].rename(s) for s in symbols], axis=1).fillna(0.0)
    strategy_return = pd.concat([backtests[s]["GrossReturn"].rename(s) for s in symbols], axis=1).fillna(0.0)
    exposure = pd.concat([backtests[s]["Exposure"].rename(s) for s in symbols], axis=1).fillna(0.0)
    position = (exposure > 0).astype(int)

    raw_corr = raw_return.corr()
    strategy_corr = strategy_return.corr()
    position_corr = position.corr()
    position_jaccard = jaccard_matrix(position)

    portfolio_return = strategy_return.mean(axis=1)
    portfolio_equity = (1.0 + portfolio_return).cumprod()
    drawdown = portfolio_equity / portfolio_equity.cummax() - 1.0
    trough = drawdown.idxmin()
    peak = portfolio_equity.loc[:trough].idxmax()

    active_count = position.sum(axis=1).rename("active_symbols")
    active_df = pd.DataFrame(
        {
            "active_symbols": active_count,
            "portfolio_equity": portfolio_equity,
            "drawdown": drawdown,
        }
    )
    dd_active = active_df.loc[(active_df.index > peak) & (active_df.index <= trough)]

    avg_individual_vol = float((strategy_return.std() * np.sqrt(365)).mean())
    portfolio_vol = float(portfolio_return.std() * np.sqrt(365))
    zero_corr_vol = float((strategy_return.std().pow(2).mean() ** 0.5) * np.sqrt(365) / (len(symbols) ** 0.5))

    prev_equity = portfolio_equity.shift(1).loc[dd_active.index].fillna(float(portfolio_equity.loc[peak]))
    daily_dd_contribution = strategy_return.loc[dd_active.index].div(len(symbols)).mul(prev_equity / float(portfolio_equity.loc[peak]), axis=0)
    dd_contribution = daily_dd_contribution.sum().rename("drawdown_contribution").reset_index().rename(columns={"index": "symbol"})

    summary_rows = [
        dict(metric="raw_return_corr", **upper_triangle_stats(raw_corr)),
        dict(metric="strategy_return_corr", **upper_triangle_stats(strategy_corr)),
        dict(metric="position_corr", **upper_triangle_stats(position_corr)),
        dict(metric="position_jaccard", **upper_triangle_stats(position_jaccard)),
    ]
    summary = pd.DataFrame(summary_rows)
    exposure_summary = pd.DataFrame(
        [
            dict(metric="avg_individual_strategy_vol", value=avg_individual_vol),
            dict(metric="portfolio_vol", value=portfolio_vol),
            dict(metric="zero_corr_reference_vol", value=zero_corr_vol),
            dict(metric="avg_active_symbols", value=float(active_count.mean())),
            dict(metric="median_active_symbols", value=float(active_count.median())),
            dict(metric="p90_active_symbols", value=float(active_count.quantile(0.90))),
            dict(metric="max_active_symbols", value=float(active_count.max())),
            dict(metric="dd_avg_active_symbols", value=float(dd_active["active_symbols"].mean())),
            dict(metric="dd_median_active_symbols", value=float(dd_active["active_symbols"].median())),
            dict(metric="dd_max_active_symbols", value=float(dd_active["active_symbols"].max())),
            dict(metric="max_drawdown", value=float(drawdown.loc[trough])),
        ]
    )
    meta = dict(
        peak_date=peak.date().isoformat(),
        trough_date=trough.date().isoformat(),
        start_date=portfolio_equity.index[0].date().isoformat(),
        end_date=portfolio_equity.index[-1].date().isoformat(),
        symbols=symbols,
    )
    return dict(
        raw_return=raw_return,
        strategy_return=strategy_return,
        exposure=exposure,
        position=position,
        raw_corr=raw_corr,
        strategy_corr=strategy_corr,
        position_corr=position_corr,
        position_jaccard=position_jaccard,
        active_df=active_df,
        dd_contribution=dd_contribution,
        summary=summary,
        exposure_summary=exposure_summary,
        meta=meta,
    )


def heat_color(value: float, vmin: float = 0.0, vmax: float = 1.0) -> tuple[int, int, int]:
    if pd.isna(value):
        return (245, 247, 250)
    value = max(vmin, min(vmax, value))
    t = (value - vmin) / (vmax - vmin) if vmax > vmin else 0.0
    base = (37, 92, 153)
    return tuple(int(255 * (1.0 - t) + c * t) for c in base)


def draw_matrix_panel(draw: ImageDraw.ImageDraw, matrix: pd.DataFrame, origin: tuple[int, int], title: str, cell: int = 47) -> None:
    ox, oy = origin
    symbols = [s.replace("USDT", "") for s in matrix.columns]
    draw_text(draw, (ox, oy - 42), title, 23, bold=True)
    for j, symbol in enumerate(symbols):
        draw_text(draw, (ox + 78 + j * cell, oy - 22), symbol, 11, fill=(55, 60, 70), bold=True)
    for i, symbol in enumerate(symbols):
        draw_text(draw, (ox, oy + 13 + i * cell), symbol, 12, fill=(55, 60, 70), bold=True)
    for i, row_symbol in enumerate(matrix.index):
        for j, col_symbol in enumerate(matrix.columns):
            value = float(matrix.loc[row_symbol, col_symbol])
            x = ox + 75 + j * cell
            y = oy + i * cell
            draw.rectangle((x, y, x + cell - 3, y + cell - 3), fill=heat_color(value), outline=(240, 243, 247))
            text_color = (255, 255, 255) if value > 0.62 else (35, 40, 45)
            draw_text(draw, (x + 8, y + 14), f"{value:.2f}", 10, fill=text_color)


def draw_correlation_compression(raw_corr: pd.DataFrame, strategy_corr: pd.DataFrame, summary: pd.DataFrame, out_path: Path) -> None:
    width, height = 1750, 930
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (70, 28), "原始相关性 vs 策略相关性", 30, bold=True)
    draw_text(draw, (70, 64), "主流币原始收益仍然正相关；右侧动量信号把收益相关性压低。", 18, fill=(90, 95, 105))

    draw_matrix_panel(draw, raw_corr, (80, 145), "原始现货日收益相关")
    draw_matrix_panel(draw, strategy_corr, (900, 145), "策略 sleeve 日收益相关")

    raw_mean = float(summary.loc[summary["metric"] == "raw_return_corr", "mean"].iloc[0])
    strat_mean = float(summary.loc[summary["metric"] == "strategy_return_corr", "mean"].iloc[0])
    compression = 1.0 - strat_mean / raw_mean if raw_mean else np.nan
    draw.rectangle((80, height - 95, width - 80, height - 55), fill=(245, 247, 250), outline=(225, 230, 236))
    draw_text(draw, (105, height - 88), f"平均相关：原始 {raw_mean:.2f} -> 策略 {strat_mean:.2f}；相关性压缩约 {pct(compression)}。", 20, fill=(45, 50, 60), bold=True)
    img.save(out_path)


def draw_position_overlap(position_corr: pd.DataFrame, position_jaccard: pd.DataFrame, summary: pd.DataFrame, out_path: Path) -> None:
    width, height = 1750, 930
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (70, 28), "持仓不同步：状态相关与重叠度", 30, bold=True)
    draw_text(draw, (70, 64), "位置相关看是否同时持仓；Jaccard 看共同持仓天数 / 任一持仓天数。", 18, fill=(90, 95, 105))

    draw_matrix_panel(draw, position_corr, (80, 145), "持仓状态相关")
    draw_matrix_panel(draw, position_jaccard, (900, 145), "持仓重叠度 Jaccard")
    pos_mean = float(summary.loc[summary["metric"] == "position_corr", "mean"].iloc[0])
    jac_mean = float(summary.loc[summary["metric"] == "position_jaccard", "mean"].iloc[0])
    draw.rectangle((80, height - 95, width - 80, height - 55), fill=(245, 247, 250), outline=(225, 230, 236))
    draw_text(draw, (105, height - 88), f"平均持仓状态相关 {pos_mean:.2f}；平均 Jaccard 重叠 {jac_mean:.2f}。这说明信号不是长期同步满仓。", 20, fill=(45, 50, 60), bold=True)
    img.save(out_path)


def draw_active_count(active_df: pd.DataFrame, meta: dict, out_path: Path) -> None:
    width, height = 1700, 1000
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (70, 28), "每日持仓数量与组合回撤", 30, bold=True)
    draw_text(draw, (70, 64), "12 币池不是满仓多币种；多数时间只持有少数进入右侧趋势的币。", 18, fill=(90, 95, 105))

    active = active_df["active_symbols"].astype(float)
    dd = active_df["drawdown"].astype(float)
    dates = active_df.index
    peak = pd.Timestamp(meta["peak_date"])
    trough = pd.Timestamp(meta["trough_date"])

    x0, x1 = 110, width - 80
    y0, y1 = 130, 485
    dd_y0, dd_y1 = 610, height - 105

    def x_at(date: pd.Timestamp) -> int:
        idx = dates.get_indexer([date], method="nearest")[0]
        return x0 + int((x1 - x0) * idx / (len(dates) - 1))

    peak_x, trough_x = x_at(peak), x_at(trough)
    draw.rectangle((peak_x, y0, trough_x, y1), fill=(255, 243, 224))
    draw.rectangle((peak_x, dd_y0, trough_x, dd_y1), fill=(255, 243, 224))

    draw_text(draw, (x0, y0 - 34), "Active symbols", 23, bold=True)
    draw.rectangle((x0, y0, x1, y1), outline=(220, 224, 230))
    for i in range(7):
        value = i * 2
        y = y1 - int((y1 - y0) * value / 12)
        draw.line((x0, y, x1, y), fill=(238, 241, 245))
        draw_text(draw, (55, y - 10), str(value), 15, fill=(95, 100, 110))
    pts = []
    values = active.values
    for i, value in enumerate(values):
        x = x0 + int((x1 - x0) * i / (len(values) - 1))
        y = y1 - int((y1 - y0) * value / 12)
        pts.append((x, y))
    draw.line(pts, fill="#255C99", width=3)
    avg_y = y1 - int((y1 - y0) * float(active.mean()) / 12)
    draw.line((x0, avg_y, x1, avg_y), fill="#D95F02", width=2)
    draw_text(draw, (x0 + 10, avg_y - 28), f"avg {active.mean():.2f}", 16, fill="#D95F02", bold=True)

    draw_text(draw, (x0, dd_y0 - 34), "Portfolio drawdown", 23, bold=True)
    draw.rectangle((x0, dd_y0, x1, dd_y1), outline=(220, 224, 230))
    min_dd = float(dd.min())
    for i in range(5):
        y = dd_y1 - int((dd_y1 - dd_y0) * i / 4)
        value = min_dd * (1 - i / 4)
        draw.line((x0, y, x1, y), fill=(238, 241, 245))
        draw_text(draw, (42, y - 10), pct(value), 15, fill=(95, 100, 110))
    pts = []
    for i, value in enumerate(dd.values):
        x = x0 + int((x1 - x0) * i / (len(dd) - 1))
        y = dd_y1 - int((dd_y1 - dd_y0) * (float(value) - min_dd) / (0 - min_dd))
        pts.append((x, y))
    draw.line(pts, fill="#C43C39", width=3)
    draw_text(draw, (peak_x + 8, dd_y0 + 10), f"Max-DD window: {meta['peak_date']} -> {meta['trough_date']}", 17, fill=(90, 65, 30), bold=True)

    draw_text(draw, (x0, y1 + 18), str(dates[0].date()), 15, fill=(95, 100, 110))
    draw_text(draw, (x1 - 95, y1 + 18), str(dates[-1].date()), 15, fill=(95, 100, 110))
    img.save(out_path)


def draw_mechanism_summary(summary: pd.DataFrame, exposure_summary: pd.DataFrame, out_path: Path) -> None:
    width, height = 1500, 900
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (70, 28), "机制摘要：相关性压缩与现金空仓", 30, bold=True)
    draw_text(draw, (70, 64), "解释 12 币池为何在较低暴露下仍有较好的风险效率。", 18, fill=(90, 95, 105))

    corr_labels = ["Raw return", "Strategy return", "Position corr", "Position Jaccard"]
    corr_metrics = ["raw_return_corr", "strategy_return_corr", "position_corr", "position_jaccard"]
    corr_values = [float(summary.loc[summary["metric"] == m, "mean"].iloc[0]) for m in corr_metrics]

    x0, y0, x1, y1 = 110, 140, 690, 760
    draw_text(draw, (x0, y0 - 38), "Average pairwise relation", 23, bold=True)
    draw.rectangle((x0, y0, x1, y1), outline=(220, 224, 230))
    for i in range(6):
        y = y1 - int((y1 - y0) * i / 5)
        draw.line((x0, y, x1, y), fill=(238, 241, 245))
        draw_text(draw, (55, y - 10), f"{i/5:.1f}", 15, fill=(95, 100, 110))
    bar_w = 80
    for i, (label, value) in enumerate(zip(corr_labels, corr_values)):
        x = x0 + 60 + i * 125
        bar_h = int((y1 - y0) * value)
        draw.rectangle((x, y1 - bar_h, x + bar_w, y1), fill=["#255C99", "#D95F02", "#2E7D32", "#6B7280"][i])
        draw_text(draw, (x + 8, y1 - bar_h - 26), f"{value:.2f}", 17, fill=(45, 50, 60), bold=True)
        draw_text(draw, (x - 20, y1 + 14), label, 13, fill=(55, 60, 70), bold=True)

    values = dict(zip(exposure_summary["metric"], exposure_summary["value"]))
    cards = [
        ("Avg active", f"{values['avg_active_symbols']:.2f}", "平均每日持仓币数"),
        ("Median active", f"{values['median_active_symbols']:.0f}", "中位数持仓币数"),
        ("DD active", f"{values['dd_avg_active_symbols']:.2f}", "最大回撤期平均持仓"),
        ("Port vol", pct(values["portfolio_vol"]), "12池组合波动"),
        ("Avg sleeve vol", pct(values["avg_individual_strategy_vol"]), "单币策略平均波动"),
        ("Max DD", pct(values["max_drawdown"]), "组合最大回撤"),
    ]
    cx0, cy0 = 790, 150
    card_w, card_h = 280, 150
    for i, (title, value, desc) in enumerate(cards):
        x = cx0 + (i % 2) * (card_w + 34)
        y = cy0 + (i // 2) * (card_h + 35)
        draw.rectangle((x, y, x + card_w, y + card_h), fill=(248, 250, 252), outline=(225, 230, 236))
        draw_text(draw, (x + 22, y + 20), title, 18, fill=(70, 75, 85), bold=True)
        draw_text(draw, (x + 22, y + 55), value, 32, fill=(37, 92, 153), bold=True)
        draw_text(draw, (x + 22, y + 105), desc, 16, fill=(100, 105, 115))
    img.save(out_path)


def make_report(context: dict, data: dict) -> str:
    summary = data["summary"]
    exposure_summary = data["exposure_summary"]
    meta = data["meta"]
    values = dict(zip(exposure_summary["metric"], exposure_summary["value"]))
    corr_rows = [
        f"| {r.metric} | {num(r.mean)} | {num(r.median)} | {num(r.min)} | {num(r.max)} |"
        for r in summary.itertuples()
    ]
    dd_contrib = data["dd_contribution"].sort_values("drawdown_contribution")
    dd_rows = [
        f"| {r.symbol} | {pct(r.drawdown_contribution)} |"
        for r in dd_contrib.itertuples()
    ]
    raw_mean = float(summary.loc[summary["metric"] == "raw_return_corr", "mean"].iloc[0])
    strategy_mean = float(summary.loc[summary["metric"] == "strategy_return_corr", "mean"].iloc[0])
    position_mean = float(summary.loc[summary["metric"] == "position_corr", "mean"].iloc[0])
    jaccard_mean = float(summary.loc[summary["metric"] == "position_jaccard", "mean"].iloc[0])
    compression = 1.0 - strategy_mean / raw_mean if raw_mean else np.nan

    return f"""# 右侧现货动量：12 币池机制解释验证

生成时间：{pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")}

## 1. 验证目的

本报告不改变策略、不改变币池，只解释为什么 12 coin pool 的风险效率更好。

核心判断不是“主流币互相不相关”，而是：

> 主流币原始收益仍然正相关，但右侧动量信号使不同币的入场、持仓和退出不同步，从而降低策略收益的有效相关性。

样本窗口：{context["common_start"]} 至 {context["common_end"]}。

12 币池：{", ".join(meta["symbols"])}。

## 2. 相关性压缩

![原始相关性 vs 策略相关性]({md_img(OUTPUT_DIR / "01_correlation_compression.png")})

| Metric | Mean | Median | Min | Max |
|---|---:|---:|---:|---:|
{chr(10).join(corr_rows)}

解释：

- 原始现货日收益平均相关性为 {num(raw_mean)}，说明它们不是非相关资产。
- 经过右侧动量信号后，策略 sleeve 日收益平均相关性降到 {num(strategy_mean)}。
- 相关性压缩约 {pct(compression)}。

这说明 12 币池的风险效率不是来自“币本身完全独立”，而是来自“趋势信号让收益实现路径不同步”。

## 3. 持仓不同步

![持仓不同步]({md_img(OUTPUT_DIR / "02_position_overlap.png")})

持仓状态平均相关为 {num(position_mean)}，平均 Jaccard 重叠为 {num(jaccard_mean)}。

含义：

- 很多币会同处于 crypto 大 beta 环境，但不会每天同时触发右侧入场。
- 组合不是长期满仓 12 个币，而是持有当下进入趋势状态的少数币。

## 4. 每日持仓数量与回撤

![每日持仓数量与回撤]({md_img(OUTPUT_DIR / "03_active_count_drawdown.png")})

![机制摘要]({md_img(OUTPUT_DIR / "04_mechanism_summary.png")})

关键数值：

- 平均每日持仓币数：{num(values["avg_active_symbols"])}。
- 持仓币数中位数：{num(values["median_active_symbols"])}。
- 90% 分位持仓币数：{num(values["p90_active_symbols"])}。
- 最大回撤区间：{meta["peak_date"]} 至 {meta["trough_date"]}。
- 最大回撤期平均持仓币数：{num(values["dd_avg_active_symbols"])}。
- 最大回撤：{pct(values["max_drawdown"])}。

这说明该组合并不是“多币长期持有”，而是“多 sleeve 候选 + 现金空仓”。熊市或震荡期大部分 sleeve 会自动退出。

## 5. 最大回撤区间贡献

| Symbol | Drawdown contribution |
|---|---:|
{chr(10).join(dd_rows)}

解释：

- 最大回撤仍然来自多个币的共同拖累，因此不能把 12 币池解释为抗系统性风险。
- 但最大回撤期平均只有 {num(values["dd_avg_active_symbols"])} 个币有仓位，说明退出机制确实降低了同时暴露。

## 6. 机制结论

可以这样解释当前策略：

1. 主流币之间仍然有明显正相关，不能依赖“天然分散”。
2. 右侧动量信号把原始相关性 {num(raw_mean)} 压到策略收益相关性 {num(strategy_mean)}。
3. 平均每日只持有 {num(values["avg_active_symbols"])} 个币，中位数只有 {num(values["median_active_symbols"])} 个。
4. 最大回撤期平均持仓进一步降到 {num(values["dd_avg_active_symbols"])} 个。

因此 12 coin pool 的风险效率更好，主要来自：

- 趋势轮动；
- 持仓不同步；
- 熊市自动现金化；
- 单币错误被 sleeve 结构稀释。

这只是解释证据，不是新的交易规则。下一步仍然应该做 walk-forward / 时间切片验证，而不是根据这些解释继续加过滤器。
"""


def main() -> None:
    baseline = load_baseline_module()
    _, _, _, _, _, backtests, context = baseline.build_results(refresh=False)
    symbols = [s for s in context["selected_symbols"] if s not in {"LTCUSDT", "AAVEUSDT"}]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    data = build_mechanism_data(backtests, symbols)

    data["raw_corr"].to_csv(OUTPUT_DIR / "raw_return_corr.csv", encoding="utf-8-sig")
    data["strategy_corr"].to_csv(OUTPUT_DIR / "strategy_return_corr.csv", encoding="utf-8-sig")
    data["position_corr"].to_csv(OUTPUT_DIR / "position_corr.csv", encoding="utf-8-sig")
    data["position_jaccard"].to_csv(OUTPUT_DIR / "position_jaccard.csv", encoding="utf-8-sig")
    data["active_df"].to_csv(OUTPUT_DIR / "active_count_drawdown.csv", encoding="utf-8-sig")
    data["dd_contribution"].to_csv(OUTPUT_DIR / "drawdown_contribution.csv", index=False, encoding="utf-8-sig")
    data["summary"].to_csv(OUTPUT_DIR / "mechanism_correlation_summary.csv", index=False, encoding="utf-8-sig")
    data["exposure_summary"].to_csv(OUTPUT_DIR / "mechanism_exposure_summary.csv", index=False, encoding="utf-8-sig")

    draw_correlation_compression(data["raw_corr"], data["strategy_corr"], data["summary"], OUTPUT_DIR / "01_correlation_compression.png")
    draw_position_overlap(data["position_corr"], data["position_jaccard"], data["summary"], OUTPUT_DIR / "02_position_overlap.png")
    draw_active_count(data["active_df"], data["meta"], OUTPUT_DIR / "03_active_count_drawdown.png")
    draw_mechanism_summary(data["summary"], data["exposure_summary"], OUTPUT_DIR / "04_mechanism_summary.png")

    REPORT_PATH.write_text(make_report(context, data), encoding="utf-8-sig")

    print(data["summary"].to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print("\nExposure summary")
    print(data["exposure_summary"].to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print("\nSaved outputs to:", OUTPUT_DIR)
    print("Saved report to:", REPORT_PATH)


if __name__ == "__main__":
    main()
