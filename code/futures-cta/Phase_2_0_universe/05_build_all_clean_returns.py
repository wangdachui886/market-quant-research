"""Phase 2.0 · Step 5 · 19 品种全量构建干净连续 returns

把 Step 4 在豆粕上验证的算法（持仓量识别主力 + 收益率拼接）
扩展到所有 19 个品种，输出统一的 clean returns 数据集。

输出：
  data_cache/contracts/<prefix>/<code>.csv   每个品种所有单合约缓存（首跑慢，后续秒读）
  data_cache/clean/<symbol>_clean.csv        每个品种的干净 returns 序列
  outputs/14_all_symbols_clean_summary.csv   19 品种 summary（覆盖区间、切换次数、raw vs clean nav 差距）
  outputs/15_raw_vs_clean_nav_grid.png       19 品种 nav 对比小图网格
  outputs/16_fake_jump_distribution.png      19 品种切换日'人造跳空'分布

预计首跑时间：4-6 分钟（拉 ~600 单合约）
                  后续重跑：< 30 秒（全部缓存）
"""
import sys
import time
from pathlib import Path

import akshare as ak
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import (
    CONTRACT_END_YEAR,
    CONTRACT_START_YEAR,
    DATA_CACHE,
    MAIN_MONTHS,
    UNIVERSE,
)

OUT_DIR = Path(__file__).parent / "outputs"
OUT_DIR.mkdir(exist_ok=True)
CONTRACTS_ROOT = DATA_CACHE / "contracts"
CONTRACTS_ROOT.mkdir(exist_ok=True)
CLEAN_DIR = DATA_CACHE / "clean"
CLEAN_DIR.mkdir(exist_ok=True)
RAW_DIR = DATA_CACHE / "raw"

matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False


# ────────────────────────────────────────────────────────────────────
#  核心算法（与 04 等价，独立实现以便单独运行）
# ────────────────────────────────────────────────────────────────────
def generate_codes(prefix: str, months: list[int],
                   start_year: int, end_year: int) -> list[str]:
    return [f"{prefix}{year % 100:02d}{mm:02d}"
            for year in range(start_year, end_year + 1) for mm in months]


SLEEP_BASE = 0.7
RETRY_WAIT = 8.0
MAX_RETRIES = 2
EMPTY_MARKER = "_EMPTY_"


def _read_cached(cache_path: Path) -> pd.DataFrame | None:
    """读缓存。空文件标记返回 None，正常 csv 返回 DataFrame。读取失败返回 None。"""
    try:
        text = cache_path.read_text(encoding="utf-8", errors="ignore")
        if text.strip() == EMPTY_MARKER or not text.strip():
            return None
        df = pd.read_csv(cache_path, parse_dates=["date"])
        return df if not df.empty else None
    except Exception:
        return None


def _try_fetch(code: str, errors_seen: list) -> pd.DataFrame | None | str:
    """单次拉取。返回 DataFrame / None(空数据) / "RETRY"(异常需重试)"""
    try:
        df = ak.futures_zh_daily_sina(symbol=code)
    except Exception as e:
        if len(errors_seen) < 3:
            errors_seen.append((code, str(e)[:80]))
        return "RETRY"
    if df is None or df.empty:
        return None
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def fetch_contracts(codes: list[str], cache_dir: Path) -> tuple[dict, dict]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    data = {}
    n_cached = n_fetched = n_empty = n_fail = 0
    errors_seen: list = []

    for code in codes:
        cache_path = cache_dir / f"{code}.csv"
        if cache_path.exists():
            cached_df = _read_cached(cache_path)
            if cached_df is not None:
                data[code] = cached_df
                n_cached += 1
            continue

        result = "RETRY"
        for attempt in range(MAX_RETRIES + 1):
            result = _try_fetch(code, errors_seen)
            if result != "RETRY":
                break
            time.sleep(RETRY_WAIT * (attempt + 1))

        if result == "RETRY":
            n_fail += 1
            time.sleep(SLEEP_BASE)
            continue
        if result is None:
            n_empty += 1
            cache_path.write_text(EMPTY_MARKER, encoding="utf-8")
            time.sleep(SLEEP_BASE)
            continue
        result.to_csv(cache_path, index=False)
        data[code] = result
        n_fetched += 1
        time.sleep(SLEEP_BASE)

    if errors_seen:
        for code, msg in errors_seen:
            print(f"      └─ ERR sample: {code} -> {msg}")
    return data, dict(cached=n_cached, fetched=n_fetched, empty=n_empty, fail=n_fail)


def build_panel(contracts_data: dict) -> pd.DataFrame:
    parts = []
    for code, df in contracts_data.items():
        sub = df.set_index("date")[["close", "hold", "volume"]].copy()
        sub.columns = pd.MultiIndex.from_product([[code], sub.columns])
        parts.append(sub)
    return pd.concat(parts, axis=1, sort=True).sort_index()


def build_clean_returns(panel: pd.DataFrame, min_hold: int = 5000) -> pd.DataFrame:
    close = panel.xs("close", level=1, axis=1)
    hold = panel.xs("hold", level=1, axis=1).copy()
    hold = hold.where(hold >= min_hold, np.nan)
    # pandas 在任一行全 NA 时会直接报 ValueError，这里先做掩码保护
    all_na = hold.isna().all(axis=1)
    dominant = hold.fillna(-np.inf).idxmax(axis=1).where(~all_na, np.nan)

    n = len(close)
    clean = np.full(n, np.nan)
    naive = np.full(n, np.nan)
    close_arr = close.values
    col_to_idx = {c: i for i, c in enumerate(close.columns)}
    dom_arr = dominant.values

    for i in range(1, n):
        c_today = dom_arr[i]
        if not isinstance(c_today, str):
            continue
        ci = col_to_idx[c_today]
        prev_same = close_arr[i - 1, ci]
        today_same = close_arr[i, ci]
        if pd.notna(prev_same) and pd.notna(today_same) and prev_same > 0:
            clean[i] = today_same / prev_same - 1
        c_prev = dom_arr[i - 1]
        if isinstance(c_prev, str):
            ci_prev = col_to_idx[c_prev]
            prev_naive = close_arr[i - 1, ci_prev]
            if pd.notna(prev_naive) and pd.notna(today_same) and prev_naive > 0:
                naive[i] = today_same / prev_naive - 1

    is_switch = (dominant != dominant.shift(1)) & dominant.notna() & dominant.shift(1).notna()
    return pd.DataFrame({
        "dominant": dominant,
        "clean_return": clean,
        "naive_return": naive,
        "is_switch": is_switch.astype(int),
    }, index=close.index)


# ────────────────────────────────────────────────────────────────────
#  单品种处理
# ────────────────────────────────────────────────────────────────────
def process_symbol(symbol: str, name: str, sector: str) -> dict | None:
    prefix = symbol.rstrip("0")
    months = MAIN_MONTHS.get(prefix)
    if months is None:
        print(f"  [SKIP] {symbol} 未配置 MAIN_MONTHS")
        return None

    codes = generate_codes(prefix, months, CONTRACT_START_YEAR, CONTRACT_END_YEAR)
    cache_dir = CONTRACTS_ROOT / prefix
    contracts_data, stats = fetch_contracts(codes, cache_dir)

    if not contracts_data:
        print(f"  [FAIL] {symbol} 无可用合约 "
              f"({stats['cached']}c/{stats['fetched']}f/{stats['empty']}e/{stats['fail']}x)")
        return None

    panel = build_panel(contracts_data)
    result = build_clean_returns(panel)
    result.to_csv(CLEAN_DIR / f"{symbol}_clean.csv", encoding="utf-8-sig")

    n_switches = int(result["is_switch"].sum())
    sw = result[result["is_switch"] == 1]
    fake_jumps_pct = (sw["naive_return"] - sw["clean_return"]) * 100
    avg_fake = float(fake_jumps_pct.mean()) if len(fake_jumps_pct) else np.nan
    n_big_jumps = int((fake_jumps_pct.abs() > 5).sum())

    raw_path = RAW_DIR / f"{symbol}.csv"
    raw_nav_final = clean_nav_final = nav_gap = np.nan
    if raw_path.exists():
        m0 = pd.read_csv(raw_path, parse_dates=["date"]).set_index("date")
        m0_ret = m0["close"].pct_change()
        common = result.index.intersection(m0.index)
        if len(common):
            raw_nav = (1 + m0_ret.loc[common].fillna(0)).cumprod()
            clean_nav = (1 + result["clean_return"].loc[common].fillna(0)).cumprod()
            raw_nav_final = float(raw_nav.iloc[-1])
            clean_nav_final = float(clean_nav.iloc[-1])
            nav_gap = (clean_nav_final / raw_nav_final - 1) * 100

    print(f"  [{symbol:5s}] {name:6s}  合约 {len(contracts_data):3d}个  "
          f"切换 {n_switches:3d}次  跳空均值 {avg_fake:+6.2f}%  "
          f"|>5%| {n_big_jumps:2d}次  nav_gap {nav_gap:+6.1f}%  "
          f"({stats['cached']}c/{stats['fetched']}f/{stats['empty']}e/{stats['fail']}x)")

    return {
        "symbol": symbol, "name": name, "sector": sector,
        "n_contracts": len(contracts_data),
        "clean_start": str(result.index.min().date()),
        "clean_end": str(result.index.max().date()),
        "n_switches": n_switches,
        "avg_fake_jump_pct": round(avg_fake, 3) if not np.isnan(avg_fake) else None,
        "n_big_jumps_>5%": n_big_jumps,
        "raw_nav_final": round(raw_nav_final, 3) if not np.isnan(raw_nav_final) else None,
        "clean_nav_final": round(clean_nav_final, 3) if not np.isnan(clean_nav_final) else None,
        "nav_gap_pct": round(nav_gap, 2) if not np.isnan(nav_gap) else None,
    }


# ────────────────────────────────────────────────────────────────────
#  汇总可视化
# ────────────────────────────────────────────────────────────────────
def plot_nav_grid(symbols: list[tuple]) -> None:
    n = len(symbols)
    cols = 4
    rows = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(16, 3.0 * rows), squeeze=False)
    for ax, (symbol, name, sector) in zip(axes.flat, symbols):
        clean_path = CLEAN_DIR / f"{symbol}_clean.csv"
        raw_path = RAW_DIR / f"{symbol}.csv"
        if not clean_path.exists() or not raw_path.exists():
            ax.set_visible(False)
            continue
        clean = pd.read_csv(clean_path, parse_dates=["date"], index_col="date")
        raw = pd.read_csv(raw_path, parse_dates=["date"], index_col="date")
        raw_ret = raw["close"].pct_change()
        common = clean.index.intersection(raw.index)
        if not len(common):
            ax.set_visible(False)
            continue
        raw_nav = (1 + raw_ret.loc[common].fillna(0)).cumprod()
        clean_nav = (1 + clean["clean_return"].loc[common].fillna(0)).cumprod()
        ax.plot(raw_nav.index, raw_nav.values, lw=0.9, color="crimson",
                label=f"raw {raw_nav.iloc[-1]:.2f}")
        ax.plot(clean_nav.index, clean_nav.values, lw=0.9, color="steelblue",
                label=f"clean {clean_nav.iloc[-1]:.2f}")
        gap = (clean_nav.iloc[-1] / raw_nav.iloc[-1] - 1) * 100
        ax.set_title(f"{name} ({sector}) gap={gap:+.0f}%", fontsize=10)
        ax.legend(fontsize=7, loc="best")
        ax.grid(alpha=0.3)
        ax.tick_params(labelsize=7)
    for ax in axes.flat[len(symbols):]:
        ax.set_visible(False)
    plt.suptitle("19 品种 raw vs clean 累计净值对比（公共区间）", fontsize=13, y=1.00)
    plt.tight_layout()
    plt.savefig(OUT_DIR / "15_raw_vs_clean_nav_grid.png", dpi=130)
    plt.close(fig)


def plot_fake_jump_distribution() -> None:
    rows = []
    for symbol, name, sector, *_ in UNIVERSE:
        path = CLEAN_DIR / f"{symbol}_clean.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path, parse_dates=["date"], index_col="date")
        sw = df[df["is_switch"] == 1]
        for _, r in sw.iterrows():
            jump = (r["naive_return"] - r["clean_return"]) * 100
            if pd.notna(jump):
                rows.append({"symbol": symbol, "name": name, "sector": sector, "jump_pct": jump})
    if not rows:
        return
    df = pd.DataFrame(rows)
    fig, ax = plt.subplots(figsize=(13, 7))
    sectors = sorted(df["sector"].unique())
    for sec in sectors:
        sub = df[df["sector"] == sec]
        ax.scatter(sub["name"], sub["jump_pct"], alpha=0.6, s=30, label=sec)
    ax.axhline(0, color="black", lw=0.7)
    ax.axhline(5, color="red", ls="--", lw=0.5)
    ax.axhline(-5, color="red", ls="--", lw=0.5)
    ax.set_ylabel("切换日人造跳空 (%)")
    ax.set_title("19 品种切换日'人造跳空'分布（负 = contango，正 = backwardation）")
    ax.legend(title="板块")
    ax.tick_params(axis="x", rotation=45)
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(OUT_DIR / "16_fake_jump_distribution.png", dpi=130)
    plt.close(fig)


# ────────────────────────────────────────────────────────────────────
#  Main
# ────────────────────────────────────────────────────────────────────
def main():
    print("=" * 70)
    print("Phase 2.0 · Step 5 · 19 品种全量构建干净连续 returns")
    print("=" * 70)
    print(f"年份范围：{CONTRACT_START_YEAR} - {CONTRACT_END_YEAR}")
    print(f"合约缓存目录：{CONTRACTS_ROOT}")
    print(f"clean 输出目录：{CLEAN_DIR}")
    print()

    summary = []
    for symbol, name, sector, *_ in UNIVERSE:
        row = process_symbol(symbol, name, sector)
        if row:
            summary.append(row)

    summary_df = pd.DataFrame(summary)
    summary_path = OUT_DIR / "14_all_symbols_clean_summary.csv"
    summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")

    print("\n" + "=" * 70)
    print(f"成功 {len(summary)} / {len(UNIVERSE)} 品种")
    print(f"汇总：{summary_path}")

    print("\n生成对比图 ...")
    plot_nav_grid([(r["symbol"], r["name"], r["sector"]) for r in summary])
    plot_fake_jump_distribution()
    print(f"  {OUT_DIR / '15_raw_vs_clean_nav_grid.png'}")
    print(f"  {OUT_DIR / '16_fake_jump_distribution.png'}")
    print("=" * 70)


if __name__ == "__main__":
    main()
