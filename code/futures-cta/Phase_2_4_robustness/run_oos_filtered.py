"""Phase 2.4 · T2 · Universe Refinement（事前经济学筛选后的 Pool OOS）

T1 的 Pool OOS Sharpe = 0.34 未通过 0.50 通过线，run_oos_diagnose_carry.py
诊断出崩溃来自 5 个品种（AU / AG / C / CF / SR），这 5 个品种的 Carry 信号
在学术文献里本就不应该使用：

  - AU / AG  : KMPV (2018) —— 贵金属 carry 只含 cost-of-carry，无 convenience
              yield，不应作为预测信号；pos_rate≈0 → 永远单边空头
  - C / CF / SR : Erb-Harvey (2006) —— policy-distorted 商品，中国临储/国储
                  制度使 basis 不反映供需

T2 的单一问题：**事前经济学筛选 Carry universe 之后，Pool OOS 能否恢复到
≥ 0.50 通过线？** 验证"双引擎分散增益"这个 Phase 2.3 主命题。

非对称合成规则（这是 T2 和 T1 的唯一区别）：
  - 14 个 Carry-valid 品种：pos = (sig_T + sig_C) / 2 × scale      （和 T1 一致）
  -  5 个 Carry-excluded 品种：pos = sig_T × scale                   （纯 TSMOM）
  - TSMOM universe 仍然是 19 品种

三条对比（同一把尺）：
  - Pool_original : 全 19 用 (T+C)/2        （T1 结果，OOS=0.34）
  - Pool_filtered : 14 用 (T+C)/2 + 5 用 T   （T2 新假设）
  - TSMOM_only    : 全 19 用 T              （作基准线，OOS=0.64）

验收判据：Pool_filtered OOS Sharpe
  ≥ 0.70 强通过 | ≥ 0.50 通过 | 0.30-0.50 红旗 | <0.30 失败
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
OUT_DIR.mkdir(exist_ok=True)

LOOKBACK = 252
LAG = 1
TARGET_VOL = 0.20
VOL_WINDOW = 60
VOL_FLOOR = 0.05
MAX_LEV = 3.0
SPLIT = pd.Timestamp("2022-12-31")

# 事前经济学筛选：排除 5 个品种的 Carry 信号（理由见文件头）
CARRY_EXCLUDED = {"AU0", "AG0", "C0", "CF0", "SR0"}


def load_ret(sym: str) -> pd.Series:
    df = pd.read_csv(CLEAN_DIR / f"{sym}_clean_returns.csv", parse_dates=["date"]).set_index("date")
    return df["clean_return"].sort_index()


def load_carry(sym: str) -> pd.Series:
    df = pd.read_csv(CARRY_DIR / f"{sym}_carry.csv", parse_dates=["date"]).set_index("date")
    return df["carry"].sort_index()


def build_three_strategies(sym: str) -> dict:
    """为单品种生成三条策略日收益：orig_pool / filt_pool / tsmom_only。

    三者唯一差异在于 pool 合成规则：
      - orig_pool : 全品种都用 (sig_T + sig_C) / 2  （T1 规则）
      - filt_pool : 若 sym 在 CARRY_EXCLUDED → 纯 sig_T；否则 (sig_T + sig_C) / 2
      - tsmom_only: 全品种都用 sig_T
    """
    ret = load_ret(sym)
    carry = load_carry(sym).reindex(ret.index)

    sig_t = tsmom_signal(ret, lookback_days=LOOKBACK).fillna(0)
    sig_c = carry_signal_raw(carry).fillna(0)
    scale = vol_target_scale(
        ret, target_vol=TARGET_VOL, window=VOL_WINDOW,
        vol_floor=VOL_FLOOR, max_leverage=MAX_LEV,
    )

    sig_orig = (sig_t + sig_c) / 2.0
    if sym in CARRY_EXCLUDED:
        sig_filt = sig_t
    else:
        sig_filt = (sig_t + sig_c) / 2.0
    sig_tonly = sig_t

    pos_orig  = sig_orig  * scale
    pos_filt  = sig_filt  * scale
    pos_tonly = sig_tonly * scale

    bt_orig  = backtest_single(ret, pos_orig,  lag_days=LAG)
    bt_filt  = backtest_single(ret, pos_filt,  lag_days=LAG)
    bt_tonly = backtest_single(ret, pos_tonly, lag_days=LAG)

    return {
        "bh":         ret,
        "orig_pool":  bt_orig["strategy_return"],
        "filt_pool":  bt_filt["strategy_return"],
        "tsmom_only": bt_tonly["strategy_return"],
    }


def period_metrics(r: pd.Series) -> dict:
    r = r.dropna()
    if len(r) < 20:
        return {k: np.nan for k in ["sharpe", "ann_ret", "ann_vol", "max_dd", "nav_end"]}
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
    }


def main() -> None:
    symbols = [row[0] for row in UNIVERSE]
    carry_keep = [s for s in symbols if s not in CARRY_EXCLUDED]

    print("=" * 100)
    print(f"Phase 2.4 · T2 · Universe Refinement")
    print(f"  TSMOM universe : {len(symbols)} 品种（不变）")
    print(f"  Carry universe : {len(carry_keep)} 品种（事前经济学筛选）")
    print(f"  Carry excluded : {sorted(CARRY_EXCLUDED)}")
    print(f"  切分           : IS ≤ {SPLIT.date()}  <  OOS")
    print(f"  参数冻结       : lookback={LOOKBACK}  target_vol={TARGET_VOL:.0%}  "
          f"vol_window={VOL_WINDOW}  lag={LAG}")
    print("=" * 100)

    bh_dict: dict[str, pd.Series] = {}
    orig_dict: dict[str, pd.Series] = {}
    filt_dict: dict[str, pd.Series] = {}
    tonly_dict: dict[str, pd.Series] = {}

    for sym in symbols:
        try:
            out = build_three_strategies(sym)
        except FileNotFoundError as e:
            print(f"  [skip] {sym}: {e}")
            continue
        bh_dict[sym]    = out["bh"]
        orig_dict[sym]  = out["orig_pool"]
        filt_dict[sym]  = out["filt_pool"]
        tonly_dict[sym] = out["tsmom_only"]

    port_bh    = pd.DataFrame(bh_dict).mean(axis=1, skipna=True).sort_index()
    port_orig  = pd.DataFrame(orig_dict).mean(axis=1, skipna=True).sort_index()
    port_filt  = pd.DataFrame(filt_dict).mean(axis=1, skipna=True).sort_index()
    port_tonly = pd.DataFrame(tonly_dict).mean(axis=1, skipna=True).sort_index()

    strategies = {
        "B&H":            port_bh,
        "TSMOM_only":     port_tonly,
        "Pool_original":  port_orig,
        "Pool_filtered":  port_filt,
    }

    rows = []
    for name, port in strategies.items():
        is_r  = port.loc[:SPLIT]
        oos_r = port.loc[SPLIT + pd.Timedelta(days=1):]
        rows.append({"strategy": name, "period": "IS",   **period_metrics(is_r)})
        rows.append({"strategy": name, "period": "OOS",  **period_metrics(oos_r)})
        rows.append({"strategy": name, "period": "Full", **period_metrics(port)})
    report = pd.DataFrame(rows)

    pivot_sharpe = report.pivot(index="strategy", columns="period", values="sharpe")[["IS", "OOS", "Full"]]
    pivot_ret    = report.pivot(index="strategy", columns="period", values="ann_ret")[["IS", "OOS", "Full"]]
    pivot_vol    = report.pivot(index="strategy", columns="period", values="ann_vol")[["IS", "OOS", "Full"]]
    pivot_dd     = report.pivot(index="strategy", columns="period", values="max_dd")[["IS", "OOS", "Full"]]

    strat_order = ["B&H", "TSMOM_only", "Pool_original", "Pool_filtered"]
    pivot_sharpe = pivot_sharpe.reindex(strat_order)
    pivot_ret    = pivot_ret.reindex(strat_order)
    pivot_vol    = pivot_vol.reindex(strat_order)
    pivot_dd     = pivot_dd.reindex(strat_order)

    def _f_sh(df):
        return df.map(lambda x: f"{x:+.2f}" if pd.notna(x) else "—")
    def _f_pct(df):
        return df.map(lambda x: f"{x:+.1%}" if pd.notna(x) else "—")

    print("\n  Sharpe：")
    print(_f_sh(pivot_sharpe).to_string())
    print("\n  年化收益：")
    print(_f_pct(pivot_ret).to_string())
    print("\n  年化波动：")
    print(_f_pct(pivot_vol).to_string())
    print("\n  最大回撤：")
    print(_f_pct(pivot_dd).to_string())

    # ---- T2 核心判据 ----
    filt_oos = pivot_sharpe.loc["Pool_filtered", "OOS"]
    orig_oos = pivot_sharpe.loc["Pool_original", "OOS"]
    tonly_oos = pivot_sharpe.loc["TSMOM_only", "OOS"]
    filt_is = pivot_sharpe.loc["Pool_filtered", "IS"]

    print("\n" + "-" * 100)
    print("T2 核心判据（Pool_filtered OOS Sharpe）")
    print("-" * 100)
    print(f"  Pool_original  OOS = {orig_oos:+.2f}   (T1 基准，未通过 0.50)")
    print(f"  TSMOM_only     OOS = {tonly_oos:+.2f}   (单引擎基线，需被超过才有'双引擎增益')")
    print(f"  Pool_filtered  OOS = {filt_oos:+.2f}   (本次 T2)")
    print(f"  Pool_filtered  IS  = {filt_is:+.2f}")
    print(f"  Δ (Filt - Orig) OOS = {filt_oos - orig_oos:+.2f}  ← 筛选带来的增益")
    print(f"  Δ (Filt - TSMOM) OOS = {filt_oos - tonly_oos:+.2f}  ← 双引擎相对单引擎的 OOS 增益")

    print()
    if filt_oos >= 0.70:
        verdict_a = "[PASS++] 强通过：Pool_filtered OOS >= 0.70"
    elif filt_oos >= 0.50:
        verdict_a = "[PASS]   通过：Pool_filtered OOS >= 0.50，Carry universe 筛选假设被证实"
    elif filt_oos >= 0.30:
        verdict_a = "[WARN]   红旗：Pool_filtered OOS 在 0.30-0.50，筛选有改善但未过通过线"
    elif filt_oos >= 0:
        verdict_a = "[FAIL]   失败：Pool_filtered OOS < 0.30"
    else:
        verdict_a = "[DEAD]   彻底失败：Pool_filtered OOS 为负"
    print(f"  判据 A (通过线)    : {verdict_a}")

    if filt_oos > tonly_oos:
        verdict_b = f"[PASS]   Pool_filtered ({filt_oos:+.2f}) > TSMOM_only ({tonly_oos:+.2f})，双引擎仍有增益"
    else:
        verdict_b = f"[FAIL]   Pool_filtered ({filt_oos:+.2f}) <= TSMOM_only ({tonly_oos:+.2f})，'双引擎分散增益' 命题被证伪"
    print(f"  判据 B (相对 T)    : {verdict_b}")

    # ---- 存表 ----
    csv_fp = OUT_DIR / "oos_filtered_metrics.csv"
    report.to_csv(csv_fp, index=False, encoding="utf-8-sig")

    # ---- 画图 ----
    fig, axes = plt.subplots(2, 1, figsize=(14, 10), gridspec_kw={"height_ratios": [2.2, 1]})

    ax = axes[0]
    cfg = {
        "B&H":           ("gray",       1.2, "-"),
        "TSMOM_only":    ("steelblue",  1.8, "--"),
        "Pool_original": ("crimson",    1.8, "--"),
        "Pool_filtered": ("darkgreen",  2.6, "-"),
    }
    for name, (color, lw, ls) in cfg.items():
        port = strategies[name]
        nav = (1 + port.fillna(0)).cumprod()
        ax.plot(nav.index, nav.values, label=name, color=color, lw=lw, ls=ls)

    ax.axvline(SPLIT, color="black", lw=1.2, ls=":", alpha=0.7)
    ymax = ax.get_ylim()[1]
    ax.text(SPLIT - pd.Timedelta(days=40), ymax * 0.95, "IS",
            ha="right", fontsize=10, color="dimgray")
    ax.text(SPLIT + pd.Timedelta(days=40), ymax * 0.95, "OOS",
            ha="left", fontsize=10, color="black", fontweight="bold")
    ax.axhline(1.0, color="black", lw=0.4, alpha=0.4)

    lines = []
    for name in strat_order:
        is_s  = pivot_sharpe.loc[name, "IS"]
        oos_s = pivot_sharpe.loc[name, "OOS"]
        lines.append(f"{name:15s}  IS={is_s:+.2f}  OOS={oos_s:+.2f}")
    ax.text(0.02, 0.97, "\n".join(lines),
            transform=ax.transAxes, fontsize=10, va="top",
            family="monospace",
            bbox=dict(boxstyle="round", facecolor="white", alpha=0.9, edgecolor="gray"))

    ax.set_title(f"T2 · Universe Refinement · 连续 NAV（切点 {SPLIT.date()}）")
    ax.set_ylabel("NAV (起点=1)")
    ax.grid(alpha=0.3)
    ax.legend(loc="lower right", fontsize=9)

    ax = axes[1]
    x = np.arange(len(strat_order))
    w = 0.28
    is_vals   = [pivot_sharpe.loc[s, "IS"]   for s in strat_order]
    oos_vals  = [pivot_sharpe.loc[s, "OOS"]  for s in strat_order]
    full_vals = [pivot_sharpe.loc[s, "Full"] for s in strat_order]
    ax.bar(x - w, is_vals,   w, label="IS",   color="lightsteelblue")
    ax.bar(x,     full_vals, w, label="Full", color="lightgray")
    oos_colors = ["#2ca02c" if v > 0.5 else ("#ff7f0e" if v > 0.3 else "#d62728") for v in oos_vals]
    ax.bar(x + w, oos_vals,  w, label="OOS", color=oos_colors)
    ax.axhline(0, color="black", lw=0.6)
    ax.axhline(0.5, color="orange", lw=0.8, ls="--", alpha=0.6, label="OOS 通过线 0.50")
    ax.axhline(0.70, color="green",  lw=0.8, ls="--", alpha=0.6, label="OOS 强通过 0.70")
    for i, (iv, fv, ov) in enumerate(zip(is_vals, full_vals, oos_vals)):
        ax.text(i - w, iv + 0.02, f"{iv:+.2f}", ha="center", fontsize=8)
        ax.text(i,     fv + 0.02, f"{fv:+.2f}", ha="center", fontsize=8)
        ax.text(i + w, ov + 0.02, f"{ov:+.2f}", ha="center", fontsize=8, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(strat_order)
    ax.set_title("Sharpe 三段对比：IS / Full / OOS（OOS 颜色反映验收等级）")
    ax.set_ylabel("Sharpe")
    ax.grid(alpha=0.3, axis="y")
    ax.legend(loc="lower right", fontsize=8, ncol=2)

    plt.tight_layout()
    png_fp = OUT_DIR / "oos_filtered_comparison.png"
    plt.savefig(png_fp, dpi=120, bbox_inches="tight")
    plt.close(fig)

    print(f"\n[save] {csv_fp}")
    print(f"[save] {png_fp}")


if __name__ == "__main__":
    main()
