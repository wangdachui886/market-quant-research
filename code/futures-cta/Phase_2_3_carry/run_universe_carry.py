"""Phase 2.3 · Step 3 · 19 品种 Carry-only 策略回测（方案 A vs B 对比）

目标：在 "只用 carry 信号" 的前提下，测试两种变体谁更好：
  A. carry_signal_raw     = sign(carry)
  B. carry_signal_smooth  = sign(rolling_mean(carry, 21))

两个都加 vol-target（复用 Phase 2.2 的 sizing），和 TSMOM baseline 公平对比。

关键框架（和 Phase 2.2 完全一致，方便横向比较）：
  信号层 : carry_signal_{raw, smooth}       ∈ {-1, 0, +1}
  仓位层 : vol_target_scale(target=20%)
  执行层 : lag 1 日
  组合层 : 动态等权

参照基准：
  - B&H 等权       Sharpe ≈ +0.60
  - TSMOM raw      Sharpe ≈ +0.52
  - TSMOM vt       Sharpe ≈ +0.70

用法：
    python Phase_2_3_carry/run_universe_carry.py

产出：
    终端：A / B / B&H / TSMOM vt 四者对比 + 逐品种表
    outputs/carry_universe_per_symbol.csv
    outputs/carry_universe_compare.png
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "Phase_2_2_tsmom"))  # 复用 backtest.py / sizing.py
sys.path.insert(0, str(HERE))

from config import UNIVERSE  # noqa: E402
from sizing import vol_target_scale  # noqa: E402
from backtest import backtest_single  # noqa: E402
from signals import carry_signal_raw, carry_signal_smooth  # noqa: E402

CLEAN_DIR = PROJECT_ROOT / "data_cache" / "tushare" / "clean"
CARRY_DIR = PROJECT_ROOT / "data_cache" / "tushare" / "carry"
OUT_DIR = HERE / "outputs"
OUT_DIR.mkdir(exist_ok=True)

LAG = 1
TARGET_VOL = 0.20
VOL_WINDOW = 60
VOL_FLOOR = 0.05
MAX_LEV = 3.0
SMOOTH_WINDOW = 21


def load_clean_returns(symbol: str) -> pd.Series:
    fp = CLEAN_DIR / f"{symbol}_clean_returns.csv"
    df = pd.read_csv(fp, parse_dates=["date"]).set_index("date")
    s = df["clean_return"].sort_index()
    s.name = symbol
    return s


def load_carry(symbol: str) -> pd.Series:
    fp = CARRY_DIR / f"{symbol}_carry.csv"
    df = pd.read_csv(fp, parse_dates=["date"]).set_index("date")
    s = df["carry"].sort_index()
    s.name = symbol
    return s


def run_one(symbol: str) -> dict:
    ret = load_clean_returns(symbol)
    carry = load_carry(symbol).reindex(ret.index)  # 对齐到 clean_returns 的 trade_date

    sig_A = carry_signal_raw(carry)
    sig_B = carry_signal_smooth(carry, window=SMOOTH_WINDOW)
    scale = vol_target_scale(ret, target_vol=TARGET_VOL, window=VOL_WINDOW,
                             vol_floor=VOL_FLOOR, max_leverage=MAX_LEV)

    pos_A = sig_A * scale
    pos_B = sig_B * scale

    bt_A = backtest_single(ret, pos_A, lag_days=LAG)
    bt_B = backtest_single(ret, pos_B, lag_days=LAG)

    return {
        "symbol": symbol,
        "clean_return": ret,
        "carry": carry,
        "scale": scale,
        "A": bt_A,
        "B": bt_B,
    }


def compute_port_metrics(port_ret: pd.Series) -> dict:
    r = port_ret.dropna()
    if len(r) == 0:
        return {k: np.nan for k in ["annual_return", "annual_vol", "sharpe", "max_dd", "nav_end"]}
    ann_ret = r.mean() * 252
    ann_vol = r.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else np.nan
    nav = (1 + r).cumprod()
    max_dd = (nav / nav.cummax() - 1).min()
    return {
        "annual_return": float(ann_ret),
        "annual_vol": float(ann_vol),
        "sharpe": float(sharpe) if pd.notna(sharpe) else np.nan,
        "max_dd": float(max_dd),
        "nav_end": float(nav.iloc[-1]),
    }


def main() -> None:
    symbols = [row[0] for row in UNIVERSE]
    print("=" * 80)
    print(f"Carry-only 策略   N={len(symbols)}   target_vol={TARGET_VOL:.0%}   "
          f"vol_window={VOL_WINDOW}d   smooth_window={SMOOTH_WINDOW}d")
    print("=" * 80)

    A_rets: dict[str, pd.Series] = {}
    B_rets: dict[str, pd.Series] = {}
    bh_rets: dict[str, pd.Series] = {}
    per_rows: list[dict] = []

    for sym in symbols:
        try:
            out = run_one(sym)
        except FileNotFoundError as e:
            print(f"  [skip] {sym}：缺数据 {e}")
            continue

        A_rets[sym] = out["A"]["strategy_return"]
        B_rets[sym] = out["B"]["strategy_return"]
        bh_rets[sym] = out["clean_return"]

        mA, mB = out["A"]["metrics"], out["B"]["metrics"]
        per_rows.append({
            "symbol": sym,
            "A_sharpe": mA["sharpe"],
            "A_ret":    mA["annual_return"],
            "A_maxdd":  mA["max_dd"],
            "A_trades_per_year": mA["trades_per_year"],
            "B_sharpe": mB["sharpe"],
            "B_ret":    mB["annual_return"],
            "B_maxdd":  mB["max_dd"],
            "B_trades_per_year": mB["trades_per_year"],
        })
        print(f"  [{sym:>4}]  "
              f"A Sharpe={mA['sharpe']:+.2f} (换手={mA['trades_per_year']:4.1f}/yr)   "
              f"B Sharpe={mB['sharpe']:+.2f} (换手={mB['trades_per_year']:4.1f}/yr)")

    if not per_rows:
        print("没有成功跑通的品种，退出")
        return

    A_df = pd.DataFrame(A_rets).sort_index()
    B_df = pd.DataFrame(B_rets).sort_index()
    bh_df = pd.DataFrame(bh_rets).sort_index()

    port_A = A_df.mean(axis=1, skipna=True)
    port_B = B_df.mean(axis=1, skipna=True)
    port_bh = bh_df.mean(axis=1, skipna=True)

    mA, mB, mBH = compute_port_metrics(port_A), compute_port_metrics(port_B), compute_port_metrics(port_bh)

    summary = pd.DataFrame(per_rows).sort_values("B_sharpe", ascending=False).reset_index(drop=True)
    csv_fp = OUT_DIR / "carry_universe_per_symbol.csv"
    summary.to_csv(csv_fp, index=False, encoding="utf-8-sig")

    print("\n" + "=" * 80)
    print("逐品种对比：A (raw sign) vs B (21d smooth sign)（按 B_sharpe 降序）")
    print("=" * 80)
    with pd.option_context("display.float_format", "{:.3f}".format, "display.width", 160):
        print(summary.to_string(index=False))

    print("\n" + "=" * 80)
    print("组合汇总（动态等权，vol-target=20%，无成本）")
    print("=" * 80)
    fmt = "{:<30s} Sharpe={:+.2f}  Ret={:+6.1%}  Vol={:5.1%}  MaxDD={:+6.1%}  NAV末={:.3f}"
    print(fmt.format("  A (raw sign)",         mA["sharpe"], mA["annual_return"], mA["annual_vol"], mA["max_dd"], mA["nav_end"]))
    print(fmt.format(f"  B (smooth {SMOOTH_WINDOW}d)",  mB["sharpe"], mB["annual_return"], mB["annual_vol"], mB["max_dd"], mB["nav_end"]))
    print(fmt.format("  B&H 等权 (参照)",       mBH["sharpe"], mBH["annual_return"], mBH["annual_vol"], mBH["max_dd"], mBH["nav_end"]))

    print("\n" + "-" * 80)
    print(f"  Δ Sharpe (B - A) = {mB['sharpe'] - mA['sharpe']:+.2f}")
    print(f"  A Sharpe > 0 占比 : {int((summary['A_sharpe'] > 0).sum())}/{len(summary)}")
    print(f"  B Sharpe > 0 占比 : {int((summary['B_sharpe'] > 0).sum())}/{len(summary)}")
    avg_trades_A = summary["A_trades_per_year"].mean()
    avg_trades_B = summary["B_trades_per_year"].mean()
    print(f"  平均换手：A = {avg_trades_A:.1f}/yr   B = {avg_trades_B:.1f}/yr   "
          f"(换手降幅 {(1 - avg_trades_B/avg_trades_A):.0%})")
    print(f"  vs B&H Sharpe={mBH['sharpe']:+.2f}：  "
          f"A {'✅' if mA['sharpe'] > mBH['sharpe'] else '❌'}   "
          f"B {'✅' if mB['sharpe'] > mBH['sharpe'] else '❌'}")
    print(f"  vs TSMOM vt Sharpe=+0.70（参照）：  "
          f"A {'✅' if mA['sharpe'] > 0.70 else '❌'}   "
          f"B {'✅' if mB['sharpe'] > 0.70 else '❌'}")

    # ---------- 画图 ----------
    fig, axes = plt.subplots(2, 1, figsize=(13, 9),
                             gridspec_kw={"height_ratios": [2, 1]})

    ax = axes[0]
    bh_nav = (1 + port_bh.fillna(0)).cumprod()
    A_nav = (1 + port_A.fillna(0)).cumprod()
    B_nav = (1 + port_B.fillna(0)).cumprod()
    ax.plot(bh_nav.index, bh_nav.values,
            label=f"B&H 等权   Sharpe={mBH['sharpe']:+.2f}  NAV={mBH['nav_end']:.2f}",
            color="gray", lw=1.3)
    ax.plot(A_nav.index, A_nav.values,
            label=f"Carry A (raw sign)   Sharpe={mA['sharpe']:+.2f}  NAV={mA['nav_end']:.2f}",
            color="lightcoral", lw=1.4, ls="--")
    ax.plot(B_nav.index, B_nav.values,
            label=f"Carry B (smooth {SMOOTH_WINDOW}d)   Sharpe={mB['sharpe']:+.2f}  NAV={mB['nav_end']:.2f}",
            color="crimson", lw=2.3)
    ax.axhline(1.0, color="black", lw=0.4, alpha=0.5)
    ax.set_title(f"Carry-only 组合：A vs B   "
                 f"(target_vol={TARGET_VOL:.0%}, vol_window={VOL_WINDOW}d)")
    ax.set_ylabel("NAV (起点=1)")
    ax.grid(alpha=0.3)
    ax.legend(loc="upper left")

    ax = axes[1]
    x = np.arange(len(summary))
    w = 0.4
    ax.bar(x - w/2, summary["A_sharpe"], w, label="A raw", color="lightcoral")
    ax.bar(x + w/2, summary["B_sharpe"], w, label="B smooth",
           color=["#2ca02c" if s > 0 else "#d62728" for s in summary["B_sharpe"]])
    ax.axhline(0, color="black", lw=0.6)
    ax.axhline(mA["sharpe"], color="lightcoral", lw=1.2, ls="--",
               label=f"A 组合 Sharpe = {mA['sharpe']:+.2f}")
    ax.axhline(mB["sharpe"], color="crimson", lw=1.5, ls="--",
               label=f"B 组合 Sharpe = {mB['sharpe']:+.2f}")
    ax.axhline(mBH["sharpe"], color="gray", lw=1.2, ls=":",
               label=f"B&H 组合 Sharpe = {mBH['sharpe']:+.2f}")
    ax.set_xticks(x)
    ax.set_xticklabels(summary["symbol"], rotation=45)
    ax.set_title("逐品种 Sharpe 对比")
    ax.set_ylabel("Sharpe")
    ax.legend(loc="lower left", ncol=2)
    ax.grid(alpha=0.3, axis="y")

    plt.tight_layout()
    png_fp = OUT_DIR / "carry_universe_compare.png"
    plt.savefig(png_fp, dpi=120, bbox_inches="tight")
    plt.close(fig)

    print(f"\n[save] {csv_fp}")
    print(f"[save] {png_fp}")


if __name__ == "__main__":
    main()
