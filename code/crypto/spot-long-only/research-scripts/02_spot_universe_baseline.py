from __future__ import annotations

import json
import math
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "spot_data_cache"
OUTPUT_DIR = ROOT / "outputs_baseline"

START_DATE = pd.Timestamp("2020-01-01")
TRADING_DAYS = 365
RF_ANNUAL = 0.0

CANDIDATE_UNIVERSE = [
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "DOGEUSDT",
    "LINKUSDT",
    "LTCUSDT",
    "AVAXUSDT",
    "TRXUSDT",
    "DOTUSDT",
    "BCHUSDT",
    "XLMUSDT",
    "ETCUSDT",
    "ATOMUSDT",
    "FILUSDT",
    "NEARUSDT",
    "UNIUSDT",
    "AAVEUSDT",
    "APTUSDT",
    "ARBUSDT",
    "OPUSDT",
    "SUIUSDT",
]

EXCLUDED_BASE_ASSETS = {
    "USDC",
    "FDUSD",
    "TUSD",
    "BUSD",
    "DAI",
    "USDP",
    "EUR",
    "TRY",
    "BRL",
    "UP",
    "DOWN",
    "BULL",
    "BEAR",
}

MIN_HISTORY_DAYS = 5 * 365
MIN_DATA_COVERAGE = 0.95
MIN_MEDIAN_QUOTE_VOLUME_90D = 10_000_000
MIN_MEDIAN_TRADES_90D = 20_000

SPOT_FEE = 0.0010
SPOT_SLIPPAGE = 0.0005


@dataclass(frozen=True)
class Baseline:
    entry_window: int = 20
    ema_window: int = 200
    atr_window: int = 14
    atr_mult: float = 3.0
    target_vol: float = 0.40
    vol_window: int = 20
    vol_floor: float = 0.20


BASELINE = Baseline()


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


def fetch_spot_klines(symbol: str, start: pd.Timestamp = START_DATE) -> pd.DataFrame:
    base_url = "https://api.binance.com/api/v3/klines"
    start_ms = int(start.timestamp() * 1000)
    rows: list[list] = []

    while True:
        params = urllib.parse.urlencode(
            {
                "symbol": symbol,
                "interval": "1d",
                "limit": 1000,
                "startTime": start_ms,
            }
        )
        url = f"{base_url}?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as response:
            payload = response.read().decode("utf-8")
        data = json.loads(payload)
        if not data:
            break
        if isinstance(data, dict):
            raise RuntimeError(f"Binance API error for {symbol}: {data}")
        rows.extend(data)
        next_ms = int(data[-1][0]) + 1
        if next_ms <= start_ms or len(data) < 1000:
            break
        start_ms = next_ms
        time.sleep(0.05)

    if not rows:
        raise RuntimeError(f"No spot kline data returned for {symbol}")

    cols = [
        "open_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "close_time",
        "quote_volume",
        "num_trades",
        "taker_buy_base",
        "taker_buy_quote",
        "ignore",
    ]
    df = pd.DataFrame(rows, columns=cols)
    df["date"] = pd.to_datetime(df["open_time"], unit="ms").dt.tz_localize(None)
    for col in ["open", "high", "low", "close", "volume", "quote_volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume", "quote_volume": "QuoteVolume"})
    df = df.set_index("date")[["Open", "High", "Low", "Close", "Volume", "QuoteVolume", "num_trades"]]
    df["num_trades"] = pd.to_numeric(df["num_trades"], errors="coerce")

    today_utc = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
    df = df.loc[df.index < today_utc]
    return df.loc[df.index >= START_DATE].dropna(subset=["Open", "High", "Low", "Close"])


def cache_path(symbol: str) -> Path:
    return DATA_DIR / f"{symbol.lower()}_spot_daily.csv"


def load_or_fetch(symbol: str, refresh: bool = False) -> pd.DataFrame:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = cache_path(symbol)
    if refresh or not path.exists():
        df = fetch_spot_klines(symbol)
        df.to_csv(path, encoding="utf-8-sig")
    else:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df.sort_index()


def base_asset(symbol: str) -> str:
    return symbol[:-4] if symbol.endswith("USDT") else symbol


def screen_symbol(symbol: str, df: pd.DataFrame, common_end: pd.Timestamp) -> dict:
    first_date = df.index[0]
    last_date = df.index[-1]
    active_start = max(first_date, START_DATE)
    expected_days = max((common_end - active_start).days + 1, 1)
    observed_days = int(df.loc[active_start:common_end].shape[0])
    coverage = observed_days / expected_days
    history_days = max((common_end - first_date).days + 1, 0)

    recent = df.loc[:common_end].tail(90)
    median_quote_90d = float(recent["QuoteVolume"].median()) if not recent.empty else 0.0
    median_trades_90d = float(recent["num_trades"].median()) if not recent.empty else 0.0
    base = base_asset(symbol)

    checks = {
        "not_excluded_asset": base not in EXCLUDED_BASE_ASSETS and not any(base.endswith(s) for s in ("UP", "DOWN", "BULL", "BEAR")),
        "history_days": history_days >= MIN_HISTORY_DAYS,
        "data_coverage": coverage >= MIN_DATA_COVERAGE,
        "quote_volume_90d": median_quote_90d >= MIN_MEDIAN_QUOTE_VOLUME_90D,
        "trades_90d": median_trades_90d >= MIN_MEDIAN_TRADES_90D,
    }
    passed = all(checks.values())
    failed_reasons = [name for name, ok in checks.items() if not ok]
    return dict(
        symbol=symbol,
        base_asset=base,
        data_start=first_date.date().isoformat(),
        data_end=last_date.date().isoformat(),
        history_days=history_days,
        observed_days=observed_days,
        coverage=coverage,
        median_quote_volume_90d=median_quote_90d,
        median_trades_90d=median_trades_90d,
        passed=passed,
        failed_reasons=";".join(failed_reasons),
    )


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


def generate_signals(df: pd.DataFrame, params: Baseline = BASELINE) -> pd.DataFrame:
    out = df.copy()
    out["Upper"] = out["High"].rolling(params.entry_window).max().shift(1)
    out["EMA"] = ema(out["Close"], params.ema_window).shift(1)
    out["ATR"] = atr(out, params.atr_window).shift(1)
    out["RVol"] = (
        out["Close"].pct_change().rolling(params.vol_window).std() * math.sqrt(TRADING_DAYS)
    ).shift(1)

    position, stop, weight = [], [], []
    current_pos = 0
    current_stop = 0.0
    current_weight = 0.0
    highest_close = 0.0

    for _, row in out.iterrows():
        ready = pd.notna(row["Upper"]) and pd.notna(row["EMA"]) and pd.notna(row["ATR"]) and pd.notna(row["RVol"])
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
                current_stop = highest_close - params.atr_mult * float(row["ATR"])
                current_weight = min(1.0, params.target_vol / max(float(row["RVol"]), params.vol_floor))
        else:
            highest_close = max(highest_close, close)
            current_stop = max(current_stop, highest_close - params.atr_mult * float(row["ATR"]))
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


def simulate_fixed_units(signal_df: pd.DataFrame, cost_rate: float) -> pd.DataFrame:
    cash = 1.0
    units = 0.0
    prev_equity = 1.0

    returns, equities, exposures, turnovers, cash_values, unit_values = [], [], [], [], [], []
    for _, row in signal_df.iterrows():
        close = float(row["Close"])
        before_equity = cash + units * close
        daily_return = before_equity / prev_equity - 1.0 if prev_equity > 0 else 0.0
        traded_notional = 0.0

        if units <= 0 and int(row["Position"]) == 1:
            target_notional = before_equity * float(row["Weight"])
            buy_notional = min(target_notional, before_equity / (1.0 + cost_rate))
            if buy_notional > 0:
                units = buy_notional / close
                cash = before_equity - buy_notional * (1.0 + cost_rate)
                traded_notional = buy_notional
        elif units > 0 and int(row["Position"]) == 0:
            sell_notional = units * close
            cash = before_equity - sell_notional * cost_rate
            traded_notional = sell_notional
            units = 0.0

        equity = cash + units * close
        if traded_notional:
            daily_return = equity / prev_equity - 1.0 if prev_equity > 0 else 0.0
        exposure = units * close / equity if equity > 0 else 0.0
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


def backtest(df: pd.DataFrame, common_index: pd.DatetimeIndex) -> pd.DataFrame:
    sig = generate_signals(df)
    gross = simulate_fixed_units(sig, cost_rate=0.0)
    net = simulate_fixed_units(sig, cost_rate=SPOT_FEE + SPOT_SLIPPAGE)

    out = sig.copy()
    out["MarketReturn"] = out["Close"].pct_change().fillna(0.0)
    out["GrossReturn"] = gross["Return"]
    out["NetReturn"] = net["Return"]
    out["GrossEquity"] = gross["Equity"]
    out["NetEquity"] = net["Equity"]
    out["Exposure"] = gross["Exposure"]
    out["Turnover"] = gross["Turnover"]
    out["MarketEquity"] = (1.0 + out["MarketReturn"]).cumprod()

    aligned = out.reindex(common_index)
    for col in ["MarketReturn", "GrossReturn", "NetReturn", "Exposure", "Turnover", "Position", "Weight"]:
        aligned[col] = aligned[col].fillna(0.0)
    aligned["Close"] = aligned["Close"].ffill()
    aligned["GrossEquity"] = (1.0 + aligned["GrossReturn"]).cumprod()
    aligned["NetEquity"] = (1.0 + aligned["NetReturn"]).cumprod()
    aligned["MarketEquity"] = (1.0 + aligned["MarketReturn"]).cumprod()
    return aligned


def metrics(ret: pd.Series, equity: pd.Series | None = None) -> dict:
    ret = ret.dropna()
    if equity is None:
        equity = (1.0 + ret).cumprod()
    equity = equity.loc[ret.index]
    years = max((ret.index[-1] - ret.index[0]).days, 1) / TRADING_DAYS
    final = float(equity.iloc[-1])
    cagr = final ** (1.0 / years) - 1.0 if final > 0 else -1.0
    std = float(ret.std())
    sharpe = ((float(ret.mean()) - RF_ANNUAL / TRADING_DAYS) / std) * math.sqrt(TRADING_DAYS) if std > 0 else 0.0
    mdd = float((equity / equity.cummax() - 1.0).min())
    calmar = cagr / abs(mdd) if mdd < 0 else 0.0
    return dict(cagr=cagr, sharpe=sharpe, mdd=mdd, calmar=calmar, vol=std * math.sqrt(TRADING_DAYS), final=final)


def trade_stats(bt: pd.DataFrame) -> dict:
    pos = bt["Position"].astype(float)
    entries = bt.index[(pos.shift(1).fillna(0.0) == 0.0) & (pos == 1.0)]
    exits = bt.index[(pos.shift(1).fillna(0.0) == 1.0) & (pos == 0.0)]
    trades = []
    for entry in entries:
        later_exits = exits[exits > entry]
        exit_date = later_exits[0] if len(later_exits) else bt.index[-1]
        if pd.isna(bt.loc[entry, "Close"]) or pd.isna(bt.loc[exit_date, "Close"]):
            continue
        trades.append(
            dict(
                entry=entry.date().isoformat(),
                exit=exit_date.date().isoformat(),
                days=(exit_date - entry).days,
                weight=float(bt.loc[entry, "Weight"]),
                close_return=float(bt.loc[exit_date, "Close"] / bt.loc[entry, "Close"] - 1.0),
            )
        )
    if not trades:
        return dict(trades=0, win_rate=np.nan, avg_days=np.nan, avg_weight=np.nan, best_trade=np.nan, worst_trade=np.nan)
    df = pd.DataFrame(trades)
    return dict(
        trades=int(len(df)),
        win_rate=float((df["close_return"] > 0).mean()),
        avg_days=float(df["days"].mean()),
        avg_weight=float(df["weight"].mean()),
        best_trade=float(df["close_return"].max()),
        worst_trade=float(df["close_return"].min()),
    )


def build_results(refresh: bool = False):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    candidate_data = {}
    screen_errors = []
    for symbol in CANDIDATE_UNIVERSE:
        try:
            candidate_data[symbol] = load_or_fetch(symbol, refresh=refresh)
        except Exception as exc:
            screen_errors.append(
                dict(
                    symbol=symbol,
                    base_asset=base_asset(symbol),
                    data_start="",
                    data_end="",
                    history_days=0,
                    observed_days=0,
                    coverage=0.0,
                    median_quote_volume_90d=0.0,
                    median_trades_90d=0.0,
                    passed=False,
                    failed_reasons=f"fetch_error:{type(exc).__name__}",
                )
            )

    if not candidate_data:
        raise RuntimeError("No candidate spot data loaded.")

    common_end = min(df.index[-1] for df in candidate_data.values())
    screen_rows = [screen_symbol(symbol, df, common_end) for symbol, df in candidate_data.items()]
    screen_rows.extend(screen_errors)
    screen_df = pd.DataFrame(screen_rows).sort_values(
        ["passed", "median_quote_volume_90d"], ascending=[False, False]
    )
    selected_symbols = screen_df.loc[screen_df["passed"], "symbol"].tolist()
    if not selected_symbols:
        raise RuntimeError("No symbols passed universe screen.")

    data = {symbol: candidate_data[symbol] for symbol in selected_symbols}
    common_index = pd.date_range(START_DATE, common_end, freq="D")
    availability = {symbol: df.index[0].date().isoformat() for symbol, df in data.items()}

    backtests = {symbol: backtest(df, common_index) for symbol, df in data.items()}
    rows, trade_rows = [], []
    for symbol, bt in backtests.items():
        for mode, ret_col, eq_col in [
            ("gross", "GrossReturn", "GrossEquity"),
            ("net_cost_model", "NetReturn", "NetEquity"),
        ]:
            rows.append(
                dict(
                    scope=symbol,
                    mode=mode,
                    start=common_index[0].date().isoformat(),
                    end=common_index[-1].date().isoformat(),
                    data_start=availability[symbol],
                    avg_exposure=float(bt["Exposure"].abs().mean()),
                    turnover=float(bt["Turnover"].sum()),
                    **metrics(bt[ret_col], bt[eq_col]),
                )
            )
        trade_rows.append(dict(scope=symbol, **trade_stats(bt)))

    for mode, ret_col in [("gross", "GrossReturn"), ("net_cost_model", "NetReturn")]:
        panel = pd.concat([bt[ret_col].rename(symbol) for symbol, bt in backtests.items()], axis=1).reindex(common_index).fillna(0.0)
        sleeve_ret = panel.mean(axis=1)
        exposure_panel = pd.concat([bt["Exposure"].rename(symbol) for symbol, bt in backtests.items()], axis=1).reindex(common_index).fillna(0.0)
        rows.append(
            dict(
                scope="MULTI_EQUAL_WEIGHT",
                mode=mode,
                start=common_index[0].date().isoformat(),
                end=common_index[-1].date().isoformat(),
                data_start="; ".join(f"{k}:{v}" for k, v in availability.items()),
                avg_exposure=float(exposure_panel.abs().mean(axis=1).mean()),
                turnover=np.nan,
                **metrics(sleeve_ret),
            )
        )

    metrics_df = pd.DataFrame(rows)
    trades_df = pd.DataFrame(trade_rows)

    yearly_rows = []
    gross_panel = pd.concat([bt["GrossReturn"].rename(symbol) for symbol, bt in backtests.items()], axis=1).reindex(common_index).fillna(0.0)
    sleeve_ret = gross_panel.mean(axis=1)
    for year, seg in sleeve_ret.groupby(sleeve_ret.index.year):
        if len(seg) >= 60:
            yearly_rows.append(dict(year=int(year), **metrics(seg)))
    yearly_df = pd.DataFrame(yearly_rows)

    contribution_rows = []
    for symbol, bt in backtests.items():
        m = metrics(bt["GrossReturn"], bt["GrossEquity"])
        contribution_rows.append(
            dict(
                symbol=symbol,
                final_equity=m["final"],
                cagr=m["cagr"],
                calmar=m["calmar"],
                avg_exposure=float(bt["Exposure"].abs().mean()),
                trade_count=int(trades_df.loc[trades_df["scope"] == symbol, "trades"].iloc[0]),
            )
        )
    contribution_df = pd.DataFrame(contribution_rows)

    context = dict(
        common_start=common_index[0].date().isoformat(),
        common_end=common_index[-1].date().isoformat(),
        availability=availability,
        selected_symbols=selected_symbols,
        candidate_symbols=CANDIDATE_UNIVERSE,
        screen_rules=dict(
            min_history_days=MIN_HISTORY_DAYS,
            min_data_coverage=MIN_DATA_COVERAGE,
            min_median_quote_volume_90d=MIN_MEDIAN_QUOTE_VOLUME_90D,
            min_median_trades_90d=MIN_MEDIAN_TRADES_90D,
        ),
    )
    return metrics_df, trades_df, yearly_df, contribution_df, screen_df, backtests, context


def pct(x: float) -> str:
    return "NA" if pd.isna(x) else f"{x:.2%}"


def num(x: float) -> str:
    return "NA" if pd.isna(x) else f"{x:.2f}"


def md_img(path: Path) -> str:
    return path.resolve().as_posix()


def draw_equity_and_drawdown(backtests: dict[str, pd.DataFrame], out_path: Path) -> None:
    width, height = 1650, 1000
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (80, 28), "现货多标的右侧趋势袖子：B baseline", 30, bold=True)
    draw_text(draw, (80, 64), "20日突破 + EMA200 + 收盘确认式3ATR退出；固定 universe 等权；gross / net 对照", 18, fill=(90, 95, 105))

    panel_g = pd.concat([bt["GrossReturn"].rename(symbol) for symbol, bt in backtests.items()], axis=1).fillna(0.0)
    panel_n = pd.concat([bt["NetReturn"].rename(symbol) for symbol, bt in backtests.items()], axis=1).fillna(0.0)
    gross_eq = (1.0 + panel_g.mean(axis=1)).cumprod()
    net_eq = (1.0 + panel_n.mean(axis=1)).cumprod()
    series_map = {"Gross": gross_eq, "Net cost model": net_eq}

    x0, y0, x1, y1 = 110, 115, width - 70, 570
    dd_y0, dd_y1 = 665, height - 90
    colors = {"Gross": "#255C99", "Net cost model": "#D95F02"}

    aligned = pd.concat(series_map, axis=1).dropna()
    log_values = np.log(aligned.clip(lower=1e-6))
    ymin, ymax = float(log_values.min().min()), float(log_values.max().max())
    pad = (ymax - ymin) * 0.08
    ymin -= pad
    ymax += pad
    draw.rectangle((x0, y0, x1, y1), outline=(215, 220, 225))
    for i in range(6):
        y = y1 - int((y1 - y0) * i / 5)
        draw.line((x0, y, x1, y), fill=(236, 239, 243))
        draw_text(draw, (30, y - 10), f"{math.exp(ymin + (ymax - ymin) * i / 5):.1f}x", 15, fill=(95, 100, 110))
    for col in aligned.columns:
        pts = []
        for i, value in enumerate(log_values[col].values):
            x = x0 + int((x1 - x0) * i / (len(aligned) - 1))
            y = y1 - int((y1 - y0) * (float(value) - ymin) / (ymax - ymin))
            pts.append((x, y))
        draw.line(pts, fill=colors[col], width=4)
    draw_text(draw, (x0, y1 + 18), str(aligned.index[0].date()), 15, fill=(95, 100, 110))
    draw_text(draw, (x1 - 95, y1 + 18), str(aligned.index[-1].date()), 15, fill=(95, 100, 110))

    for i, col in enumerate(aligned.columns):
        lx = x0 + 30 + i * 260
        draw.rectangle((lx, 605, lx + 28, 622), fill=colors[col])
        draw_text(draw, (lx + 38, 600), col, 18, fill=(50, 55, 65))

    dd = aligned / aligned.cummax() - 1.0
    min_dd = float(dd.min().min())
    draw_text(draw, (x0, dd_y0 - 42), "组合回撤", 24, bold=True)
    draw.rectangle((x0, dd_y0, x1, dd_y1), outline=(215, 220, 225))
    for i in range(5):
        y = dd_y1 - int((dd_y1 - dd_y0) * i / 4)
        val = min_dd * (1 - i / 4)
        draw.line((x0, y, x1, y), fill=(236, 239, 243))
        draw_text(draw, (30, y - 10), pct(val), 15, fill=(95, 100, 110))
    for col in dd.columns:
        pts = []
        for i, value in enumerate(dd[col].values):
            x = x0 + int((x1 - x0) * i / (len(dd) - 1))
            y = dd_y1 - int((dd_y1 - dd_y0) * (float(value) - min_dd) / (0 - min_dd)) if min_dd < 0 else dd_y1
            pts.append((x, y))
        draw.line(pts, fill=colors[col], width=3)
    img.save(out_path)


def draw_symbol_bars(metrics_df: pd.DataFrame, out_path: Path) -> None:
    width, height = 1650, 980
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (70, 28), "单币表现：同一套 B baseline", 30, bold=True)
    draw_text(draw, (70, 64), "所有币从统一窗口统计；未上市前按现金空仓。", 18, fill=(90, 95, 105))

    df = metrics_df.query("mode == 'gross' and scope != 'MULTI_EQUAL_WEIGHT'").copy()
    df = df.sort_values("calmar", ascending=False)
    symbols = df["scope"].tolist()

    panels = [("CAGR", "cagr", False), ("Calmar", "calmar", False), ("MDD", "mdd", True)]
    origins = [(80, 135), (80, 420), (80, 705)]
    panel_w, panel_h = width - 150, 210
    colors = ["#255C99", "#2E7D32", "#D95F02"]
    for (title, col, abs_mode), (ox, oy), color in zip(panels, origins, colors):
        vals = [(abs(float(v)) if abs_mode else float(v)) for v in df[col]]
        max_abs = max([abs(v) for v in vals] + [1e-9]) * 1.18
        draw_text(draw, (ox, oy - 34), title, 23, bold=True)
        draw.rectangle((ox, oy, ox + panel_w, oy + panel_h), outline=(220, 224, 230))
        baseline = oy + panel_h - 48 if abs_mode else oy + panel_h // 2
        draw.line((ox + 45, baseline, ox + panel_w - 20, baseline), fill=(190, 195, 205), width=2)
        step = (panel_w - 90) / len(symbols)
        bar_w = max(36, int(step * 0.55))
        for i, (symbol, value) in enumerate(zip(symbols, vals)):
            x = int(ox + 55 + i * step)
            if abs_mode:
                bar_h = int((panel_h - 80) * value / max_abs)
                y = baseline - bar_h
                rect = (x, y, x + bar_w, baseline)
                text_y = y - 24
            else:
                half_h = (panel_h - 80) // 2
                bar_h = int(half_h * abs(value) / max_abs)
                if value >= 0:
                    y = baseline - bar_h
                    rect = (x, y, x + bar_w, baseline)
                    text_y = y - 24
                else:
                    y = baseline + bar_h
                    rect = (x, baseline, x + bar_w, y)
                    text_y = y + 4
            draw.rectangle(rect, fill=color if value >= 0 or abs_mode else "#C43C39")
            text = f"{value:.2f}" if col == "calmar" else pct(value)
            draw_text(draw, (x - 6, text_y), text, 13, fill=(45, 50, 60))
            draw_text(draw, (x - 10, baseline + 9), symbol.replace("USDT", ""), 13, fill=(55, 60, 70), bold=True)
        if abs_mode:
            draw_text(draw, (ox + 45, oy + panel_h - 23), "MDD 用绝对值展示，越低越好", 14, fill=(110, 115, 125))
    img.save(out_path)


def draw_yearly_chart(yearly_df: pd.DataFrame, out_path: Path) -> None:
    width, height = 1400, 760
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (70, 28), "组合分年份表现", 30, bold=True)
    draw_text(draw, (70, 64), "gross returns；用于识别是否过度依赖单一年份。", 18, fill=(90, 95, 105))
    df = yearly_df.copy()
    years = df["year"].astype(str).tolist()
    vals = df["cagr"].astype(float).tolist()
    min_v, max_v = min(vals + [0]), max(vals + [0])
    top = max(abs(min_v), abs(max_v)) * 1.25 if vals else 1.0
    x0, y0, x1, y1 = 90, 125, width - 70, height - 100
    zero_y = y0 + int((y1 - y0) * (top / (2 * top)))
    draw.rectangle((x0, y0, x1, y1), outline=(220, 224, 230))
    draw.line((x0, zero_y, x1, zero_y), fill=(130, 135, 145), width=2)
    step = (x1 - x0 - 70) / len(years)
    bar_w = int(step * 0.55)
    for i, (year, value) in enumerate(zip(years, vals)):
        x = int(x0 + 45 + i * step)
        bar_h = int((y1 - y0) * abs(value) / (2 * top))
        if value >= 0:
            y = zero_y - bar_h
            draw.rectangle((x, y, x + bar_w, zero_y), fill="#255C99")
            draw_text(draw, (x - 5, y - 26), pct(value), 15, fill=(45, 50, 60))
        else:
            y = zero_y + bar_h
            draw.rectangle((x, zero_y, x + bar_w, y), fill="#C43C39")
            draw_text(draw, (x - 5, y + 6), pct(value), 15, fill=(45, 50, 60))
        draw_text(draw, (x + 4, y1 + 14), year, 15, bold=True)
    img.save(out_path)


def make_baseline_doc(context: dict) -> str:
    availability = "\n".join(f"- {symbol}: spot data starts {date}" for symbol, date in context["availability"].items())
    rules = context["screen_rules"]
    return f"""# BASELINE - Crypto Spot Long-Only Trend Sleeve

## 1. Role

This strategy is a spot-only, long-only trend sleeve. It does not replace DCA and does not carry a hidden BTC core.

## 2. Fixed Rule

- Universe: {", ".join(context["selected_symbols"])}
- Window: {context["common_start"]} -> {context["common_end"]}
- Entry: close above previous 20-day high and close above previous EMA200.
- Position sizing: at entry, invest `min(1, 40% / max(20-day realized vol, 20% vol floor))` of sleeve equity.
- Holding: fixed spot units after entry; no daily rebalancing back to target weight.
- Exit: close-based 3ATR trailing exit, confirmed on daily close.
- Cash: no yield in strategy return.
- Shorting: prohibited.
- Per-symbol tuning: prohibited.

## 3. Data

Spot OHLCV is cached in `spot_data_cache/` from Binance spot daily klines.

{availability}

## 4. Universe Screen

Candidates are screened before backtesting:

- Minimum history days: {rules["min_history_days"]}
- Minimum data coverage: {rules["min_data_coverage"]:.0%}
- Minimum recent median quote volume: {rules["min_median_quote_volume_90d"]:,.0f} USDT over the latest 90 days
- Minimum recent median trade count: {rules["min_median_trades_90d"]:,.0f} trades per day over the latest 90 days
- Stablecoins, fiat pairs, and leveraged tokens are excluded.

## 5. Promotion Gates

- Gross edge must be visible at the universe portfolio level.
- Edge cannot be explained by only one coin or one year.
- New filters are observations first; they are not allowed into trading logic without separate OOS or walk-forward evidence.
- Cost and slippage checks happen after gross edge is established.
"""


def make_report(metrics_df: pd.DataFrame, trades_df: pd.DataFrame, yearly_df: pd.DataFrame, contribution_df: pd.DataFrame, screen_df: pd.DataFrame, context: dict) -> str:
    multi_gross = metrics_df.query("scope == 'MULTI_EQUAL_WEIGHT' and mode == 'gross'").iloc[0]
    multi_net = metrics_df.query("scope == 'MULTI_EQUAL_WEIGHT' and mode == 'net_cost_model'").iloc[0]
    single = metrics_df.query("mode == 'gross' and scope != 'MULTI_EQUAL_WEIGHT'").copy()
    single = single.sort_values("calmar", ascending=False)

    single_rows = [
        f"| {r.scope} | {r.data_start} | {pct(r.cagr)} | {num(r.sharpe)} | {pct(r.mdd)} | {num(r.calmar)} | {pct(r.avg_exposure)} |"
        for r in single.itertuples()
    ]
    yearly_rows = [
        f"| {int(r.year)} | {pct(r.cagr)} | {num(r.sharpe)} | {pct(r.mdd)} | {num(r.calmar)} |"
        for r in yearly_df.itertuples()
    ]
    contribution_rows = [
        f"| {r.symbol} | {num(r.final_equity)}x | {pct(r.cagr)} | {num(r.calmar)} | {pct(r.avg_exposure)} | {int(r.trade_count)} |"
        for r in contribution_df.sort_values("final_equity", ascending=False).itertuples()
    ]
    screen_rows = []
    screen_show = screen_df.sort_values(["passed", "median_quote_volume_90d"], ascending=[False, False])
    for r in screen_show.itertuples():
        status = "PASS" if bool(r.passed) else "FAIL"
        reason = "" if bool(r.passed) else r.failed_reasons
        screen_rows.append(
            f"| {r.symbol} | {status} | {r.data_start} | {int(r.history_days)} | {r.coverage:.1%} | "
            f"{float(r.median_quote_volume_90d):,.0f} | {float(r.median_trades_90d):,.0f} | {reason} |"
        )
    availability_text = "；".join(f"{symbol} {date}" for symbol, date in context["availability"].items())
    rules = context["screen_rules"]

    return f"""# Crypto 现货右侧 Long-Only B Baseline 扩展验证

> 生成时间：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}
> 数据：Binance spot daily klines，本地缓存 `spot_data_cache/`
> 统一窗口：{context["common_start"]} -> {context["common_end"]}

## 1. 本轮边界

本轮只验证冻结后的 B baseline，不做参数优化，不比较 A/C。Universe 先经过主流币可交易性筛选，再进入回测。

- 现货、long-only、无底仓、无做空。
- 入场后持有固定数量现货，不做每日目标权重再平衡。
- 新币上市前按现金空仓处理，收益为 0。
- Sharpe 使用 `rf=0`，现金收益不计入策略曲线。

数据起点：{availability_text}。

## 2. Universe 筛选

候选池：{", ".join(context["candidate_symbols"])}

筛选规则：

- 上市/数据历史不少于 `{rules["min_history_days"]}` 天。
- 数据覆盖率不低于 `{rules["min_data_coverage"]:.0%}`。
- 最近 90 日 median quote volume 不低于 `{rules["min_median_quote_volume_90d"]:,.0f}` USDT。
- 最近 90 日 median daily trades 不低于 `{rules["min_median_trades_90d"]:,.0f}`。
- 排除稳定币、法币、杠杆代币。

通过筛选并进入回测：{", ".join(context["selected_symbols"])}

| Symbol | Status | Data start | History days | Coverage | Median quote vol 90d | Median trades 90d | Failed reasons |
|---|---:|---:|---:|---:|---:|---:|---|
{chr(10).join(screen_rows)}

## 3. 固定规则

`20日突破 + EMA200 + 收盘确认式 3ATR trailing exit`

仓位：入场时按 `min(1, 40% / max(20日实现波动, 20%波动下限))` 投入；退出时全部卖出。

## 4. 组合结果

| 口径 | CAGR | Sharpe | MDD | Calmar | Vol | Avg Exposure | Final |
|---|---:|---:|---:|---:|---:|---:|---:|
| Gross | {pct(multi_gross.cagr)} | {num(multi_gross.sharpe)} | {pct(multi_gross.mdd)} | {num(multi_gross.calmar)} | {pct(multi_gross.vol)} | {pct(multi_gross.avg_exposure)} | {num(multi_gross.final)}x |
| Net cost model | {pct(multi_net.cagr)} | {num(multi_net.sharpe)} | {pct(multi_net.mdd)} | {num(multi_net.calmar)} | {pct(multi_net.vol)} | {pct(multi_net.avg_exposure)} | {num(multi_net.final)}x |

![组合净值与回撤]({md_img(OUTPUT_DIR / "01_baseline_equity_drawdown.png")})

## 5. 单币表现

| Symbol | Data start | CAGR | Sharpe | MDD | Calmar | Avg Exposure |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(single_rows)}

![单币表现]({md_img(OUTPUT_DIR / "02_symbol_metrics.png")})

## 6. 分年份表现

| Year | CAGR | Sharpe | MDD | Calmar |
|---|---:|---:|---:|---:|
{chr(10).join(yearly_rows)}

![分年份表现]({md_img(OUTPUT_DIR / "03_yearly_returns.png")})

## 7. 贡献集中度

| Symbol | Final equity | CAGR | Calmar | Avg Exposure | Trades |
|---|---:|---:|---:|---:|---:|
{chr(10).join(contribution_rows)}

## 8. 初步结论

这一步的目的不是证明可以交易，而是确认：在现货数据、扩展 universe、统一窗口下，B baseline 是否仍有可观察的 gross edge。

如果组合层表现稳定，但贡献主要集中在少数币或少数年份，下一步应做分行情归因和 walk-forward，而不是立刻增加过滤器。
"""


def main() -> None:
    metrics_df, trades_df, yearly_df, contribution_df, screen_df, backtests, context = build_results(refresh=False)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    screen_df.to_csv(OUTPUT_DIR / "universe_screen.csv", index=False, encoding="utf-8-sig")
    metrics_df.to_csv(OUTPUT_DIR / "baseline_metrics.csv", index=False, encoding="utf-8-sig")
    trades_df.to_csv(OUTPUT_DIR / "baseline_trade_stats.csv", index=False, encoding="utf-8-sig")
    yearly_df.to_csv(OUTPUT_DIR / "baseline_yearly_metrics.csv", index=False, encoding="utf-8-sig")
    contribution_df.to_csv(OUTPUT_DIR / "baseline_contribution.csv", index=False, encoding="utf-8-sig")

    draw_equity_and_drawdown(backtests, OUTPUT_DIR / "01_baseline_equity_drawdown.png")
    draw_symbol_bars(metrics_df, OUTPUT_DIR / "02_symbol_metrics.png")
    draw_yearly_chart(yearly_df, OUTPUT_DIR / "03_yearly_returns.png")

    (ROOT / "BASELINE.md").write_text(make_baseline_doc(context), encoding="utf-8-sig")
    (ROOT / "02_spot_universe_baseline_report.md").write_text(
        make_report(metrics_df, trades_df, yearly_df, contribution_df, screen_df, context),
        encoding="utf-8-sig",
    )

    print(metrics_df.query("scope == 'MULTI_EQUAL_WEIGHT'").to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print(f"\nSaved spot cache to: {DATA_DIR}")
    print(f"Saved outputs to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
