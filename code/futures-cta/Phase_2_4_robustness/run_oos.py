"""Phase 2.4 · T1 · Out-of-Sample 检验

检验 Phase 2.3 的 Pool Sharpe=0.86 是否"只在历史那段上对"。

设计（已对齐的 5 个决策）：
  1. 切点       : 2022-12-31（IS 6 年 : OOS 3 年，≈ 2:1）
  2. 跨界方式   : 自然跨界——OOS 段的 rolling 信号/scale 允许回看 IS 尾部
                  （严格回看无未来函数，等价于"实盘在 2022 末不 reset 继续跑"）
  3. 严格性     : 半严格 OOS——承认 universe 选择看过全期，只检验
                 "规则在新时间段是否稳定"
  4. 指标口径   : IS / OOS / Full 三段独立算指标（3 策略 × 3 口径 = 9 组）
  5. 成本       : 本脚本不加，T5 专门测

策略（和 Phase 2.3 run_pooled.py 完全一致）：
  Layer 1 · 信号   tsmom_signal(lookback=252) + carry_signal_raw
  Layer 2 · 仓位   vol_target_scale(target=20%, window=60, floor=5%, max_lev=3)
  Layer 3 · 执行   shift(lag=1)
  Pool 合成       sig_p = (sig_t + sig_c) / 2；pos_p = sig_p × scale
  组合层          等权 19 品种

验收（Pool OOS Sharpe）：
  ≥ 0.70 强通过 | ≥ 0.50 通过 | 0.30-0.50 红旗 | <0.30 失败

用法：
    python Phase_2_4_robustness/run_oos.py
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
PROJECT_ROOT = HERE.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "Phase_2_2_tsmom"))
sys.path.insert(0, str(PROJECT_ROOT / "Phase_2_3_carry"))

from config import UNIVERSE  # noqa: E402
from sizing import vol_target_scale  # noqa: E402
from backtest import backtest_single  # noqa: E402


# 同名模块（Phase 2.2 / 2.3 都有 signals.py）用 importlib 显式加载
def _load_module(name: str, fp: Path):
    spec = importlib.util.spec_from_file_location(name, fp)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_tsmom_sig = _load_module("tsmom_signals", PROJECT_ROOT / "Phase_2_2_tsmom" / "signals.py")
_carry_sig = _load_module("carry_signals", PROJECT_ROOT / "Phase_2_3_carry" / "signals.py")
tsmom_signal = _tsmom_sig.tsmom_signal
carry_signal_raw = _carry_sig.carry_signal_raw


CLEAN_DIR = PROJECT_ROOT / "data_cache" / "tushare" / "clean"
CARRY_DIR = PROJECT_ROOT / "data_cache" / "tushare" / "carry"
OUT_DIR = HERE / "outputs"
OUT_DIR.mkdir(exist_ok=True)

# ---- 参数（全部从 Phase 2.3 冻结） ----
LOOKBACK = 252
LAG = 1
TARGET_VOL = 0.20
VOL_WINDOW = 60
VOL_FLOOR = 0.05
MAX_LEV = 3.0

# ---- OOS 切点 ----
SPLIT_DATE = pd.Timestamp("2022-12-31")


# ============================================================================
# 数据 + 单品种策略生成（和 Phase 2.3 一致）
# ============================================================================
def load_clean_returns(symbol: str) -> pd.Series:
    df = pd.read_csv(CLEAN_DIR / f"{symbol}_clean_returns.csv", parse_dates=["date"]).set_index("date")
    s = df["clean_return"].sort_index()
    s.name = symbol
    return s


def load_carry(symbol: str) -> pd.Series:
    df = pd.read_csv(CARRY_DIR / f"{symbol}_carry.csv", parse_dates=["date"]).set_index("date")
    s = df["carry"].sort_index()
    s.name = symbol
    return s


def build_strategy_returns(symbol: str) -> dict:
    """为单品种生成三条策略日收益（T / C / Pool），以及 B&H。

    所有滚动窗口在全期上计算（自然跨界），下游再按日期切 IS/OOS。
    """
    ret = load_clean_returns(symbol)
    carry = load_carry(symbol).reindex(ret.index)

    sig_t = tsmom_signal(ret, lookback_days=LOOKBACK)
    sig_c = carry_signal_raw(carry)
    scale = vol_target_scale(ret, target_vol=TARGET_VOL, window=VOL_WINDOW,
                             vol_floor=VOL_FLOOR, max_leverage=MAX_LEV)

    pos_t = sig_t * scale
    pos_c = sig_c * scale
    sig_p = (sig_t.fillna(0) + sig_c.fillna(0)) / 2.0
    pos_p = sig_p * scale

    bt_t = backtest_single(ret, pos_t, lag_days=LAG)
    bt_c = backtest_single(ret, pos_c, lag_days=LAG)
    bt_p = backtest_single(ret, pos_p, lag_days=LAG)

    return {
        "bh":  ret,
        "T":   bt_t["strategy_return"],
        "C":   bt_c["strategy_return"],
        "P":   bt_p["strategy_return"],
    }


# ============================================================================
# 指标计算（分段）
# ============================================================================
def period_metrics(ret: pd.Series) -> dict:
    r = ret.dropna()
    if len(r) < 20:
        return {k: np.nan for k in ["sharpe", "ann_ret", "ann_vol", "max_dd", "nav_end", "n_days"]}
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
        "nav_end": float(nav.iloc[-1]),
        "n_days":  int(len(r)),
    }


def split_ret(port_ret: pd.Series, split: pd.Timestamp) -> tuple[pd.Series, pd.Series]:
    return port_ret.loc[:split], port_ret.loc[split + pd.Timedelta(days=1):]


# ============================================================================
# 主流程
# ============================================================================
def main() -> None:
    symbols = [row[0] for row in UNIVERSE]

    print("=" * 90)
    print(f"Phase 2.4 · T1 OOS   N={len(symbols)}   "
          f"IS: …→{SPLIT_DATE.date()}   OOS: {SPLIT_DATE.date()}+1→…")
    print(f"参数冻结：lookback={LOOKBACK}  target_vol={TARGET_VOL:.0%}  "
          f"vol_window={VOL_WINDOW}  lag={LAG}")
    print("=" * 90)

    # 逐品种生成四条序列
    bh_rets: dict[str, pd.Series] = {}
    T_rets: dict[str, pd.Series] = {}
    C_rets: dict[str, pd.Series] = {}
    P_rets: dict[str, pd.Series] = {}

    for sym in symbols:
        try:
            out = build_strategy_returns(sym)
        except FileNotFoundError as e:
            print(f"  [skip] {sym}: {e}")
            continue
        bh_rets[sym] = out["bh"]
        T_rets[sym] = out["T"]
        C_rets[sym] = out["C"]
        P_rets[sym] = out["P"]

    # 组合层（动态等权）
    port_bh = pd.DataFrame(bh_rets).mean(axis=1, skipna=True).sort_index()
    port_T = pd.DataFrame(T_rets).mean(axis=1, skipna=True).sort_index()
    port_C = pd.DataFrame(C_rets).mean(axis=1, skipna=True).sort_index()
    port_P = pd.DataFrame(P_rets).mean(axis=1, skipna=True).sort_index()

    strategies = {"B&H": port_bh, "TSMOM": port_T, "Carry": port_C, "Pool": port_P}

    # 三段指标计算
    rows = []
    for name, port in strategies.items():
        is_ret, oos_ret = split_ret(port, SPLIT_DATE)
        rows.append({"strategy": name, "period": "IS",   **period_metrics(is_ret)})
        rows.append({"strategy": name, "period": "OOS",  **period_metrics(oos_ret)})
        rows.append({"strategy": name, "period": "Full", **period_metrics(port)})

    report = pd.DataFrame(rows)

    # ---- 打印汇总表 ----
    print("\n" + "=" * 90)
    print("指标对比（IS / OOS / Full）")
    print("=" * 90)
    pivot_sharpe = report.pivot(index="strategy", columns="period", values="sharpe")[["IS", "OOS", "Full"]]
    pivot_ret    = report.pivot(index="strategy", columns="period", values="ann_ret")[["IS", "OOS", "Full"]]
    pivot_vol    = report.pivot(index="strategy", columns="period", values="ann_vol")[["IS", "OOS", "Full"]]
    pivot_dd     = report.pivot(index="strategy", columns="period", values="max_dd")[["IS", "OOS", "Full"]]

    def _fmt_sharpe(df):
        return df.map(lambda x: f"{x:+.2f}" if pd.notna(x) else "—")
    def _fmt_pct(df):
        return df.map(lambda x: f"{x:+.1%}" if pd.notna(x) else "—")

    print("\n  Sharpe：")
    print(_fmt_sharpe(pivot_sharpe).to_string())
    print("\n  年化收益：")
    print(_fmt_pct(pivot_ret).to_string())
    print("\n  年化波动：")
    print(_fmt_pct(pivot_vol).to_string())
    print("\n  最大回撤：")
    print(_fmt_pct(pivot_dd).to_string())

    # ---- OOS 衰减 ----
    print("\n" + "-" * 90)
    print("Sharpe 衰减（OOS - IS）")
    print("-" * 90)
    for strat in ["B&H", "TSMOM", "Carry", "Pool"]:
        is_s = pivot_sharpe.loc[strat, "IS"]
        oos_s = pivot_sharpe.loc[strat, "OOS"]
        delta = oos_s - is_s
        ratio = oos_s / is_s if is_s != 0 else np.nan
        mark = "✅" if delta > -0.3 else ("⚠️" if delta > -0.6 else "❌")
        print(f"  {strat:>6}:  IS {is_s:+.2f}  →  OOS {oos_s:+.2f}   "
              f"Δ={delta:+.2f}  (OOS/IS={ratio:+.1%})  {mark}")

    # ---- 验收 ----
    pool_oos = pivot_sharpe.loc["Pool", "OOS"]
    print("\n" + "-" * 90)
    print("最终验收（按 Pool OOS Sharpe）")
    print("-" * 90)
    if pool_oos >= 0.70:
        verdict = "✅✅ 强通过：Pool OOS Sharpe ≥ 0.70，几乎无衰减"
    elif pool_oos >= 0.50:
        verdict = "✅ 通过：Pool OOS Sharpe ≥ 0.50，策略在新时间段稳定"
    elif pool_oos >= 0.30:
        verdict = "⚠️ 红旗：Pool OOS Sharpe 在 0.30-0.50 之间，需要诊断"
    elif pool_oos >= 0:
        verdict = "❌ 失败：Pool OOS Sharpe < 0.30，IS 结果大概率是运气"
    else:
        verdict = "☠️ 彻底失败：Pool OOS Sharpe 为负"
    print(f"  Pool OOS Sharpe = {pool_oos:+.2f}   {verdict}")

    # ---- 存表 ----
    csv_fp = OUT_DIR / "oos_metrics.csv"
    report.to_csv(csv_fp, index=False, encoding="utf-8-sig")

    # ---- 画图 ----
    fig, axes = plt.subplots(2, 1, figsize=(14, 10),
                             gridspec_kw={"height_ratios": [2.2, 1]})

    # --- 上：连续 NAV + 切点竖线 ---
    ax = axes[0]
    cfg = {
        "B&H":   ("gray",      1.2, "-",  False),
        "TSMOM": ("steelblue", 1.5, "--", False),
        "Carry": ("crimson",   1.5, "--", False),
        "Pool":  ("darkgreen", 2.4, "-",  True),
    }
    for name, (color, lw, ls, _) in cfg.items():
        port = strategies[name]
        nav = (1 + port.fillna(0)).cumprod()
        ax.plot(nav.index, nav.values, label=name, color=color, lw=lw, ls=ls)

    ax.axvline(SPLIT_DATE, color="black", lw=1.2, ls=":", alpha=0.7)
    ymax = ax.get_ylim()[1]
    ax.text(SPLIT_DATE - pd.Timedelta(days=40), ymax * 0.95, "IS",
            ha="right", fontsize=10, color="dimgray")
    ax.text(SPLIT_DATE + pd.Timedelta(days=40), ymax * 0.95, "OOS",
            ha="left", fontsize=10, color="black", fontweight="bold")
    ax.axhline(1.0, color="black", lw=0.4, alpha=0.4)

    # 丰富 legend：标注 IS/OOS Sharpe
    legend_lines = []
    for name in ["B&H", "TSMOM", "Carry", "Pool"]:
        is_s = pivot_sharpe.loc[name, "IS"]
        oos_s = pivot_sharpe.loc[name, "OOS"]
        legend_lines.append(f"{name}   IS={is_s:+.2f}  OOS={oos_s:+.2f}")
    ax.text(0.02, 0.97, "\n".join(legend_lines),
            transform=ax.transAxes, fontsize=10, va="top",
            family="monospace",
            bbox=dict(boxstyle="round", facecolor="white", alpha=0.85, edgecolor="gray"))

    ax.set_title(f"IS vs OOS · 连续 NAV（切点 {SPLIT_DATE.date()}）")
    ax.set_ylabel("NAV (起点=1)")
    ax.grid(alpha=0.3)
    ax.legend(loc="lower right", fontsize=9)

    # --- 下：Sharpe 对比柱 ---
    ax = axes[1]
    strats_order = ["B&H", "TSMOM", "Carry", "Pool"]
    x = np.arange(len(strats_order))
    w = 0.28
    is_vals = [pivot_sharpe.loc[s, "IS"] for s in strats_order]
    oos_vals = [pivot_sharpe.loc[s, "OOS"] for s in strats_order]
    full_vals = [pivot_sharpe.loc[s, "Full"] for s in strats_order]
    ax.bar(x - w, is_vals,   w, label="IS",   color="lightsteelblue")
    ax.bar(x,     full_vals, w, label="Full", color="lightgray")
    ax.bar(x + w, oos_vals,  w, label="OOS",
           color=["#2ca02c" if v > 0.5 else ("#ff7f0e" if v > 0.3 else "#d62728") for v in oos_vals])
    ax.axhline(0, color="black", lw=0.6)
    ax.axhline(0.5, color="orange", lw=0.8, ls="--", alpha=0.6, label="OOS 通过线 0.50")
    ax.axhline(0.70, color="green", lw=0.8, ls="--", alpha=0.6, label="OOS 强通过 0.70")
    for i, (ival, fval, oval) in enumerate(zip(is_vals, full_vals, oos_vals)):
        ax.text(i - w, ival + 0.02, f"{ival:+.2f}", ha="center", fontsize=8)
        ax.text(i,     fval + 0.02, f"{fval:+.2f}", ha="center", fontsize=8)
        ax.text(i + w, oval + 0.02, f"{oval:+.2f}", ha="center", fontsize=8, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(strats_order)
    ax.set_title("Sharpe 三段对比：IS / Full / OOS（OOS 颜色反映验收等级）")
    ax.set_ylabel("Sharpe")
    ax.grid(alpha=0.3, axis="y")
    ax.legend(loc="lower right", fontsize=8, ncol=2)

    plt.tight_layout()
    png_fp = OUT_DIR / "oos_comparison.png"
    plt.savefig(png_fp, dpi=120, bbox_inches="tight")
    plt.close(fig)

    print(f"\n[save] {csv_fp}")
    print(f"[save] {png_fp}")


if __name__ == "__main__":
    main()
