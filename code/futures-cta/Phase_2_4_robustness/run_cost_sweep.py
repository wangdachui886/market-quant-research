"""Phase 2.4 · T5 · 交易成本敏感性扫描（net-of-cost 压测）

目的
  Phase 2.3 / T2 / T2.5 的所有结论都建立在"零成本"假设上。
  本脚本把成本模型（单边 bp × |position.diff()|）扣进每日收益，
  横扫 {0, 1, 2, 5, 10, 20} bp，看看 OOS edge 在多大成本下就被吃光。

四个待测组合（和 T2.5 严格对齐）
  1. Pool_filtered_19   事前经济学筛选后的部署候选（T2 基线）
  2. Pool_on_14         Carry-valid 对照组（T2.5 主裁判）
  3. TSMOM_only_19      单引擎参考（含贵金属 TSMOM 运气）
  4. TSMOM_only_14      单引擎对照（剥离贵金属）

成本模型
  daily_cost = cost_bp × 1e-4 × |position.diff()|
  - position = signal × vol_target_scale，所以 vol-target 的每日微调也扣费
    （这是"跟上目标波动就要付成本"的真实成本，不是 bug）
  - 翻转一次（例如 +1 → -1）扣 2×cost_bp bp NAV；半程进/出扣 cost_bp

两条 break-even 红线（都保留）
  A. OOS Sharpe 红线 = 0.60   （B&H Full-sample Sharpe，Phase 2.0 沪铜推得）
     含义：risk-adjusted 来看，还比 HODL 好吗？
  B. OOS 年化 ≥ 2.5%          （货币基金/余额宝等值收益）
     含义：扣完成本还跑赢无风险现金吗？

不做什么
  - 不做多资产不同成本（先用统一 bp，后续 Phase 2.5 再按品种细化）
  - 不改 vol_target（固定 20% 年化）
  - 不重新选择 universe（严格复用 T2/T2.5 定义）

工作流
  写完→停。用户自己跑，结果贴回来一起解读。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "Phase_2_2_tsmom"))

from config import UNIVERSE  # noqa: E402
from sizing import vol_target_scale  # noqa: E402
from backtest import backtest_single  # noqa: E402

_spec_t = importlib.util.spec_from_file_location(
    "tsmom_sig_p22", ROOT / "Phase_2_2_tsmom" / "signals.py"
)
_m_t = importlib.util.module_from_spec(_spec_t); _spec_t.loader.exec_module(_m_t)
tsmom_signal = _m_t.tsmom_signal

_spec_c = importlib.util.spec_from_file_location(
    "carry_sig_p23", ROOT / "Phase_2_3_carry" / "signals.py"
)
_m_c = importlib.util.module_from_spec(_spec_c); _spec_c.loader.exec_module(_m_c)
carry_signal_raw = _m_c.carry_signal_raw

CLEAN_DIR = ROOT / "data_cache" / "tushare" / "clean"
CARRY_DIR = ROOT / "data_cache" / "tushare" / "carry"
OUT_DIR = HERE / "outputs"

# === 冻结参数（和 T1/T2/T2.5 完全一致） ===
LOOKBACK = 252
LAG = 1
TARGET_VOL = 0.20
VOL_WINDOW = 60
VOL_FLOOR = 0.05
MAX_LEV = 3.0
SPLIT = pd.Timestamp("2022-12-31")

CARRY_EXCLUDED = {"AU0", "AG0", "C0", "CF0", "SR0"}
GOLD = {"AU0", "AG0"}

# === 成本扫描网格（单边 bp） ===
BP_GRID = [0, 1, 2, 5, 10, 20]

# === Break-even 红线 ===
BH_SHARPE = 0.60    # Phase 2.0 沪铜 Buy&Hold Full Sharpe
CASH_RET = 0.025    # 货基/余额宝等值年化


# -----------------------------------------------------------------------------
# 数据 / 信号
# -----------------------------------------------------------------------------
def load_ret(sym: str) -> pd.Series:
    df = pd.read_csv(CLEAN_DIR / f"{sym}_clean_returns.csv", parse_dates=["date"]).set_index("date")
    return df["clean_return"].sort_index()


def load_carry(sym: str) -> pd.Series:
    df = pd.read_csv(CARRY_DIR / f"{sym}_carry.csv", parse_dates=["date"]).set_index("date")
    return df["carry"].sort_index()


def build_position(sym: str, mode: str) -> tuple[pd.Series, pd.Series]:
    """构造 (clean_returns, position)；position = signal × vol_target_scale。

    mode:
      - "tsmom"     : 纯 TSMOM
      - "pool_full" : 全品种 (T+C)/2
      - "pool_filt" : 事前经济学筛选，CARRY_EXCLUDED 用 T，其他 (T+C)/2
    """
    ret = load_ret(sym)
    carry = load_carry(sym).reindex(ret.index)
    sig_t = tsmom_signal(ret, lookback_days=LOOKBACK).fillna(0)
    sig_c = carry_signal_raw(carry).fillna(0)
    scale = vol_target_scale(
        ret, target_vol=TARGET_VOL, window=VOL_WINDOW,
        vol_floor=VOL_FLOOR, max_leverage=MAX_LEV,
    )

    if mode == "tsmom":
        sig = sig_t
    elif mode == "pool_full":
        sig = (sig_t + sig_c) / 2.0
    elif mode == "pool_filt":
        sig = sig_t if sym in CARRY_EXCLUDED else (sig_t + sig_c) / 2.0
    else:
        raise ValueError(mode)

    position = sig * scale
    return ret, position


def port_return(symbols: list[str], mode: str, cost_bp: float) -> pd.Series:
    """对给定 universe、mode、成本，构造等权组合日收益（扣完成本）。"""
    rets = {}
    for sym in symbols:
        try:
            ret, pos = build_position(sym, mode)
            # 直接把 position 当 signal 传入（position 已经含 vol-target）
            # lag_days=1：在 backtest_single 内部对 position 再 shift(1)
            # 注意：这里 signal 参数实际是 position（未滞后），内部滞后
            bt = backtest_single(ret, pos, lag_days=LAG, cost_bp=cost_bp)
            rets[sym] = bt["strategy_return"]
        except FileNotFoundError:
            continue
    return pd.DataFrame(rets).mean(axis=1, skipna=True).sort_index()


# -----------------------------------------------------------------------------
# 指标
# -----------------------------------------------------------------------------
def period_metrics(r: pd.Series) -> dict:
    r = r.dropna()
    if len(r) < 20:
        return {k: np.nan for k in ["sharpe", "ann_ret", "ann_vol", "max_dd"]}
    ann_ret = r.mean() * 252
    ann_vol = r.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else np.nan
    nav = (1 + r).cumprod()
    max_dd = (nav / nav.cummax() - 1).min()
    return {
        "sharpe":  float(sharpe) if pd.notna(sharpe) else np.nan,
        "ann_ret": float(ann_ret),
        "ann_vol": float(ann_vol),
        "max_dd":  float(max_dd),
    }


def split_metrics(port: pd.Series) -> dict:
    is_r = port.loc[:SPLIT]
    oos_r = port.loc[SPLIT + pd.Timedelta(days=1):]
    return {
        "IS":   period_metrics(is_r),
        "OOS":  period_metrics(oos_r),
        "Full": period_metrics(port),
    }


def linear_breakeven(bp_grid: list[int], values: list[float], threshold: float) -> float | None:
    """在 (bp, value) 网格上线性插值，找 value 首次跌到 threshold 的 bp。

    约定：value 随 bp 单调下降；threshold 高于 bp=0 时的 value → 返回 0；
    threshold 低于 bp_max 时的 value → 返回 np.inf（成本杀不死）。
    """
    if values[0] <= threshold:
        return 0.0
    if values[-1] > threshold:
        return float("inf")
    for i in range(len(bp_grid) - 1):
        v0, v1 = values[i], values[i + 1]
        if v0 > threshold >= v1:
            b0, b1 = bp_grid[i], bp_grid[i + 1]
            # 线性插值：value = v0 + (v1-v0) * (bp-b0)/(b1-b0)
            if v1 == v0:
                return float(b0)
            return float(b0 + (threshold - v0) * (b1 - b0) / (v1 - v0))
    return None


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main() -> None:
    all_syms = [row[0] for row in UNIVERSE]
    syms_19 = all_syms
    syms_14 = [s for s in all_syms if s not in CARRY_EXCLUDED]

    print("=" * 110)
    print("Phase 2.4 · T5 · 交易成本敏感性扫描")
    print("=" * 110)
    print(f"  成本网格 (单边 bp) : {BP_GRID}")
    print(f"  成本模型           : daily_cost = cost_bp × 1e-4 × |position.diff()|")
    print(f"  universe 19        : {len(syms_19)} 品种")
    print(f"  universe 14        : {len(syms_14)} 品种 (剔除 {sorted(CARRY_EXCLUDED)})")
    print(f"  切点               : IS ≤ {SPLIT.date()} < OOS")
    print(f"  Break-even 红线    : OOS Sharpe ≥ {BH_SHARPE} (B&H)  |  OOS 年化 ≥ {CASH_RET:.1%} (货基)")
    print()

    # 4 个策略定义
    strategies = [
        ("Pool_filtered_19", syms_19, "pool_filt"),
        ("Pool_on_14",       syms_14, "pool_full"),
        ("TSMOM_only_19",    syms_19, "tsmom"),
        ("TSMOM_only_14",    syms_14, "tsmom"),
    ]

    # 主循环：4 策略 × 6 成本
    rows = []
    for name, syms, mode in strategies:
        print(f"  [run] {name}  n={len(syms)}  mode={mode}")
        for bp in BP_GRID:
            port = port_return(syms, mode, cost_bp=float(bp))
            m = split_metrics(port)
            rows.append({
                "strategy": name,
                "n_symbols": len(syms),
                "cost_bp": bp,
                "IS_sharpe":  m["IS"]["sharpe"],
                "IS_ret":     m["IS"]["ann_ret"],
                "OOS_sharpe": m["OOS"]["sharpe"],
                "OOS_ret":    m["OOS"]["ann_ret"],
                "OOS_vol":    m["OOS"]["ann_vol"],
                "OOS_dd":     m["OOS"]["max_dd"],
                "Full_sharpe": m["Full"]["sharpe"],
                "Full_ret":   m["Full"]["ann_ret"],
            })
    df = pd.DataFrame(rows)

    # 打印 OOS 矩阵（主表）
    print("\n" + "-" * 110)
    print("OOS Sharpe 随成本下降（核心表）")
    print("-" * 110)
    header = f"{'strategy':20}" + "".join(f"  bp={b:>3}" for b in BP_GRID)
    print(header)
    for name, _, _ in strategies:
        sub = df[df["strategy"] == name].sort_values("cost_bp")
        row_str = f"{name:20}"
        for v in sub["OOS_sharpe"].values:
            row_str += f"  {v:>+6.2f}"
        print(row_str)

    print("\n" + "-" * 110)
    print("OOS 年化收益 随成本下降")
    print("-" * 110)
    print(header)
    for name, _, _ in strategies:
        sub = df[df["strategy"] == name].sort_values("cost_bp")
        row_str = f"{name:20}"
        for v in sub["OOS_ret"].values:
            row_str += f"  {v:>+6.1%}"
        print(row_str)

    # Break-even 汇总
    print("\n" + "-" * 110)
    print(f"Break-even 成本（线性插值）")
    print(f"  红线 A : OOS Sharpe  ≥ {BH_SHARPE:.2f}  (B&H 基准)")
    print(f"  红线 B : OOS 年化    ≥ {CASH_RET:.1%}  (货基/余额宝)")
    print("-" * 110)
    print(f"{'strategy':20} {'BE_sharpe (bp)':>18} {'BE_return (bp)':>18}")
    be_rows = []
    for name, _, _ in strategies:
        sub = df[df["strategy"] == name].sort_values("cost_bp")
        bps = sub["cost_bp"].tolist()
        sharpes = sub["OOS_sharpe"].tolist()
        rets = sub["OOS_ret"].tolist()
        be_s = linear_breakeven(bps, sharpes, BH_SHARPE)
        be_r = linear_breakeven(bps, rets, CASH_RET)
        be_rows.append({"strategy": name, "BE_sharpe_bp": be_s, "BE_return_bp": be_r})
        s_str = "never_passes" if be_s == 0 else ("cost_cant_kill" if be_s == float("inf") else f"{be_s:>6.1f}")
        r_str = "never_passes" if be_r == 0 else ("cost_cant_kill" if be_r == float("inf") else f"{be_r:>6.1f}")
        print(f"{name:20} {s_str:>18} {r_str:>18}")

    # 存表
    csv_fp = OUT_DIR / "cost_sweep_metrics.csv"
    df.to_csv(csv_fp, index=False, encoding="utf-8-sig")
    be_fp = OUT_DIR / "cost_sweep_breakeven.csv"
    pd.DataFrame(be_rows).to_csv(be_fp, index=False, encoding="utf-8-sig")

    # ------------------------------------------------------------------
    # 画图：两子图 (Sharpe vs bp, ann_ret vs bp)
    # ------------------------------------------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(15, 6))
    colors = {
        "Pool_filtered_19": "#2ca02c",
        "Pool_on_14":       "#1f77b4",
        "TSMOM_only_19":    "#d62728",
        "TSMOM_only_14":    "#ff7f0e",
    }
    markers = {
        "Pool_filtered_19": "o",
        "Pool_on_14":       "s",
        "TSMOM_only_19":    "^",
        "TSMOM_only_14":    "D",
    }

    ax = axes[0]
    for name, _, _ in strategies:
        sub = df[df["strategy"] == name].sort_values("cost_bp")
        ax.plot(sub["cost_bp"], sub["OOS_sharpe"],
                marker=markers[name], color=colors[name], lw=1.8, ms=8,
                label=name)
    ax.axhline(BH_SHARPE, color="black", ls="--", lw=1.0, alpha=0.7,
               label=f"B&H red line = {BH_SHARPE}")
    ax.axhline(0, color="gray", ls=":", lw=0.8, alpha=0.5)
    ax.set_xlabel("Single-side cost (bp)")
    ax.set_ylabel("OOS Sharpe (2023-2025)")
    ax.set_title("OOS Sharpe vs Transaction Cost")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=9, loc="best")

    ax = axes[1]
    for name, _, _ in strategies:
        sub = df[df["strategy"] == name].sort_values("cost_bp")
        ax.plot(sub["cost_bp"], sub["OOS_ret"] * 100,
                marker=markers[name], color=colors[name], lw=1.8, ms=8,
                label=name)
    ax.axhline(CASH_RET * 100, color="black", ls="--", lw=1.0, alpha=0.7,
               label=f"Cash red line = {CASH_RET:.1%}")
    ax.axhline(0, color="gray", ls=":", lw=0.8, alpha=0.5)
    ax.set_xlabel("Single-side cost (bp)")
    ax.set_ylabel("OOS annualized return (%)")
    ax.set_title("OOS Annual Return vs Transaction Cost")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=9, loc="best")

    plt.suptitle("Phase 2.4 · T5 · Transaction Cost Sensitivity", y=1.02, fontsize=13)
    plt.tight_layout()
    fig_fp = OUT_DIR / "cost_sweep.png"
    plt.savefig(fig_fp, dpi=120, bbox_inches="tight")
    plt.close(fig)

    print(f"\n[save] {csv_fp}")
    print(f"[save] {be_fp}")
    print(f"[save] {fig_fp}")
    print("\n[done] T5 完成。请把 CSV + 图贴回来，我们一起解读。")


if __name__ == "__main__":
    main()
