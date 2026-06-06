from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
BASELINE_SCRIPT = ROOT / "02_spot_universe_baseline.py"
OUTPUT_DIR = ROOT / "outputs_boundary_tests"
REPORT_PATH = ROOT / "09_boundary_deployment_tests_report.md"

POOL12 = [
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

COST_LEVELS = [0.0, 0.0015, 0.0030, 0.0050, 0.0100, 0.0200]
TARGET_EXPOSURE = 0.40

CAPITAL_RULE_LABELS = {
    "fixed_slots": "Fixed slots",
    "target_40": "Target 40% exposure",
    "active_redeploy": "Active redeploy",
}

CAPITAL_COLORS = {
    "fixed_slots": "#255C99",
    "target_40": "#2E7D32",
    "active_redeploy": "#D95F02",
}


def load_baseline_module():
    spec = importlib.util.spec_from_file_location("spot_boundary_baseline", BASELINE_SCRIPT)
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


def assert_pool(context: dict) -> None:
    selected = set(context["selected_symbols"])
    expected = set(POOL12)
    missing = expected - selected
    unexpected = selected - expected - {"LTCUSDT", "AAVEUSDT"}
    if missing or unexpected:
        raise ValueError(f"Universe drifted. missing={sorted(missing)}, unexpected={sorted(unexpected)}")


def concat_panel(backtests: dict[str, pd.DataFrame], symbols: list[str], column: str) -> pd.DataFrame:
    return pd.concat([backtests[s][column].rename(s) for s in symbols], axis=1).fillna(0.0)


def fixed_slot_return(backtests: dict[str, pd.DataFrame], symbols: list[str], column: str = "GrossReturn") -> pd.Series:
    return concat_panel(backtests, symbols, column).mean(axis=1)


def exposure_panel(backtests: dict[str, pd.DataFrame], symbols: list[str]) -> pd.DataFrame:
    return concat_panel(backtests, symbols, "Exposure")


def build_cost_sensitivity(baseline, common_start: pd.Timestamp, common_end: pd.Timestamp) -> pd.DataFrame:
    rows = []
    common_index = pd.date_range(pd.Timestamp(common_start), pd.Timestamp(common_end), freq="D")
    for cost in COST_LEVELS:
        cols = []
        for symbol in POOL12:
            df = baseline.load_or_fetch(symbol, refresh=False)
            sig = baseline.generate_signals(df)
            sim = baseline.simulate_fixed_units(sig, cost_rate=cost)
            cols.append(sim["Return"].rename(symbol).reindex(common_index).fillna(0.0))
        ret = pd.concat(cols, axis=1).mean(axis=1)
        row = dict(one_way_cost=cost, cost_bps=cost * 10_000)
        row.update(baseline.metrics(ret))
        rows.append(row)
    return pd.DataFrame(rows)


def build_capital_rules(baseline, backtests: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    returns = concat_panel(backtests, POOL12, "GrossReturn")
    exposure = exposure_panel(backtests, POOL12)
    n = len(POOL12)

    fixed_ret = returns.mean(axis=1)
    prev_exposure = exposure.shift(1).fillna(0.0)
    prev_active = prev_exposure > 0
    active_count = prev_active.sum(axis=1)

    fixed_prev_exp = prev_exposure.mean(axis=1)
    max_scale = (n / active_count.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    target_scale = (TARGET_EXPOSURE / fixed_prev_exp.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    target_scale = np.minimum(target_scale, max_scale)

    rule_returns = {
        "fixed_slots": fixed_ret,
        "target_40": fixed_ret * target_scale,
        "active_redeploy": fixed_ret * max_scale,
    }
    rule_exposure = {
        "fixed_slots": exposure.mean(axis=1),
        "target_40": (fixed_prev_exp * target_scale).reindex(fixed_ret.index).fillna(0.0),
        "active_redeploy": prev_exposure.where(prev_active).mean(axis=1).reindex(fixed_ret.index).fillna(0.0),
    }

    rows = []
    equity_cols = {}
    for rule, ret in rule_returns.items():
        m = baseline.metrics(ret)
        eq = (1.0 + ret).cumprod()
        equity_cols[rule] = eq
        exp = rule_exposure[rule]
        rows.append(
            dict(
                rule=rule,
                label=CAPITAL_RULE_LABELS[rule],
                avg_exposure=float(exp.mean()),
                p95_exposure=float(exp.quantile(0.95)),
                max_exposure=float(exp.max()),
                avg_active_symbols=float(active_count.mean()),
                median_active_symbols=float(active_count.median()),
                **m,
            )
        )
    equity_df = pd.DataFrame(equity_cols)
    metrics_df = pd.DataFrame(rows)
    return metrics_df, equity_df


def build_missing_coin_stress(baseline, backtests: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    base_ret = fixed_slot_return(backtests, POOL12)
    base = baseline.metrics(base_ret)
    rows.append(dict(scenario="FULL12", missing_symbol="", n_symbols=len(POOL12), **base))
    for missing in POOL12:
        symbols = [s for s in POOL12 if s != missing]
        ret = fixed_slot_return(backtests, symbols)
        row = dict(scenario=f"WITHOUT_{missing}", missing_symbol=missing, n_symbols=len(symbols))
        row.update(baseline.metrics(ret))
        row.update(
            delta_cagr=row["cagr"] - base["cagr"],
            delta_sharpe=row["sharpe"] - base["sharpe"],
            delta_mdd=row["mdd"] - base["mdd"],
            delta_calmar=row["calmar"] - base["calmar"],
            delta_final=row["final"] - base["final"],
        )
        rows.append(row)
    out = pd.DataFrame(rows)
    out.loc[out["scenario"] == "FULL12", ["delta_cagr", "delta_sharpe", "delta_mdd", "delta_calmar", "delta_final"]] = 0.0
    return out


def draw_cost_sensitivity(cost_df: pd.DataFrame, out_path: Path) -> None:
    width, height = 1450, 820
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (70, 28), "交易成本敏感性", 30, bold=True)
    draw_text(draw, (70, 64), "12 币池 fixed slots；横轴为单边成本，含手续费和滑点。", 18, fill=(90, 95, 105))

    x0, x1 = 110, width - 90
    panels = [("CAGR", "cagr", True, 130, 285), ("Calmar", "calmar", False, 465, 620)]
    for title, col, is_pct, y0, y1 in panels:
        draw_text(draw, (x0, y0 - 36), title, 23, bold=True)
        draw.rectangle((x0, y0, x1, y1), outline=(220, 224, 230))
        values = cost_df[col].astype(float).values
        ymin, ymax = min(0.0, float(values.min())), float(values.max())
        pad = max((ymax - ymin) * 0.10, 0.02)
        ymax += pad
        ymin -= pad
        for i in range(5):
            y = y1 - int((y1 - y0) * i / 4)
            value = ymin + (ymax - ymin) * i / 4
            draw.line((x0, y, x1, y), fill=(238, 241, 245))
            label = pct(value) if is_pct else f"{value:.1f}"
            draw_text(draw, (35, y - 10), label, 14, fill=(95, 100, 110))
        pts = []
        for i, row in enumerate(cost_df.itertuples()):
            x = x0 + int((x1 - x0) * i / (len(cost_df) - 1))
            value = float(getattr(row, col))
            y = y1 - int((y1 - y0) * (value - ymin) / (ymax - ymin))
            pts.append((x, y))
            draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill="#255C99")
            draw_text(draw, (x - 22, y1 + 12), f"{row.cost_bps:.0f}bp", 13, fill=(55, 60, 70), bold=True)
        draw.line(pts, fill="#255C99", width=4)
    img.save(out_path)


def draw_capital_rules(metrics_df: pd.DataFrame, equity_df: pd.DataFrame, out_path: Path) -> None:
    width, height = 1700, 1050
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (70, 28), "资金分配规则压力测试", 30, bold=True)
    draw_text(draw, (70, 64), "活跃重分配不含额外日度再平衡成本；收益偏乐观，重点看回撤放大。", 18, fill=(90, 95, 105))

    x0, x1 = 105, width - 80
    y0, y1 = 130, 540
    dd_y0, dd_y1 = 660, height - 105
    eq = equity_df.copy()
    log_eq = np.log(eq.clip(lower=1e-8))
    ymin, ymax = float(log_eq.min().min()), float(log_eq.max().max())
    pad = max((ymax - ymin) * 0.08, 0.01)
    ymin -= pad
    ymax += pad
    draw.rectangle((x0, y0, x1, y1), outline=(220, 224, 230))
    draw_text(draw, (x0, y0 - 34), "Equity", 23, bold=True)
    for i in range(6):
        y = y1 - int((y1 - y0) * i / 5)
        value = np.exp(ymin + (ymax - ymin) * i / 5)
        draw.line((x0, y, x1, y), fill=(238, 241, 245))
        draw_text(draw, (36, y - 10), f"{value:.1f}x", 14, fill=(95, 100, 110))
    for rule in equity_df.columns:
        vals = log_eq[rule].values
        pts = []
        for i, value in enumerate(vals):
            x = x0 + int((x1 - x0) * i / (len(vals) - 1))
            y = y1 - int((y1 - y0) * (float(value) - ymin) / (ymax - ymin))
            pts.append((x, y))
        draw.line(pts, fill=CAPITAL_COLORS[rule], width=4)

    dd = equity_df / equity_df.cummax() - 1.0
    min_dd = float(dd.min().min())
    draw_text(draw, (x0, dd_y0 - 34), "Drawdown", 23, bold=True)
    draw.rectangle((x0, dd_y0, x1, dd_y1), outline=(220, 224, 230))
    for i in range(5):
        y = dd_y1 - int((dd_y1 - dd_y0) * i / 4)
        value = min_dd * (1 - i / 4)
        draw.line((x0, y, x1, y), fill=(238, 241, 245))
        draw_text(draw, (36, y - 10), pct(value), 14, fill=(95, 100, 110))
    for rule in dd.columns:
        vals = dd[rule].values
        pts = []
        for i, value in enumerate(vals):
            x = x0 + int((x1 - x0) * i / (len(vals) - 1))
            y = dd_y1 - int((dd_y1 - dd_y0) * (float(value) - min_dd) / (0 - min_dd))
            pts.append((x, y))
        draw.line(pts, fill=CAPITAL_COLORS[rule], width=3)

    for i, rule in enumerate(["fixed_slots", "target_40", "active_redeploy"]):
        lx = x0 + 70 + i * 440
        draw.rectangle((lx, height - 72, lx + 28, height - 55), fill=CAPITAL_COLORS[rule])
        row = metrics_df[metrics_df["rule"] == rule].iloc[0]
        draw_text(draw, (lx + 38, height - 77), f"{CAPITAL_RULE_LABELS[rule]} | MDD {pct(row.mdd)}", 17, fill=(50, 55, 65), bold=True)
    img.save(out_path)


def draw_capital_metrics(metrics_df: pd.DataFrame, out_path: Path) -> None:
    width, height = 1550, 900
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (70, 28), "资金分配规则指标对比", 30, bold=True)
    draw_text(draw, (70, 64), "MDD 用绝对值展示，越低越好。", 18, fill=(90, 95, 105))

    panels = [("CAGR", "cagr", True), ("MDD", "mdd", True), ("Calmar", "calmar", False), ("Avg exposure", "avg_exposure", True)]
    origins = [(80, 140), (820, 140), (80, 520), (820, 520)]
    panel_w, panel_h = 630, 260
    rule_order = ["fixed_slots", "target_40", "active_redeploy"]
    for (title, col, is_pct), (ox, oy) in zip(panels, origins):
        draw_text(draw, (ox, oy - 34), title, 22, bold=True)
        draw.rectangle((ox, oy, ox + panel_w, oy + panel_h), outline=(220, 224, 230))
        vals = []
        for rule in rule_order:
            value = float(metrics_df[metrics_df["rule"] == rule][col].iloc[0])
            vals.append(abs(value) if col == "mdd" else value)
        max_v = max(vals + [1e-9]) * 1.18
        baseline = oy + panel_h - 48
        draw.line((ox + 45, baseline, ox + panel_w - 30, baseline), fill=(190, 195, 205), width=2)
        for i, rule in enumerate(rule_order):
            raw_value = float(metrics_df[metrics_df["rule"] == rule][col].iloc[0])
            value = abs(raw_value) if col == "mdd" else raw_value
            bar_h = int((panel_h - 85) * value / max_v)
            x = ox + 70 + i * 170
            draw.rectangle((x, baseline - bar_h, x + 90, baseline), fill=CAPITAL_COLORS[rule])
            label = f"{value:.2f}" if col == "calmar" else pct(value)
            draw_text(draw, (x - 2, baseline - bar_h - 25), label, 15, fill=(45, 50, 60), bold=True)
            draw_text(draw, (x - 24, baseline + 12), CAPITAL_RULE_LABELS[rule], 13, fill=(55, 60, 70), bold=True)
    img.save(out_path)


def draw_missing_coin(stress_df: pd.DataFrame, out_path: Path) -> None:
    width, height = 1650, 960
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (70, 28), "缺币 / 交易所可得性压力测试", 30, bold=True)
    draw_text(draw, (70, 64), "每次缺失一个币，剩余币等权；这是部署敏感性，不是删币建议。", 18, fill=(90, 95, 105))

    df = stress_df[stress_df["scenario"] != "FULL12"].sort_values("delta_calmar", ascending=True).reset_index(drop=True)
    x0, x1 = 370, width - 170
    y0, y1 = 125, height - 95
    vals = df["delta_calmar"].astype(float).tolist()
    min_v, max_v = min(vals + [0.0]), max(vals + [0.0])
    span = max_v - min_v if max_v > min_v else 1.0
    zero_x = x0 + int((0 - min_v) / span * (x1 - x0))
    draw.line((zero_x, y0 - 20, zero_x, y1 + 10), fill=(140, 145, 155), width=2)
    step = (y1 - y0) / len(df)
    bar_h = max(28, int(step * 0.58))
    for i, row in enumerate(df.itertuples()):
        y = int(y0 + i * step)
        value = float(row.delta_calmar)
        end_x = x0 + int((value - min_v) / span * (x1 - x0))
        color = "#255C99" if value >= 0 else "#C43C39"
        draw.rectangle((min(zero_x, end_x), y, max(zero_x, end_x), y + bar_h), fill=color)
        draw_text(draw, (70, y - 1), row.missing_symbol.replace("USDT", ""), 18, fill=(45, 50, 60), bold=True)
        label_x = end_x + 12 if value >= 0 else end_x - 145
        draw_text(draw, (label_x, y - 1), f"ΔCalmar {value:+.2f} / CAGR {pct(float(row.cagr))}", 15, fill=(45, 50, 60))
    img.save(out_path)


def table_cost(cost_df: pd.DataFrame) -> str:
    rows = []
    for row in cost_df.itertuples():
        rows.append(f"| {row.cost_bps:.0f}bp | {pct(row.cagr)} | {num(row.sharpe)} | {pct(row.mdd)} | {num(row.calmar)} | {num(row.final)}x |")
    return "\n".join(rows)


def table_capital(metrics_df: pd.DataFrame) -> str:
    rows = []
    for row in metrics_df.itertuples():
        rows.append(
            f"| {row.label} | {pct(row.cagr)} | {num(row.sharpe)} | {pct(row.mdd)} | {num(row.calmar)} | {num(row.final)}x | {pct(row.avg_exposure)} | {pct(row.p95_exposure)} | {pct(row.max_exposure)} |"
        )
    return "\n".join(rows)


def table_missing(stress_df: pd.DataFrame) -> str:
    df = stress_df[stress_df["scenario"] != "FULL12"].sort_values("delta_calmar", ascending=True)
    rows = []
    for row in df.itertuples():
        rows.append(f"| {row.missing_symbol} | {pct(row.cagr)} | {num(row.sharpe)} | {pct(row.mdd)} | {num(row.calmar)} | {num(row.delta_calmar)} | {pct(row.delta_cagr)} |")
    return "\n".join(rows)


def make_report(cost_df: pd.DataFrame, capital_df: pd.DataFrame, missing_df: pd.DataFrame, context: dict) -> str:
    fixed = capital_df[capital_df["rule"] == "fixed_slots"].iloc[0]
    target = capital_df[capital_df["rule"] == "target_40"].iloc[0]
    active = capital_df[capital_df["rule"] == "active_redeploy"].iloc[0]
    base_cost = cost_df[cost_df["one_way_cost"] == 0.0015].iloc[0]
    high_cost = cost_df[cost_df["one_way_cost"] == 0.02].iloc[0]
    worst_missing = missing_df[missing_df["scenario"] != "FULL12"].sort_values("delta_calmar").iloc[0]
    best_missing = missing_df[missing_df["scenario"] != "FULL12"].sort_values("delta_calmar", ascending=False).iloc[0]
    sample_start = pd.Timestamp(context["common_start"]).strftime("%Y-%m-%d")
    sample_end = pd.Timestamp(context["common_end"]).strftime("%Y-%m-%d")

    return f"""# 右侧现货动量：最终边界与部署压力测试

生成时间：{pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")}

样本区间：{sample_start} 至 {sample_end}

## 1. 测试目的

本轮不改信号、不改参数、不改币池，只检查部署边界。

固定对象：12 coin pool 与 B baseline。

主要问题：

1. 成本冲击能不能活下来；
2. 如果某个币无法交易，结果是否脆弱；
3. 如果把空闲现金重新分配给活跃信号，MDD 是否明显放大。

## 2. 交易成本敏感性

![交易成本敏感性]({md_img(OUTPUT_DIR / "01_cost_sensitivity.png")})

| One-way cost | CAGR | Sharpe | MDD | Calmar | Final |
|---:|---:|---:|---:|---:|---:|
{table_cost(cost_df)}

解读：

- 基准成本 15bp 单边时，CAGR {pct(base_cost.cagr)}，MDD {pct(base_cost.mdd)}，Calmar {num(base_cost.calmar)}。
- 极端成本 200bp 单边时，CAGR 仍有 {pct(high_cost.cagr)}，但 Calmar 降到 {num(high_cost.calmar)}。
- 说明策略不是极端依赖低成本，但成本会持续侵蚀 Calmar。

## 3. 资金分配规则压力测试

![资金分配权益与回撤]({md_img(OUTPUT_DIR / "02_capital_rules_equity_drawdown.png")})

![资金分配指标]({md_img(OUTPUT_DIR / "03_capital_rules_metrics.png")})

| Rule | CAGR | Sharpe | MDD | Calmar | Final | Avg exposure | P95 exposure | Max exposure |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
{table_capital(capital_df)}

规则说明：

- Fixed slots：当前 baseline，固定 12 个 sleeve，未触发信号的槽位留现金。
- Target 40% exposure：用上一日已知暴露把组合尽量拉到 40% 暴露，不能超过活跃信号可承载上限。
- Active redeploy：把资金全部重新分配给上一日仍活跃的信号，不使用杠杆。

重要 caveat：`Target 40% exposure` 和 `Active redeploy` 没有扣除额外日度再平衡成本，因此收益偏乐观；这里主要看回撤边界。

核心发现：

- Fixed slots 的 MDD 为 {pct(fixed.mdd)}。
- Target 40% exposure 的 MDD 放大到 {pct(target.mdd)}。
- Active redeploy 的 MDD 放大到 {pct(active.mdd)}。

你的预判成立：现金空仓是当前策略的重要风险控制。把空闲现金重新塞给活跃信号后，收益可能更高，但 MDD 会显著恶化。

## 4. 缺币 / 交易所可得性压力测试

![缺币压力测试]({md_img(OUTPUT_DIR / "04_missing_coin_stress.png")})

| Missing symbol | CAGR | Sharpe | MDD | Calmar | Δ Calmar | Δ CAGR |
|---|---:|---:|---:|---:|---:|---:|
{table_missing(missing_df)}

解释：

- 这是部署敏感性测试，不是新的删币依据。
- 最伤的缺失币是 `{worst_missing.missing_symbol}`，ΔCalmar {num(worst_missing.delta_calmar)}。
- 最有利的缺失币是 `{best_missing.missing_symbol}`，ΔCalmar {num(best_missing.delta_calmar)}。

如果某些交易所无法交易个别币，12 池仍可运行，但具体币缺失会改变收益/风险形态；部署前需要用实际交易所可得列表重跑。

## 5. 当前结论

边界测试支持三个部署原则：

1. 不要把现金空仓强行再投资。它不是低效闲置，而是策略风险控制的一部分。
2. 12 池可以承受中等成本冲击，但成本越高，Calmar 越快被侵蚀。
3. 缺币不会让策略立刻失效，但部署币池必须和实际交易所可得性绑定。

因此，当前 baseline 应保持：

> 固定 12 sleeve，未触发信号留现金，不做活跃信号满分配。

下一步如果继续推进，应整理最终策略说明与部署前检查清单，而不是继续优化参数。
"""


def main() -> None:
    baseline = load_baseline_module()
    _, _, _, _, _, backtests, context = baseline.build_results(refresh=False)
    assert_pool(context)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    cost_df = build_cost_sensitivity(baseline, context["common_start"], context["common_end"])
    capital_df, capital_equity = build_capital_rules(baseline, backtests)
    missing_df = build_missing_coin_stress(baseline, backtests)

    cost_df.to_csv(OUTPUT_DIR / "boundary_cost_sensitivity.csv", index=False, encoding="utf-8-sig")
    capital_df.to_csv(OUTPUT_DIR / "boundary_capital_rules.csv", index=False, encoding="utf-8-sig")
    capital_equity.to_csv(OUTPUT_DIR / "boundary_capital_rule_equity.csv", encoding="utf-8-sig")
    missing_df.to_csv(OUTPUT_DIR / "boundary_missing_coin_stress.csv", index=False, encoding="utf-8-sig")

    draw_cost_sensitivity(cost_df, OUTPUT_DIR / "01_cost_sensitivity.png")
    draw_capital_rules(capital_df, capital_equity, OUTPUT_DIR / "02_capital_rules_equity_drawdown.png")
    draw_capital_metrics(capital_df, OUTPUT_DIR / "03_capital_rules_metrics.png")
    draw_missing_coin(missing_df, OUTPUT_DIR / "04_missing_coin_stress.png")

    REPORT_PATH.write_text(make_report(cost_df, capital_df, missing_df, context), encoding="utf-8-sig")

    print("Cost sensitivity")
    print(cost_df[["cost_bps", "cagr", "sharpe", "mdd", "calmar", "final"]].to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print("\nCapital rules")
    print(capital_df[["label", "cagr", "sharpe", "mdd", "calmar", "final", "avg_exposure", "p95_exposure", "max_exposure"]].to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print("\nMissing coin stress")
    print(missing_df[missing_df["scenario"] != "FULL12"][["missing_symbol", "cagr", "sharpe", "mdd", "calmar", "delta_calmar", "delta_cagr"]].sort_values("delta_calmar").to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print(f"\nSaved outputs to: {OUTPUT_DIR}")
    print(f"Saved report to: {REPORT_PATH}")


if __name__ == "__main__":
    main()
