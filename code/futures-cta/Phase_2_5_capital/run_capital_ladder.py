"""Phase 2.5a · 资金阶梯 / 实盘可部署性分析

承接 Phase 2.4 · T5 的发现：
  - Pool_filtered_19 在零成本下 OOS Sharpe 1.27，BE=15bp，看起来稳健
  - 但其中约 0.64 Sharpe 来自 AU/AG 的 TSMOM 单边（低换手、耐成本）
  - Pool_on_14（剥离贵金属的"干净双引擎"）bp=0 Sharpe 0.63，但 BE_sharpe 只有 0.6bp
  - T5 留下的关键问题：10万资金真能持有 AU/AG 吗？能复刻哪个版本？

本脚本回答一个问题：
  "在资金档 K ∈ {10, 30, 50, 100, 300, 1000} 万时，扣完：
    (1) 整手化约束（小于半手的品种被挤出组合）
    (2) 保证金预算约束（总占用 ≤ 账户 50%）
    (3) 实盘成本（单边 2bp）
  之后，Pool_filtered_19 和 Pool_on_14 各自的净 OOS Sharpe / 年化是多少？"

核心映射（理想仓位 → 实盘仓位）
  - 原始回测里每品种在组合里等权 1/N，其名义暴露 = (K/N) × ideal_position
  - 转换成手数：lots = round( (K/N) × ideal_pos / (price × multiplier) )
  - 如果 |target_notional| < 半手名义值 → lots=0，该品种当日被踢出
  - 再用当日总保证金占用检查，超过 K × 0.50 则按比例降杠杆
  - degraded_position = lots × price × mult × N / K  （反算回"单位化仓位"喂给 backtest_single）

假设（写死，保守口径）
  - 成本：2 bp 单边（国内主力合约典型）
  - 保证金上限：50% 账户（留 2x 缓冲防 vol spike / 追保）
  - 保证金率：近似按交易所公布 + 期货公司加成（每品种 8-13%）
  - 整手化：round-half-away-from-zero，保留方向

输出
  outputs/capital_ladder_metrics.csv  主表（6×2 = 12 行）
  outputs/capital_ladder_verdict.csv  每档最小可部署资金判决
  outputs/capital_ladder.png          Sharpe-vs-K 和有效品种数-vs-K 两张图
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

RAW_DIR = ROOT / "data_cache" / "raw"
CLEAN_DIR = ROOT / "data_cache" / "tushare" / "clean"
CARRY_DIR = ROOT / "data_cache" / "tushare" / "carry"
OUT_DIR = HERE / "outputs"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# === 冻结参数（与 T1/T2/T2.5/T5 一致） ===
LOOKBACK = 252
LAG = 1
TARGET_VOL = 0.20
VOL_WINDOW = 60
VOL_FLOOR = 0.05
MAX_LEV = 3.0
SPLIT = pd.Timestamp("2022-12-31")

CARRY_EXCLUDED = {"AU0", "AG0", "C0", "CF0", "SR0"}

# === Phase 2.5a 新增实盘假设 ===
COST_BP = 2.0                # 单边成本（T5 扫描显示实盘中位数 2-3bp）
MARGIN_BUDGET = 0.50         # 最大保证金占用比例（剩 50% 缓冲 vol spike + 追保）
CAPITAL_GRID = [10, 30, 50, 100, 300, 1000]  # 单位：万元

# === 保证金率（近似，交易所公布 + 期货公司加成 2-3%，2025 年典型值） ===
MARGIN_RATE = {
    "AU0": 0.10, "AG0": 0.12,
    "CU0": 0.11, "ZN0": 0.11, "AL0": 0.10,
    "RB0": 0.09, "HC0": 0.09, "I0": 0.13, "J0": 0.14,
    "TA0": 0.09, "MA0": 0.10, "RU0": 0.13, "SC0": 0.13,
    "M0":  0.09, "C0":  0.08, "P0":  0.11, "Y0":  0.10,
    "SR0": 0.08, "CF0": 0.08,
}

UNIVERSE_MAP = {row[0]: row for row in UNIVERSE}  # sym -> (sym, name, sector, exch, mult)


# -----------------------------------------------------------------------------
# 数据加载
# -----------------------------------------------------------------------------
def load_ret(sym: str) -> pd.Series:
    df = pd.read_csv(CLEAN_DIR / f"{sym}_clean_returns.csv", parse_dates=["date"]).set_index("date")
    return df["clean_return"].sort_index()


def load_carry(sym: str) -> pd.Series:
    df = pd.read_csv(CARRY_DIR / f"{sym}_carry.csv", parse_dates=["date"]).set_index("date")
    return df["carry"].sort_index()


def load_price(sym: str) -> pd.Series:
    """主力连续合约 close。用来做整手化与保证金计算。"""
    df = pd.read_csv(RAW_DIR / f"{sym}.csv", parse_dates=["date"]).set_index("date")
    return df["close"].sort_index()


# -----------------------------------------------------------------------------
# 理想仓位（未整手化，和 T2/T2.5 一致）
# -----------------------------------------------------------------------------
def build_ideal_pos(sym: str, mode: str) -> tuple[pd.Series, pd.Series, pd.Series]:
    """返回 (clean_returns, ideal_position_unshifted, price)。

    mode:
      - "pool_filt" : CARRY_EXCLUDED 用纯 TSMOM，其他 (T+C)/2
      - "pool_full" : 全品种 (T+C)/2
    """
    ret = load_ret(sym)
    carry = load_carry(sym).reindex(ret.index)
    price = load_price(sym).reindex(ret.index).ffill()

    sig_t = tsmom_signal(ret, lookback_days=LOOKBACK).fillna(0)
    sig_c = carry_signal_raw(carry).fillna(0)
    scale = vol_target_scale(
        ret, target_vol=TARGET_VOL, window=VOL_WINDOW,
        vol_floor=VOL_FLOOR, max_leverage=MAX_LEV,
    )

    if mode == "pool_filt":
        sig = sig_t if sym in CARRY_EXCLUDED else (sig_t + sig_c) / 2.0
    elif mode == "pool_full":
        sig = (sig_t + sig_c) / 2.0
    else:
        raise ValueError(mode)

    pos_ideal = sig * scale
    return ret, pos_ideal, price


# -----------------------------------------------------------------------------
# 整手化 + 保证金约束 → 降级仓位
# -----------------------------------------------------------------------------
def degrade_positions(
    symbols: list[str],
    mode: str,
    capital: float,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """对给定 universe、mode、资金档 K，返回：
      - rets_df:    每品种 clean_returns（对齐到公共日期）
      - lots_df:    每日实际手数
      - deg_pos_df: 每品种降级后"单位化仓位"（喂回 backtest_single 用）
      - diag_df:    诊断表（每日有效品种数、margin util）
    """
    K = capital * 1e4
    N = len(symbols)
    if N == 0:
        raise ValueError("empty universe")

    # 收集各品种数据
    rets = {}
    pos_ideals = {}
    prices = {}
    for sym in symbols:
        try:
            ret, pos_ideal, price = build_ideal_pos(sym, mode)
            rets[sym] = ret
            pos_ideals[sym] = pos_ideal
            prices[sym] = price
        except FileNotFoundError:
            continue

    rets_df = pd.DataFrame(rets).sort_index()
    pos_df = pd.DataFrame(pos_ideals).reindex(rets_df.index).fillna(0)
    price_df = pd.DataFrame(prices).reindex(rets_df.index).ffill()

    # 每品种合约乘数
    mult = pd.Series({sym: UNIVERSE_MAP[sym][4] for sym in rets_df.columns})
    mgr = pd.Series({sym: MARGIN_RATE[sym] for sym in rets_df.columns})

    # 单手名义值：price × multiplier
    per_lot_notional = price_df.mul(mult, axis=1)   # shape: (T, N)

    # 目标名义暴露（每品种等权 1/N）：(K/N) × ideal_pos
    target_notional = pos_df.mul(K / N)             # shape: (T, N)

    # 理想手数 → 整手化（round-half-away-from-zero）
    raw_lots = target_notional / per_lot_notional.replace(0, np.nan)
    lots_int = np.sign(raw_lots) * np.floor(np.abs(raw_lots) + 0.5)
    lots_int = lots_int.fillna(0).astype(int)

    # 实际名义暴露与保证金占用
    actual_notional = lots_int * per_lot_notional
    margin_used = actual_notional.abs().mul(mgr, axis=1)     # shape (T, N)

    # 每日组合级别保证金预算检查
    total_margin = margin_used.sum(axis=1)
    budget = K * MARGIN_BUDGET
    # 超额比例
    over_ratio = (total_margin / budget).clip(lower=1.0)  # >=1
    # 超预算日按比例缩手数（先除以缩放因子再重新整手化）
    # 为保持最小代码分支，只在超预算日再做一次 round
    scale_down = 1.0 / over_ratio                             # <=1 on days超预算
    mask_over = over_ratio > 1.0
    if mask_over.any():
        # 缩放后的目标名义
        adj_target = target_notional.loc[mask_over].mul(scale_down.loc[mask_over], axis=0)
        adj_raw_lots = adj_target / per_lot_notional.loc[mask_over].replace(0, np.nan)
        adj_lots = np.sign(adj_raw_lots) * np.floor(np.abs(adj_raw_lots) + 0.5)
        lots_int.loc[mask_over] = adj_lots.fillna(0).astype(int).values
        # 重算实际保证金
        actual_notional = lots_int * per_lot_notional
        margin_used = actual_notional.abs().mul(mgr, axis=1)
        total_margin = margin_used.sum(axis=1)

    # 降级仓位：用 lots × price × mult × N / K 反算（这样喂回 backtest_single 得到一致 pnl）
    deg_pos = actual_notional * (N / K)

    # 诊断
    active_count = (lots_int != 0).sum(axis=1)     # 每日有效品种数
    margin_util = total_margin / K                 # 每日保证金占用率
    diag_df = pd.DataFrame({
        "active_syms": active_count,
        "margin_util": margin_util,
        "budget_hit":  mask_over.astype(int),
    })

    return rets_df, lots_int, deg_pos, diag_df


# -----------------------------------------------------------------------------
# 组合回测
# -----------------------------------------------------------------------------
def backtest_degraded(
    rets_df: pd.DataFrame,
    deg_pos: pd.DataFrame,
    cost_bp: float = COST_BP,
) -> pd.Series:
    """给每个品种用 backtest_single 跑，再组合等权平均（与 T2/T2.5 一致）。"""
    strat_rets = {}
    for sym in rets_df.columns:
        bt = backtest_single(
            rets_df[sym], deg_pos[sym], lag_days=LAG, cost_bp=cost_bp,
        )
        strat_rets[sym] = bt["strategy_return"]
    return pd.DataFrame(strat_rets).mean(axis=1, skipna=True).sort_index()


# -----------------------------------------------------------------------------
# 指标
# -----------------------------------------------------------------------------
def period_metrics(r: pd.Series) -> dict:
    r = r.dropna()
    if len(r) < 20:
        return {"sharpe": np.nan, "ann_ret": np.nan, "ann_vol": np.nan, "max_dd": np.nan}
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


def oos(port: pd.Series) -> dict:
    return period_metrics(port.loc[SPLIT + pd.Timedelta(days=1):])


# -----------------------------------------------------------------------------
# 主流程
# -----------------------------------------------------------------------------
def main() -> None:
    all_syms = [row[0] for row in UNIVERSE]
    syms_19 = all_syms
    syms_14 = [s for s in all_syms if s not in CARRY_EXCLUDED]

    strategies = [
        ("Pool_filtered_19", syms_19, "pool_filt", 19),
        ("Pool_on_14",       syms_14, "pool_full", 14),
    ]

    print("=" * 110)
    print("Phase 2.5a · 资金阶梯 × 实盘约束 · 净业绩矩阵")
    print("=" * 110)
    print(f"  成本              : 单边 {COST_BP} bp")
    print(f"  保证金预算        : 账户 × {MARGIN_BUDGET:.0%}")
    print(f"  资金档（万元）    : {CAPITAL_GRID}")
    print(f"  策略              : Pool_filtered_19 (19), Pool_on_14 (14)")
    print(f"  切点              : OOS > {SPLIT.date()}")
    print()

    rows = []
    for name, syms, mode, N in strategies:
        print(f"  [run] {name}")
        for K in CAPITAL_GRID:
            rets_df, lots_df, deg_pos, diag = degrade_positions(syms, mode, capital=K)
            port_ret = backtest_degraded(rets_df, deg_pos, cost_bp=COST_BP)
            m = oos(port_ret)

            diag_oos = diag.loc[SPLIT + pd.Timedelta(days=1):]
            avg_active = float(diag_oos["active_syms"].mean())
            avg_util = float(diag_oos["margin_util"].mean())
            max_util = float(diag_oos["margin_util"].max())
            budget_hit_pct = float(diag_oos["budget_hit"].mean())

            rows.append({
                "strategy":         name,
                "capital_wan":      K,
                "N_universe":       N,
                "net_oos_sharpe":   m["sharpe"],
                "net_oos_ret":      m["ann_ret"],
                "net_oos_vol":      m["ann_vol"],
                "net_oos_dd":       m["max_dd"],
                "avg_active":       avg_active,
                "eff_ratio":        avg_active / N,
                "avg_margin_util":  avg_util,
                "max_margin_util":  max_util,
                "budget_hit_pct":   budget_hit_pct,
            })

    df = pd.DataFrame(rows)

    # 主表
    print("\n" + "-" * 110)
    print("核心矩阵：Net OOS Sharpe | Net 年化 | 有效品种 | 保证金占用")
    print("-" * 110)
    print(f"{'strategy':20} {'K(万)':>7} {'Shp':>7} {'Ret':>7} {'N_eff':>8} {'Eff%':>6} {'MgUtil':>7} {'HitCap%':>8}")
    for _, r in df.iterrows():
        print(f"{r['strategy']:20} {r['capital_wan']:>7} "
              f"{r['net_oos_sharpe']:>+7.2f} {r['net_oos_ret']:>+7.1%} "
              f"{r['avg_active']:>8.1f} {r['eff_ratio']:>6.0%} "
              f"{r['avg_margin_util']:>7.1%} {r['budget_hit_pct']:>8.1%}")

    # 最小资金判决
    def min_capital_for(target_sharpe: float, strat: str) -> str:
        sub = df[df["strategy"] == strat].sort_values("capital_wan")
        hits = sub[sub["net_oos_sharpe"] >= target_sharpe]
        if len(hits) == 0:
            return f"> {CAPITAL_GRID[-1]}万 (扫描内未通过)"
        return f"{int(hits.iloc[0]['capital_wan'])} 万"

    print("\n" + "-" * 110)
    print("最小资金门槛（OOS Sharpe 达标）")
    print("-" * 110)
    for thr in [0.3, 0.5, 0.6, 0.8, 1.0]:
        p19 = min_capital_for(thr, "Pool_filtered_19")
        p14 = min_capital_for(thr, "Pool_on_14")
        print(f"  target Sharpe >= {thr:.2f}   Pool_filtered_19: {p19:15}   Pool_on_14: {p14}")

    # 存表
    csv_fp = OUT_DIR / "capital_ladder_metrics.csv"
    df.to_csv(csv_fp, index=False, encoding="utf-8-sig")

    # 判决表
    verdict_rows = []
    for strat in ["Pool_filtered_19", "Pool_on_14"]:
        for thr in [0.3, 0.5, 0.6, 0.8, 1.0]:
            verdict_rows.append({
                "strategy": strat,
                "target_sharpe": thr,
                "min_capital": min_capital_for(thr, strat),
            })
    vdf = pd.DataFrame(verdict_rows)
    vdf_fp = OUT_DIR / "capital_ladder_verdict.csv"
    vdf.to_csv(vdf_fp, index=False, encoding="utf-8-sig")

    # ------------------------------------------------------------------
    # 画图
    # ------------------------------------------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(15, 6))
    colors = {"Pool_filtered_19": "#2ca02c", "Pool_on_14": "#1f77b4"}
    markers = {"Pool_filtered_19": "o", "Pool_on_14": "s"}

    ax = axes[0]
    for name, _, _, _ in strategies:
        sub = df[df["strategy"] == name].sort_values("capital_wan")
        ax.plot(sub["capital_wan"], sub["net_oos_sharpe"],
                marker=markers[name], color=colors[name], lw=1.8, ms=8, label=name)
    ax.axhline(0.60, color="black", ls="--", lw=1.0, alpha=0.7, label="B&H red line 0.60")
    ax.axhline(0.30, color="gray", ls=":", lw=0.8, alpha=0.6, label="weak floor 0.30")
    ax.axhline(0, color="gray", ls="-", lw=0.5, alpha=0.3)
    ax.set_xscale("log")
    ax.set_xlabel("Capital (10k RMB, log scale)")
    ax.set_ylabel("Net OOS Sharpe")
    ax.set_title(f"Net OOS Sharpe vs Capital\n(cost={COST_BP}bp, margin cap={MARGIN_BUDGET:.0%})")
    ax.grid(alpha=0.3, which="both")
    ax.legend(fontsize=9, loc="best")

    ax = axes[1]
    for name, _, _, N in strategies:
        sub = df[df["strategy"] == name].sort_values("capital_wan")
        ax.plot(sub["capital_wan"], sub["eff_ratio"] * 100,
                marker=markers[name], color=colors[name], lw=1.8, ms=8,
                label=f"{name} (N={N})")
    ax.axhline(50, color="gray", ls=":", lw=0.8, alpha=0.6, label="50% effective floor")
    ax.set_xscale("log")
    ax.set_xlabel("Capital (10k RMB, log scale)")
    ax.set_ylabel("Avg effective symbols (% of N)")
    ax.set_title("Diversification Integrity vs Capital")
    ax.grid(alpha=0.3, which="both")
    ax.legend(fontsize=9, loc="best")
    ax.set_ylim(0, 105)

    plt.suptitle("Phase 2.5a · Capital Ladder · Deployability Matrix", y=1.02, fontsize=13)
    plt.tight_layout()
    fig_fp = OUT_DIR / "capital_ladder.png"
    plt.savefig(fig_fp, dpi=120, bbox_inches="tight")
    plt.close(fig)

    print(f"\n[save] {csv_fp}")
    print(f"[save] {vdf_fp}")
    print(f"[save] {fig_fp}")
    print("\n[done] Phase 2.5a 完成。请把三张输出贴回来，我们一起定论。")


if __name__ == "__main__":
    main()
