from __future__ import annotations

import importlib.util
import math
import sys
import types
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "outputs"
SOURCE_CACHE = ROOT.parent / "策略组合试验" / "crypto 右侧CTA" / ".cache"

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
START_DATE = "2020-01-01"
COMMON_START = pd.Timestamp("2020-01-01")
TRADING_DAYS = 365

# Spot cost is reported after gross edge. It is intentionally not used to
# choose the structure in this first design pass.
SPOT_FEE = 0.0010
SPOT_SLIPPAGE = 0.0005
RF_ANNUAL = 0.0
NORMALIZED_VOL = 0.25
NORMALIZED_AVG_EXPOSURE = 0.25


@dataclass(frozen=True)
class Variant:
    key: str
    label: str
    entry_window: int
    ema_window: int
    exit_type: str
    atr_window: int = 14
    atr_mult: float = 3.0
    exit_window: int = 20
    target_vol: float = 0.40
    vol_window: int = 20
    vol_floor: float = 0.20


VARIANTS = [
    Variant(
        key="A_current_15d_atr32",
        label="A 现有结构: 15日突破 + EMA200 + 收盘确认式3.2ATR跟踪退出",
        entry_window=15,
        ema_window=200,
        exit_type="atr_trailing",
        atr_mult=3.2,
    ),
    Variant(
        key="B_canonical_20d_atr30",
        label="B 标准结构: 20日突破 + EMA200 + 收盘确认式3.0ATR跟踪退出",
        entry_window=20,
        ema_window=200,
        exit_type="atr_trailing",
        atr_mult=3.0,
    ),
    Variant(
        key="C_donchian_20d_exit",
        label="C 通道结构: 20日突破 + EMA200 + 收盘确认式20日低点退出",
        entry_window=20,
        ema_window=200,
        exit_type="donchian_low",
        atr_mult=3.0,
        exit_window=20,
    ),
]


def ensure_pickle_compat() -> None:
    """Allow reading old pandas pickles even when pyarrow is unavailable."""
    try:
        import pyarrow  # noqa: F401
        return
    except Exception:
        pass

    import pandas.core.arrays.arrow.array as arrow_array
    import pandas.core.arrays.string_ as string_array

    original_init = string_array.StringDtype.__init__

    def patched_init(self, storage=None, na_value=pd.NA):
        return original_init(self, storage="python", na_value=na_value)

    string_array.StringDtype.__init__ = patched_init

    pa = types.ModuleType("pyarrow")
    lib = types.ModuleType("pyarrow.lib")
    lib.type_for_alias = lambda alias: ("type", alias)
    lib.py_buffer = lambda payload: payload
    lib._restore_array = lambda *args, **kwargs: [
        "Open",
        "High",
        "Low",
        "Close",
        "fundingRate",
    ]
    pa.lib = lib
    pa.chunked_array = lambda data: data
    sys.modules["pyarrow"] = pa
    sys.modules["pyarrow.lib"] = lib
    arrow_array.pa = pa


def cache_file(symbol: str) -> Path:
    name = "btc_daily.pkl" if symbol == "BTCUSDT" else f"{symbol.lower()}_daily.pkl"
    return SOURCE_CACHE / name


def load_symbol(symbol: str) -> pd.DataFrame:
    ensure_pickle_compat()
    path = cache_file(symbol)
    if not path.exists():
        raise FileNotFoundError(f"Missing cache for {symbol}: {path}")
    df = pd.read_pickle(path).copy()
    df = df.set_axis(["Open", "High", "Low", "Close", "fundingRate"], axis=1)
    df.index = pd.to_datetime(df.index).tz_localize(None)
    for col in ["Open", "High", "Low", "Close", "fundingRate"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.loc[pd.Timestamp(START_DATE) :].dropna(subset=["Open", "High", "Low", "Close"])
    df["fundingRate"] = 0.0
    return df


def ema(series: pd.Series, n: int) -> pd.Series:
    return series.ewm(span=n, adjust=False).mean()


def atr(df: pd.DataFrame, n: int) -> pd.Series:
    tr = pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - df["Close"].shift(1)).abs(),
            (df["Low"] - df["Close"].shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(n).mean()


def generate_signals(df: pd.DataFrame, variant: Variant) -> pd.DataFrame:
    out = df.copy()
    out["Upper"] = out["High"].rolling(variant.entry_window).max().shift(1)
    out["Lower"] = out["Low"].rolling(variant.exit_window).min().shift(1)
    out["EMA"] = ema(out["Close"], variant.ema_window).shift(1)
    out["ATR"] = atr(out, variant.atr_window).shift(1)
    out["RVol"] = (
        out["Close"].pct_change().rolling(variant.vol_window).std() * math.sqrt(TRADING_DAYS)
    ).shift(1)

    pos, stop, weight = [], [], []
    current_pos = 0
    current_stop = 0.0
    current_weight = 0.0
    highest_close = 0.0

    for _, row in out.iterrows():
        ready = (
            pd.notna(row["Upper"])
            and pd.notna(row["EMA"])
            and pd.notna(row["RVol"])
            and (variant.exit_type != "atr_trailing" or pd.notna(row["ATR"]))
        )
        if not ready:
            pos.append(0)
            stop.append(np.nan)
            weight.append(0.0)
            continue

        close = float(row["Close"])

        if current_pos == 0:
            if close > float(row["Upper"]) and close > float(row["EMA"]):
                current_pos = 1
                highest_close = close
                current_weight = min(1.0, variant.target_vol / max(float(row["RVol"]), variant.vol_floor))
                if variant.exit_type == "atr_trailing":
                    current_stop = highest_close - variant.atr_mult * float(row["ATR"])
                else:
                    current_stop = float(row["Lower"])
        else:
            if variant.exit_type == "atr_trailing":
                highest_close = max(highest_close, close)
                current_stop = max(current_stop, highest_close - variant.atr_mult * float(row["ATR"]))
                exit_now = close < current_stop
            elif variant.exit_type == "donchian_low":
                current_stop = float(row["Lower"])
                exit_now = close < current_stop
            else:
                raise ValueError(f"Unknown exit_type: {variant.exit_type}")

            if exit_now:
                current_pos = 0
                current_stop = 0.0
                current_weight = 0.0

        pos.append(current_pos)
        stop.append(current_stop if current_pos else np.nan)
        weight.append(current_weight)

    out["Position"] = pos
    out["Stop"] = stop
    out["Weight"] = weight
    return out


def simulate_fixed_units(sig: pd.DataFrame, cost_rate: float) -> pd.DataFrame:
    """Close-to-close event backtest: buy fixed spot units on entry, sell on exit."""
    cash = 1.0
    units = 0.0
    equity = 1.0
    prev_equity = 1.0

    returns, equities, exposures, turnovers = [], [], [], []
    cash_values, unit_values = [], []

    for _, row in sig.iterrows():
        close = float(row["Close"])
        before_trade_equity = cash + units * close
        daily_return = before_trade_equity / prev_equity - 1.0 if prev_equity > 0 else 0.0
        traded_notional = 0.0

        target_position = int(row["Position"])
        if units <= 0 and target_position == 1:
            target_notional = before_trade_equity * float(row["Weight"])
            if target_notional > 0:
                buy_notional = min(target_notional, before_trade_equity / (1.0 + cost_rate))
                units = buy_notional / close
                cash = before_trade_equity - buy_notional * (1.0 + cost_rate)
                traded_notional = buy_notional
        elif units > 0 and target_position == 0:
            sell_notional = units * close
            cash = before_trade_equity - sell_notional * cost_rate
            traded_notional = sell_notional
            units = 0.0

        equity = cash + units * close
        if traded_notional:
            daily_return = equity / prev_equity - 1.0 if prev_equity > 0 else 0.0

        exposure = (units * close / equity) if equity > 0 else 0.0
        turnover = traded_notional / before_trade_equity if before_trade_equity > 0 else 0.0

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
        index=sig.index,
    )


def backtest(df: pd.DataFrame, variant: Variant, common_index: pd.DatetimeIndex | None = None) -> pd.DataFrame:
    sig = generate_signals(df, variant)
    gross_sim = simulate_fixed_units(sig, cost_rate=0.0)
    net_sim = simulate_fixed_units(sig, cost_rate=SPOT_FEE + SPOT_SLIPPAGE)

    out = sig.copy()
    out["MarketReturn"] = out["Close"].pct_change().fillna(0.0)
    out["Exposure"] = gross_sim["Exposure"]
    out["Turnover"] = gross_sim["Turnover"]
    out["GrossReturn"] = gross_sim["Return"]
    out["NetReturn"] = net_sim["Return"]
    out["GrossEquity"] = gross_sim["Equity"]
    out["NetEquity"] = net_sim["Equity"]
    out["MarketEquity"] = (1.0 + out["MarketReturn"]).cumprod()

    if common_index is None:
        return out

    aligned = out.reindex(common_index)
    for col in ["MarketReturn", "GrossReturn", "NetReturn", "Exposure", "Turnover"]:
        aligned[col] = aligned[col].fillna(0.0)
    for col in ["Position", "Weight"]:
        aligned[col] = aligned[col].fillna(0.0)
    aligned["GrossEquity"] = (1.0 + aligned["GrossReturn"]).cumprod()
    aligned["NetEquity"] = (1.0 + aligned["NetReturn"]).cumprod()
    aligned["MarketEquity"] = (1.0 + aligned["MarketReturn"]).cumprod()
    aligned["Close"] = aligned["Close"].ffill()
    return aligned


def metrics(ret: pd.Series, equity: pd.Series | None = None) -> dict:
    ret = ret.dropna()
    if equity is None:
        equity = (1.0 + ret).cumprod()
    equity = equity.loc[ret.index]
    if ret.empty or equity.empty:
        return dict(cagr=np.nan, sharpe=np.nan, mdd=np.nan, calmar=np.nan, vol=np.nan, final=np.nan)

    years = max((ret.index[-1] - ret.index[0]).days, 1) / TRADING_DAYS
    final = float(equity.iloc[-1])
    cagr = final ** (1.0 / years) - 1.0 if final > 0 else -1.0
    std = float(ret.std())
    sharpe = ((float(ret.mean()) - RF_ANNUAL / TRADING_DAYS) / std) * math.sqrt(TRADING_DAYS) if std > 0 else 0.0
    mdd = float((equity / equity.cummax() - 1.0).min())
    calmar = cagr / abs(mdd) if mdd < 0 else 0.0
    return dict(cagr=cagr, sharpe=sharpe, mdd=mdd, calmar=calmar, vol=std * math.sqrt(TRADING_DAYS), final=final)


def trade_stats(bt: pd.DataFrame) -> dict:
    position = bt["Position"].astype(float)
    entries = bt.index[(position.shift(1).fillna(0.0) == 0.0) & (position == 1.0)]
    exits = bt.index[(position.shift(1).fillna(0.0) == 1.0) & (position == 0.0)]
    rows = []
    for entry in entries:
        next_exits = exits[exits > entry]
        exit_date = next_exits[0] if len(next_exits) else bt.index[-1]
        close_ret = float(bt.loc[exit_date, "Close"] / bt.loc[entry, "Close"] - 1.0)
        rows.append(
            dict(
                entry=entry,
                exit=exit_date,
                days=(exit_date - entry).days,
                weight=float(bt.loc[entry, "Weight"]),
                close_ret=close_ret,
            )
        )
    trades = pd.DataFrame(rows)
    if trades.empty:
        return dict(trades=0, win_rate=np.nan, avg_days=np.nan, avg_weight=np.nan)
    return dict(
        trades=int(len(trades)),
        win_rate=float((trades["close_ret"] > 0).mean()),
        avg_days=float(trades["days"].mean()),
        avg_weight=float(trades["weight"].mean()),
    )


def build_results() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict, dict]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    data = {symbol: load_symbol(symbol) for symbol in SYMBOLS}
    common_end = min(df.index[-1] for df in data.values())
    common_index = pd.date_range(COMMON_START, common_end, freq="D")
    availability = {symbol: data[symbol].index[0].date().isoformat() for symbol in SYMBOLS}
    backtests: dict[tuple[str, str], pd.DataFrame] = {}
    sleeve_returns: dict[str, pd.Series] = {}
    sleeve_exposures: dict[str, pd.Series] = {}
    rows = []
    trade_rows = []

    for variant in VARIANTS:
        for symbol, df in data.items():
            bt = backtest(df, variant, common_index=common_index)
            backtests[(variant.key, symbol)] = bt
            for mode, ret_col, eq_col in [
                ("gross", "GrossReturn", "GrossEquity"),
                ("net_cost_model", "NetReturn", "NetEquity"),
            ]:
                m = metrics(bt[ret_col], bt[eq_col])
                rows.append(
                    dict(
                        variant=variant.key,
                        label=variant.label,
                        scope=symbol,
                        mode=mode,
                        start=bt.index[0].date().isoformat(),
                        end=bt.index[-1].date().isoformat(),
                        data_start=availability[symbol],
                        avg_exposure=float(bt["Exposure"].abs().mean()),
                        turnover=float(bt["Turnover"].sum()),
                        **m,
                    )
                )
            trade_rows.append(dict(variant=variant.key, scope=symbol, **trade_stats(bt)))

    for variant in VARIANTS:
        for mode, ret_col in [("gross", "GrossReturn"), ("net_cost_model", "NetReturn")]:
            panel = pd.concat(
                [backtests[(variant.key, symbol)][ret_col].rename(symbol) for symbol in SYMBOLS],
                axis=1,
            ).reindex(common_index).fillna(0.0)
            sleeve_ret = panel.mean(axis=1)
            m = metrics(sleeve_ret)
            exposure_panel = pd.concat(
                [backtests[(variant.key, symbol)]["Exposure"].rename(symbol) for symbol in SYMBOLS],
                axis=1,
            ).reindex(common_index).fillna(0.0)
            if mode == "gross":
                sleeve_returns[variant.key] = sleeve_ret
                sleeve_exposures[variant.key] = exposure_panel.mean(axis=1)
            rows.append(
                dict(
                    variant=variant.key,
                    label=variant.label,
                    scope="MULTI_EQUAL_WEIGHT",
                    mode=mode,
                    start=panel.index[0].date().isoformat(),
                    end=panel.index[-1].date().isoformat(),
                    data_start="; ".join(f"{k}:{v}" for k, v in availability.items()),
                    avg_exposure=float(exposure_panel.abs().mean(axis=1).mean()),
                    turnover=np.nan,
                    **m,
                )
            )

    metrics_df = pd.DataFrame(rows)
    trades_df = pd.DataFrame(trade_rows)

    yearly_rows = []
    for variant in VARIANTS:
        panel = pd.concat(
            [backtests[(variant.key, symbol)]["GrossReturn"].rename(symbol) for symbol in SYMBOLS],
            axis=1,
        ).reindex(common_index).fillna(0.0)
        sleeve = panel.mean(axis=1)
        for year, seg in sleeve.groupby(sleeve.index.year):
            if len(seg) < 60:
                continue
            yearly_rows.append(dict(variant=variant.key, year=int(year), **metrics(seg)))
    yearly_df = pd.DataFrame(yearly_rows)

    normalized_rows = []
    for variant in VARIANTS:
        sleeve_ret = sleeve_returns[variant.key]
        avg_exposure = float(sleeve_exposures[variant.key].abs().mean())
        vol = float(sleeve_ret.std() * math.sqrt(TRADING_DAYS))
        vol_scale = NORMALIZED_VOL / vol if vol > 0 else np.nan
        exposure_scale = NORMALIZED_AVG_EXPOSURE / avg_exposure if avg_exposure > 0 else np.nan
        for test_name, scale in [
            ("same_annual_vol_25pct", vol_scale),
            ("same_avg_exposure_25pct", exposure_scale),
        ]:
            scaled_ret = sleeve_ret * scale if pd.notna(scale) else sleeve_ret * np.nan
            normalized_rows.append(
                dict(
                    variant=variant.key,
                    label=variant.label,
                    test=test_name,
                    scale=scale,
                    raw_vol=vol,
                    raw_avg_exposure=avg_exposure,
                    **metrics(scaled_ret),
                )
            )
    normalized_df = pd.DataFrame(normalized_rows)

    context = dict(common_start=COMMON_START.date().isoformat(), common_end=common_end.date().isoformat(), availability=availability)
    return metrics_df, trades_df, yearly_df, normalized_df, backtests, context


def pct(x: float) -> str:
    if pd.isna(x):
        return "NA"
    return f"{x:.2%}"


def num(x: float) -> str:
    if pd.isna(x):
        return "NA"
    return f"{x:.2f}"


def get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
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


def draw_text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, size: int, fill=(30, 35, 40), bold=False) -> None:
    draw.text(xy, text, font=get_font(size, bold=bold), fill=fill)


def draw_line_chart(series_map: dict[str, pd.Series], title: str, out_path: Path) -> None:
    width, height = 1600, 900
    margin_l, margin_r, margin_t, margin_b = 110, 60, 95, 95
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    colors = ["#255C99", "#D95F02", "#2E7D32", "#6A3D9A", "#444444"]

    draw_text(draw, (margin_l, 28), title, 30, bold=True)
    draw_text(draw, (margin_l, 63), "现货 / 无底仓 / gross returns；曲线按共同样本起点归一到 1.0", 18, fill=(90, 95, 105))

    aligned = pd.concat(series_map, axis=1).dropna()
    aligned = aligned / aligned.iloc[0]
    log_values = np.log(aligned.clip(lower=1e-6))
    ymin, ymax = float(log_values.min().min()), float(log_values.max().max())
    pad = (ymax - ymin) * 0.08 if ymax > ymin else 0.1
    ymin -= pad
    ymax += pad

    x0, y0 = margin_l, margin_t
    x1, y1 = width - margin_r, height - margin_b
    draw.rectangle((x0, y0, x1, y1), outline=(210, 215, 220), width=1)
    for i in range(6):
        y = y1 - int((y1 - y0) * i / 5)
        draw.line((x0, y, x1, y), fill=(235, 238, 242), width=1)
        val = math.exp(ymin + (ymax - ymin) * i / 5)
        draw_text(draw, (18, y - 10), f"{val:.1f}x", 16, fill=(95, 100, 110))

    n = len(aligned)
    if n <= 1:
        return
    for idx, col in enumerate(aligned.columns):
        points = []
        for j, value in enumerate(log_values[col].values):
            x = x0 + int((x1 - x0) * j / (n - 1))
            y = y1 - int((y1 - y0) * (float(value) - ymin) / (ymax - ymin))
            points.append((x, y))
        draw.line(points, fill=colors[idx % len(colors)], width=4)
        lx, ly = x0 + 20 + idx * 360, height - 56
        draw.rectangle((lx, ly, lx + 24, ly + 14), fill=colors[idx % len(colors)])
        draw_text(draw, (lx + 34, ly - 5), col, 17, fill=(50, 55, 65))

    draw_text(draw, (x0, height - 33), str(aligned.index[0].date()), 15, fill=(95, 100, 110))
    draw_text(draw, (x1 - 95, height - 33), str(aligned.index[-1].date()), 15, fill=(95, 100, 110))
    img.save(out_path)


def draw_bar_panels(metrics_df: pd.DataFrame, out_path: Path) -> None:
    width, height = 1600, 960
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (70, 28), "结构对照：多标的等权袖子", 30, bold=True)
    draw_text(draw, (70, 63), "仅用于结构判断；A/B/C 不做大网格优化", 18, fill=(90, 95, 105))

    multi = metrics_df.query("scope == 'MULTI_EQUAL_WEIGHT' and mode == 'gross'").copy()
    labels = ["A", "B", "C"]
    variant_keys = [v.key for v in VARIANTS]
    panels = [
        ("CAGR", "cagr", False),
        ("Sharpe", "sharpe", False),
        ("Calmar", "calmar", False),
        ("MDD", "mdd", True),
    ]
    colors = ["#255C99", "#D95F02", "#2E7D32"]
    panel_w, panel_h = 700, 330
    origins = [(80, 130), (850, 130), (80, 545), (850, 545)]

    for (title, col, abs_mode), (ox, oy) in zip(panels, origins):
        vals = []
        for key in variant_keys:
            value = float(multi.loc[multi["variant"] == key, col].iloc[0])
            vals.append(abs(value) if abs_mode else value)
        max_v = max(vals) if vals else 1.0
        min_v = min(0.0, min(vals)) if vals else 0.0
        top = max_v * 1.20 if max_v > 0 else 1.0
        draw_text(draw, (ox, oy - 34), title, 24, bold=True)
        draw.rectangle((ox, oy, ox + panel_w, oy + panel_h), outline=(220, 224, 230))
        baseline = oy + panel_h - 45
        draw.line((ox + 55, baseline, ox + panel_w - 30, baseline), fill=(190, 195, 205), width=2)
        bar_w = 95
        gap = 105
        for i, value in enumerate(vals):
            x = ox + 90 + i * (bar_w + gap)
            bar_h = int((panel_h - 85) * value / top) if top > 0 else 0
            y = baseline - bar_h
            draw.rectangle((x, y, x + bar_w, baseline), fill=colors[i])
            label = f"{value:.2f}" if col in ("sharpe", "calmar") else pct(value)
            draw_text(draw, (x - 5, y - 28), label, 17, fill=(45, 50, 60))
            draw_text(draw, (x + 36, baseline + 13), labels[i], 20, bold=True)
        if abs_mode:
            draw_text(draw, (ox + 55, oy + panel_h - 23), "MDD 用绝对值展示，越低越好", 15, fill=(110, 115, 125))

    img.save(out_path)


def draw_heatmap(metrics_df: pd.DataFrame, out_path: Path) -> None:
    width, height = 1500, 860
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (70, 28), "跨标的 Calmar 稳定性", 30, bold=True)
    draw_text(draw, (70, 63), "gross returns；同一套参数应用到不同现货标的", 18, fill=(90, 95, 105))

    df = metrics_df.query("mode == 'gross' and scope in @SYMBOLS").copy()
    table = df.pivot(index="scope", columns="variant", values="calmar").reindex(SYMBOLS)
    cols = [v.key for v in VARIANTS]
    x0, y0 = 260, 150
    cell_w, cell_h = 330, 110
    for j, variant in enumerate(VARIANTS):
        draw_text(draw, (x0 + j * cell_w + 25, y0 - 58), variant.key.split("_")[0], 24, bold=True)
        draw_text(draw, (x0 + j * cell_w + 25, y0 - 30), variant.label.split(":")[0], 16, fill=(90, 95, 105))
    for i, symbol in enumerate(SYMBOLS):
        draw_text(draw, (70, y0 + i * cell_h + 35), symbol, 23, bold=True)
        for j, col in enumerate(cols):
            value = float(table.loc[symbol, col])
            if value >= 1.0:
                fill = (190, 225, 195)
            elif value >= 0.5:
                fill = (226, 238, 203)
            elif value >= 0.0:
                fill = (248, 230, 190)
            else:
                fill = (242, 198, 198)
            x = x0 + j * cell_w
            y = y0 + i * cell_h
            draw.rectangle((x, y, x + cell_w - 18, y + cell_h - 18), fill=fill, outline=(215, 220, 225))
            draw_text(draw, (x + 108, y + 35), f"{value:.2f}", 28, fill=(35, 45, 55), bold=True)
    draw_text(draw, (70, height - 65), "阅读方式：绿色越深越稳定；单一币种好看但跨币不稳，不应晋升为核心规则。", 18, fill=(80, 85, 95))
    img.save(out_path)


def draw_normalized_tests(normalized_df: pd.DataFrame, out_path: Path) -> None:
    width, height = 1600, 920
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (70, 28), "归一化检验：剥离风险开得更大的影响", 30, bold=True)
    draw_text(draw, (70, 63), "同组合波动=25%年化；同平均暴露=25%。这是结构诊断，不是实盘杠杆建议。", 18, fill=(90, 95, 105))

    tests = [
        ("same_annual_vol_25pct", "同波动 25% 年化"),
        ("same_avg_exposure_25pct", "同平均暴露 25%"),
    ]
    metrics_to_plot = [("CAGR", "cagr", False), ("MDD", "mdd", True), ("Calmar", "calmar", False)]
    colors = ["#255C99", "#D95F02", "#2E7D32"]
    labels = ["A", "B", "C"]
    variant_keys = [v.key for v in VARIANTS]
    panel_w, panel_h = 470, 300

    for row_idx, (test_key, test_label) in enumerate(tests):
        y_base = 140 + row_idx * 380
        draw_text(draw, (70, y_base - 45), test_label, 24, bold=True)
        sub = normalized_df.loc[normalized_df["test"] == test_key].set_index("variant")
        for col_idx, (title, col, abs_mode) in enumerate(metrics_to_plot):
            ox = 70 + col_idx * 505
            oy = y_base
            vals = []
            for key in variant_keys:
                value = float(sub.loc[key, col])
                vals.append(abs(value) if abs_mode else value)
            top = max(vals) * 1.20 if max(vals) > 0 else 1.0
            draw_text(draw, (ox, oy - 28), title, 20, bold=True)
            draw.rectangle((ox, oy, ox + panel_w, oy + panel_h), outline=(220, 224, 230))
            baseline = oy + panel_h - 44
            draw.line((ox + 45, baseline, ox + panel_w - 30, baseline), fill=(190, 195, 205), width=2)
            for i, value in enumerate(vals):
                x = ox + 65 + i * 130
                bar_h = int((panel_h - 85) * value / top) if top > 0 else 0
                y = baseline - bar_h
                draw.rectangle((x, y, x + 72, baseline), fill=colors[i])
                text = f"{value:.2f}" if col == "calmar" else pct(value)
                draw_text(draw, (x - 15, y - 26), text, 15, fill=(45, 50, 60))
                draw_text(draw, (x + 25, baseline + 10), labels[i], 18, bold=True)
            if abs_mode:
                draw_text(draw, (ox + 45, oy + panel_h - 22), "绝对值，越低越好", 14, fill=(110, 115, 125))

    img.save(out_path)


def make_report(metrics_df: pd.DataFrame, trades_df: pd.DataFrame, yearly_df: pd.DataFrame, normalized_df: pd.DataFrame, context: dict) -> str:
    multi_gross = metrics_df.query("scope == 'MULTI_EQUAL_WEIGHT' and mode == 'gross'").copy()
    multi_net = metrics_df.query("scope == 'MULTI_EQUAL_WEIGHT' and mode == 'net_cost_model'").copy()

    rows = []
    for variant in VARIANTS:
        g = multi_gross.loc[multi_gross["variant"] == variant.key].iloc[0]
        n = multi_net.loc[multi_net["variant"] == variant.key].iloc[0]
        rows.append(
            f"| {variant.key} | {variant.label} | {pct(g.cagr)} | {num(g.sharpe)} | "
            f"{pct(g.mdd)} | {num(g.calmar)} | {pct(n.cagr)} | {num(n.calmar)} |"
        )

    cross_rows = []
    single = metrics_df.query("mode == 'gross' and scope in @SYMBOLS").copy()
    for variant in VARIANTS:
        vals = single.loc[single["variant"] == variant.key].set_index("scope")
        cross_rows.append(
            f"| {variant.key} | "
            + " | ".join(num(float(vals.loc[s, "calmar"])) for s in SYMBOLS)
            + " |"
        )

    norm_rows = []
    for variant in VARIANTS:
        same_vol = normalized_df.query("variant == @variant.key and test == 'same_annual_vol_25pct'").iloc[0]
        same_exp = normalized_df.query("variant == @variant.key and test == 'same_avg_exposure_25pct'").iloc[0]
        norm_rows.append(
            f"| {variant.key} | {pct(same_vol.cagr)} | {pct(same_vol.mdd)} | {num(same_vol.calmar)} | "
            f"{pct(same_exp.cagr)} | {pct(same_exp.mdd)} | {num(same_exp.calmar)} |"
        )

    availability_text = "；".join(f"{symbol} 数据起点 {date}" for symbol, date in context["availability"].items())

    report = f"""# Crypto 现货右侧 Long-Only 策略结构设计

> 生成时间：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}
> 数据来源：本地缓存 `{SOURCE_CACHE}`
> 统一统计窗口：{context["common_start"]} -> {context["common_end"]}
> 研究边界：现货、long-only、无底仓、无做空；先看 gross edge，再看成本后 net edge。

## 1. 研究假设

这条策略不承担 BTC 长期底仓职责，DCA 已经负责长期 beta。它的职责是：

> 当主流 crypto 现货资产出现右侧趋势时，用有限暴露捕捉上涨趋势；趋势不成立时空仓。

因此本轮设计禁止三件事：

- 不恢复 `10% core` 底仓。
- 不引入做空。
- 不为单一币种单独调参。

本轮所有单币和组合指标都统一从 `{context["common_start"]}` 开始统计。币种上市或缓存数据起点晚于该日期时，上市前按现金空仓处理，收益为 0。数据覆盖：{availability_text}。

## 2. Baseline 结构

本轮只比较三个结构，不做大网格优化：

| 结构 | 说明 |
|---|---|
| A | 现有结构去底仓、去 funding：15 日突破 + EMA200 + 收盘确认式 3.2ATR 跟踪退出 |
| B | 更朴素的标准结构：20 日突破 + EMA200 + 收盘确认式 3.0ATR 跟踪退出 |
| C | 通道结构：20 日突破 + EMA200 + 收盘确认式 20 日低点退出 |

仓位统一为：入场时用 `min(1, 目标波动 / max(20日实现波动, 20%波动下限))` 计算目标投入比例；回测按事件驱动执行，入场时买入固定数量现货，持仓期间不做百分比再平衡，退出时卖出。

退出规则是日线收盘确认，不是盘中 stop order。ATR 退出的准确叫法是 **close-based ATR trailing exit**，即用收盘价更新最高收盘和止损线，再用收盘价确认是否退出。

## 3. 多标的等权结果

组合为四个独立现货 sleeve 等权。`net_cost_model` 使用一侧 `fee={SPOT_FEE:.2%}`、`slippage={SPOT_SLIPPAGE:.2%}` 的占位成本模型，成本不是本轮结构选择的第一依据。

| 结构 | 规则 | Gross CAGR | Gross Sharpe | Gross MDD | Gross Calmar | Net CAGR | Net Calmar |
|---|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

粗看 C 的组合层收益和 Calmar 最高，但它的回撤也最深；B 的收益接近 A/C 的有效区间，且回撤更干净、BTC/ETH 稳定性更好。因此当前核心 baseline 暂定为 **B_canonical_20d_atr30**；C 只作为进攻型候选，等待归一化、分行情和 walk-forward 后再决定是否晋升。

![多标的净值曲线](outputs/01_multi_equity_curves.png)

![结构指标对照](outputs/02_structure_comparison.png)

## 4. 跨标的稳定性

| 结构 | BTC | ETH | SOL | BNB |
|---|---:|---:|---:|---:|
{chr(10).join(cross_rows)}

![跨标的Calmar热力图](outputs/03_cross_asset_calmar_heatmap.png)

## 5. 归一化检验

为避免 C 只是因为持仓更久、风险暴露更大而胜出，本轮新增两个诊断：

- 同组合波动：把 A/B/C 的组合收益都缩放到 25% 年化波动。
- 同平均暴露：把 A/B/C 的组合收益都缩放到 25% 平均暴露。

| 结构 | 同波动 CAGR | 同波动 MDD | 同波动 Calmar | 同暴露 CAGR | 同暴露 MDD | 同暴露 Calmar |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(norm_rows)}

![归一化检验](outputs/04_normalized_tests.png)

归一化结果只用于判断结构质量，不代表实盘应该加杠杆或精确压波动。如果 C 的优势主要来自更高风险暴露，后续应保持候选身份，而不是直接替代 B。

## 6. 初步判断

1. 这条策略应升级为“主流现货多标的右侧趋势袖子”，而不是继续优化 BTC 单标的。
2. `ATR` 仍更适合作为退出距离，而不是第一步改成入场门槛。
3. 当前核心 baseline 暂定为 B：`20日突破 + EMA200 + 收盘确认式 3ATR 跟踪退出`。
4. C 是有价值的进攻型候选，但它必须通过同窗口、同波动、同暴露、分行情和 walk-forward 检查后才能晋升。
5. 下一步如果要加过滤器，必须先证明亏损主要来自假突破；否则新增过滤器默认只记为 observation。

## 7. 下一步建议

下一步不做参数优化，做以下验证：

- 固定同一套参数，增加更多主流现货资产，但先排除流动性和上市时间明显不足的币。
- 将结果拆成牛市、熊市、震荡市三段，确认不是单一年份或单一币种贡献。
- 对候选结构做 walk-forward 稳定性检查，但不允许 walk-forward 反向选择最终参数。
- 成本验证放在 gross edge 成立之后，单独做 spot fee、滑点、交易频率的 net edge decomposition。

## 8. 输出文件

- `outputs/structure_metrics.csv`
- `outputs/trade_stats.csv`
- `outputs/yearly_metrics.csv`
- `outputs/normalized_metrics.csv`
- `outputs/01_multi_equity_curves.png`
- `outputs/02_structure_comparison.png`
- `outputs/03_cross_asset_calmar_heatmap.png`
- `outputs/04_normalized_tests.png`
"""
    return report


def main() -> None:
    metrics_df, trades_df, yearly_df, normalized_df, backtests, context = build_results()
    metrics_df.to_csv(OUTPUT_DIR / "structure_metrics.csv", index=False, encoding="utf-8-sig")
    trades_df.to_csv(OUTPUT_DIR / "trade_stats.csv", index=False, encoding="utf-8-sig")
    yearly_df.to_csv(OUTPUT_DIR / "yearly_metrics.csv", index=False, encoding="utf-8-sig")
    normalized_df.to_csv(OUTPUT_DIR / "normalized_metrics.csv", index=False, encoding="utf-8-sig")

    equity_map = {}
    for variant in VARIANTS:
        panel = pd.concat(
            [backtests[(variant.key, symbol)]["GrossReturn"].rename(symbol) for symbol in SYMBOLS],
            axis=1,
        ).fillna(0.0)
        equity_map[variant.key] = (1.0 + panel.mean(axis=1)).cumprod()
    draw_line_chart(equity_map, "Crypto 现货 Long-Only 多标的等权趋势袖子", OUTPUT_DIR / "01_multi_equity_curves.png")
    draw_bar_panels(metrics_df, OUTPUT_DIR / "02_structure_comparison.png")
    draw_heatmap(metrics_df, OUTPUT_DIR / "03_cross_asset_calmar_heatmap.png")
    draw_normalized_tests(normalized_df, OUTPUT_DIR / "04_normalized_tests.png")

    report = make_report(metrics_df, trades_df, yearly_df, normalized_df, context)
    (ROOT / "右侧现货long-only_结构设计报告.md").write_text(report, encoding="utf-8")

    multi = metrics_df.query("scope == 'MULTI_EQUAL_WEIGHT' and mode == 'gross'")[
        ["variant", "cagr", "sharpe", "mdd", "calmar", "final"]
    ]
    print(multi.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print(f"\nSaved outputs to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
