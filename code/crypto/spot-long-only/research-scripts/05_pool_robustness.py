from __future__ import annotations

import importlib.util
import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
BASELINE_SCRIPT = ROOT / "02_spot_universe_baseline.py"
OUTPUT_DIR = ROOT / "outputs_robustness"
REPORT_PATH = ROOT / "05_pool_robustness_report.md"

FULL14 = "FULL14"
POOL12 = "POOL12_DROP_LTC_AAVE"
BTC_ONLY = "BTC_ONLY"
CORE4 = "CORE4_BTC_ETH_SOL_BNB"

POOL_LABELS = {
    FULL14: "14 coin pool",
    POOL12: "12 coin pool",
    BTC_ONLY: "BTC only",
    CORE4: "BTC/ETH/SOL/BNB",
}


def load_baseline_module():
    spec = importlib.util.spec_from_file_location("spot_pool_robustness_baseline", BASELINE_SCRIPT)
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


def portfolio_return(backtests: dict[str, pd.DataFrame], symbols: list[str], column: str = "GrossReturn") -> pd.Series:
    panel = pd.concat([backtests[s][column].rename(s) for s in symbols], axis=1).fillna(0.0)
    return panel.mean(axis=1)


def metric_row(baseline, backtests: dict[str, pd.DataFrame], symbols: list[str], label: str, mode: str = "gross") -> dict:
    column = "GrossReturn" if mode == "gross" else "NetReturn"
    ret = portfolio_return(backtests, symbols, column)
    exposure = pd.concat([backtests[s]["Exposure"].rename(s) for s in symbols], axis=1).fillna(0.0).abs().mean(axis=1).mean()
    return dict(pool=label, n_symbols=len(symbols), avg_exposure=float(exposure), symbols=", ".join(symbols), mode=mode, **baseline.metrics(ret))


def build_leave_one(baseline, backtests: dict[str, pd.DataFrame], selected_symbols: list[str], full_metrics: dict) -> pd.DataFrame:
    rows = []
    for removed in selected_symbols:
        symbols = [s for s in selected_symbols if s != removed]
        row = metric_row(baseline, backtests, symbols, removed, mode="gross")
        row.update(
            removed=removed,
            delta_cagr=row["cagr"] - full_metrics["cagr"],
            delta_sharpe=row["sharpe"] - full_metrics["sharpe"],
            delta_mdd=row["mdd"] - full_metrics["mdd"],
            delta_calmar=row["calmar"] - full_metrics["calmar"],
            delta_final=row["final"] - full_metrics["final"],
        )
        rows.append(row)
    return pd.DataFrame(rows).sort_values("delta_calmar", ascending=False)


def build_leave_two(baseline, backtests: dict[str, pd.DataFrame], selected_symbols: list[str], full_metrics: dict) -> pd.DataFrame:
    rows = []
    for a, b in itertools.combinations(selected_symbols, 2):
        symbols = [s for s in selected_symbols if s not in {a, b}]
        row = metric_row(baseline, backtests, symbols, f"{a}+{b}", mode="gross")
        row.update(
            removed_a=a,
            removed_b=b,
            removed_pair=f"{a}+{b}",
            is_ltc_aave_pair={a, b} == {"LTCUSDT", "AAVEUSDT"},
            delta_cagr=row["cagr"] - full_metrics["cagr"],
            delta_sharpe=row["sharpe"] - full_metrics["sharpe"],
            delta_mdd=row["mdd"] - full_metrics["mdd"],
            delta_calmar=row["calmar"] - full_metrics["calmar"],
            delta_final=row["final"] - full_metrics["final"],
        )
        rows.append(row)
    out = pd.DataFrame(rows)
    out["rank_by_calmar"] = out["calmar"].rank(ascending=False, method="min").astype(int)
    out["rank_by_cagr"] = out["cagr"].rank(ascending=False, method="min").astype(int)
    out["rank_by_sharpe"] = out["sharpe"].rank(ascending=False, method="min").astype(int)
    return out.sort_values("calmar", ascending=False)


def rolling_metrics(baseline, backtests: dict[str, pd.DataFrame], pools: dict[str, list[str]]) -> pd.DataFrame:
    index = next(iter(backtests.values())).index
    first = index[0]
    last_start = index[-1] - pd.DateOffset(years=2) + pd.Timedelta(days=1)
    starts = pd.date_range(first, last_start, freq="MS")
    if starts.empty or starts[0] != first:
        starts = pd.DatetimeIndex([first]).append(starts)

    rows = []
    for start in starts:
        end = start + pd.DateOffset(years=2) - pd.Timedelta(days=1)
        for pool, symbols in pools.items():
            ret = portfolio_return(backtests, symbols).loc[start:end]
            if len(ret) < 365:
                continue
            row = dict(pool=pool, label=POOL_LABELS[pool], window_start=start.date().isoformat(), window_end=end.date().isoformat(), n_symbols=len(symbols))
            row.update(baseline.metrics(ret))
            rows.append(row)
    return pd.DataFrame(rows)


def rolling_summary(rolling_df: pd.DataFrame) -> pd.DataFrame:
    pivots = {
        metric: rolling_df.pivot(index="window_start", columns="pool", values=metric)
        for metric in ["cagr", "sharpe", "mdd", "calmar"]
    }
    rows = []
    for challenger in [CORE4, POOL12]:
        common = pivots["cagr"][[challenger, BTC_ONLY]].dropna().index
        cagr = pivots["cagr"].loc[common]
        sharpe = pivots["sharpe"].loc[common]
        mdd = pivots["mdd"].loc[common]
        calmar = pivots["calmar"].loc[common]
        rows.append(
            dict(
                challenger=challenger,
                label=POOL_LABELS[challenger],
                benchmark=BTC_ONLY,
                benchmark_label=POOL_LABELS[BTC_ONLY],
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
    return pd.DataFrame(rows)


def draw_leave_one(leave_one_df: pd.DataFrame, out_path: Path) -> None:
    width, height = 1650, 940
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (70, 28), "Leave-one-out：删除单币后的变化", 30, bold=True)
    draw_text(draw, (70, 64), "相对 14 币池；正值表示删除该币后组合指标改善。", 18, fill=(90, 95, 105))

    df = leave_one_df.sort_values("delta_calmar", ascending=False).reset_index(drop=True)
    symbols = df["removed"].str.replace("USDT", "").tolist()
    panels = [("Δ Calmar", "delta_calmar", False), ("Δ CAGR", "delta_cagr", True)]
    origins = [(85, 135), (85, 530)]
    colors = {"pos": "#255C99", "neg": "#C43C39"}
    panel_w, panel_h = width - 160, 285

    for (title, col, is_pct), (ox, oy) in zip(panels, origins):
        values = df[col].astype(float).tolist()
        max_abs = max(abs(min(values + [0.0])), abs(max(values + [0.0]))) * 1.18
        max_abs = max(max_abs, 1e-9)
        baseline_y = oy + panel_h // 2
        draw_text(draw, (ox, oy - 34), title, 23, bold=True)
        draw.rectangle((ox, oy, ox + panel_w, oy + panel_h), outline=(220, 224, 230))
        draw.line((ox + 45, baseline_y, ox + panel_w - 25, baseline_y), fill=(150, 155, 165), width=2)
        step = (panel_w - 90) / len(df)
        bar_w = max(38, int(step * 0.55))
        for i, (symbol, value) in enumerate(zip(symbols, values)):
            x = int(ox + 55 + i * step)
            bar_h = int((panel_h - 85) / 2 * abs(value) / max_abs)
            if value >= 0:
                rect = (x, baseline_y - bar_h, x + bar_w, baseline_y)
                text_y = baseline_y - bar_h - 24
                color = colors["pos"]
            else:
                rect = (x, baseline_y, x + bar_w, baseline_y + bar_h)
                text_y = baseline_y + bar_h + 4
                color = colors["neg"]
            draw.rectangle(rect, fill=color)
            label = pct(value) if is_pct else f"{value:+.2f}"
            draw_text(draw, (x - 8, text_y), label, 13, fill=(45, 50, 60))
            draw_text(draw, (x - 8, baseline_y + 10), symbol, 13, fill=(55, 60, 70), bold=True)
    img.save(out_path)


def draw_leave_two(leave_two_df: pd.DataFrame, out_path: Path) -> None:
    width, height = 1650, 980
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (70, 28), "Leave-two-out：删除两币后的 Calmar 排名", 30, bold=True)
    draw_text(draw, (70, 64), "展示 Calmar 排名前 15 的删除组合；橙色为 LTC/AAVE。", 18, fill=(90, 95, 105))

    df = leave_two_df.sort_values("calmar", ascending=False).head(15).copy()
    max_v = max(float(df["calmar"].max()), 1e-9) * 1.12
    x0, x1 = 430, width - 160
    y0, y1 = 125, height - 90
    step = (y1 - y0) / len(df)
    bar_h = max(28, int(step * 0.58))
    for i, row in enumerate(df.itertuples()):
        y = int(y0 + i * step)
        label = row.removed_pair.replace("USDT", "")
        color = "#D95F02" if row.is_ltc_aave_pair else "#255C99"
        bar_w = int((x1 - x0) * float(row.calmar) / max_v)
        draw_text(draw, (70, y - 1), f"{int(row.rank_by_calmar):02d}. {label}", 18, fill=(45, 50, 60), bold=True)
        draw.rectangle((x0, y, x0 + bar_w, y + bar_h), fill=color)
        draw_text(draw, (x0 + bar_w + 12, y - 1), f"Calmar {float(row.calmar):.2f} / CAGR {pct(float(row.cagr))}", 16, fill=(45, 50, 60))
    img.save(out_path)


def draw_rolling_calmar(rolling_df: pd.DataFrame, out_path: Path) -> None:
    width, height = 1650, 900
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (70, 28), "2 年滚动窗口：Calmar 对比", 30, bold=True)
    draw_text(draw, (70, 64), "每月起点滚动 2 年；用于观察池子优势是否只来自单一阶段。", 18, fill=(90, 95, 105))

    colors = {BTC_ONLY: "#255C99", CORE4: "#2E7D32", POOL12: "#D95F02"}
    pivot = rolling_df.pivot(index="window_start", columns="pool", values="calmar")
    pivot.index = pd.to_datetime(pivot.index)
    pivot = pivot[[BTC_ONLY, CORE4, POOL12]]
    x0, y0, x1, y1 = 95, 130, width - 80, height - 150
    ymin, ymax = float(pivot.min().min()), float(pivot.max().max())
    pad = max((ymax - ymin) * 0.08, 0.05)
    ymin -= pad
    ymax += pad
    draw.rectangle((x0, y0, x1, y1), outline=(220, 224, 230))
    for i in range(6):
        y = y1 - int((y1 - y0) * i / 5)
        value = ymin + (ymax - ymin) * i / 5
        draw.line((x0, y, x1, y), fill=(236, 239, 243))
        draw_text(draw, (35, y - 10), f"{value:.1f}", 15, fill=(95, 100, 110))

    for pool in pivot.columns:
        pts = []
        values = pivot[pool].astype(float).values
        for i, value in enumerate(values):
            x = x0 + int((x1 - x0) * i / (len(values) - 1))
            y = y1 - int((y1 - y0) * (value - ymin) / (ymax - ymin))
            pts.append((x, y))
        draw.line(pts, fill=colors[pool], width=4)

    for i, pool in enumerate(pivot.columns):
        lx = x0 + 40 + i * 360
        draw.rectangle((lx, height - 95, lx + 28, height - 78), fill=colors[pool])
        draw_text(draw, (lx + 38, height - 100), POOL_LABELS[pool], 18, fill=(50, 55, 65))
    draw_text(draw, (x0, y1 + 18), str(pivot.index[0].date()), 15, fill=(95, 100, 110))
    draw_text(draw, (x1 - 95, y1 + 18), str(pivot.index[-1].date()), 15, fill=(95, 100, 110))
    img.save(out_path)


def draw_rolling_winrates(summary_df: pd.DataFrame, out_path: Path) -> None:
    width, height = 1400, 760
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (70, 28), "2 年滚动窗口：相对 BTC 胜率", 30, bold=True)
    draw_text(draw, (70, 64), "胜率指窗口内该指标优于 BTC only 的比例。", 18, fill=(90, 95, 105))

    metrics = [("CAGR", "cagr_win_rate"), ("Sharpe", "sharpe_win_rate"), ("MDD", "mdd_win_rate"), ("Calmar", "calmar_win_rate")]
    colors = {CORE4: "#2E7D32", POOL12: "#D95F02"}
    x0, y0, x1, y1 = 120, 130, width - 80, height - 120
    draw.rectangle((x0, y0, x1, y1), outline=(220, 224, 230))
    for i in range(6):
        y = y1 - int((y1 - y0) * i / 5)
        draw.line((x0, y, x1, y), fill=(236, 239, 243))
        draw_text(draw, (55, y - 10), pct(i / 5), 15, fill=(95, 100, 110))

    group_w = (x1 - x0 - 90) / len(metrics)
    bar_w = 95
    for i, (label, col) in enumerate(metrics):
        gx = x0 + 60 + int(i * group_w)
        draw_text(draw, (gx + 32, y1 + 20), label, 18, fill=(55, 60, 70), bold=True)
        for j, pool in enumerate([CORE4, POOL12]):
            row = summary_df[summary_df["challenger"] == pool].iloc[0]
            value = float(row[col])
            bar_h = int((y1 - y0) * value)
            x = gx + j * (bar_w + 20)
            draw.rectangle((x, y1 - bar_h, x + bar_w, y1), fill=colors[pool])
            draw_text(draw, (x + 10, y1 - bar_h - 26), pct(value), 16, fill=(45, 50, 60), bold=True)

    for i, pool in enumerate([CORE4, POOL12]):
        lx = x0 + 50 + i * 380
        draw.rectangle((lx, height - 65, lx + 28, height - 48), fill=colors[pool])
        draw_text(draw, (lx + 38, height - 70), POOL_LABELS[pool], 18, fill=(50, 55, 65))
    img.save(out_path)


def make_report(context: dict, full_rows: pd.DataFrame, leave_one: pd.DataFrame, leave_two: pd.DataFrame, rolling_summary_df: pd.DataFrame) -> str:
    full = full_rows.set_index("pool")
    pool12_symbols = full.loc[POOL12, "symbols"]
    ltc_aave = leave_two[leave_two["is_ltc_aave_pair"]].iloc[0]
    top_leave_one = leave_one.head(5)
    bottom_leave_one = leave_one.tail(5).sort_values("delta_calmar")
    top_pairs = leave_two.head(10)

    one_rows = [
        f"| {r.removed} | {pct(r.cagr)} | {num(r.sharpe)} | {pct(r.mdd)} | {num(r.calmar)} | {num(r.delta_calmar)} | {pct(r.delta_cagr)} |"
        for r in leave_one.itertuples()
    ]
    pair_rows = [
        f"| {int(r.rank_by_calmar)} | {r.removed_pair} | {pct(r.cagr)} | {num(r.sharpe)} | {pct(r.mdd)} | {num(r.calmar)} | {pct(r.delta_cagr)} |"
        for r in top_pairs.itertuples()
    ]
    rolling_rows = [
        f"| {r.label} | {int(r.windows)} | {pct(r.cagr_win_rate)} | {pct(r.sharpe_win_rate)} | {pct(r.mdd_win_rate)} | {pct(r.calmar_win_rate)} | {pct(r.avg_cagr_diff)} | {num(r.avg_calmar_diff)} |"
        for r in rolling_summary_df.itertuples()
    ]

    return f"""# 右侧现货动量：池子稳健性验证

生成时间：{pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")}

## 1. 验证目标

本轮只验证币池稳健性，不改入场、不改出场、不新增过滤器。

核心问题：

> 从 14 币池删除 `LTC/AAVE` 得到 12 币池，是不是有稳健证据，而不是事后挑答案？

基础口径：

- 策略仍为 B baseline：20 日突破 + EMA200 + close-based 3ATR trailing exit。
- 样本窗口：{context["common_start"]} 至 {context["common_end"]}。
- 14 币池来自 5 年历史 + 流动性筛选。
- 12 币池：{pool12_symbols}。

## 2. 全样本三组结果

| Pool | N | CAGR | Sharpe | MDD | Calmar | Final |
|---|---:|---:|---:|---:|---:|---:|
| BTC only | {int(full.loc[BTC_ONLY, "n_symbols"])} | {pct(full.loc[BTC_ONLY, "cagr"])} | {num(full.loc[BTC_ONLY, "sharpe"])} | {pct(full.loc[BTC_ONLY, "mdd"])} | {num(full.loc[BTC_ONLY, "calmar"])} | {num(full.loc[BTC_ONLY, "final"])}x |
| BTC/ETH/SOL/BNB | {int(full.loc[CORE4, "n_symbols"])} | {pct(full.loc[CORE4, "cagr"])} | {num(full.loc[CORE4, "sharpe"])} | {pct(full.loc[CORE4, "mdd"])} | {num(full.loc[CORE4, "calmar"])} | {num(full.loc[CORE4, "final"])}x |
| 14 coin pool | {int(full.loc[FULL14, "n_symbols"])} | {pct(full.loc[FULL14, "cagr"])} | {num(full.loc[FULL14, "sharpe"])} | {pct(full.loc[FULL14, "mdd"])} | {num(full.loc[FULL14, "calmar"])} | {num(full.loc[FULL14, "final"])}x |
| 12 coin pool | {int(full.loc[POOL12, "n_symbols"])} | {pct(full.loc[POOL12, "cagr"])} | {num(full.loc[POOL12, "sharpe"])} | {pct(full.loc[POOL12, "mdd"])} | {num(full.loc[POOL12, "calmar"])} | {num(full.loc[POOL12, "final"])}x |

## 3. Leave-one-out

![Leave-one-out]({md_img(OUTPUT_DIR / "01_leave_one_out.png")})

| Removed | CAGR | Sharpe | MDD | Calmar | Δ Calmar | Δ CAGR |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(one_rows)}

解读：

- 删除后改善最明显的前 5 个：{", ".join(top_leave_one["removed"].tolist())}。
- 删除后伤害最大的前 5 个：{", ".join(bottom_leave_one["removed"].tolist())}。
- `LTC` 在 leave-one-out 中属于明确应该删除的标的：删除后 Calmar 和 CAGR 同时改善。
- `AAVE` 单独删除的改善不一定最大，但它在归因中接近零贡献、最大回撤期拖累明显；所以更适合作为和 LTC 一起删除的风险清理项。

## 4. Leave-two-out

![Leave-two-out]({md_img(OUTPUT_DIR / "02_leave_two_out.png")})

Calmar 前 10：

| Rank | Removed pair | CAGR | Sharpe | MDD | Calmar | Δ CAGR |
|---:|---|---:|---:|---:|---:|---:|
{chr(10).join(pair_rows)}

`LTC/AAVE` 删除组合的 Calmar 排名：第 {int(ltc_aave.rank_by_calmar)} / {len(leave_two)}；CAGR 排名：第 {int(ltc_aave.rank_by_cagr)} / {len(leave_two)}；Sharpe 排名：第 {int(ltc_aave.rank_by_sharpe)} / {len(leave_two)}。

解释：

- 如果只按 Calmar 排名扫描，`LTC/AAVE` 不是唯一可能组合。
- 但本轮删除规则不是“寻找最优两币删除”，而是只删除归因已经证明差的币。
- 因此 `LTC/AAVE` 可以作为保守清理，不应继续扩展成删除更多币的优化搜索。

## 5. 2 年滚动窗口

![滚动 Calmar]({md_img(OUTPUT_DIR / "03_rolling_calmar.png")})

![滚动胜率]({md_img(OUTPUT_DIR / "04_rolling_winrates.png")})

相对 BTC only 的滚动胜率：

| Challenger | Windows | CAGR win | Sharpe win | MDD win | Calmar win | Avg CAGR diff | Avg Calmar diff |
|---|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(rolling_rows)}

## 6. 当前判断

稳健性结论要克制：

1. 删除 `LTC` 是硬结论。
2. 删除 `AAVE` 是合理的风险清理，但证据弱于 `LTC`。
3. `LTC/AAVE -> 12 coin pool` 是当前可接受的保守版本，但不是通过全组合扫描得到的“最优池子”。
4. 下一步不应继续删币，而应做同风险/同暴露归一化比较；否则很容易把币池筛选变成事后优化。

如果后续同风险/同暴露后，12 coin pool 仍然优于 BTC only，并且不明显弱于 Core4，它才适合晋升为右侧现货动量的正式 baseline。
"""


def main() -> None:
    baseline = load_baseline_module()
    _, _, _, _, _, backtests, context = baseline.build_results(refresh=False)
    selected = context["selected_symbols"]
    pools = {
        BTC_ONLY: ["BTCUSDT"],
        CORE4: ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"],
        FULL14: selected,
        POOL12: [s for s in selected if s not in {"LTCUSDT", "AAVEUSDT"}],
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    full_rows = pd.DataFrame([metric_row(baseline, backtests, symbols, pool) for pool, symbols in pools.items()])
    full14_metrics = full_rows[full_rows["pool"] == FULL14].iloc[0].to_dict()
    leave_one = build_leave_one(baseline, backtests, selected, full14_metrics)
    leave_two = build_leave_two(baseline, backtests, selected, full14_metrics)
    rolling = rolling_metrics(baseline, backtests, {BTC_ONLY: pools[BTC_ONLY], CORE4: pools[CORE4], POOL12: pools[POOL12]})
    roll_summary = rolling_summary(rolling)

    full_rows.to_csv(OUTPUT_DIR / "robustness_full_pools.csv", index=False, encoding="utf-8-sig")
    leave_one.to_csv(OUTPUT_DIR / "robustness_leave_one_out.csv", index=False, encoding="utf-8-sig")
    leave_two.to_csv(OUTPUT_DIR / "robustness_leave_two_out.csv", index=False, encoding="utf-8-sig")
    rolling.to_csv(OUTPUT_DIR / "robustness_rolling_2y.csv", index=False, encoding="utf-8-sig")
    roll_summary.to_csv(OUTPUT_DIR / "robustness_rolling_summary.csv", index=False, encoding="utf-8-sig")

    draw_leave_one(leave_one, OUTPUT_DIR / "01_leave_one_out.png")
    draw_leave_two(leave_two, OUTPUT_DIR / "02_leave_two_out.png")
    draw_rolling_calmar(rolling, OUTPUT_DIR / "03_rolling_calmar.png")
    draw_rolling_winrates(roll_summary, OUTPUT_DIR / "04_rolling_winrates.png")

    REPORT_PATH.write_text(make_report(context, full_rows, leave_one, leave_two, roll_summary), encoding="utf-8-sig")

    print(full_rows[["pool", "n_symbols", "cagr", "sharpe", "mdd", "calmar", "final"]].to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print("\nLTC/AAVE pair")
    print(leave_two[leave_two["is_ltc_aave_pair"]][["removed_pair", "rank_by_calmar", "rank_by_cagr", "rank_by_sharpe", "cagr", "sharpe", "mdd", "calmar"]].to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print("\nRolling summary")
    print(roll_summary.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print(f"\nSaved outputs to: {OUTPUT_DIR}")
    print(f"Saved report to: {REPORT_PATH}")


if __name__ == "__main__":
    main()
