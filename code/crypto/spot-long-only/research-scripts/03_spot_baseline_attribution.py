from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
BASELINE_SCRIPT = ROOT / "02_spot_universe_baseline.py"
OUTPUT_DIR = ROOT / "outputs_attribution"


def load_baseline_module():
    spec = importlib.util.spec_from_file_location("spot_long_only_baseline", BASELINE_SCRIPT)
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


def mix_color(base: tuple[int, int, int], strength: float) -> tuple[int, int, int]:
    strength = max(0.0, min(1.0, strength))
    return tuple(int(255 * (1.0 - strength) + c * strength) for c in base)


def build_panels(backtests: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    gross_panel = pd.concat([bt["GrossReturn"].rename(symbol) for symbol, bt in backtests.items()], axis=1).fillna(0.0)
    net_panel = pd.concat([bt["NetReturn"].rename(symbol) for symbol, bt in backtests.items()], axis=1).fillna(0.0)
    exposure_panel = pd.concat([bt["Exposure"].rename(symbol) for symbol, bt in backtests.items()], axis=1).fillna(0.0)
    return gross_panel, net_panel, exposure_panel


def wealth_contribution(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    portfolio_return = panel.mean(axis=1)
    portfolio_equity = (1.0 + portfolio_return).cumprod()
    prev_equity = portfolio_equity.shift(1).fillna(1.0)
    daily_contribution = panel.div(len(panel.columns)).mul(prev_equity, axis=0)
    total_contribution = daily_contribution.sum()
    return daily_contribution, portfolio_return, portfolio_equity


def annual_contribution(panel: pd.DataFrame, portfolio_equity: pd.Series) -> pd.DataFrame:
    rows = []
    prev_equity = portfolio_equity.shift(1).fillna(1.0)
    for year, idx in panel.groupby(panel.index.year).groups.items():
        seg = panel.loc[idx]
        if seg.empty:
            continue
        start_equity = float(prev_equity.loc[seg.index[0]])
        if not math.isfinite(start_equity) or start_equity <= 0:
            start_equity = 1.0
        scaled_prev = prev_equity.loc[seg.index] / start_equity
        daily = seg.div(len(panel.columns)).mul(scaled_prev, axis=0)
        annual_return = float(portfolio_equity.loc[seg.index[-1]] / start_equity - 1.0)
        for symbol, value in daily.sum().items():
            rows.append(
                dict(
                    year=int(year),
                    symbol=symbol,
                    annual_return_contribution=float(value),
                    annual_return=annual_return,
                    contribution_share=float(value / annual_return) if abs(annual_return) > 1e-12 else np.nan,
                )
            )
    return pd.DataFrame(rows)


def max_drawdown_contribution(panel: pd.DataFrame, portfolio_equity: pd.Series) -> tuple[pd.DataFrame, dict]:
    drawdown = portfolio_equity / portfolio_equity.cummax() - 1.0
    trough_date = drawdown.idxmin()
    peak_date = portfolio_equity.loc[:trough_date].idxmax()
    seg = panel.loc[(panel.index > peak_date) & (panel.index <= trough_date)]
    if seg.empty:
        rows = [dict(symbol=symbol, drawdown_contribution=0.0) for symbol in panel.columns]
    else:
        prev_equity = portfolio_equity.shift(1).loc[seg.index].fillna(float(portfolio_equity.loc[peak_date]))
        scaled_prev = prev_equity / float(portfolio_equity.loc[peak_date])
        daily = seg.div(len(panel.columns)).mul(scaled_prev, axis=0)
        rows = [dict(symbol=symbol, drawdown_contribution=float(value)) for symbol, value in daily.sum().items()]
    meta = dict(
        peak_date=peak_date.date().isoformat(),
        trough_date=trough_date.date().isoformat(),
        max_drawdown=float(portfolio_equity.loc[trough_date] / portfolio_equity.loc[peak_date] - 1.0),
    )
    return pd.DataFrame(rows), meta


def symbol_attribution(
    baseline,
    backtests: dict[str, pd.DataFrame],
    gross_panel: pd.DataFrame,
    exposure_panel: pd.DataFrame,
    daily_contribution: pd.DataFrame,
    portfolio_equity: pd.Series,
) -> pd.DataFrame:
    total_profit = float(portfolio_equity.iloc[-1] - 1.0)
    rows = []
    for symbol, bt in backtests.items():
        m = baseline.metrics(bt["GrossReturn"], bt["GrossEquity"])
        t = baseline.trade_stats(bt)
        contribution = float(daily_contribution[symbol].sum())
        rows.append(
            dict(
                symbol=symbol,
                wealth_contribution_x=contribution,
                contribution_share=contribution / total_profit if abs(total_profit) > 1e-12 else np.nan,
                avg_exposure=float(exposure_panel[symbol].mean()),
                active_days=int((exposure_panel[symbol] > 0).sum()),
                active_day_ratio=float((exposure_panel[symbol] > 0).mean()),
                cagr=m["cagr"],
                sharpe=m["sharpe"],
                mdd=m["mdd"],
                calmar=m["calmar"],
                final_equity=m["final"],
                trades=int(t["trades"]),
                win_rate=t["win_rate"],
                avg_days=t["avg_days"],
            )
        )
    out = pd.DataFrame(rows).sort_values("wealth_contribution_x", ascending=False)
    positive_sum = out.loc[out["wealth_contribution_x"] > 0, "wealth_contribution_x"].sum()
    out["positive_contribution_share"] = np.where(
        positive_sum > 0,
        out["wealth_contribution_x"].clip(lower=0.0) / positive_sum,
        np.nan,
    )
    return out


def group_attribution(symbol_df: pd.DataFrame) -> pd.DataFrame:
    groups = {
        "BTC_ETH": ["BTCUSDT", "ETHUSDT"],
        "BTC_ETH_BNB_SOL": ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"],
        "NON_CORE_REST": [s for s in symbol_df["symbol"] if s not in {"BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"}],
    }
    total = float(symbol_df["wealth_contribution_x"].sum())
    rows = []
    for name, symbols in groups.items():
        seg = symbol_df[symbol_df["symbol"].isin(symbols)]
        contribution = float(seg["wealth_contribution_x"].sum())
        rows.append(
            dict(
                group=name,
                symbols=", ".join(symbols),
                wealth_contribution_x=contribution,
                contribution_share=contribution / total if abs(total) > 1e-12 else np.nan,
            )
        )
    return pd.DataFrame(rows)


def concentration_summary(symbol_df: pd.DataFrame, portfolio_equity: pd.Series, net_equity: pd.Series, dd_meta: dict) -> pd.DataFrame:
    s = symbol_df.sort_values("wealth_contribution_x", ascending=False)
    total = float(symbol_df["wealth_contribution_x"].sum())
    positives = s.loc[s["wealth_contribution_x"] > 0, "wealth_contribution_x"]
    positive_shares = positives / positives.sum() if positives.sum() > 0 else positives
    effective_positive_count = float(1.0 / positive_shares.pow(2).sum()) if len(positive_shares) else np.nan
    rows = [
        ("gross_final_equity", float(portfolio_equity.iloc[-1])),
        ("net_final_equity", float(net_equity.iloc[-1])),
        ("gross_profit_x", float(portfolio_equity.iloc[-1] - 1.0)),
        ("net_cost_drag_x", float(net_equity.iloc[-1] - portfolio_equity.iloc[-1])),
        ("top1_share_of_profit", float(s.head(1)["wealth_contribution_x"].sum() / total)),
        ("top3_share_of_profit", float(s.head(3)["wealth_contribution_x"].sum() / total)),
        ("top5_share_of_profit", float(s.head(5)["wealth_contribution_x"].sum() / total)),
        ("top6_share_of_profit", float(s.head(6)["wealth_contribution_x"].sum() / total)),
        ("effective_positive_count", effective_positive_count),
        ("negative_symbol_count", float((symbol_df["wealth_contribution_x"] < 0).sum())),
        ("max_drawdown", float(dd_meta["max_drawdown"])),
    ]
    return pd.DataFrame(rows, columns=["metric", "value"])


def draw_total_contribution(symbol_df: pd.DataFrame, out_path: Path) -> None:
    width, height = 1650, 980
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (70, 28), "单币最终财富贡献归因", 30, bold=True)
    draw_text(draw, (70, 64), "口径：每日等权 sleeve 收益乘以前一日组合权益；所有贡献相加等于组合最终盈利。", 18, fill=(90, 95, 105))

    df = symbol_df.sort_values("wealth_contribution_x", ascending=True).reset_index(drop=True)
    values = df["wealth_contribution_x"].astype(float).tolist()
    min_v, max_v = min(values + [0.0]), max(values + [0.0])
    span = max_v - min_v if max_v > min_v else 1.0
    x0, x1 = 330, width - 185
    y0, y1 = 125, height - 105
    zero_x = x0 + int((0.0 - min_v) / span * (x1 - x0))
    draw.line((zero_x, y0 - 20, zero_x, y1 + 10), fill=(140, 145, 155), width=2)

    step = (y1 - y0) / len(df)
    bar_h = max(24, int(step * 0.58))
    for i, row in enumerate(df.itertuples()):
        y = int(y0 + i * step)
        value = float(row.wealth_contribution_x)
        end_x = x0 + int((value - min_v) / span * (x1 - x0))
        color = "#255C99" if value >= 0 else "#C43C39"
        rect = (min(zero_x, end_x), y, max(zero_x, end_x), y + bar_h)
        draw.rectangle(rect, fill=color)
        draw_text(draw, (70, y - 1), row.symbol.replace("USDT", ""), 18, bold=True)
        label_x = end_x + 12 if value >= 0 else end_x - 145
        draw_text(draw, (label_x, y - 1), f"{value:+.2f}x / {pct(float(row.contribution_share))}", 16, fill=(45, 50, 60))

    top3 = symbol_df.sort_values("wealth_contribution_x", ascending=False).head(3)
    draw_text(draw, (70, height - 64), f"Top3: {', '.join(top3['symbol'].str.replace('USDT', '').tolist())}；合计贡献 {pct(float(top3['contribution_share'].sum()))}", 18, fill=(70, 75, 85), bold=True)
    img.save(out_path)


def draw_yearly_heatmap(year_df: pd.DataFrame, symbol_order: list[str], out_path: Path) -> None:
    width, height = 1750, 920
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (70, 28), "年度收益贡献热力图", 30, bold=True)
    draw_text(draw, (70, 64), "每个格子表示该币对当年组合收益的贡献百分点；行内合计等于当年组合收益。", 18, fill=(90, 95, 105))

    years = sorted(year_df["year"].unique())
    pivot = year_df.pivot(index="year", columns="symbol", values="annual_return_contribution").reindex(index=years, columns=symbol_order).fillna(0.0)
    annual = year_df.groupby("year")["annual_return"].first().reindex(years)
    max_abs = float(np.nanmax(np.abs(pivot.values))) if len(pivot.values) else 1.0
    max_abs = max(max_abs, 1e-9)

    x0, y0 = 155, 135
    cell_w, cell_h = 103, 78
    for j, symbol in enumerate(symbol_order):
        draw_text(draw, (x0 + j * cell_w + 12, y0 - 32), symbol.replace("USDT", ""), 14, fill=(55, 60, 70), bold=True)
    draw_text(draw, (x0 + len(symbol_order) * cell_w + 25, y0 - 32), "Year", 15, fill=(55, 60, 70), bold=True)

    for i, year in enumerate(years):
        y = y0 + i * cell_h
        draw_text(draw, (70, y + 24), str(year), 18, bold=True)
        for j, symbol in enumerate(symbol_order):
            x = x0 + j * cell_w
            value = float(pivot.loc[year, symbol])
            strength = min(1.0, abs(value) / max_abs)
            color = mix_color((37, 92, 153), strength) if value >= 0 else mix_color((196, 60, 57), strength)
            draw.rectangle((x, y, x + cell_w - 6, y + cell_h - 8), fill=color, outline=(235, 238, 242))
            draw_text(draw, (x + 10, y + 24), f"{value:+.1%}", 13, fill=(35, 40, 45))
        draw_text(draw, (x0 + len(symbol_order) * cell_w + 25, y + 24), pct(float(annual.loc[year])), 17, fill=(45, 50, 60), bold=True)

    draw_text(draw, (70, height - 58), "蓝色为正贡献，红色为负贡献；颜色深浅只表示绝对贡献大小。", 17, fill=(90, 95, 105))
    img.save(out_path)


def draw_drawdown_contribution(drawdown_df: pd.DataFrame, meta: dict, out_path: Path) -> None:
    width, height = 1650, 900
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (70, 28), "最大回撤区间归因", 30, bold=True)
    draw_text(draw, (70, 64), f"区间：{meta['peak_date']} -> {meta['trough_date']}；组合回撤 {pct(float(meta['max_drawdown']))}", 18, fill=(90, 95, 105))

    df = drawdown_df.sort_values("drawdown_contribution", ascending=False).reset_index(drop=True)
    values = df["drawdown_contribution"].astype(float).tolist()
    min_v, max_v = min(values + [0.0]), max(values + [0.0])
    span = max_v - min_v if max_v > min_v else 1.0
    x0, x1 = 330, width - 185
    y0, y1 = 125, height - 95
    zero_x = x0 + int((0.0 - min_v) / span * (x1 - x0))
    draw.line((zero_x, y0 - 20, zero_x, y1 + 10), fill=(140, 145, 155), width=2)
    step = (y1 - y0) / len(df)
    bar_h = max(24, int(step * 0.58))
    for i, row in enumerate(df.itertuples()):
        y = int(y0 + i * step)
        value = float(row.drawdown_contribution)
        end_x = x0 + int((value - min_v) / span * (x1 - x0))
        color = "#2E7D32" if value >= 0 else "#C43C39"
        draw.rectangle((min(zero_x, end_x), y, max(zero_x, end_x), y + bar_h), fill=color)
        draw_text(draw, (70, y - 1), row.symbol.replace("USDT", ""), 18, bold=True)
        label_x = end_x + 12 if value >= 0 else end_x - 108
        draw_text(draw, (label_x, y - 1), f"{value:+.2%}", 16, fill=(45, 50, 60))
    img.save(out_path)


def make_report(
    context: dict,
    symbol_df: pd.DataFrame,
    group_df: pd.DataFrame,
    year_df: pd.DataFrame,
    drawdown_df: pd.DataFrame,
    summary_df: pd.DataFrame,
    dd_meta: dict,
) -> str:
    summary = dict(zip(summary_df["metric"], summary_df["value"]))
    top = symbol_df.sort_values("wealth_contribution_x", ascending=False)
    top_rows = [
        f"| {r.symbol} | {num(r.wealth_contribution_x)}x | {pct(r.contribution_share)} | {pct(r.avg_exposure)} | {pct(r.cagr)} | {num(r.calmar)} | {int(r.trades)} |"
        for r in top.itertuples()
    ]
    group_rows = [
        f"| {r.group} | {num(r.wealth_contribution_x)}x | {pct(r.contribution_share)} | {r.symbols} |"
        for r in group_df.itertuples()
    ]
    year_lines = []
    for year, seg in year_df.groupby("year"):
        seg = seg.sort_values("annual_return_contribution", ascending=False)
        leaders = ", ".join(f"{r.symbol.replace('USDT', '')} {pct(r.annual_return_contribution)}" for r in seg.head(3).itertuples())
        laggards = ", ".join(f"{r.symbol.replace('USDT', '')} {pct(r.annual_return_contribution)}" for r in seg.tail(2).itertuples())
        annual_return = float(seg["annual_return"].iloc[0])
        year_lines.append(f"- {int(year)}：组合 {pct(annual_return)}；贡献靠前：{leaders}；低贡献/拖累：{laggards}。")
    dd_rows = [
        f"| {r.symbol} | {pct(r.drawdown_contribution)} |"
        for r in drawdown_df.sort_values("drawdown_contribution").itertuples()
    ]

    top3_symbols = ", ".join(top.head(3)["symbol"].str.replace("USDT", "").tolist())
    negative_symbols = ", ".join(top.loc[top["wealth_contribution_x"] < 0, "symbol"].str.replace("USDT", "").tolist())
    negative_text = negative_symbols if negative_symbols else "无"

    return f"""# 右侧现货 long-only：B baseline 归因报告

生成时间：{pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")}

## 1. 归因口径

本报告只做归因，不改参数，不新增过滤器。

- Universe：5 年历史 + 流动性筛选后的现货主流币池。
- 策略：20 日突破 + EMA200 + close-based 3ATR trailing exit。
- 组合：每个币一个 sleeve，组合层固定等权。
- 归因：每日组合收益为 `mean(symbol_return)`；每日财富贡献为 `前一日组合权益 * symbol_return / N`。
- 这个口径下，所有单币贡献相加，严格等于组合最终盈利。

## 2. 组合层结果

- 起止区间：{context["common_start"]} 至 {context["common_end"]}。
- 入选标的：{", ".join(context["selected_symbols"])}。
- Gross final equity：{num(summary["gross_final_equity"])}x。
- Net final equity：{num(summary["net_final_equity"])}x。
- Gross profit：{num(summary["gross_profit_x"])}x。
- Net cost drag：{num(summary["net_cost_drag_x"])}x。
- 最大回撤：{pct(summary["max_drawdown"])}，区间 {dd_meta["peak_date"]} 至 {dd_meta["trough_date"]}。

## 3. 单币最终财富贡献

![单币最终财富贡献]({md_img(OUTPUT_DIR / "01_total_contribution.png")})

| Symbol | Wealth contribution | Share of gross profit | Avg exposure | CAGR | Calmar | Trades |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(top_rows)}

集中度：

- Top1 贡献占比：{pct(summary["top1_share_of_profit"])}。
- Top3 贡献占比：{pct(summary["top3_share_of_profit"])}，主要是 {top3_symbols}。
- Top5 贡献占比：{pct(summary["top5_share_of_profit"])}。
- 正贡献有效标的数：{num(summary["effective_positive_count"])}。
- 负贡献标的：{negative_text}。

## 4. 核心币与非核心币

| Group | Wealth contribution | Share | Symbols |
|---|---:|---:|---|
{chr(10).join(group_rows)}

解释：

- BTC/ETH 不是本策略收益的主要来源，只贡献约 {pct(float(group_df.loc[group_df["group"] == "BTC_ETH", "contribution_share"].iloc[0]))}。
- BTC/ETH/BNB/SOL 合计约 {pct(float(group_df.loc[group_df["group"] == "BTC_ETH_BNB_SOL", "contribution_share"].iloc[0]))}。
- 其余主流 alt 合计贡献更高，因此这个策略本质上不是纯 BTC/ETH trend sleeve，而是主流 alt right-tail capture。

## 5. 年度贡献

![年度收益贡献热力图]({md_img(OUTPUT_DIR / "02_yearly_contribution_heatmap.png")})

{chr(10).join(year_lines)}

## 6. 最大回撤归因

![最大回撤归因]({md_img(OUTPUT_DIR / "03_drawdown_contribution.png")})

| Symbol | Max-DD contribution |
|---|---:|
{chr(10).join(dd_rows)}

## 7. 初步判断

当前归因没有显示“一两个币撑起全部收益”的危险信号：Top3 约 {pct(summary["top3_share_of_profit"])}，正贡献有效标的数约 {num(summary["effective_positive_count"])}。这比单点参数胜出更健康。

但它也暴露了一个更重要的结构事实：收益主要来自主流 alt 的趋势扩散，而不是 BTC/ETH 本身。如果未来要上实盘，组合设计应明确承认这一点：

1. BTC/ETH 可以是稳定性锚，但不是收益主引擎。
2. alt 池筛选必须比入场参数更重要，尤其要固定历史、流动性和交易所现货可交易性规则。
3. 下一步应做分阶段归因和滚动样本验证，确认 alt 扩散收益不是 2021 单周期幻觉。
"""


def main() -> None:
    baseline = load_baseline_module()
    _, _, _, _, _, backtests, context = baseline.build_results(refresh=False)

    gross_panel, net_panel, exposure_panel = build_panels(backtests)
    daily_contribution, gross_return, gross_equity = wealth_contribution(gross_panel)
    _, net_return, net_equity = wealth_contribution(net_panel)

    symbol_df = symbol_attribution(baseline, backtests, gross_panel, exposure_panel, daily_contribution, gross_equity)
    year_df = annual_contribution(gross_panel, gross_equity)
    drawdown_df, dd_meta = max_drawdown_contribution(gross_panel, gross_equity)
    group_df = group_attribution(symbol_df)
    summary_df = concentration_summary(symbol_df, gross_equity, net_equity, dd_meta)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    daily_contribution.to_csv(OUTPUT_DIR / "attribution_daily_symbol_contribution.csv", encoding="utf-8-sig")
    pd.DataFrame(
        {
            "gross_return": gross_return,
            "gross_equity": gross_equity,
            "net_return": net_return,
            "net_equity": net_equity,
        }
    ).to_csv(OUTPUT_DIR / "attribution_portfolio_equity.csv", encoding="utf-8-sig")
    symbol_df.to_csv(OUTPUT_DIR / "attribution_symbol.csv", index=False, encoding="utf-8-sig")
    year_df.to_csv(OUTPUT_DIR / "attribution_year_symbol.csv", index=False, encoding="utf-8-sig")
    drawdown_df.to_csv(OUTPUT_DIR / "attribution_drawdown.csv", index=False, encoding="utf-8-sig")
    group_df.to_csv(OUTPUT_DIR / "attribution_group.csv", index=False, encoding="utf-8-sig")
    summary_df.to_csv(OUTPUT_DIR / "attribution_summary.csv", index=False, encoding="utf-8-sig")

    symbol_order = symbol_df.sort_values("wealth_contribution_x", ascending=False)["symbol"].tolist()
    draw_total_contribution(symbol_df, OUTPUT_DIR / "01_total_contribution.png")
    draw_yearly_heatmap(year_df, symbol_order, OUTPUT_DIR / "02_yearly_contribution_heatmap.png")
    draw_drawdown_contribution(drawdown_df, dd_meta, OUTPUT_DIR / "03_drawdown_contribution.png")

    (ROOT / "03_spot_baseline_attribution_report.md").write_text(
        make_report(context, symbol_df, group_df, year_df, drawdown_df, summary_df, dd_meta),
        encoding="utf-8-sig",
    )

    print(symbol_df[["symbol", "wealth_contribution_x", "contribution_share", "avg_exposure", "cagr", "calmar"]].to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print("\nSummary")
    print(summary_df.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print(f"\nSaved outputs to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
