from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont


SCRIPT_DIR = Path(__file__).resolve().parent
ARCHIVE_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(ARCHIVE_ROOT))

from Core.config import DEFAULT_CONFIG  # noqa: E402
from Core.data_io import load_cache_dir  # noqa: E402
from Core.indicators import add_indicators  # noqa: E402


DATA_DIR = ARCHIVE_ROOT / "spot_data_cache"
OUTPUT_DIR = ARCHIVE_ROOT / "data" / "outputs_buyhold_compare"
FIGURE_DIR = ARCHIVE_ROOT / "figures"
REPORT_PATH = ARCHIVE_ROOT / "reports" / "11_buy_hold_static_compare_report.md"

POOL12 = list(DEFAULT_CONFIG.symbols)
CORE4 = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
BTC_ONLY = ["BTCUSDT"]

POOLS = {
    "BTC_ONLY": dict(label="BTC only", symbols=BTC_ONLY, color="#255C99"),
    "CORE4": dict(label="Core4", symbols=CORE4, color="#2E7D32"),
    "POOL12": dict(label="12 coin pool", symbols=POOL12, color="#D95F02"),
}

MODEL_COLORS = {
    "Strategy": "#255C99",
    "BuyHold": "#C43C39",
    "BTC B&H": "#7A5195",
    "Core4 B&H": "#2E7D32",
    "Pool12 B&H": "#C43C39",
}

COST_RATE = 0.0015
START_DATE = pd.Timestamp("2020-01-01")
TRADING_DAYS = 365


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


def draw_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    size: int,
    fill=(30, 35, 40),
    bold: bool = False,
    anchor: str | None = None,
) -> None:
    draw.text(xy, text, font=get_font(size, bold=bold), fill=fill, anchor=anchor)


def pct(x: float) -> str:
    return "NA" if pd.isna(x) else f"{x:.2%}"


def pp(x: float) -> str:
    return "NA" if pd.isna(x) else f"{x * 100:.2f}pp"


def num(x: float) -> str:
    return "NA" if pd.isna(x) else f"{x:.2f}"


def md_img(path: Path) -> str:
    return path.resolve().as_posix()


def drawdown(equity: pd.Series) -> pd.Series:
    return equity / equity.cummax() - 1.0


def metrics(ret: pd.Series, equity: pd.Series | None = None) -> dict[str, float]:
    ret = ret.dropna()
    if equity is None:
        equity = (1.0 + ret).cumprod()
    equity = equity.loc[ret.index]
    years = max((ret.index[-1] - ret.index[0]).days, 1) / TRADING_DAYS
    final = float(equity.iloc[-1])
    cagr = final ** (1.0 / years) - 1.0 if final > 0 else -1.0
    std = float(ret.std())
    sharpe = float(ret.mean() / std * math.sqrt(TRADING_DAYS)) if std > 0 else 0.0
    mdd = float(drawdown(equity).min())
    calmar = cagr / abs(mdd) if mdd < 0 else 0.0
    return dict(cagr=cagr, sharpe=sharpe, mdd=mdd, calmar=calmar, vol=std * math.sqrt(TRADING_DAYS), final=final)


def generate_signals_rebased(df: pd.DataFrame, start: pd.Timestamp) -> pd.DataFrame:
    out = add_indicators(df, config=DEFAULT_CONFIG)
    out = out.loc[out.index >= start].copy()

    position: list[int] = []
    stop: list[float] = []
    weight: list[float] = []
    current_pos = 0
    current_stop = 0.0
    current_weight = 0.0
    highest_close = 0.0

    for _, row in out.iterrows():
        ready = (
            pd.notna(row["Upper"])
            and pd.notna(row["EMA"])
            and pd.notna(row["ATR"])
            and pd.notna(row["RVol"])
        )
        if not ready:
            position.append(0)
            stop.append(np.nan)
            weight.append(0.0)
            continue

        close = float(row["Close"])
        if current_pos == 0:
            if close > float(row["Upper"]) and close > float(row["EMA"]):
                current_pos = 1
                highest_close = close
                current_stop = highest_close - DEFAULT_CONFIG.atr_mult * float(row["ATR"])
                current_weight = min(1.0, DEFAULT_CONFIG.target_vol / max(float(row["RVol"]), DEFAULT_CONFIG.vol_floor))
        else:
            highest_close = max(highest_close, close)
            current_stop = max(current_stop, highest_close - DEFAULT_CONFIG.atr_mult * float(row["ATR"]))
            if close < current_stop:
                current_pos = 0
                current_stop = 0.0
                current_weight = 0.0

        position.append(current_pos)
        stop.append(current_stop if current_pos else np.nan)
        weight.append(current_weight)

    out["Position"] = position
    out["Stop"] = stop
    out["Weight"] = weight
    return out


def simulate_strategy(signal_df: pd.DataFrame, cost_rate: float = COST_RATE) -> pd.DataFrame:
    target_pos = signal_df["Position"].shift(1).fillna(0.0)
    target_weight = signal_df["Weight"].shift(1).fillna(0.0)

    cash = 1.0
    units = 0.0
    prev_equity = 1.0
    returns, equities, exposures, turnovers = [], [], [], []

    for dt, row in signal_df.iterrows():
        price = row["Open"]
        if pd.isna(price) or price <= 0:
            returns.append(0.0)
            equities.append(prev_equity)
            exposures.append(0.0)
            turnovers.append(0.0)
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
        prev_equity = equity

    return pd.DataFrame({"Return": returns, "Equity": equities, "Exposure": exposures, "Turnover": turnovers}, index=signal_df.index)


def simulate_buy_hold(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, cost_rate: float = COST_RATE) -> pd.DataFrame:
    index = pd.date_range(start, end, freq="D")
    prices = df["Open"].reindex(index)

    cash = 1.0
    units = 0.0
    bought = False
    prev_equity = 1.0
    returns, equities, exposures, turnovers = [], [], [], []

    for dt in index:
        price = prices.loc[dt]
        if pd.isna(price) or price <= 0:
            returns.append(0.0)
            equities.append(prev_equity)
            exposures.append(0.0 if not bought else exposures[-1] if exposures else 0.0)
            turnovers.append(0.0)
            continue

        px = float(price)
        before_equity = cash + units * px if bought else cash
        daily_return = before_equity / prev_equity - 1.0 if prev_equity > 0 else 0.0
        traded_notional = 0.0

        if not bought:
            buy_notional = before_equity / (1.0 + cost_rate)
            units = buy_notional / px
            cash = before_equity - buy_notional * (1.0 + cost_rate)
            traded_notional = buy_notional
            bought = True

        equity = cash + units * px
        if traded_notional:
            daily_return = equity / prev_equity - 1.0 if prev_equity > 0 else 0.0
        exposure = units * px / equity if equity > 0 else 0.0
        turnover = traded_notional / before_equity if before_equity > 0 else 0.0

        returns.append(daily_return)
        equities.append(equity)
        exposures.append(exposure)
        turnovers.append(turnover)
        prev_equity = equity

    return pd.DataFrame({"Return": returns, "Equity": equities, "Exposure": exposures, "Turnover": turnovers}, index=index)


def portfolio_series(symbol_frames: dict[str, pd.DataFrame], symbols: list[str], index: pd.DatetimeIndex, column: str) -> pd.Series:
    panel = pd.concat([symbol_frames[s][column].rename(s) for s in symbols], axis=1).reindex(index).fillna(0.0)
    return panel.mean(axis=1)


def portfolio_from_symbol_frames(
    symbol_frames: dict[str, pd.DataFrame],
    symbols: list[str],
    index: pd.DatetimeIndex,
) -> pd.DataFrame:
    equity_panel = pd.concat([symbol_frames[s]["Equity"].rename(s) for s in symbols], axis=1).reindex(index).ffill().fillna(1.0)
    exposure_panel = pd.concat([symbol_frames[s]["Exposure"].rename(s) for s in symbols], axis=1).reindex(index).fillna(0.0)
    turnover_panel = pd.concat([symbol_frames[s]["Turnover"].rename(s) for s in symbols], axis=1).reindex(index).fillna(0.0)

    equity = equity_panel.mean(axis=1)
    ret = equity.pct_change().fillna(equity.iloc[0] - 1.0)
    total_equity = equity_panel.sum(axis=1).replace(0.0, np.nan)
    exposure = (exposure_panel * equity_panel).sum(axis=1) / total_equity
    turnover = turnover_panel.mean(axis=1)
    return pd.DataFrame({"Return": ret, "Equity": equity, "Exposure": exposure.fillna(0.0), "Turnover": turnover}, index=index)


def pool_start(data: dict[str, pd.DataFrame], symbols: list[str]) -> pd.Timestamp:
    return max(pd.Timestamp(data[s].index[0]) for s in symbols)


def build_comparisons(data: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[tuple[str, str], pd.DataFrame]]:
    common_end = min(pd.Timestamp(df.index[-1]) for df in data.values())
    rows: list[dict] = []
    equity_cols: dict[str, pd.Series] = {}
    drawdown_cols: dict[str, pd.Series] = {}
    detail_frames: dict[tuple[str, str], pd.DataFrame] = {}

    scenarios: dict[str, dict] = {
        "cash_slots": dict(label="Cash slots from 2020", start_by_pool=False),
        "common_sample": dict(label="Common listed sample", start_by_pool=True),
    }

    for scenario, scenario_spec in scenarios.items():
        for pool, pool_spec in POOLS.items():
            symbols = pool_spec["symbols"]
            start = pool_start(data, symbols) if scenario_spec["start_by_pool"] else START_DATE
            index = pd.date_range(start, common_end, freq="D")

            strategy_frames = {
                symbol: simulate_strategy(generate_signals_rebased(data[symbol], start), cost_rate=COST_RATE)
                for symbol in symbols
            }
            buyhold_frames = {
                symbol: simulate_buy_hold(data[symbol], start, common_end, cost_rate=COST_RATE)
                for symbol in symbols
            }

            strategy_portfolio = portfolio_from_symbol_frames(strategy_frames, symbols, index)
            buyhold_portfolio = portfolio_from_symbol_frames(buyhold_frames, symbols, index)
            strategy_ret = strategy_portfolio["Return"]
            buyhold_ret = buyhold_portfolio["Return"]
            strategy_eq = strategy_portfolio["Equity"]
            buyhold_eq = buyhold_portfolio["Equity"]
            strategy_vol = float(strategy_ret.std() * math.sqrt(TRADING_DAYS))
            buyhold_vol = float(buyhold_ret.std() * math.sqrt(TRADING_DAYS))
            samevol_scale = strategy_vol / buyhold_vol if buyhold_vol > 0 else 0.0
            samevol_buyhold_ret = buyhold_ret * samevol_scale
            samevol_buyhold_eq = (1.0 + samevol_buyhold_ret).cumprod()
            strategy_exposure = strategy_portfolio["Exposure"]
            buyhold_exposure = buyhold_portfolio["Exposure"]
            strategy_turnover = strategy_portfolio["Turnover"]
            buyhold_turnover = buyhold_portfolio["Turnover"]

            strategy_metrics = metrics(strategy_ret, strategy_eq)
            buyhold_metrics = metrics(buyhold_ret, buyhold_eq)
            samevol_metrics = metrics(samevol_buyhold_ret, samevol_buyhold_eq)

            row = {
                "scenario": scenario,
                "scenario_label": scenario_spec["label"],
                "pool": pool,
                "pool_label": pool_spec["label"],
                "symbols": ",".join(symbols),
                "start": start.date().isoformat(),
                "end": common_end.date().isoformat(),
                "n_days": len(index),
                "strategy_avg_exposure": float(strategy_exposure.mean()),
                "buyhold_avg_exposure": float(buyhold_exposure.mean()),
                "strategy_total_turnover": float(strategy_turnover.sum() / len(symbols)),
                "buyhold_total_turnover": float(buyhold_turnover.sum() / len(symbols)),
                "samevol_scale": samevol_scale,
            }
            for key, value in strategy_metrics.items():
                row[f"strategy_{key}"] = value
            for key, value in buyhold_metrics.items():
                row[f"buyhold_{key}"] = value
            for key, value in samevol_metrics.items():
                row[f"samevol_buyhold_{key}"] = value
            row["delta_cagr"] = row["strategy_cagr"] - row["buyhold_cagr"]
            row["mdd_reduction"] = abs(row["buyhold_mdd"]) - abs(row["strategy_mdd"])
            row["delta_sharpe"] = row["strategy_sharpe"] - row["buyhold_sharpe"]
            row["delta_calmar"] = row["strategy_calmar"] - row["buyhold_calmar"]
            row["calmar_ratio"] = row["strategy_calmar"] / row["buyhold_calmar"] if row["buyhold_calmar"] != 0 else np.nan
            row["final_ratio"] = row["strategy_final"] / row["buyhold_final"] if row["buyhold_final"] != 0 else np.nan
            row["samevol_delta_cagr"] = row["strategy_cagr"] - row["samevol_buyhold_cagr"]
            row["samevol_mdd_reduction"] = abs(row["samevol_buyhold_mdd"]) - abs(row["strategy_mdd"])
            row["samevol_calmar_ratio"] = row["strategy_calmar"] / row["samevol_buyhold_calmar"] if row["samevol_buyhold_calmar"] != 0 else np.nan
            row["samevol_final_ratio"] = row["strategy_final"] / row["samevol_buyhold_final"] if row["samevol_buyhold_final"] != 0 else np.nan
            rows.append(row)

            prefix = f"{scenario}_{pool}"
            equity_cols[f"{prefix}_strategy"] = strategy_eq
            equity_cols[f"{prefix}_buyhold"] = buyhold_eq
            drawdown_cols[f"{prefix}_strategy"] = drawdown(strategy_eq)
            drawdown_cols[f"{prefix}_buyhold"] = drawdown(buyhold_eq)
            detail_frames[(scenario, pool)] = pd.DataFrame(
                {
                    "StrategyReturn": strategy_ret,
                    "BuyHoldReturn": buyhold_ret,
                    "BuyHoldSameVolReturn": samevol_buyhold_ret,
                    "StrategyEquity": strategy_eq,
                    "BuyHoldEquity": buyhold_eq,
                    "BuyHoldSameVolEquity": samevol_buyhold_eq,
                    "StrategyDrawdown": drawdown(strategy_eq),
                    "BuyHoldDrawdown": drawdown(buyhold_eq),
                    "BuyHoldSameVolDrawdown": drawdown(samevol_buyhold_eq),
                    "StrategyExposure": strategy_exposure,
                    "BuyHoldExposure": buyhold_exposure,
                }
            )

    summary = pd.DataFrame(rows)
    equity = pd.concat(equity_cols, axis=1).sort_index()
    drawdowns = pd.concat(drawdown_cols, axis=1).sort_index()
    return summary, equity, drawdowns, detail_frames


def _line_points(series: pd.Series, box: tuple[int, int, int, int], y_min: float, y_max: float, log_scale: bool = False) -> list[tuple[int, int]]:
    x0, y0, x1, y1 = box
    clean = series.dropna()
    if clean.empty:
        return []
    vals = clean.astype(float).clip(lower=1e-9) if log_scale else clean.astype(float)
    vals = np.log(vals.to_numpy()) if log_scale else vals.to_numpy()
    yy_min = math.log(y_min) if log_scale else y_min
    yy_max = math.log(y_max) if log_scale else y_max
    span = max(yy_max - yy_min, 1e-12)
    n = len(series)
    points = []
    for i, (dt, val) in enumerate(zip(clean.index, vals)):
        pos = series.index.get_loc(dt)
        x = x0 + int((x1 - x0) * pos / max(n - 1, 1))
        y = y1 - int((y1 - y0) * (float(val) - yy_min) / span)
        points.append((x, y))
    return points


def draw_line_chart(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    series_map: dict[str, pd.Series],
    colors: dict[str, str],
    title: str,
    log_scale: bool = False,
    pct_axis: bool = False,
) -> None:
    x0, y0, x1, y1 = box
    draw.rectangle(box, outline="#D7DEE8", width=2)
    draw_text(draw, (x0, y0 - 34), title, 24, bold=True)

    all_values = pd.concat(series_map.values()).dropna()
    if log_scale:
        all_values = all_values[all_values > 0]
    if all_values.empty:
        return
    y_min = float(all_values.min())
    y_max = float(all_values.max())
    if log_scale:
        y_min = max(y_min * 0.9, 1e-6)
        y_max = y_max * 1.1
    elif pct_axis and y_max <= 0:
        y_min = min(y_min * 1.05, 0.0)
        y_max = 0.0
    elif pct_axis:
        y_min = min(y_min, 0.0)
        y_max = max(y_max, 0.0)
        pad = (y_max - y_min) * 0.08 if y_max > y_min else 0.1
        y_min = y_min - pad
        y_max = y_max + pad
    else:
        pad = (y_max - y_min) * 0.08 if y_max > y_min else 0.1
        y_min = y_min - pad
        y_max = y_max + pad

    for i in range(5):
        frac = i / 4
        y = y1 - int((y1 - y0) * frac)
        draw.line((x0, y, x1, y), fill="#EDF1F5", width=1)
        if log_scale:
            val = math.exp(math.log(y_min) + (math.log(y_max) - math.log(y_min)) * frac)
        else:
            val = y_min + (y_max - y_min) * frac
        label = pct(val) if pct_axis else f"{val:.1f}x"
        draw_text(draw, (x0 - 10, y), label, 15, fill="#5C6670", anchor="rm")

    for label, series in series_map.items():
        pts = _line_points(series, box, y_min, y_max, log_scale=log_scale)
        if len(pts) >= 2:
            draw.line(pts, fill=colors[label], width=4)

    legend_x = x0
    legend_y = y1 + 22
    for label, color in colors.items():
        if label not in series_map:
            continue
        draw.rectangle((legend_x, legend_y, legend_x + 22, legend_y + 12), fill=color)
        draw_text(draw, (legend_x + 30, legend_y - 4), label, 17, fill="#2A3238")
        legend_x += 220


def save_equity_drawdown_figure(detail_frames: dict[tuple[str, str], pd.DataFrame]) -> Path:
    path = FIGURE_DIR / "11_buyhold_01_pool12_equity_drawdown.png"
    img = Image.new("RGB", (1600, 1080), "#FFFFFF")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (70, 44), "Pool12: right-side strategy vs static Buy & Hold", 36, bold=True)
    draw_text(draw, (70, 88), "Cash-slots from 2020, next-open net with 15bp one-way cost", 22, fill="#5C6670")

    pool12 = detail_frames[("cash_slots", "POOL12")]
    core4 = detail_frames[("cash_slots", "CORE4")]
    btc = detail_frames[("cash_slots", "BTC_ONLY")]
    series_map = {
        "Pool12 Strategy": pool12["StrategyEquity"],
        "Pool12 B&H": pool12["BuyHoldEquity"],
        "Core4 B&H": core4["BuyHoldEquity"],
        "BTC B&H": btc["BuyHoldEquity"],
    }
    colors = {
        "Pool12 Strategy": "#255C99",
        "Pool12 B&H": "#C43C39",
        "Core4 B&H": "#2E7D32",
        "BTC B&H": "#7A5195",
    }
    draw_line_chart(draw, (120, 170, 1510, 560), series_map, colors, "Equity curve", log_scale=True)
    dd_map = {label: drawdown(series) for label, series in series_map.items()}
    draw_line_chart(draw, (120, 680, 1510, 980), dd_map, colors, "Drawdown", pct_axis=True)
    img.save(path)
    return path


def save_metrics_figure(summary: pd.DataFrame) -> Path:
    path = FIGURE_DIR / "11_buyhold_02_metrics_delta.png"
    data = summary[summary["scenario"] == "cash_slots"].set_index("pool").loc[["BTC_ONLY", "CORE4", "POOL12"]]

    img = Image.new("RGB", (1600, 980), "#FFFFFF")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (70, 44), "Where does the strategy beat or lag static holding?", 36, bold=True)
    draw_text(draw, (70, 88), "Raw delta CAGR is negative, while drawdown control and Calmar are positive", 22, fill="#5C6670")

    panels = [
        ("Delta CAGR", "delta_cagr", "pp", "#255C99"),
        ("MDD reduction", "mdd_reduction", "pp", "#2E7D32"),
        ("Calmar ratio", "calmar_ratio", "x", "#D95F02"),
    ]
    pool_labels = ["BTC only", "Core4", "Pool12"]
    for p_i, (title, col, unit, color) in enumerate(panels):
        x0 = 95 + p_i * 500
        y0, x1, y1 = 190, x0 + 405, 770
        draw.rectangle((x0, y0, x1, y1), outline="#D7DEE8", width=2)
        draw_text(draw, (x0 + 18, y0 + 18), title, 24, bold=True)
        vals = data[col].to_numpy(dtype=float)
        baseline = 0.0 if unit == "pp" else 1.0
        v_min = min(vals.min(), baseline)
        v_max = max(vals.max(), baseline)
        pad = (v_max - v_min) * 0.2 if v_max > v_min else 0.2
        v_min -= pad
        v_max += pad
        zero_y = y1 - 70 - int((y1 - y0 - 150) * (baseline - v_min) / max(v_max - v_min, 1e-9))
        draw.line((x0 + 50, zero_y, x1 - 30, zero_y), fill="#AAB4BF", width=2)

        for i, val in enumerate(vals):
            cx = x0 + 95 + i * 110
            bar_w = 58
            bar_y = y1 - 70 - int((y1 - y0 - 150) * (val - v_min) / max(v_max - v_min, 1e-9))
            top, bottom = sorted([zero_y, bar_y])
            draw.rectangle((cx - bar_w // 2, top, cx + bar_w // 2, bottom), fill=color)
            label = pp(val) if unit == "pp" else f"{val:.2f}x"
            draw_text(draw, (cx, top - 26), label, 18, fill="#20262D", bold=True, anchor="mm")
            draw_text(draw, (cx, y1 - 40), pool_labels[i], 17, fill="#3B4650", anchor="mm")

    note = "Positive delta means strategy has higher CAGR / lower absolute drawdown / higher Calmar than static holding."
    draw_text(draw, (95, 870), note, 22, fill="#5C6670")
    img.save(path)
    return path


def save_relative_nav_figure(detail_frames: dict[tuple[str, str], pd.DataFrame]) -> Path:
    path = FIGURE_DIR / "11_buyhold_03_relative_nav_raw.png"
    img = Image.new("RGB", (1600, 820), "#FFFFFF")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (70, 44), "Raw relative NAV: Strategy / same-pool Buy & Hold", 36, bold=True)
    draw_text(draw, (70, 88), "This is the full opportunity-cost view; below 1 means B&H has higher terminal wealth", 22, fill="#5C6670")

    series_map = {}
    colors = {}
    for pool, spec in POOLS.items():
        frame = detail_frames[("cash_slots", pool)]
        label = spec["label"]
        series_map[label] = frame["StrategyEquity"] / frame["BuyHoldEquity"]
        colors[label] = spec["color"]
    draw_line_chart(draw, (120, 180, 1510, 690), series_map, colors, "Relative equity", log_scale=False)
    img.save(path)
    return path


def save_samevol_relative_figure(detail_frames: dict[tuple[str, str], pd.DataFrame]) -> Path:
    path = FIGURE_DIR / "11_buyhold_04_relative_nav_same_vol.png"
    img = Image.new("RGB", (1600, 820), "#FFFFFF")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (70, 44), "Same-vol relative NAV: Strategy / volatility-scaled Buy & Hold", 36, bold=True)
    draw_text(draw, (70, 88), "This asks whether the rule wins after B&H is scaled down to the strategy's realized volatility", 22, fill="#5C6670")

    series_map = {}
    colors = {}
    for pool, spec in POOLS.items():
        frame = detail_frames[("cash_slots", pool)]
        label = spec["label"]
        series_map[label] = frame["StrategyEquity"] / frame["BuyHoldSameVolEquity"]
        colors[label] = spec["color"]
    draw_line_chart(draw, (120, 180, 1510, 690), series_map, colors, "Relative equity", log_scale=False)
    img.save(path)
    return path


def save_common_sample_figure(summary: pd.DataFrame) -> Path:
    path = FIGURE_DIR / "11_buyhold_05_common_sample_check.png"
    data = summary[summary["scenario"] == "common_sample"].set_index("pool").loc[["BTC_ONLY", "CORE4", "POOL12"]]

    img = Image.new("RGB", (1600, 900), "#FFFFFF")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (70, 44), "Common-sample check", 36, bold=True)
    draw_text(draw, (70, 88), "Each pool starts only after all its constituents have listed", 22, fill="#5C6670")

    headers = ["Pool", "Start", "Strategy CAGR", "B&H CAGR", "Strategy MDD", "B&H MDD", "Calmar uplift"]
    col_x = [80, 300, 500, 720, 940, 1160, 1380]
    y = 175
    draw.rectangle((60, y - 20, 1540, y + 42), fill="#EEF3F8")
    for x, header in zip(col_x, headers):
        draw_text(draw, (x, y), header, 20, bold=True)
    y += 75
    for pool in ["BTC_ONLY", "CORE4", "POOL12"]:
        row = data.loc[pool]
        values = [
            row["pool_label"],
            row["start"],
            pct(row["strategy_cagr"]),
            pct(row["buyhold_cagr"]),
            pct(row["strategy_mdd"]),
            pct(row["buyhold_mdd"]),
            f"{row['calmar_ratio']:.2f}x",
        ]
        draw.line((60, y - 18, 1540, y - 18), fill="#E1E7EE", width=1)
        for x, value in zip(col_x, values):
            draw_text(draw, (x, y), str(value), 21, fill="#20262D")
        y += 74

    draw_text(draw, (80, 650), "Purpose", 24, bold=True)
    draw_text(
        draw,
        (80, 695),
        "This separates the alpha test from the listing-time effect. If Pool12 still improves risk efficiency here,",
        21,
        fill="#3B4650",
    )
    draw_text(
        draw,
        (80, 730),
        "the conclusion is not only driven by cash slots before SOL / AVAX / NEAR / UNI existed.",
        21,
        fill="#3B4650",
    )
    img.save(path)
    return path


def rolling_window_metrics(detail_frames: dict[tuple[str, str], pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict] = []
    for scenario in ["cash_slots", "common_sample"]:
        for pool, pool_spec in POOLS.items():
            frame = detail_frames[(scenario, pool)].dropna(subset=["StrategyEquity", "BuyHoldEquity"])
            first = pd.Timestamp(frame.index[0])
            last = pd.Timestamp(frame.index[-1])
            for years in [1, 2, 3]:
                latest_start = last - pd.DateOffset(years=years) + pd.DateOffset(days=1)
                if latest_start < first:
                    continue
                starts = [first]
                starts.extend(pd.date_range(first + pd.offsets.MonthBegin(1), latest_start, freq="MS"))
                starts = sorted(set(pd.Timestamp(s) for s in starts if pd.Timestamp(s) <= latest_start))
                for start in starts:
                    end = start + pd.DateOffset(years=years) - pd.DateOffset(days=1)
                    seg = frame.loc[start:end].copy()
                    if len(seg) < int(365 * years * 0.90):
                        continue

                    strategy_eq = seg["StrategyEquity"] / float(seg["StrategyEquity"].iloc[0])
                    buyhold_eq = seg["BuyHoldEquity"] / float(seg["BuyHoldEquity"].iloc[0])
                    strategy_ret = strategy_eq.pct_change().fillna(0.0)
                    buyhold_ret = buyhold_eq.pct_change().fillna(0.0)
                    strategy_vol = float(strategy_ret.std() * math.sqrt(TRADING_DAYS))
                    buyhold_vol = float(buyhold_ret.std() * math.sqrt(TRADING_DAYS))
                    scale = strategy_vol / buyhold_vol if buyhold_vol > 0 else 0.0
                    samevol_ret = buyhold_ret * scale
                    samevol_eq = (1.0 + samevol_ret).cumprod()

                    strategy_m = metrics(strategy_ret, strategy_eq)
                    buyhold_m = metrics(buyhold_ret, buyhold_eq)
                    samevol_m = metrics(samevol_ret, samevol_eq)

                    row = {
                        "scenario": scenario,
                        "pool": pool,
                        "pool_label": pool_spec["label"],
                        "window_years": years,
                        "start": start.date().isoformat(),
                        "end": pd.Timestamp(seg.index[-1]).date().isoformat(),
                        "n_days": len(seg),
                        "samevol_scale": scale,
                    }
                    for key, value in strategy_m.items():
                        row[f"strategy_{key}"] = value
                    for key, value in buyhold_m.items():
                        row[f"buyhold_{key}"] = value
                    for key, value in samevol_m.items():
                        row[f"samevol_buyhold_{key}"] = value
                    row["delta_cagr"] = row["strategy_cagr"] - row["buyhold_cagr"]
                    row["samevol_delta_cagr"] = row["strategy_cagr"] - row["samevol_buyhold_cagr"]
                    row["mdd_reduction"] = abs(row["buyhold_mdd"]) - abs(row["strategy_mdd"])
                    row["samevol_mdd_reduction"] = abs(row["samevol_buyhold_mdd"]) - abs(row["strategy_mdd"])
                    row["delta_sharpe"] = row["strategy_sharpe"] - row["buyhold_sharpe"]
                    row["delta_calmar"] = row["strategy_calmar"] - row["buyhold_calmar"]
                    row["samevol_delta_calmar"] = row["strategy_calmar"] - row["samevol_buyhold_calmar"]
                    row["calmar_ratio"] = row["strategy_calmar"] / row["buyhold_calmar"] if row["buyhold_calmar"] != 0 else np.nan
                    row["samevol_calmar_ratio"] = row["strategy_calmar"] / row["samevol_buyhold_calmar"] if row["samevol_buyhold_calmar"] != 0 else np.nan
                    row["raw_cagr_win"] = row["delta_cagr"] > 0
                    row["samevol_cagr_win"] = row["samevol_delta_cagr"] > 0
                    row["mdd_better"] = row["mdd_reduction"] > 0
                    row["samevol_mdd_better"] = row["samevol_mdd_reduction"] > 0
                    row["sharpe_win"] = row["delta_sharpe"] > 0
                    row["calmar_win"] = row["delta_calmar"] > 0
                    row["samevol_calmar_win"] = row["samevol_delta_calmar"] > 0
                    rows.append(row)
    return pd.DataFrame(rows)


def summarize_rolling(rolling: pd.DataFrame, scenario: str = "common_sample") -> pd.DataFrame:
    view = rolling[rolling["scenario"] == scenario].copy()
    grouped = view.groupby(["scenario", "pool", "pool_label", "window_years"], as_index=False)
    return grouped.agg(
        n_windows=("start", "count"),
        raw_cagr_win_rate=("raw_cagr_win", "mean"),
        samevol_cagr_win_rate=("samevol_cagr_win", "mean"),
        mdd_better_rate=("mdd_better", "mean"),
        samevol_mdd_better_rate=("samevol_mdd_better", "mean"),
        sharpe_win_rate=("sharpe_win", "mean"),
        calmar_win_rate=("calmar_win", "mean"),
        samevol_calmar_win_rate=("samevol_calmar_win", "mean"),
        median_delta_cagr=("delta_cagr", "median"),
        median_samevol_delta_cagr=("samevol_delta_cagr", "median"),
        median_mdd_reduction=("mdd_reduction", "median"),
        median_samevol_mdd_reduction=("samevol_mdd_reduction", "median"),
        median_calmar_ratio=("calmar_ratio", "median"),
        median_samevol_calmar_ratio=("samevol_calmar_ratio", "median"),
    )


def save_rolling_win_rate_figure(rolling_summary: pd.DataFrame) -> Path:
    path = FIGURE_DIR / "11_buyhold_06_rolling_win_rates.png"
    data = rolling_summary.set_index(["pool", "window_years"]).sort_index()
    img = Image.new("RGB", (1700, 1080), "#FFFFFF")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (70, 44), "Rolling start-date test: win rates vs Buy & Hold", 36, bold=True)
    draw_text(draw, (70, 88), "Common-sample, monthly rolling starts; windows overlap, so this is sensitivity evidence rather than independent OOS", 22, fill="#5C6670")

    headers = ["Pool", "Window", "N", "Raw CAGR win", "Same-vol CAGR win", "MDD better", "Sharpe win", "Calmar win"]
    col_x = [70, 290, 430, 545, 775, 1060, 1260, 1455]
    y = 175
    draw.rectangle((50, y - 22, 1650, y + 42), fill="#EEF3F8")
    for x, header in zip(col_x, headers):
        draw_text(draw, (x, y), header, 19, bold=True)
    y += 70

    for pool in ["BTC_ONLY", "CORE4", "POOL12"]:
        for years in [1, 2, 3]:
            if (pool, years) not in data.index:
                continue
            row = data.loc[(pool, years)]
            values = [
                row["pool_label"],
                f"{years}Y",
                f"{int(row['n_windows'])}",
                pct(row["raw_cagr_win_rate"]),
                pct(row["samevol_cagr_win_rate"]),
                pct(row["mdd_better_rate"]),
                pct(row["sharpe_win_rate"]),
                pct(row["calmar_win_rate"]),
            ]
            draw.line((50, y - 18, 1650, y - 18), fill="#E1E7EE", width=1)
            for i, (x, value) in enumerate(zip(col_x, values)):
                fill = "#20262D"
                if i >= 3:
                    rate = float(str(value).strip("%")) / 100.0
                    fill = "#2E7D32" if rate >= 0.65 else "#D95F02" if rate >= 0.45 else "#C43C39"
                draw_text(draw, (x, y), value, 20, fill=fill, bold=i >= 3)
            y += 58
        y += 18

    draw_text(draw, (70, 980), "Read: raw CAGR win can be low while MDD / Sharpe / Calmar win rates remain high; that is the risk-efficiency profile.", 21, fill="#5C6670")
    img.save(path)
    return path


def save_rolling_pool12_distribution_figure(rolling: pd.DataFrame) -> Path:
    path = FIGURE_DIR / "11_buyhold_07_pool12_rolling_distributions.png"
    data = rolling[(rolling["scenario"] == "common_sample") & (rolling["pool"] == "POOL12")].copy()
    metrics_to_plot = [
        ("Raw delta CAGR", "delta_cagr", "#255C99"),
        ("Same-vol delta CAGR", "samevol_delta_cagr", "#2E7D32"),
        ("MDD reduction", "mdd_reduction", "#D95F02"),
    ]

    img = Image.new("RGB", (1700, 980), "#FFFFFF")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (70, 44), "Pool12 rolling distributions", 36, bold=True)
    draw_text(draw, (70, 88), "Median and interquartile range across monthly rolling starts", 22, fill="#5C6670")

    for panel_i, (title, col, color) in enumerate(metrics_to_plot):
        x0 = 90 + panel_i * 535
        y0, x1, y1 = 180, x0 + 450, 795
        draw.rectangle((x0, y0, x1, y1), outline="#D7DEE8", width=2)
        draw_text(draw, (x0 + 18, y0 + 18), title, 23, bold=True)
        vals_all = data[col].dropna()
        v_min = min(float(vals_all.min()), 0.0)
        v_max = max(float(vals_all.max()), 0.0)
        pad = (v_max - v_min) * 0.15 if v_max > v_min else 0.1
        v_min -= pad
        v_max += pad
        zero_y = y1 - 70 - int((y1 - y0 - 150) * (0.0 - v_min) / max(v_max - v_min, 1e-9))
        draw.line((x0 + 60, zero_y, x1 - 40, zero_y), fill="#AAB4BF", width=2)

        for idx, years in enumerate([1, 2, 3]):
            vals = data[data["window_years"] == years][col].dropna()
            if vals.empty:
                continue
            q25, med, q75 = vals.quantile([0.25, 0.50, 0.75])
            cx = x0 + 105 + idx * 125
            def y_for(v: float) -> int:
                return y1 - 70 - int((y1 - y0 - 150) * (float(v) - v_min) / max(v_max - v_min, 1e-9))

            y25, ymed, y75 = y_for(q25), y_for(med), y_for(q75)
            top, bottom = sorted([y25, y75])
            draw.rectangle((cx - 32, top, cx + 32, bottom), fill=color)
            draw.line((cx - 42, ymed, cx + 42, ymed), fill="#20262D", width=4)
            draw_text(draw, (cx, top - 24), pp(float(med)), 17, fill="#20262D", bold=True, anchor="mm")
            draw_text(draw, (cx, y1 - 38), f"{years}Y", 18, fill="#3B4650", anchor="mm")

    draw_text(draw, (90, 890), "Boxes show P25-P75; label is median. Positive values favor the strategy.", 21, fill="#5C6670")
    img.save(path)
    return path


def table_for_report(summary: pd.DataFrame, scenario: str) -> str:
    cols = [
        "pool_label",
        "start",
        "strategy_cagr",
        "buyhold_cagr",
        "delta_cagr",
        "strategy_mdd",
        "buyhold_mdd",
        "mdd_reduction",
        "strategy_sharpe",
        "buyhold_sharpe",
        "strategy_calmar",
        "buyhold_calmar",
        "calmar_ratio",
        "strategy_final",
        "buyhold_final",
        "final_ratio",
        "strategy_avg_exposure",
        "buyhold_avg_exposure",
    ]
    view = summary[summary["scenario"] == scenario].set_index("pool").loc[["BTC_ONLY", "CORE4", "POOL12"]][cols]
    lines = [
        "| Pool | Start | Strat CAGR | B&H CAGR | Delta CAGR | Strat MDD | B&H MDD | MDD reduction | Strat Sharpe | B&H Sharpe | Strat Calmar | B&H Calmar | Calmar ratio | Strat Final | B&H Final | Final ratio | Strat avg exposure | B&H avg exposure |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for _, row in view.iterrows():
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["pool_label"]),
                    str(row["start"]),
                    pct(row["strategy_cagr"]),
                    pct(row["buyhold_cagr"]),
                    pp(row["delta_cagr"]),
                    pct(row["strategy_mdd"]),
                    pct(row["buyhold_mdd"]),
                    pp(row["mdd_reduction"]),
                    num(row["strategy_sharpe"]),
                    num(row["buyhold_sharpe"]),
                    num(row["strategy_calmar"]),
                    num(row["buyhold_calmar"]),
                    f"{row['calmar_ratio']:.2f}x",
                    f"{row['strategy_final']:.2f}x",
                    f"{row['buyhold_final']:.2f}x",
                    f"{row['final_ratio']:.2f}x",
                    pct(row["strategy_avg_exposure"]),
                    pct(row["buyhold_avg_exposure"]),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def rolling_table_for_report(rolling_summary: pd.DataFrame) -> str:
    view = rolling_summary.set_index(["pool", "window_years"]).sort_index()
    lines = [
        "| Pool | Window | N | Raw CAGR win | Same-vol CAGR win | MDD better | Sharpe win | Calmar win | Median raw delta CAGR | Median same-vol delta CAGR | Median MDD reduction | Median Calmar ratio |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for pool in ["BTC_ONLY", "CORE4", "POOL12"]:
        for years in [1, 2, 3]:
            if (pool, years) not in view.index:
                continue
            row = view.loc[(pool, years)]
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(row["pool_label"]),
                        f"{years}Y",
                        f"{int(row['n_windows'])}",
                        pct(row["raw_cagr_win_rate"]),
                        pct(row["samevol_cagr_win_rate"]),
                        pct(row["mdd_better_rate"]),
                        pct(row["sharpe_win_rate"]),
                        pct(row["calmar_win_rate"]),
                        pp(row["median_delta_cagr"]),
                        pp(row["median_samevol_delta_cagr"]),
                        pp(row["median_mdd_reduction"]),
                        f"{row['median_calmar_ratio']:.2f}x",
                    ]
                )
                + " |"
            )
    return "\n".join(lines)


def pool12_rolling_takeaway(rolling_summary: pd.DataFrame, years: int) -> pd.Series:
    row = rolling_summary[(rolling_summary["pool"] == "POOL12") & (rolling_summary["window_years"] == years)]
    if row.empty:
        raise ValueError(f"No Pool12 rolling summary for {years}Y")
    return row.iloc[0]


def samevol_table_for_report(summary: pd.DataFrame, scenario: str) -> str:
    cols = [
        "pool_label",
        "samevol_scale",
        "strategy_cagr",
        "samevol_buyhold_cagr",
        "samevol_delta_cagr",
        "strategy_mdd",
        "samevol_buyhold_mdd",
        "samevol_mdd_reduction",
        "strategy_calmar",
        "samevol_buyhold_calmar",
        "samevol_calmar_ratio",
        "strategy_final",
        "samevol_buyhold_final",
        "samevol_final_ratio",
    ]
    view = summary[summary["scenario"] == scenario].set_index("pool").loc[["BTC_ONLY", "CORE4", "POOL12"]][cols]
    lines = [
        "| Pool | B&H scale | Strat CAGR | Same-vol B&H CAGR | Delta CAGR | Strat MDD | Same-vol B&H MDD | MDD reduction | Strat Calmar | Same-vol B&H Calmar | Calmar ratio | Strat Final | Same-vol B&H Final | Final ratio |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for _, row in view.iterrows():
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["pool_label"]),
                    pct(row["samevol_scale"]),
                    pct(row["strategy_cagr"]),
                    pct(row["samevol_buyhold_cagr"]),
                    pp(row["samevol_delta_cagr"]),
                    pct(row["strategy_mdd"]),
                    pct(row["samevol_buyhold_mdd"]),
                    pp(row["samevol_mdd_reduction"]),
                    num(row["strategy_calmar"]),
                    num(row["samevol_buyhold_calmar"]),
                    f"{row['samevol_calmar_ratio']:.2f}x",
                    f"{row['strategy_final']:.2f}x",
                    f"{row['samevol_buyhold_final']:.2f}x",
                    f"{row['samevol_final_ratio']:.2f}x",
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def write_report(summary: pd.DataFrame, rolling_summary: pd.DataFrame, figures: list[Path]) -> None:
    cash = summary[summary["scenario"] == "cash_slots"].set_index("pool")
    pool12 = cash.loc["POOL12"]
    core4 = cash.loc["CORE4"]
    btc = cash.loc["BTC_ONLY"]
    pool12_roll_2y = pool12_rolling_takeaway(rolling_summary, 2)
    pool12_roll_3y = pool12_rolling_takeaway(rolling_summary, 3)

    text = f"""# 右侧现货动量：静态 Buy & Hold 基准对比

生成时间：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}

本轮只补一个机会成本基准，不优化参数，不改变币池，不新增过滤器。

对比目的：确认右侧 long-only 策略相对于最朴素的静态持有，到底是提高收益、降低回撤，还是只是承受了更少风险暴露。

## 1. 对比口径

- 策略：固定 sleeve，收盘确认信号，次日开盘执行，单边成本 15bp。
- Buy & Hold：同一币池初始等权买入，买入后固定 units，不再平衡，买入成本同样按 15bp 扣除。
- `cash_slots`：从 2020-01-01 起算；未上市 / 无数据的币视为现金，上市后才买入或等待策略信号。
- `common_sample`：每个币池从所有成分币都有数据的日期起算，用于排除上市时间差异。

## 2. Cash-slots 主结果：原始静态持有

![Pool12 equity and drawdown]({md_img(figures[0])})

![Metric deltas]({md_img(figures[1])})

{table_for_report(summary, "cash_slots")}

解读：

- Pool12 策略 CAGR 为 {pct(pool12['strategy_cagr'])}，静态 B&H 为 {pct(pool12['buyhold_cagr'])}，年化差为 {pp(pool12['delta_cagr'])}。
- Pool12 策略 MDD 为 {pct(pool12['strategy_mdd'])}，静态 B&H 为 {pct(pool12['buyhold_mdd'])}，回撤改善 {pp(pool12['mdd_reduction'])}。
- Pool12 策略 Calmar 为 {num(pool12['strategy_calmar'])}，静态 B&H 为 {num(pool12['buyhold_calmar'])}，Calmar 倍数为 {pool12['calmar_ratio']:.2f}x。
- 策略平均暴露只有 {pct(pool12['strategy_avg_exposure'])}，B&H 平均暴露为 {pct(pool12['buyhold_avg_exposure'])}。这说明优势不是来自更高仓位，而是来自趋势确认、现金过滤和退出规则。
- 必须明确：原始静态 B&H 的 CAGR 和终值更高，尤其 12 币池。策略没有赢绝对终值，它赢的是回撤控制、Sharpe 和 Calmar。

## 3. Raw 相对净值

![Relative NAV]({md_img(figures[2])})

`Strategy / Buy & Hold` 是完整机会成本视角。Pool12 原始 B&H 因为长期满仓持有高弹性币，终值大幅高于策略；这说明如果投资者能承受接近 80% 的回撤，静态持有在本样本内有更高绝对收益。

## 4. 同波动 B&H 检查

![Same-vol relative NAV]({md_img(figures[3])})

{samevol_table_for_report(summary, "cash_slots")}

解读：

- 同波动口径不是替代原始 B&H，而是回答风险效率问题：如果把 B&H 降杠杆 / 留现金到和策略相同波动，谁的收益更高。
- Pool12 同波动 B&H CAGR 为 {pct(pool12['samevol_buyhold_cagr'])}，策略为 {pct(pool12['strategy_cagr'])}，策略高出 {pp(pool12['samevol_delta_cagr'])}。
- Pool12 同波动 B&H MDD 为 {pct(pool12['samevol_buyhold_mdd'])}，策略 MDD 为 {pct(pool12['strategy_mdd'])}，策略仍改善 {pp(pool12['samevol_mdd_reduction'])}。
- 这说明策略的价值更准确地说是“风险效率 alpha”，不是无条件打败满仓 B&H 的终值 alpha。

## 5. Common-sample 检查

![Common sample]({md_img(figures[4])})

{table_for_report(summary, "common_sample")}

解读：

- Common-sample 的作用是避免“12 币池早期有些币没上市，所以现金槽位降低了回撤”的解释风险。
- 在这个口径下，Pool12 仍然主要通过更低回撤和更高 Calmar 体现优势；这支持策略 alpha 不是单纯由上市时间差造成。
- BTC only 与 Core4 的结果用于确认：策略不是只靠一个币池定义取胜，而是在不同静态持有基准下都能体现风险效率改善。

## 6. 滚动起点验证

![Rolling win rates]({md_img(figures[5])})

![Pool12 rolling distributions]({md_img(figures[6])})

{rolling_table_for_report(rolling_summary)}

解释：

- 滚动窗口使用 common-sample 口径、月度起点、1/2/3 年固定窗口；窗口高度重叠，所以它是起点敏感性检验，不是 18 个独立样本。
- Pool12 在 2 年窗口里，原始 CAGR 胜率为 {pct(pool12_roll_2y['raw_cagr_win_rate'])}，但 MDD 改善胜率为 {pct(pool12_roll_2y['mdd_better_rate'])}，Sharpe 胜率为 {pct(pool12_roll_2y['sharpe_win_rate'])}，Calmar 胜率为 {pct(pool12_roll_2y['calmar_win_rate'])}。
- Pool12 在 3 年窗口里，同波动 CAGR 胜率为 {pct(pool12_roll_3y['samevol_cagr_win_rate'])}，Calmar 胜率为 {pct(pool12_roll_3y['calmar_win_rate'])}，中位同波动 CAGR 差为 {pp(pool12_roll_3y['median_samevol_delta_cagr'])}。
- 因此，滚动结果不支持“策略在任意起点都赢满仓 B&H 的绝对收益”；它支持的是“多数滚动窗口里，策略改善回撤和风险效率”。

## 7. Alpha 解释

这部分验证后，可以更清楚地把 alpha 拆成两层：

1. 不是绝对收益上战胜满仓 beta：原始 B&H 的 CAGR 和终值更高，这一点不能回避。
2. 右侧规则贡献：突破 + EMA200 避免长期弱势阶段，ATR trailing exit 在趋势破坏后退出，未触发信号的 sleeve 保持现金。
3. 多币异步趋势贡献：不同币种的趋势窗口不同步，Pool12 的相对净值更稳定，说明它不是单一 BTC 择时的变体。
4. 风险效率贡献：策略用更低平均暴露，显著降低 MDD，并在同波动口径下获得更高 CAGR 和 Calmar。

## 8. 当前结论

静态 Buy & Hold 对比后的结论应更谨慎：

> 相比同币池原始静态持有，右侧现货 long-only 策略不赢绝对终值，也不应被包装成满仓 B&H 替代品；它大幅降低最大回撤，并在静态样本与滚动窗口中提高 Sharpe / Calmar。更准确的定位是风险效率 alpha，其来源是“趋势确认后的阶段性参与 + 无趋势时现金过滤 + ATR 收盘确认退出”。

下一步不建议继续参数扫描。更有价值的是把这组 Buy & Hold 对比加入终稿 PPT / 归档摘要，并进入纸面跟踪。
"""
    REPORT_PATH.write_text(text, encoding="utf-8")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

    data = load_cache_dir(DATA_DIR, symbols=POOL12)
    summary, equity, drawdowns, detail_frames = build_comparisons(data)
    rolling = rolling_window_metrics(detail_frames)
    rolling_summary = summarize_rolling(rolling, scenario="common_sample")

    summary.to_csv(OUTPUT_DIR / "11_buyhold_summary.csv", index=False, encoding="utf-8-sig")
    equity.to_csv(OUTPUT_DIR / "11_buyhold_equity_curves.csv", encoding="utf-8-sig")
    drawdowns.to_csv(OUTPUT_DIR / "11_buyhold_drawdowns.csv", encoding="utf-8-sig")
    rolling.to_csv(OUTPUT_DIR / "11_buyhold_rolling_windows.csv", index=False, encoding="utf-8-sig")
    rolling_summary.to_csv(OUTPUT_DIR / "11_buyhold_rolling_summary_common_sample.csv", index=False, encoding="utf-8-sig")
    for (scenario, pool), frame in detail_frames.items():
        frame.to_csv(OUTPUT_DIR / f"11_buyhold_detail_{scenario}_{pool}.csv", encoding="utf-8-sig")

    figures = [
        save_equity_drawdown_figure(detail_frames),
        save_metrics_figure(summary),
        save_relative_nav_figure(detail_frames),
        save_samevol_relative_figure(detail_frames),
        save_common_sample_figure(summary),
        save_rolling_win_rate_figure(rolling_summary),
        save_rolling_pool12_distribution_figure(rolling),
    ]
    write_report(summary, rolling_summary, figures)

    print(summary[["scenario", "pool", "strategy_cagr", "buyhold_cagr", "samevol_buyhold_cagr", "strategy_mdd", "buyhold_mdd", "samevol_buyhold_mdd", "strategy_calmar", "buyhold_calmar", "samevol_buyhold_calmar"]])
    print(f"report={REPORT_PATH}")


if __name__ == "__main__":
    main()
