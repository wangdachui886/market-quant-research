"""Phase 2.0 · Step 3.5 · 验证新浪 M0 主力连续拼接逻辑

问题：M0 在 21 年中只检测到 12 个 |return|>8% 跳空，
     但豆粕主力一年切换 3 次 → 21 年应有 ~60 次切换。
     5 倍的 gap，说明检测方法或数据本身有问题。

测试 1：阈值敏感性 —— 阈值降到 3%/2% 红点是否暴增？
   若暴增 → 说明 M0 是硬拼接，只是 8% 阈值漏了大量中等跳空（解释 A）
   若不变 → 说明 M0 已经被平滑处理（解释 B）

测试 2：M0 vs 真实单合约 —— 在同一时间轴画 M0 + 6 个单合约
   若 M0 完全跟某一段单合约重合 → 硬拼接
   若 M0 是单合约之间的某种平均 / 平滑 → 指数连续

输出：
   outputs/09_threshold_sensitivity.png   阈值 8/5/3/2% 下的红点对比
   outputs/10_continuous_vs_single.png    M0 vs 单合约对比图
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
from config import RAW_DIR

OUT_DIR = Path(__file__).parent / "outputs"
OUT_DIR.mkdir(exist_ok=True)

matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False


# ────────────────────────────────────────────────────────────────────
#  测试 1：阈值敏感性
# ────────────────────────────────────────────────────────────────────
def test_threshold_sensitivity(symbol: str = "M0",
                                thresholds=(0.08, 0.05, 0.03, 0.02)):
    df = pd.read_csv(RAW_DIR / f"{symbol}.csv", parse_dates=["date"])
    df["ret"] = df["close"].pct_change()

    print(f"\n[测试 1] {symbol} 不同阈值下的疑似跳空数量")
    print(f"{'阈值':>8} {'红点数':>8} {'占比':>10} {'年均':>8}")
    years = (df["date"].max() - df["date"].min()).days / 365.25
    for t in thresholds:
        n = int(df["ret"].abs().gt(t).sum())
        pct = n / len(df) * 100
        per_year = n / years
        print(f"{t*100:>7.1f}% {n:>8d} {pct:>9.2f}% {per_year:>7.1f}")

    fig, axes = plt.subplots(len(thresholds), 1,
                             figsize=(13, 2.5 * len(thresholds)),
                             sharex=True)
    for ax, t in zip(axes, thresholds):
        mask = df["ret"].abs() > t
        ax.plot(df["date"], df["ret"] * 100, lw=0.25, color="gray")
        ax.scatter(df.loc[mask, "date"], df.loc[mask, "ret"] * 100,
                   color="red", s=6, zorder=5)
        ax.axhline(t * 100, color="red", ls="--", lw=0.5)
        ax.axhline(-t * 100, color="red", ls="--", lw=0.5)
        ax.set_title(f"|return| > {t*100:.0f}% : "
                     f"共 {int(mask.sum())} 个 "
                     f"({mask.sum()/len(df)*100:.2f}%, "
                     f"{mask.sum()/years:.1f} 个/年)")
        ax.set_ylabel("收益率 %")
    plt.tight_layout()
    out = OUT_DIR / "09_threshold_sensitivity.png"
    plt.savefig(out, dpi=130)
    plt.close(fig)
    print(f"输出：{out}")


# ────────────────────────────────────────────────────────────────────
#  测试 2：M0 vs 真实单合约
# ────────────────────────────────────────────────────────────────────
def fetch_single_contracts(contracts: list[str]) -> dict[str, pd.DataFrame]:
    print(f"\n[测试 2] 拉取 {len(contracts)} 个单合约")
    out = {}
    for c in contracts:
        try:
            df = ak.futures_zh_daily_sina(symbol=c)
        except Exception as e:
            print(f"  {c:8s}  ERROR {e}")
            time.sleep(0.5)
            continue
        if df is None or df.empty:
            print(f"  {c:8s}  空数据")
        else:
            df = df.copy()
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)
            print(f"  {c:8s}  {len(df):4d} 行  "
                  f"{df['date'].min().date()} → {df['date'].max().date()}")
            out[c] = df
        time.sleep(0.5)
    return out


def plot_continuous_vs_single(m0: pd.DataFrame,
                               contracts_data: dict,
                               window_start: pd.Timestamp,
                               window_end: pd.Timestamp):
    fig, ax = plt.subplots(figsize=(14, 7))
    m0_w = m0[(m0["date"] >= window_start) & (m0["date"] <= window_end)]
    ax.plot(m0_w["date"], m0_w["close"], lw=2.8, color="black",
            label="M0 主力连续", zorder=10)

    colors = plt.cm.tab10.colors
    for i, (code, df) in enumerate(contracts_data.items()):
        sub = df[(df["date"] >= window_start) & (df["date"] <= window_end)]
        if len(sub) == 0:
            continue
        ax.plot(sub["date"], sub["close"], lw=1.2, alpha=0.7,
                color=colors[i % len(colors)], label=code)

    ax.set_title(f"M0 主力连续 vs 真实单合约 "
                 f"({window_start.date()} → {window_end.date()})\n"
                 f"若 M0 与某段单合约完全重合 = 硬拼接；若平滑居中 = 指数 / 加权连续")
    ax.set_ylabel("收盘价")
    ax.legend(loc="best", ncol=4, fontsize=9)
    ax.grid(alpha=0.3)
    plt.tight_layout()
    out = OUT_DIR / "10_continuous_vs_single.png"
    plt.savefig(out, dpi=130)
    plt.close(fig)
    print(f"输出：{out}")


# ────────────────────────────────────────────────────────────────────
#  Main
# ────────────────────────────────────────────────────────────────────
def main():
    print("=" * 70)
    print("Phase 2.0 · Step 3.5 · 验证 M0 主力连续拼接逻辑")
    print("=" * 70)

    test_threshold_sensitivity("M0")

    contracts = ["M2401", "M2405", "M2409",
                 "M2501", "M2505", "M2509", "M2601"]
    contracts_data = fetch_single_contracts(contracts)

    if contracts_data:
        m0 = pd.read_csv(RAW_DIR / "M0.csv", parse_dates=["date"])
        plot_continuous_vs_single(
            m0, contracts_data,
            window_start=pd.Timestamp("2023-09-01"),
            window_end=pd.Timestamp("2025-04-01"),
        )

    print("\n" + "=" * 70)
    print("结论怎么读：")
    print("  · 测试 1 阈值降到 3%/2% 红点是否暴增（年均 3 次以上）？")
    print("    暴增 → 硬拼接 + 8% 阈值过高（解释 A）")
    print("    不变 → 数据已平滑（解释 B）")
    print("  · 测试 2 M0 黑线是否跟某段彩色线完全重合并跳到下一段？")
    print("    重合并跳 → 硬拼接")
    print("    平滑居中 → 平滑 / 指数连续")
    print("=" * 70)


if __name__ == "__main__":
    main()
