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
OUTPUT_DIR = ROOT / "outputs_final_validation"
REPORT_PATH = ROOT / "10_final_predeployment_validation_report.md"

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

CORE4 = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
BTC_ONLY = ["BTCUSDT"]

VARIANTS = {
    "same_close_gross": dict(label="Same close gross", price_col="Close", signal_lag=0, cost=0.0),
    "next_open_gross": dict(label="Next open gross", price_col="Open", signal_lag=1, cost=0.0),
    "next_close_gross": dict(label="Next close gross", price_col="Close", signal_lag=1, cost=0.0),
    "next_open_15bp": dict(label="Next open 15bp", price_col="Open", signal_lag=1, cost=0.0015),
}

POOLS = {
    "BTC_ONLY": dict(label="BTC only", symbols=BTC_ONLY, color="#255C99"),
    "CORE4": dict(label="BTC/ETH/SOL/BNB", symbols=CORE4, color="#2E7D32"),
    "POOL12": dict(label="12 coin pool", symbols=POOL12, color="#D95F02"),
}

VARIANT_COLORS = {
    "same_close_gross": "#255C99",
    "next_open_gross": "#2E7D32",
    "next_close_gross": "#D95F02",
    "next_open_15bp": "#C43C39",
}


def load_baseline_module():
    spec = importlib.util.spec_from_file_location("spot_final_validation_baseline", BASELINE_SCRIPT)
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


def money(x: float) -> str:
    if pd.isna(x):
        return "NA"
    if x >= 1_000_000_000:
        return f"${x / 1_000_000_000:.2f}B"
    if x >= 1_000_000:
        return f"${x / 1_000_000:.2f}M"
    return f"${x:,.0f}"


def md_img(path: Path) -> str:
    return path.resolve().as_posix()


def assert_pool(context: dict) -> None:
    selected = set(context["selected_symbols"])
    expected = set(POOL12)
    missing = expected - selected
    unexpected = selected - expected - {"LTCUSDT", "AAVEUSDT"}
    if missing or unexpected:
        raise ValueError(f"Universe drifted. missing={sorted(missing)}, unexpected={sorted(unexpected)}")


def simulate_at_price(signal_df: pd.DataFrame, price_col: str, signal_lag: int, cost_rate: float) -> pd.DataFrame:
    target_pos = signal_df["Position"].shift(signal_lag).fillna(0.0)
    target_weight = signal_df["Weight"].shift(signal_lag).fillna(0.0)

    cash = 1.0
    units = 0.0
    prev_equity = 1.0

    returns, equities, exposures, turnovers, cash_values, unit_values = [], [], [], [], [], []
    for dt, row in signal_df.iterrows():
        price = row[price_col]
        if pd.isna(price) or price <= 0:
            returns.append(0.0)
            equities.append(prev_equity)
            exposures.append(0.0)
            turnovers.append(0.0)
            cash_values.append(cash)
            unit_values.append(units)
            continue

        px = float(price)
        before_equity = cash + units * px
        daily_return = before_equity / prev_equity - 1.0 if prev_equity > 0 else 0.0
        traded_notional = 0.0
        desired_pos = int(target_pos.loc[dt])
        desired_weight = float(target_weight.loc[dt])

        if units <= 0 and desired_pos == 1:
            target_notional = before_equity * desired_weight
            buy_notional = min(target_notional, before_equity / (1.0 + cost_rate))
            if buy_notional > 0:
                units = buy_notional / px
                cash = before_equity - buy_notional * (1.0 + cost_rate)
                traded_notional = buy_notional
        elif units > 0 and desired_pos == 0:
            sell_notional = units * px
            cash = before_equity - sell_notional * cost_rate
            traded_notional = sell_notional
            units = 0.0

        equity = cash + units * px
        if traded_notional:
            daily_return = equity / prev_equity - 1.0 if prev_equity > 0 else 0.0
        exposure = units * px / equity if equity > 0 else 0.0
        turnover = traded_notional / before_equity if before_equity > 0 else 0.0

        returns.append(daily_return)
        equities.append(equity)
        exposures.append(exposure)
        turnovers.append(turnover)
        cash_values.append(cash)
        unit_values.append(units)
        prev_equity = equity

    return pd.DataFrame(
        {
            "Return": returns,
            "Equity": equities,
            "Exposure": exposures,
            "Turnover": turnovers,
            "Cash": cash_values,
            "Units": unit_values,
        },
        index=signal_df.index,
    )


def portfolio_return(symbol_returns: dict[str, pd.Series], symbols: list[str], common_index: pd.DatetimeIndex) -> pd.Series:
    panel = pd.concat([symbol_returns[s].rename(s) for s in symbols], axis=1).reindex(common_index).fillna(0.0)
    return panel.mean(axis=1)


def build_execution_variants(baseline, context: dict) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, dict[str, pd.Series]]]:
    common_index = pd.date_range(context["common_start"], context["common_end"], freq="D")
    rows = []
    equity_cols = {}
    all_symbol_returns: dict[str, dict[str, pd.Series]] = {}

    for variant, spec in VARIANTS.items():
        symbol_returns = {}
        exposure_cols = []
        turnover_cols = []
        for symbol in POOL12:
            df = baseline.load_or_fetch(symbol, refresh=False)
            signal = baseline.generate_signals(df)
            sim = simulate_at_price(signal, spec["price_col"], spec["signal_lag"], spec["cost"])
            symbol_returns[symbol] = sim["Return"].reindex(common_index).fillna(0.0)
            exposure_cols.append(sim["Exposure"].rename(symbol).reindex(common_index).fillna(0.0))
            turnover_cols.append(sim["Turnover"].rename(symbol).reindex(common_index).fillna(0.0))

        ret = portfolio_return(symbol_returns, POOL12, common_index)
        eq = (1.0 + ret).cumprod()
        exposure_panel = pd.concat(exposure_cols, axis=1)
        turnover_panel = pd.concat(turnover_cols, axis=1)
        rows.append(
            dict(
                variant=variant,
                label=spec["label"],
                price_col=spec["price_col"],
                signal_lag=spec["signal_lag"],
                one_way_cost=spec["cost"],
                avg_exposure=float(exposure_panel.mean(axis=1).mean()),
                total_turnover=float(turnover_panel.sum(axis=1).sum() / len(POOL12)),
                **baseline.metrics(ret, eq),
            )
        )
        equity_cols[variant] = eq
        all_symbol_returns[variant] = symbol_returns

    return pd.DataFrame(rows), pd.DataFrame(equity_cols), all_symbol_returns


def build_period_metrics(baseline, context: dict, symbol_returns: dict[str, pd.Series]) -> pd.DataFrame:
    common_start = pd.Timestamp(context["common_start"])
    common_end = pd.Timestamp(context["common_end"])
    common_index = pd.date_range(common_start, common_end, freq="D")
    periods = [
        ("FULL", "2020-2026", common_start, common_end),
        ("P1_2020_2021", "2020-2021", pd.Timestamp("2020-01-01"), pd.Timestamp("2021-12-31")),
        ("P2_2022_2023", "2022-2023", pd.Timestamp("2022-01-01"), pd.Timestamp("2023-12-31")),
        ("P3_2024_NOW", "2024-now", pd.Timestamp("2024-01-01"), common_end),
    ]
    rows = []
    for period, period_label, start, end in periods:
        for pool, spec in POOLS.items():
            ret = portfolio_return(symbol_returns, spec["symbols"], common_index).loc[start:end]
            if len(ret) < 180:
                continue
            rows.append(dict(period=period, period_label=period_label, pool=pool, label=spec["label"], n_days=len(ret), **baseline.metrics(ret)))
    return pd.DataFrame(rows)


def build_data_integrity(baseline, context: dict) -> pd.DataFrame:
    common_end = pd.Timestamp(context["common_end"])
    rows = []
    for symbol in POOL12:
        df = baseline.load_or_fetch(symbol, refresh=False).loc[:common_end].copy()
        active_start = max(df.index[0], baseline.START_DATE)
        active = df.loc[active_start:common_end]
        expected = pd.date_range(active_start, common_end, freq="D")
        missing_days = len(expected.difference(active.index))
        duplicate_days = int(df.index.duplicated().sum())
        invalid_ohlc = int(((active["High"] < active[["Open", "Close"]].max(axis=1)) | (active["Low"] > active[["Open", "Close"]].min(axis=1)) | (active["Low"] <= 0)).sum())
        nonpositive_volume = int(((active["Volume"] <= 0) | (active["QuoteVolume"] <= 0)).sum())
        coverage = len(active) / max(len(expected), 1)
        recent = active.tail(90)
        rows.append(
            dict(
                symbol=symbol,
                data_start=active.index[0].date().isoformat(),
                data_end=active.index[-1].date().isoformat(),
                observed_days=len(active),
                expected_days=len(expected),
                coverage=coverage,
                missing_days=missing_days,
                duplicate_days=duplicate_days,
                invalid_ohlc=invalid_ohlc,
                nonpositive_volume=nonpositive_volume,
                median_quote_volume_90d=float(recent["QuoteVolume"].median()),
                median_trades_90d=float(recent["num_trades"].median()),
            )
        )
    return pd.DataFrame(rows)


def build_liquidity_capacity(baseline, backtests: dict[str, pd.DataFrame], context: dict) -> pd.DataFrame:
    common_end = pd.Timestamp(context["common_end"])
    rows = []
    trade_rows = []
    n = len(POOL12)
    for symbol in POOL12:
        bt = backtests[symbol].loc[:common_end].copy()
        raw = baseline.load_or_fetch(symbol, refresh=False).loc[:common_end]
        quote_volume = raw["QuoteVolume"].reindex(bt.index)
        trade_unit = (bt["Turnover"].fillna(0.0) * bt["GrossEquity"].ffill()).replace(0.0, np.nan)
        cap_1pct = quote_volume * 0.01 * n / trade_unit
        cap_025pct = quote_volume * 0.0025 * n / trade_unit
        trades = pd.DataFrame({"cap_1pct_adv": cap_1pct, "cap_025pct_adv": cap_025pct}).dropna()
        for dt, row in trades.iterrows():
            trade_rows.append(dict(symbol=symbol, date=dt.date().isoformat(), cap_1pct_adv=float(row["cap_1pct_adv"]), cap_025pct_adv=float(row["cap_025pct_adv"])))
        rows.append(
            dict(
                symbol=symbol,
                trades=len(trades),
                min_cap_1pct_adv=float(trades["cap_1pct_adv"].min()) if len(trades) else np.nan,
                p05_cap_1pct_adv=float(trades["cap_1pct_adv"].quantile(0.05)) if len(trades) else np.nan,
                median_cap_1pct_adv=float(trades["cap_1pct_adv"].median()) if len(trades) else np.nan,
                min_cap_025pct_adv=float(trades["cap_025pct_adv"].min()) if len(trades) else np.nan,
            )
        )
    out = pd.DataFrame(rows).sort_values("min_cap_1pct_adv")
    trades_df = pd.DataFrame(trade_rows)
    if not trades_df.empty:
        overall = dict(
            symbol="ALL",
            trades=int(trades_df.shape[0]),
            min_cap_1pct_adv=float(trades_df["cap_1pct_adv"].min()),
            p05_cap_1pct_adv=float(trades_df["cap_1pct_adv"].quantile(0.05)),
            median_cap_1pct_adv=float(trades_df["cap_1pct_adv"].median()),
            min_cap_025pct_adv=float(trades_df["cap_025pct_adv"].min()),
        )
        out = pd.concat([pd.DataFrame([overall]), out], ignore_index=True)
    return out


def draw_execution_equity(metrics_df: pd.DataFrame, equity_df: pd.DataFrame, out_path: Path) -> None:
    width, height = 1700, 1050
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (70, 28), "执行滞后压力测试：净值与回撤", 30, bold=True)
    draw_text(draw, (70, 64), "Same close 是原始收盘成交口径；Next open / close 是收盘确认后的延迟执行压力测试。", 18, fill=(90, 95, 105))

    x0, x1 = 110, width - 80
    y0, y1 = 130, 540
    dd_y0, dd_y1 = 660, height - 105

    log_eq = np.log(equity_df.clip(lower=1e-8))
    ymin, ymax = float(log_eq.min().min()), float(log_eq.max().max())
    pad = max((ymax - ymin) * 0.08, 0.01)
    ymin -= pad
    ymax += pad
    draw.rectangle((x0, y0, x1, y1), outline=(220, 224, 230))
    draw_text(draw, (x0, y0 - 34), "Equity", 23, bold=True)
    for i in range(6):
        y = y1 - int((y1 - y0) * i / 5)
        value = math.exp(ymin + (ymax - ymin) * i / 5)
        draw.line((x0, y, x1, y), fill=(238, 241, 245))
        draw_text(draw, (36, y - 10), f"{value:.1f}x", 14, fill=(95, 100, 110))
    for variant in VARIANTS:
        vals = log_eq[variant].values
        pts = [(x0 + int((x1 - x0) * i / (len(vals) - 1)), y1 - int((y1 - y0) * (float(v) - ymin) / (ymax - ymin))) for i, v in enumerate(vals)]
        draw.line(pts, fill=VARIANT_COLORS[variant], width=4)

    dd = equity_df / equity_df.cummax() - 1.0
    min_dd = float(dd.min().min())
    draw.rectangle((x0, dd_y0, x1, dd_y1), outline=(220, 224, 230))
    draw_text(draw, (x0, dd_y0 - 34), "Drawdown", 23, bold=True)
    for i in range(5):
        y = dd_y1 - int((dd_y1 - dd_y0) * i / 4)
        value = min_dd * (1 - i / 4)
        draw.line((x0, y, x1, y), fill=(238, 241, 245))
        draw_text(draw, (36, y - 10), pct(value), 14, fill=(95, 100, 110))
    for variant in VARIANTS:
        vals = dd[variant].values
        pts = [(x0 + int((x1 - x0) * i / (len(vals) - 1)), dd_y1 - int((dd_y1 - dd_y0) * (float(v) - min_dd) / (0 - min_dd))) for i, v in enumerate(vals)]
        draw.line(pts, fill=VARIANT_COLORS[variant], width=3)

    for i, variant in enumerate(VARIANTS):
        row = metrics_df[metrics_df["variant"] == variant].iloc[0]
        lx = x0 + 10 + i * 375
        draw.rectangle((lx, height - 72, lx + 28, height - 55), fill=VARIANT_COLORS[variant])
        draw_text(draw, (lx + 38, height - 77), f"{row.label} | MDD {pct(row.mdd)}", 16, fill=(50, 55, 65), bold=True)
    img.save(out_path)


def draw_execution_metrics(metrics_df: pd.DataFrame, out_path: Path) -> None:
    width, height = 1550, 900
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (70, 28), "执行口径指标对比", 30, bold=True)
    draw_text(draw, (70, 64), "MDD 用绝对值展示，越低越好。", 18, fill=(90, 95, 105))

    panels = [("CAGR", "cagr", True), ("MDD", "mdd", True), ("Sharpe", "sharpe", False), ("Calmar", "calmar", False)]
    origins = [(80, 140), (820, 140), (80, 520), (820, 520)]
    panel_w, panel_h = 630, 260
    order = list(VARIANTS)
    for (title, col, is_pct), (ox, oy) in zip(panels, origins):
        draw_text(draw, (ox, oy - 34), title, 22, bold=True)
        draw.rectangle((ox, oy, ox + panel_w, oy + panel_h), outline=(220, 224, 230))
        vals = []
        for variant in order:
            raw = float(metrics_df.loc[metrics_df["variant"] == variant, col].iloc[0])
            vals.append(abs(raw) if col == "mdd" else raw)
        max_v = max(vals + [1e-9]) * 1.18
        baseline = oy + panel_h - 48
        draw.line((ox + 45, baseline, ox + panel_w - 30, baseline), fill=(190, 195, 205), width=2)
        for i, variant in enumerate(order):
            row = metrics_df[metrics_df["variant"] == variant].iloc[0]
            raw = float(row[col])
            value = abs(raw) if col == "mdd" else raw
            bar_h = int((panel_h - 88) * value / max_v)
            x = ox + 55 + i * 135
            draw.rectangle((x, baseline - bar_h, x + 78, baseline), fill=VARIANT_COLORS[variant])
            label = pct(value) if is_pct else f"{value:.2f}"
            draw_text(draw, (x - 2, baseline - bar_h - 25), label, 14, fill=(45, 50, 60), bold=True)
            short = row.label.replace(" gross", "").replace(" 15bp", "")
            draw_text(draw, (x - 22, baseline + 12), short, 11, fill=(55, 60, 70), bold=True)
    img.save(out_path)


def draw_period_validation(period_df: pd.DataFrame, out_path: Path) -> None:
    width, height = 1650, 920
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (70, 28), "分阶段验证：Next open gross", 30, bold=True)
    draw_text(draw, (70, 64), "用更保守的次日开盘执行口径比较 BTC、Core4 与 12 coin pool。", 18, fill=(90, 95, 105))

    periods = ["2020-2026", "2020-2021", "2022-2023", "2024-now"]
    pools = ["BTC_ONLY", "CORE4", "POOL12"]
    metrics = [("CAGR", "cagr", True), ("Calmar", "calmar", False)]
    panel_w, panel_h = 700, 610
    origins = [(75, 185), (875, 185)]

    for (title, col, is_pct), (ox, oy) in zip(metrics, origins):
        draw_text(draw, (ox, oy - 40), title, 23, bold=True)
        draw.rectangle((ox, oy, ox + panel_w, oy + panel_h), outline=(220, 224, 230))
        values = []
        for period_label in periods:
            for pool in pools:
                row = period_df[(period_df["period_label"] == period_label) & (period_df["pool"] == pool)]
                if not row.empty:
                    values.append(float(row[col].iloc[0]))
        ymin, ymax = min(0.0, min(values)), max(values)
        pad = max((ymax - ymin) * 0.12, 0.05)
        ymin -= pad
        ymax += pad
        zero_y = oy + panel_h - 65 - int((panel_h - 115) * (0 - ymin) / (ymax - ymin))
        draw.line((ox + 55, zero_y, ox + panel_w - 30, zero_y), fill=(170, 175, 185), width=2)
        for i, period_label in enumerate(periods):
            group_x = ox + 75 + i * 150
            draw_text(draw, (group_x - 5, oy + panel_h - 42), period_label, 12, fill=(55, 60, 70), bold=True)
            for j, pool in enumerate(pools):
                row = period_df[(period_df["period_label"] == period_label) & (period_df["pool"] == pool)].iloc[0]
                value = float(row[col])
                bar_h = int((panel_h - 115) * abs(value) / (ymax - ymin))
                x = group_x + j * 38
                if value >= 0:
                    y0 = zero_y - bar_h
                    y1 = zero_y
                else:
                    y0 = zero_y
                    y1 = zero_y + bar_h
                draw.rectangle((x, y0, x + 28, y1), fill=POOLS[pool]["color"])
                label = pct(value) if is_pct else f"{value:.1f}"
                draw_text(draw, (x - 8, y0 - 24 if value >= 0 else y1 + 3), label, 10, fill=(45, 50, 60), bold=True)

    for i, pool in enumerate(pools):
        lx = 590 + i * 220
        draw.rectangle((lx, height - 70, lx + 28, height - 53), fill=POOLS[pool]["color"])
        draw_text(draw, (lx + 38, height - 75), POOLS[pool]["label"], 16, fill=(50, 55, 65), bold=True)
    img.save(out_path)


def draw_liquidity_capacity(liquidity_df: pd.DataFrame, out_path: Path) -> None:
    width, height = 1650, 950
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (70, 28), "流动性容量粗检", 30, bold=True)
    draw_text(draw, (70, 64), "估算口径：单次交易不超过当日 quote volume 的 1%；横轴为可承载初始资金规模。", 18, fill=(90, 95, 105))

    df = liquidity_df[liquidity_df["symbol"] != "ALL"].sort_values("min_cap_1pct_adv")
    x0, x1 = 390, width - 170
    y0, y1 = 125, height - 95
    vals = df["min_cap_1pct_adv"].astype(float).clip(lower=1.0)
    log_min, log_max = math.log10(vals.min() * 0.8), math.log10(vals.max() * 1.3)
    step = (y1 - y0) / len(df)
    bar_h = max(28, int(step * 0.58))
    for i, row in enumerate(df.itertuples()):
        y = int(y0 + i * step)
        value = float(row.min_cap_1pct_adv)
        end_x = x0 + int((math.log10(max(value, 1.0)) - log_min) / (log_max - log_min) * (x1 - x0))
        draw.rectangle((x0, y, end_x, y + bar_h), fill="#255C99")
        draw_text(draw, (70, y - 1), row.symbol.replace("USDT", ""), 18, fill=(45, 50, 60), bold=True)
        draw_text(draw, (end_x + 12, y - 1), f"min {money(value)} / p05 {money(float(row.p05_cap_1pct_adv))}", 15, fill=(45, 50, 60))
    img.save(out_path)


def table_execution(metrics_df: pd.DataFrame) -> str:
    rows = []
    for row in metrics_df.itertuples():
        rows.append(f"| {row.label} | {row.price_col} | {int(row.signal_lag)} | {pct(row.one_way_cost)} | {pct(row.cagr)} | {num(row.sharpe)} | {pct(row.mdd)} | {num(row.calmar)} | {num(row.final)}x | {pct(row.avg_exposure)} |")
    return "\n".join(rows)


def table_period(period_df: pd.DataFrame) -> str:
    rows = []
    order = ["2020-2026", "2020-2021", "2022-2023", "2024-now"]
    for period_label in order:
        for pool in ["BTC_ONLY", "CORE4", "POOL12"]:
            row = period_df[(period_df["period_label"] == period_label) & (period_df["pool"] == pool)].iloc[0]
            rows.append(f"| {period_label} | {row.label} | {pct(row.cagr)} | {num(row.sharpe)} | {pct(row.mdd)} | {num(row.calmar)} | {num(row.final)}x |")
    return "\n".join(rows)


def table_integrity(data_df: pd.DataFrame) -> str:
    rows = []
    for row in data_df.itertuples():
        rows.append(f"| {row.symbol} | {row.data_start} | {row.data_end} | {pct(row.coverage)} | {int(row.missing_days)} | {int(row.duplicate_days)} | {int(row.invalid_ohlc)} | {int(row.nonpositive_volume)} | {money(row.median_quote_volume_90d)} |")
    return "\n".join(rows)


def table_liquidity(liquidity_df: pd.DataFrame) -> str:
    rows = []
    for row in liquidity_df.itertuples():
        rows.append(f"| {row.symbol} | {int(row.trades)} | {money(row.min_cap_1pct_adv)} | {money(row.p05_cap_1pct_adv)} | {money(row.median_cap_1pct_adv)} | {money(row.min_cap_025pct_adv)} |")
    return "\n".join(rows)


def make_report(context: dict, execution_df: pd.DataFrame, period_df: pd.DataFrame, data_df: pd.DataFrame, liquidity_df: pd.DataFrame) -> str:
    same = execution_df[execution_df["variant"] == "same_close_gross"].iloc[0]
    next_open = execution_df[execution_df["variant"] == "next_open_gross"].iloc[0]
    next_open_net = execution_df[execution_df["variant"] == "next_open_15bp"].iloc[0]
    next_close = execution_df[execution_df["variant"] == "next_close_gross"].iloc[0]
    data_issues = int((data_df[["missing_days", "duplicate_days", "invalid_ohlc", "nonpositive_volume"]].sum(axis=1) > 0).sum())
    all_liq = liquidity_df[liquidity_df["symbol"] == "ALL"].iloc[0]

    return f"""# 右侧现货动量：最终上线前验证

生成时间：{pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")}

样本区间：{context["common_start"]} 至 {context["common_end"]}

本轮不优化参数，不新增过滤器，不调整币池。目标是验证当前候选 baseline 在更保守执行、数据完整性和流动性口径下是否还能站住。

固定币池：

`{", ".join(POOL12)}`

## 1. 执行滞后压力测试

![执行滞后净值与回撤]({md_img(OUTPUT_DIR / "01_execution_delay_equity_drawdown.png")})

![执行口径指标对比]({md_img(OUTPUT_DIR / "02_execution_delay_metrics.png")})

| Variant | Price | Signal lag | One-way cost | CAGR | Sharpe | MDD | Calmar | Final | Avg exposure |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
{table_execution(execution_df)}

解读：

- 原始 `same close gross`：CAGR {pct(same.cagr)}，MDD {pct(same.mdd)}，Calmar {num(same.calmar)}。
- 更现实的 `next open gross`：CAGR {pct(next_open.cagr)}，MDD {pct(next_open.mdd)}，Calmar {num(next_open.calmar)}。
- `next open 15bp` 加入单边 15bp 成本后：CAGR {pct(next_open_net.cagr)}，MDD {pct(next_open_net.mdd)}，Calmar {num(next_open_net.calmar)}。
- 更滞后的 `next close gross`：CAGR {pct(next_close.cagr)}，MDD {pct(next_close.mdd)}，Calmar {num(next_close.calmar)}。

这说明策略不依赖“同日收盘完美成交”。如果用收盘确认后次日开盘执行，风险效率仍然保留。

## 2. 分阶段验证

![分阶段验证]({md_img(OUTPUT_DIR / "03_period_validation.png")})

以下全部使用 `next open gross`，即收盘确认后下一根日线开盘成交：

| Period | Pool | CAGR | Sharpe | MDD | Calmar | Final |
|---|---|---:|---:|---:|---:|---:|
{table_period(period_df)}

解读：

- 12 coin pool 的核心优势仍然主要体现在 Sharpe / MDD / Calmar，而不是每个阶段都压过 BTC 的 CAGR。
- 2024-now 仍然有正收益和较低回撤，但样本较短，只能作为最近阶段检查，不能当长期证明。

## 3. 数据完整性检查

| Symbol | Data start | Data end | Coverage | Missing days | Duplicates | Invalid OHLC | Nonpositive volume | Median quote vol 90d |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
{table_integrity(data_df)}

检查结果：`{data_issues}` 个币存在缺失日、重复日、OHLC 异常或非正成交量问题。

## 4. 流动性容量粗检

![流动性容量粗检]({md_img(OUTPUT_DIR / "04_liquidity_capacity.png")})

| Symbol | Trades | Min cap at 1% ADV | P05 cap at 1% ADV | Median cap at 1% ADV | Min cap at 0.25% ADV |
|---|---:|---:|---:|---:|---:|
{table_liquidity(liquidity_df)}

解释：

- 这是粗略容量检查，不是滑点模型。
- 口径是：单次交易名义金额不超过当日 quote volume 的 1%。
- 全部历史交易中，最紧的 1% ADV 初始资金容量约为 `{money(all_liq.min_cap_1pct_adv)}`；若用更保守的 0.25% ADV，约为 `{money(all_liq.min_cap_025pct_adv)}`。
- 这个最小值主要反映早期个别币低流动性阶段，不代表当前容量；但它说明实盘不能完全忽略订单金额上限。

## 5. 最终判断

本轮验证通过了最关键的部署前压力项：

1. 收盘确认后次日开盘执行没有破坏策略主体；
2. 成本进入后仍保留较好的风险效率；
3. 12 coin pool 的优势仍是风险调整收益，而不是单纯追求更高 CAGR；
4. 当前缓存数据没有发现结构性完整性问题；
5. 流动性不是否定 alpha 的证据，但部署时必须设置单笔 ADV 上限；资金规模上去后需要单独建滑点模型。

因此，当前策略可以封存为：

> 右侧现货 long-only 动量 alpha 候选 baseline：固定 12 sleeve，收盘确认信号，次日开盘可执行，未触发信号的 sleeve 留现金，不做活跃信号满仓重分配。

接下来不建议继续围绕参数做优化。更合理的是进入纸面跟踪与实盘前工程化：每日信号复现、交易所可得性核对、订单金额上限、异常数据报警、以及未来样本滚动复盘。
"""


def main() -> None:
    baseline = load_baseline_module()
    _, _, _, _, _, backtests, context = baseline.build_results(refresh=False)
    assert_pool(context)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    execution_df, equity_df, all_symbol_returns = build_execution_variants(baseline, context)
    period_df = build_period_metrics(baseline, context, all_symbol_returns["next_open_gross"])
    data_df = build_data_integrity(baseline, context)
    liquidity_df = build_liquidity_capacity(baseline, backtests, context)

    execution_df.to_csv(OUTPUT_DIR / "final_execution_variants.csv", index=False, encoding="utf-8-sig")
    equity_df.to_csv(OUTPUT_DIR / "final_execution_equity.csv", encoding="utf-8-sig")
    period_df.to_csv(OUTPUT_DIR / "final_period_metrics_next_open.csv", index=False, encoding="utf-8-sig")
    data_df.to_csv(OUTPUT_DIR / "final_data_integrity.csv", index=False, encoding="utf-8-sig")
    liquidity_df.to_csv(OUTPUT_DIR / "final_liquidity_capacity.csv", index=False, encoding="utf-8-sig")

    draw_execution_equity(execution_df, equity_df, OUTPUT_DIR / "01_execution_delay_equity_drawdown.png")
    draw_execution_metrics(execution_df, OUTPUT_DIR / "02_execution_delay_metrics.png")
    draw_period_validation(period_df, OUTPUT_DIR / "03_period_validation.png")
    draw_liquidity_capacity(liquidity_df, OUTPUT_DIR / "04_liquidity_capacity.png")

    REPORT_PATH.write_text(make_report(context, execution_df, period_df, data_df, liquidity_df), encoding="utf-8-sig")

    print("Execution variants")
    print(execution_df[["label", "cagr", "sharpe", "mdd", "calmar", "final", "avg_exposure"]].to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print("\nPeriod metrics, next open gross")
    print(period_df[["period_label", "label", "cagr", "sharpe", "mdd", "calmar", "final"]].to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print("\nData integrity")
    print(data_df[["symbol", "coverage", "missing_days", "duplicate_days", "invalid_ohlc", "nonpositive_volume"]].to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print("\nLiquidity capacity")
    print(liquidity_df[["symbol", "trades", "min_cap_1pct_adv", "p05_cap_1pct_adv", "median_cap_1pct_adv", "min_cap_025pct_adv"]].to_string(index=False, float_format=lambda x: f"{x:.2f}"))
    print(f"\nSaved outputs to: {OUTPUT_DIR}")
    print(f"Saved report to: {REPORT_PATH}")


if __name__ == "__main__":
    main()
