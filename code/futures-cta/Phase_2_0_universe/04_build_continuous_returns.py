"""Phase 2.0 · Step 4 · 收益率拼接构建干净连续合约（豆粕 M POC）

目标：
  解决 Step 3.5 发现的"M0 是硬拼接、含 ~60 个人造跳空"问题。
  用"主力识别 + 收益率拼接"方法构建干净的连续 returns 序列。

算法（Carver《Systematic Trading》工业标准）：
  1. 拉豆粕所有主力月份合约（1/5/9 × 2005-2026 ≈ 60 个候选）
  2. 每天的"主力" = 当日持仓量最大的合约
  3. 每天 clean_return(t) = close_主力(t)(t) / close_主力(t)(t-1) - 1
       —— 关键：分子分母用同一合约（今天的主力），而非昨天主力 vs 今天主力
       —— 这样切换日没有人造跳空，得到的是"持续持有主力"的真实日收益
  4. 切换日（主力变化）也能算出 clean return，因为新主力在 t-1 已经在交易

输出：
  data_cache/contracts_M/<code>.csv     每个单合约日线缓存
  data_cache/clean/M_clean_returns.csv  干净 returns 序列（含 dominant、is_switch）
  outputs/11_M_clean_vs_raw_returns.png 对比 M0 raw return vs M clean return
  outputs/12_M_dominant_timeline.png    主力切换时间线
  outputs/13_M_clean_vs_raw_nav.png     用两种 return 累乘的净值曲线对比
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
from config import DATA_CACHE

OUT_DIR = Path(__file__).parent / "outputs"
OUT_DIR.mkdir(exist_ok=True)
CONTRACTS_DIR = DATA_CACHE / "contracts_M"
CONTRACTS_DIR.mkdir(exist_ok=True)
CLEAN_DIR = DATA_CACHE / "clean"
CLEAN_DIR.mkdir(exist_ok=True)

matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False


# ────────────────────────────────────────────────────────────────────
#  Step 1：合约代码生成 + 批量拉取
# ────────────────────────────────────────────────────────────────────
def generate_contract_codes(prefix: str, main_months: list[int],
                             start_year: int, end_year: int) -> list[str]:
    codes = []
    for year in range(start_year, end_year + 1):
        yy = year % 100
        for mm in main_months:
            codes.append(f"{prefix}{yy:02d}{mm:02d}")
    return codes


def fetch_contracts(codes: list[str], cache_dir: Path,
                     force_refresh: bool = False) -> dict[str, pd.DataFrame]:
    data = {}
    print(f"开始拉取 {len(codes)} 个候选合约 → {cache_dir}")
    n_cached = n_fetched = n_fail = n_empty = 0
    for code in codes:
        cache_path = cache_dir / f"{code}.csv"
        if cache_path.exists() and not force_refresh:
            df = pd.read_csv(cache_path, parse_dates=["date"])
            data[code] = df
            n_cached += 1
            continue
        try:
            df = ak.futures_zh_daily_sina(symbol=code)
        except Exception:
            n_fail += 1
            time.sleep(0.3)
            continue
        if df is None or df.empty:
            n_empty += 1
            time.sleep(0.3)
            continue
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        df.to_csv(cache_path, index=False)
        data[code] = df
        n_fetched += 1
        time.sleep(0.3)
    print(f"  缓存命中 {n_cached} / 新拉取 {n_fetched} / 空数据 {n_empty} / 异常 {n_fail}")
    print(f"  最终可用合约 {len(data)} 个")
    return data


# ────────────────────────────────────────────────────────────────────
#  Step 2：构建 (date × contract × field) panel
# ────────────────────────────────────────────────────────────────────
def build_panel(contracts_data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    parts = []
    for code, df in contracts_data.items():
        sub = df.set_index("date")[["close", "hold", "volume"]].copy()
        sub.columns = pd.MultiIndex.from_product([[code], sub.columns])
        parts.append(sub)
    panel = pd.concat(parts, axis=1).sort_index()
    return panel


# ────────────────────────────────────────────────────────────────────
#  Step 3：识别每日主力 + 构建干净 return
# ────────────────────────────────────────────────────────────────────
def build_clean_returns(panel: pd.DataFrame, min_hold: int = 5000) -> pd.DataFrame:
    """主算法。返回 DataFrame: dominant, clean_return, naive_return, is_switch"""
    close = panel.xs("close", level=1, axis=1)
    hold = panel.xs("hold", level=1, axis=1).copy()
    hold = hold.where(hold >= min_hold, np.nan)
    dominant = hold.idxmax(axis=1)

    n = len(close)
    clean = np.full(n, np.nan)
    naive = np.full(n, np.nan)

    close_arr = close.values
    cols = list(close.columns)
    col_to_idx = {c: i for i, c in enumerate(cols)}
    dom_arr = dominant.values

    for i in range(1, n):
        c_today = dom_arr[i]
        c_prev = dom_arr[i - 1]
        if not isinstance(c_today, str):
            continue
        ci_today = col_to_idx[c_today]
        prev_close_same = close_arr[i - 1, ci_today]
        today_close_same = close_arr[i, ci_today]
        if pd.notna(prev_close_same) and pd.notna(today_close_same) and prev_close_same > 0:
            clean[i] = today_close_same / prev_close_same - 1
        if isinstance(c_prev, str):
            ci_prev = col_to_idx[c_prev]
            prev_close_naive = close_arr[i - 1, ci_prev]
            if pd.notna(prev_close_naive) and pd.notna(today_close_same) and prev_close_naive > 0:
                naive[i] = today_close_same / prev_close_naive - 1

    is_switch = (dominant != dominant.shift(1)) & dominant.notna() & dominant.shift(1).notna()

    out = pd.DataFrame({
        "dominant": dominant,
        "clean_return": clean,
        "naive_return": naive,
        "is_switch": is_switch.astype(int),
    }, index=close.index)
    out["clean_close"] = (1 + pd.Series(clean, index=close.index).fillna(0)).cumprod() * 1000
    return out


# ────────────────────────────────────────────────────────────────────
#  Step 4：报告 + 可视化
# ────────────────────────────────────────────────────────────────────
def report_switches(result: pd.DataFrame) -> pd.DataFrame:
    n = int(result["is_switch"].sum())
    span_years = (result.index.max() - result.index.min()).days / 365.25
    print(f"\n主力切换次数：{n} 次（{span_years:.1f} 年，{n/span_years:.1f} 次/年）")
    print(f"  期望（豆粕 1/5/9 月主力，3 次/年 × {span_years:.1f}年）≈ {span_years*3:.0f} 次")

    sw = result[result["is_switch"] == 1].copy()
    sw["fake_jump_pct"] = (sw["naive_return"] - sw["clean_return"]) * 100
    print(f"\n切换日'人造跳空'(naive - clean) 统计 (%)：")
    print(sw["fake_jump_pct"].describe().round(3).to_string())

    big = sw[sw["fake_jump_pct"].abs() > 5]
    print(f"\n|人造跳空| > 5% 的切换：{len(big)} 次（这些是被 8% 阈值漏掉的中等跳空）")
    if len(big):
        print(big[["dominant", "naive_return", "clean_return", "fake_jump_pct"]]
              .head(10).round(4).to_string())
    return sw


def plot_clean_vs_raw_returns(result: pd.DataFrame, m0_path: Path, output: Path):
    m0 = pd.read_csv(m0_path, parse_dates=["date"]).set_index("date")
    m0["return"] = m0["close"].pct_change()

    fig, axes = plt.subplots(2, 1, figsize=(13, 7), sharex=True)
    big_m0 = m0[m0["return"].abs() > 0.05]
    axes[0].plot(m0.index, m0["return"] * 100, lw=0.25, color="gray")
    axes[0].scatter(big_m0.index, big_m0["return"] * 100, color="red", s=8)
    axes[0].axhline(5, color="red", ls="--", lw=0.4)
    axes[0].axhline(-5, color="red", ls="--", lw=0.4)
    axes[0].set_title(f"M0 raw return（新浪硬拼接）— |>5%| 红点 {len(big_m0)} 个")
    axes[0].set_ylabel("收益率 %")

    big_clean = result[result["clean_return"].abs() > 0.05]
    axes[1].plot(result.index, result["clean_return"] * 100, lw=0.25, color="gray")
    axes[1].scatter(big_clean.index, big_clean["clean_return"] * 100, color="red", s=8)
    axes[1].axhline(5, color="red", ls="--", lw=0.4)
    axes[1].axhline(-5, color="red", ls="--", lw=0.4)
    axes[1].set_title(f"M clean return（收益率拼接）— |>5%| 红点 {len(big_clean)} 个 "
                      f"（差额 = 被消除的人造跳空）")
    axes[1].set_ylabel("收益率 %")

    plt.tight_layout()
    plt.savefig(output, dpi=130)
    plt.close(fig)


def plot_dominant_timeline(result: pd.DataFrame, output: Path):
    contracts = sorted(result["dominant"].dropna().unique())
    contract_to_id = {c: i for i, c in enumerate(contracts)}
    ids = result["dominant"].map(contract_to_id)

    fig, ax = plt.subplots(figsize=(13, 5))
    ax.scatter(result.index, ids, s=2, color="steelblue")
    ax.set_yticks(range(len(contracts)))
    ax.set_yticklabels(contracts, fontsize=6)
    ax.set_title(f"豆粕 M 主力合约切换时间线（共 {len(contracts)} 个合约曾任主力）")
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(output, dpi=130)
    plt.close(fig)


def plot_nav_comparison(result: pd.DataFrame, m0_path: Path, output: Path):
    """两种 return 累乘的净值曲线对比 —— 看长期偏差有多大"""
    m0 = pd.read_csv(m0_path, parse_dates=["date"]).set_index("date")
    m0_ret = m0["close"].pct_change().fillna(0)
    m0_nav = (1 + m0_ret).cumprod()

    clean_ret = result["clean_return"].fillna(0)
    clean_nav = (1 + clean_ret).cumprod()

    common = m0_nav.index.intersection(clean_nav.index)
    m0_nav = m0_nav.loc[common]
    clean_nav = clean_nav.loc[common] / clean_nav.loc[common].iloc[0]
    m0_nav = m0_nav / m0_nav.iloc[0]

    fig, ax = plt.subplots(figsize=(13, 6))
    ax.plot(m0_nav.index, m0_nav.values, lw=1.2, color="crimson",
            label=f"M0 raw 净值（含人造跳空）末值 {m0_nav.iloc[-1]:.3f}")
    ax.plot(clean_nav.index, clean_nav.values, lw=1.2, color="steelblue",
            label=f"M clean 净值（收益率拼接）末值 {clean_nav.iloc[-1]:.3f}")
    ax.set_title(f"持续持有豆粕主力的累计净值：raw vs clean "
                 f"（差距 = {(clean_nav.iloc[-1]/m0_nav.iloc[-1]-1)*100:+.1f}%）")
    ax.set_ylabel("累计净值（起点 = 1）")
    ax.legend()
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(output, dpi=130)
    plt.close(fig)


# ────────────────────────────────────────────────────────────────────
#  Main
# ────────────────────────────────────────────────────────────────────
def main():
    print("=" * 70)
    print("Phase 2.0 · Step 4 · 收益率拼接构建干净连续（豆粕 M POC）")
    print("=" * 70)

    codes = generate_contract_codes("M", [1, 5, 9], 2005, 2026)
    print(f"\n候选合约代码 {len(codes)} 个：M0501 ... M2609")

    contracts_data = fetch_contracts(codes, CONTRACTS_DIR)
    if not contracts_data:
        print("[FAIL] 未拉到任何合约，终止")
        return

    panel = build_panel(contracts_data)
    print(f"\nPanel: {panel.shape[0]} 个交易日 × {panel.shape[1]//3} 个合约")

    result = build_clean_returns(panel)
    valid = int(result["clean_return"].notna().sum())
    print(f"\nClean returns 区间：{result.index.min().date()} → {result.index.max().date()}")
    print(f"有效行数：{valid} / {len(result)}")

    report_switches(result)

    out_csv = CLEAN_DIR / "M_clean_returns.csv"
    result.to_csv(out_csv, encoding="utf-8-sig")
    print(f"\n[输出] {out_csv}")

    m0_path = DATA_CACHE / "raw" / "M0.csv"
    plot_clean_vs_raw_returns(result, m0_path, OUT_DIR / "11_M_clean_vs_raw_returns.png")
    print(f"[输出] {OUT_DIR / '11_M_clean_vs_raw_returns.png'}")

    plot_dominant_timeline(result, OUT_DIR / "12_M_dominant_timeline.png")
    print(f"[输出] {OUT_DIR / '12_M_dominant_timeline.png'}")

    plot_nav_comparison(result, m0_path, OUT_DIR / "13_M_clean_vs_raw_nav.png")
    print(f"[输出] {OUT_DIR / '13_M_clean_vs_raw_nav.png'}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
