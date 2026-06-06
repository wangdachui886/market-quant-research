from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
BASELINE_SCRIPT = ROOT / "02_spot_universe_baseline.py"
OUTPUT_DIR = ROOT / "outputs_pool_compare"
REPORT_PATH = ROOT / "04_pool_comparison_report.md"

POOL_DEFINITIONS = {
    "BTC_ONLY": ["BTCUSDT"],
    "CORE4_BTC_ETH_SOL_BNB": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"],
}

POOL_LABELS = {
    "BTC_ONLY": "BTC only",
    "CORE4_BTC_ETH_SOL_BNB": "BTC/ETH/SOL/BNB",
    "POOL12_DROP_LTC_AAVE": "12 coin pool",
}

PERIODS = {
    "FULL": (None, None, "2020-2026"),
    "2020": ("2020-01-01", "2020-12-31", "2020"),
    "2021": ("2021-01-01", "2021-12-31", "2021"),
    "POST_2021": ("2022-01-01", None, "2022-2026"),
}


def load_baseline_module():
    spec = importlib.util.spec_from_file_location("spot_pool_compare_baseline", BASELINE_SCRIPT)
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
    pools = dict(POOL_DEFINITIONS)
    pools["POOL12_DROP_LTC_AAVE"] = [s for s in selected_symbols if s not in {"LTCUSDT", "AAVEUSDT"}]
    return pools


def portfolio_panel(backtests: dict[str, pd.DataFrame], symbols: list[str], column: str) -> pd.DataFrame:
    return pd.concat([backtests[s][column].rename(s) for s in symbols], axis=1).fillna(0.0)


def slice_period(series: pd.Series, start: str | None, end: str | None) -> pd.Series:
    out = series.copy()
    if start:
        out = out.loc[pd.Timestamp(start) :]
    if end:
        out = out.loc[: pd.Timestamp(end)]
    return out


def compute_pool_outputs(baseline, backtests: dict[str, pd.DataFrame], pools: dict[str, list[str]]):
    metrics_rows, yearly_rows, membership_rows = [], [], []
    equity_map, drawdown_map = {}, {}

    for pool, symbols in pools.items():
        for symbol in symbols:
            membership_rows.append(dict(pool=pool, label=POOL_LABELS[pool], symbol=symbol))

        for mode, column in [("gross", "GrossReturn"), ("net_cost_model", "NetReturn")]:
            panel = portfolio_panel(backtests, symbols, column)
            full_return = panel.mean(axis=1)
            full_equity = (1.0 + full_return).cumprod()
            if mode == "gross":
                equity_map[pool] = full_equity
                drawdown_map[pool] = full_equity / full_equity.cummax() - 1.0

            exposure_panel = portfolio_panel(backtests, symbols, "Exposure")
            base_metrics = baseline.metrics(full_return, full_equity)
            metrics_rows.append(
                dict(
                    pool=pool,
                    label=POOL_LABELS[pool],
                    period="FULL",
                    period_label=PERIODS["FULL"][2],
                    mode=mode,
                    n_symbols=len(symbols),
                    avg_exposure=float(exposure_panel.abs().mean(axis=1).mean()),
                    symbols=", ".join(symbols),
                    **base_metrics,
                )
            )

            if mode == "gross":
                for period, (start, end, period_label) in PERIODS.items():
                    ret = slice_period(full_return, start, end)
                    if len(ret) < 60:
                        continue
                    metrics_rows.append(
                        dict(
                            pool=pool,
                            label=POOL_LABELS[pool],
                            period=period,
                            period_label=period_label,
                            mode="gross_period",
                            n_symbols=len(symbols),
                            avg_exposure=float(slice_period(exposure_panel.abs().mean(axis=1), start, end).mean()),
                            symbols=", ".join(symbols),
                            **baseline.metrics(ret),
                        )
                    )

                for year, ret in full_return.groupby(full_return.index.year):
                    if len(ret) < 60:
                        continue
                    yearly_rows.append(
                        dict(
                            pool=pool,
                            label=POOL_LABELS[pool],
                            year=int(year),
                            **baseline.metrics(ret),
                        )
                    )

    return (
        pd.DataFrame(metrics_rows),
        pd.DataFrame(yearly_rows),
        pd.DataFrame(membership_rows),
        equity_map,
        drawdown_map,
    )


def draw_equity_compare(equity_map: dict[str, pd.Series], drawdown_map: dict[str, pd.Series], out_path: Path) -> None:
    width, height = 1650, 1000
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (76, 28), "右侧现货动量：池子对比", 30, bold=True)
    draw_text(draw, (76, 64), "同一套 B baseline：BTC 单币 vs 核心4币 vs 删除 LTC/AAVE 后的12币池。", 18, fill=(90, 95, 105))

    colors = {"BTC_ONLY": "#255C99", "CORE4_BTC_ETH_SOL_BNB": "#2E7D32", "POOL12_DROP_LTC_AAVE": "#D95F02"}
    labels = {k: POOL_LABELS[k] for k in equity_map}
    aligned = pd.concat(equity_map, axis=1).dropna()
    log_values = np.log(aligned.clip(lower=1e-8))
    x0, y0, x1, y1 = 110, 125, width - 70, 570
    dd_y0, dd_y1 = 670, height - 90

    ymin, ymax = float(log_values.min().min()), float(log_values.max().max())
    pad = max((ymax - ymin) * 0.08, 0.01)
    ymin -= pad
    ymax += pad
    draw.rectangle((x0, y0, x1, y1), outline=(215, 220, 225))
    for i in range(6):
        y = y1 - int((y1 - y0) * i / 5)
        value = np.exp(ymin + (ymax - ymin) * i / 5)
        draw.line((x0, y, x1, y), fill=(236, 239, 243))
        draw_text(draw, (35, y - 10), f"{value:.1f}x", 15, fill=(95, 100, 110))

    for pool in aligned.columns:
        pts = []
        for i, value in enumerate(log_values[pool].values):
            x = x0 + int((x1 - x0) * i / (len(aligned) - 1))
            y = y1 - int((y1 - y0) * (float(value) - ymin) / (ymax - ymin))
            pts.append((x, y))
        draw.line(pts, fill=colors[pool], width=4)

    for i, pool in enumerate(aligned.columns):
        lx = x0 + 30 + i * 330
        draw.rectangle((lx, 605, lx + 28, 622), fill=colors[pool])
        draw_text(draw, (lx + 38, 600), labels[pool], 18, fill=(50, 55, 65))

    dd = pd.concat(drawdown_map, axis=1).reindex(aligned.index).dropna()
    min_dd = float(dd.min().min())
    draw_text(draw, (x0, dd_y0 - 42), "组合回撤", 24, bold=True)
    draw.rectangle((x0, dd_y0, x1, dd_y1), outline=(215, 220, 225))
    for i in range(5):
        y = dd_y1 - int((dd_y1 - dd_y0) * i / 4)
        value = min_dd * (1 - i / 4)
        draw.line((x0, y, x1, y), fill=(236, 239, 243))
        draw_text(draw, (35, y - 10), pct(value), 15, fill=(95, 100, 110))
    for pool in dd.columns:
        pts = []
        for i, value in enumerate(dd[pool].values):
            x = x0 + int((x1 - x0) * i / (len(dd) - 1))
            y = dd_y1 - int((dd_y1 - dd_y0) * (float(value) - min_dd) / (0 - min_dd))
            pts.append((x, y))
        draw.line(pts, fill=colors[pool], width=3)
    img.save(out_path)


def draw_metric_bars(metrics_df: pd.DataFrame, out_path: Path) -> None:
    width, height = 1550, 980
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (70, 28), "全样本指标对比", 30, bold=True)
    draw_text(draw, (70, 64), "Gross 口径；net 成本结果在报告表格中列出。", 18, fill=(90, 95, 105))

    df = metrics_df[(metrics_df["period"] == "FULL") & (metrics_df["mode"] == "gross")].copy()
    order = ["BTC_ONLY", "CORE4_BTC_ETH_SOL_BNB", "POOL12_DROP_LTC_AAVE"]
    df = df.set_index("pool").loc[order].reset_index()
    panels = [("CAGR", "cagr", False), ("Sharpe", "sharpe", False), ("MDD", "mdd", True), ("Calmar", "calmar", False)]
    colors = {"BTC_ONLY": "#255C99", "CORE4_BTC_ETH_SOL_BNB": "#2E7D32", "POOL12_DROP_LTC_AAVE": "#D95F02"}
    origins = [(80, 135), (800, 135), (80, 545), (800, 545)]
    panel_w, panel_h = 635, 290

    for (title, col, abs_mode), (ox, oy) in zip(panels, origins):
        draw_text(draw, (ox, oy - 34), title, 23, bold=True)
        draw.rectangle((ox, oy, ox + panel_w, oy + panel_h), outline=(220, 224, 230))
        values = [(abs(float(v)) if abs_mode else float(v)) for v in df[col]]
        max_v = max(values + [1e-9]) * 1.18
        bar_w, gap = 105, 80
        baseline = oy + panel_h - 55
        draw.line((ox + 45, baseline, ox + panel_w - 30, baseline), fill=(190, 195, 205), width=2)
        for i, row in enumerate(df.itertuples()):
            value = abs(float(getattr(row, col))) if abs_mode else float(getattr(row, col))
            bar_h = int((panel_h - 95) * value / max_v)
            x = ox + 70 + i * (bar_w + gap)
            y = baseline - bar_h
            draw.rectangle((x, y, x + bar_w, baseline), fill=colors[row.pool])
            label = f"{value:.2f}" if col in {"sharpe", "calmar"} else pct(value)
            draw_text(draw, (x - 3, y - 28), label, 17, fill=(45, 50, 60), bold=True)
            draw_text(draw, (x - 20, baseline + 12), POOL_LABELS[row.pool], 14, fill=(55, 60, 70), bold=True)
        if abs_mode:
            draw_text(draw, (ox + 45, oy + panel_h - 25), "MDD 用绝对值展示，越低越好。", 14, fill=(100, 105, 115))
    img.save(out_path)


def draw_period_bars(period_df: pd.DataFrame, out_path: Path) -> None:
    width, height = 1650, 900
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (70, 28), "分阶段 CAGR 对比", 30, bold=True)
    draw_text(draw, (70, 64), "核心检查：离开 2021 后，池子是否仍然优于 BTC。", 18, fill=(90, 95, 105))

    df = period_df[period_df["mode"] == "gross_period"].copy()
    df = df[df["period"].isin(["2020", "2021", "POST_2021"])]
    period_order = ["2020", "2021", "POST_2021"]
    pool_order = ["BTC_ONLY", "CORE4_BTC_ETH_SOL_BNB", "POOL12_DROP_LTC_AAVE"]
    colors = {"BTC_ONLY": "#255C99", "CORE4_BTC_ETH_SOL_BNB": "#2E7D32", "POOL12_DROP_LTC_AAVE": "#D95F02"}

    x0, y0, x1, y1 = 95, 135, width - 75, height - 120
    vals = df["cagr"].astype(float).tolist()
    top = max(abs(min(vals + [0])), abs(max(vals + [0]))) * 1.18
    top = max(top, 1e-9)
    zero_y = y0 + int((y1 - y0) * top / (2 * top))
    draw.rectangle((x0, y0, x1, y1), outline=(220, 224, 230))
    draw.line((x0, zero_y, x1, zero_y), fill=(130, 135, 145), width=2)

    group_w = (x1 - x0 - 80) / len(period_order)
    bar_w = 90
    for i, period in enumerate(period_order):
        gx = x0 + 60 + int(i * group_w)
        draw_text(draw, (gx + 55, y1 + 24), PERIODS[period][2], 18, fill=(55, 60, 70), bold=True)
        for j, pool in enumerate(pool_order):
            row = df[(df["period"] == period) & (df["pool"] == pool)].iloc[0]
            value = float(row["cagr"])
            bar_h = int((y1 - y0) * abs(value) / (2 * top))
            x = gx + j * (bar_w + 18)
            if value >= 0:
                y = zero_y - bar_h
                rect = (x, y, x + bar_w, zero_y)
                text_y = y - 25
            else:
                y = zero_y + bar_h
                rect = (x, zero_y, x + bar_w, y)
                text_y = y + 5
            draw.rectangle(rect, fill=colors[pool])
            draw_text(draw, (x - 2, text_y), pct(value), 15, fill=(45, 50, 60), bold=True)
    for i, pool in enumerate(pool_order):
        lx = x0 + 40 + i * 360
        draw.rectangle((lx, height - 68, lx + 28, height - 51), fill=colors[pool])
        draw_text(draw, (lx + 38, height - 73), POOL_LABELS[pool], 18, fill=(50, 55, 65))
    img.save(out_path)


def make_markdown_report(metrics_df: pd.DataFrame, membership_df: pd.DataFrame, context: dict) -> str:
    full = metrics_df[metrics_df["period"] == "FULL"].copy()
    gross = full[full["mode"] == "gross"].set_index("pool")
    net = full[full["mode"] == "net_cost_model"].set_index("pool")
    period = metrics_df[metrics_df["mode"] == "gross_period"].copy()

    def metric_table(df: pd.DataFrame) -> str:
        rows = []
        for pool in ["BTC_ONLY", "CORE4_BTC_ETH_SOL_BNB", "POOL12_DROP_LTC_AAVE"]:
            r = df.loc[pool]
            rows.append(
                f"| {POOL_LABELS[pool]} | {int(r.n_symbols)} | {pct(r.cagr)} | {num(r.sharpe)} | {pct(r.mdd)} | {num(r.calmar)} | {num(r.final)}x | {pct(r.avg_exposure)} |"
            )
        return "\n".join(rows)

    period_rows = []
    for pool in ["BTC_ONLY", "CORE4_BTC_ETH_SOL_BNB", "POOL12_DROP_LTC_AAVE"]:
        for per in ["2020", "2021", "POST_2021"]:
            r = period[(period["pool"] == pool) & (period["period"] == per)].iloc[0]
            period_rows.append(
                f"| {POOL_LABELS[pool]} | {r.period_label} | {pct(r.cagr)} | {num(r.sharpe)} | {pct(r.mdd)} | {num(r.calmar)} | {num(r.final)}x |"
            )

    members = membership_df.groupby("pool")["symbol"].apply(lambda x: ", ".join(x)).to_dict()
    deleted = "LTCUSDT, AAVEUSDT"
    btc = gross.loc["BTC_ONLY"]
    core4 = gross.loc["CORE4_BTC_ETH_SOL_BNB"]
    pool12 = gross.loc["POOL12_DROP_LTC_AAVE"]
    pool12_post = period[(period["pool"] == "POOL12_DROP_LTC_AAVE") & (period["period"] == "POST_2021")].iloc[0]
    core4_post = period[(period["pool"] == "CORE4_BTC_ETH_SOL_BNB") & (period["period"] == "POST_2021")].iloc[0]
    btc_post = period[(period["pool"] == "BTC_ONLY") & (period["period"] == "POST_2021")].iloc[0]

    return f"""# 右侧现货动量：池子对比报告

生成时间：{pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")}

## 1. 本轮问题

本轮不讨论“多币种配置”本身，只回答一个更窄的问题：

> 同一套右侧现货动量 baseline，在一个经过筛选并删除差币的有效池子里，是否比 BTC 单币更值得做？

策略逻辑保持不变：

- 20 日突破入场；
- EMA200 过滤；
- close-based 3ATR trailing exit；
- 入场时固定现货 units，持仓期间不动态调仓；
- 现金收益按 0 处理；
- 交易成本口径为 fee 0.10% + slippage 0.05% 单边。

样本窗口：{context["common_start"]} 至 {context["common_end"]}。

## 2. 对比池子

| Pool | Symbols |
|---|---|
| BTC only | {members["BTC_ONLY"]} |
| BTC/ETH/SOL/BNB | {members["CORE4_BTC_ETH_SOL_BNB"]} |
| 12 coin pool | {members["POOL12_DROP_LTC_AAVE"]} |

12 coin pool 的构造：从 5 年历史 + 流动性筛选后的 14 币池中删除 `{deleted}`。删除理由不是参数优化，而是归因层面表现差：`LTC` 为明确负贡献，`AAVE` 接近零贡献且最大回撤期拖累明显。

## 3. 全样本结果

![权益曲线与回撤]({md_img(OUTPUT_DIR / "01_pool_equity_drawdown.png")})

![指标对比]({md_img(OUTPUT_DIR / "02_pool_metrics.png")})

Gross：

| Pool | N | CAGR | Sharpe | MDD | Calmar | Final | Avg exposure |
|---|---:|---:|---:|---:|---:|---:|---:|
{metric_table(gross)}

Net cost model：

| Pool | N | CAGR | Sharpe | MDD | Calmar | Final | Avg exposure |
|---|---:|---:|---:|---:|---:|---:|---:|
{metric_table(net)}

解读：

- BTC only 是必要基准：gross CAGR {pct(btc.cagr)}，Calmar {num(btc.calmar)}。
- Core4 全样本收益最高：gross CAGR {pct(core4.cagr)}，final {num(core4.final)}x。
- 12 coin pool 的全样本 CAGR 略低于 Core4，但 Sharpe {num(pool12.sharpe)}、MDD {pct(pool12.mdd)}、Calmar {num(pool12.calmar)} 是三组里最均衡的。
- 相比 BTC only，12 coin pool 在 CAGR、Sharpe、MDD、Calmar、final 上都更好；这是当前最核心的正证据。

## 4. 分阶段稳定性

![分阶段 CAGR 对比]({md_img(OUTPUT_DIR / "03_period_cagr.png")})

| Pool | Period | CAGR | Sharpe | MDD | Calmar | Final |
|---|---|---:|---:|---:|---:|---:|
{chr(10).join(period_rows)}

关键点：

- 2021 年 Core4 最强，说明 Core4 全样本优势明显吃到 SOL/BNB 的单轮大趋势。
- 2022-2026 阶段，12 coin pool CAGR {pct(pool12_post.cagr)}，低于 BTC only 的 {pct(btc_post.cagr)}，但高于 Core4 的 {pct(core4_post.cagr)}。
- 同一阶段，12 coin pool 的 Sharpe、MDD、Calmar 都优于 BTC only 和 Core4；所以它不是收益率单项胜出，而是风险调整后更稳。

## 5. 当前结论

当前应保留三个判断：

1. 右侧现货动量 baseline 本身仍然是核心，不需要改入场/出场参数。
2. 币池不是越大越好；`LTC/AAVE` 应先删掉。
3. 当前候选 baseline 应从 14 币池降为 12 币池，而不是继续扩散到更多币。

更谨慎的表述是：

> 12 coin pool 暂时是 BTC only 的升级候选。它全样本优于 BTC；在 2022-2026 阶段，绝对 CAGR 低于 BTC，但风险调整表现更好。Core4 全样本收益更高，所以下一步要比较“集中核心4币”与“分散12币池”在滚动样本和风险暴露上的稳定性。

## 6. 下一步建议

下一步不要新增过滤器，先做两个验证：

1. 滚动 2 年窗口：看 12 coin pool 相对 BTC 和 Core4 的超额是否稳定。
2. 风险暴露归一化：把三组拉到同一目标波动或同一平均暴露，再比较 CAGR、MDD、Calmar。

如果这两步后 12 coin pool 仍然更稳，它才有资格成为右侧现货动量的正式 baseline；否则就应考虑 Core4 或 BTC-only 作为更干净的实现。
"""


def main() -> None:
    baseline = load_baseline_module()
    _, _, _, _, _, backtests, context = baseline.build_results(refresh=False)
    pools = build_pools(context["selected_symbols"])

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    metrics_df, yearly_df, membership_df, equity_map, drawdown_map = compute_pool_outputs(baseline, backtests, pools)

    metrics_df.to_csv(OUTPUT_DIR / "pool_metrics.csv", index=False, encoding="utf-8-sig")
    yearly_df.to_csv(OUTPUT_DIR / "pool_yearly_metrics.csv", index=False, encoding="utf-8-sig")
    membership_df.to_csv(OUTPUT_DIR / "pool_membership.csv", index=False, encoding="utf-8-sig")

    draw_equity_compare(equity_map, drawdown_map, OUTPUT_DIR / "01_pool_equity_drawdown.png")
    draw_metric_bars(metrics_df, OUTPUT_DIR / "02_pool_metrics.png")
    draw_period_bars(metrics_df, OUTPUT_DIR / "03_period_cagr.png")

    REPORT_PATH.write_text(make_markdown_report(metrics_df, membership_df, context), encoding="utf-8-sig")

    full = metrics_df[(metrics_df["period"] == "FULL") & (metrics_df["mode"].isin(["gross", "net_cost_model"]))]
    print(full[["label", "mode", "n_symbols", "cagr", "sharpe", "mdd", "calmar", "final", "avg_exposure"]].to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print(f"\nSaved outputs to: {OUTPUT_DIR}")
    print(f"Saved report to: {REPORT_PATH}")


if __name__ == "__main__":
    main()
