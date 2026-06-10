"""Phase 2.3 · Step 3c · TSMOM + Carry 双引擎 Pooling

基础算式（B2 / average 版，便于 PnL 归因）：

  pos_t = sign(tsmom_signal)  × scale        # TSMOM 单引擎标准仓位
  pos_c = sign(carry_signal)  × scale        # Carry 单引擎标准仓位
  pos_p = (sign(tsmom) + sign(carry)) / 2 × scale
         = 0.5 × pos_t  + 0.5 × pos_c        # 等权平均

  pnl_pool = ret × pos_p  = 0.5 × (ret × pos_t) + 0.5 × (ret × pos_c)
          = 0.5 × pnl_tsmom + 0.5 × pnl_carry

这带来三点好处：
  1) 当两引擎同意 → 合成 = ±1 × scale，等价于单引擎 20% 目标波动
  2) 当两引擎打架 → 合成 = 0，空仓（B1 sign-of-sum 也是 0，完全等价）
  3) 当一方 NaN（比如 TSMOM 前 252 日无信号）→ 合成 = ±0.5 × scale（半仓）
  4) PnL 可以严格拆成 "一半来自 TSMOM + 一半来自 Carry"，做归因

对比基准（同 universe，同 vol-target 参数）：
  - B&H 等权             ~+0.60
  - TSMOM vt (Phase 2.2)  ~+0.70
  - Carry vt A (raw sign) ~+0.68
  - Pooled  (本脚本)        ?

关键观察指标：
  - 组合 Sharpe 能否 > 0.70（单引擎最高）？
  - 两引擎分歧率（agreement rate）分布
  - PnL 归因：谁贡献多少？
  - "打架品种"（AU/AG/C）是拖累还是反而因 pool=0 而减损？

用法：
    python Phase_2_3_carry/run_pooled.py
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
sys.path.insert(0, str(HERE))

from config import UNIVERSE  # noqa: E402
from sizing import vol_target_scale  # noqa: E402
from backtest import backtest_single  # noqa: E402
from signals import carry_signal_raw  # noqa: E402


# Phase 2.2 和 Phase 2.3 都有 signals.py，用显式文件路径避免冲突
def _load_module_from_path(name: str, fp: Path):
    spec = importlib.util.spec_from_file_location(name, fp)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_tsmom_signals = _load_module_from_path(
    "tsmom_signals_phase22",
    PROJECT_ROOT / "Phase_2_2_tsmom" / "signals.py",
)
tsmom_signal = _tsmom_signals.tsmom_signal

CLEAN_DIR = PROJECT_ROOT / "data_cache" / "tushare" / "clean"
CARRY_DIR = PROJECT_ROOT / "data_cache" / "tushare" / "carry"
OUT_DIR = HERE / "outputs"
OUT_DIR.mkdir(exist_ok=True)

LOOKBACK = 252
LAG = 1
TARGET_VOL = 0.20
VOL_WINDOW = 60
VOL_FLOOR = 0.05
MAX_LEV = 3.0


# --------------------------------------------------------------------------
# 数据加载
# --------------------------------------------------------------------------
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


# --------------------------------------------------------------------------
# 单品种：同时跑三策略 + 记录 agreement
# --------------------------------------------------------------------------
def run_one(symbol: str) -> dict:
    ret = load_clean_returns(symbol)
    carry = load_carry(symbol).reindex(ret.index)

    sig_t = tsmom_signal(ret, lookback_days=LOOKBACK)
    sig_c = carry_signal_raw(carry)
    scale = vol_target_scale(ret, target_vol=TARGET_VOL, window=VOL_WINDOW,
                             vol_floor=VOL_FLOOR, max_leverage=MAX_LEV)

    # 三种仓位
    pos_t = sig_t * scale
    pos_c = sig_c * scale
    sig_p = (sig_t.fillna(0) + sig_c.fillna(0)) / 2.0
    pos_p = sig_p * scale

    bt_t = backtest_single(ret, pos_t, lag_days=LAG)
    bt_c = backtest_single(ret, pos_c, lag_days=LAG)
    bt_p = backtest_single(ret, pos_p, lag_days=LAG)

    # 两引擎一致性统计（都有信号、非 NaN 的日子）
    both_valid = sig_t.notna() & sig_c.notna()
    sig_t_v = sig_t[both_valid]
    sig_c_v = sig_c[both_valid]
    agree = (sig_t_v == sig_c_v).sum()       # 完全同意（都 +1 或都 -1 或都 0）
    opposite = ((sig_t_v * sig_c_v) < 0).sum()  # 严格相反（一 +1 一 -1）
    n_both = len(sig_t_v)

    return {
        "symbol": symbol,
        "clean_return": ret,
        "sig_t": sig_t, "sig_c": sig_c, "sig_p": sig_p,
        "scale": scale,
        "t": bt_t, "c": bt_c, "p": bt_p,
        "n_both": int(n_both),
        "n_agree": int(agree),
        "n_opposite": int(opposite),
        "agree_rate": float(agree / n_both) if n_both > 0 else np.nan,
        "opposite_rate": float(opposite / n_both) if n_both > 0 else np.nan,
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
        "annual_vol":    float(ann_vol),
        "sharpe":        float(sharpe) if pd.notna(sharpe) else np.nan,
        "max_dd":        float(max_dd),
        "nav_end":       float(nav.iloc[-1]),
    }


def main() -> None:
    symbols = [row[0] for row in UNIVERSE]
    print("=" * 88)
    print(f"TSMOM × Carry 双引擎 Pooling   N={len(symbols)}   "
          f"lookback={LOOKBACK}d   target_vol={TARGET_VOL:.0%}")
    print("=" * 88)

    t_rets: dict[str, pd.Series] = {}
    c_rets: dict[str, pd.Series] = {}
    p_rets: dict[str, pd.Series] = {}
    bh_rets: dict[str, pd.Series] = {}
    per_rows: list[dict] = []

    for sym in symbols:
        try:
            out = run_one(sym)
        except FileNotFoundError as e:
            print(f"  [skip] {sym}: {e}")
            continue

        t_rets[sym] = out["t"]["strategy_return"]
        c_rets[sym] = out["c"]["strategy_return"]
        p_rets[sym] = out["p"]["strategy_return"]
        bh_rets[sym] = out["clean_return"]

        mt, mc, mp = out["t"]["metrics"], out["c"]["metrics"], out["p"]["metrics"]
        per_rows.append({
            "symbol": sym,
            "T_sharpe": mt["sharpe"],
            "C_sharpe": mc["sharpe"],
            "P_sharpe": mp["sharpe"],
            "P_ret":    mp["annual_return"],
            "P_maxdd":  mp["max_dd"],
            "agree_rate":    out["agree_rate"],
            "opposite_rate": out["opposite_rate"],
        })
        print(f"  [{sym:>4}]  "
              f"T={mt['sharpe']:+.2f}  "
              f"C={mc['sharpe']:+.2f}  "
              f"P={mp['sharpe']:+.2f}  "
              f"agree={out['agree_rate']:.0%}  "
              f"opp={out['opposite_rate']:.0%}")

    if not per_rows:
        print("没有成功跑通的品种"); return

    T_df = pd.DataFrame(t_rets).sort_index()
    C_df = pd.DataFrame(c_rets).sort_index()
    P_df = pd.DataFrame(p_rets).sort_index()
    bh_df = pd.DataFrame(bh_rets).sort_index()

    port_T = T_df.mean(axis=1, skipna=True)
    port_C = C_df.mean(axis=1, skipna=True)
    port_P = P_df.mean(axis=1, skipna=True)
    port_bh = bh_df.mean(axis=1, skipna=True)

    mT, mC, mP, mBH = (compute_port_metrics(x) for x in (port_T, port_C, port_P, port_bh))

    summary = pd.DataFrame(per_rows).sort_values("P_sharpe", ascending=False).reset_index(drop=True)
    csv_fp = OUT_DIR / "pooled_per_symbol.csv"
    summary.to_csv(csv_fp, index=False, encoding="utf-8-sig")

    # ---------- 逐品种表 ----------
    print("\n" + "=" * 88)
    print("逐品种：TSMOM / Carry / Pool（按 P_sharpe 降序）")
    print("=" * 88)
    with pd.option_context("display.float_format", "{:.3f}".format, "display.width", 160):
        print(summary.to_string(index=False))

    # ---------- 组合层 ----------
    print("\n" + "=" * 88)
    print("组合汇总（动态等权 / vol-target=20% / 无成本）")
    print("=" * 88)
    fmt = "{:<26s} Sharpe={:+.2f}  Ret={:+6.1%}  Vol={:5.1%}  MaxDD={:+6.1%}  NAV末={:.3f}"
    print(fmt.format("  TSMOM vt (T)",      mT["sharpe"],  mT["annual_return"],  mT["annual_vol"],  mT["max_dd"],  mT["nav_end"]))
    print(fmt.format("  Carry vt A (C)",    mC["sharpe"],  mC["annual_return"],  mC["annual_vol"],  mC["max_dd"],  mC["nav_end"]))
    print(fmt.format("  Pooled 0.5T+0.5C",  mP["sharpe"],  mP["annual_return"],  mP["annual_vol"],  mP["max_dd"],  mP["nav_end"]))
    print(fmt.format("  B&H 等权 (参照)",    mBH["sharpe"], mBH["annual_return"], mBH["annual_vol"], mBH["max_dd"], mBH["nav_end"]))

    # ---------- PnL 归因 ----------
    # pnl_pool = 0.5 × pnl_T + 0.5 × pnl_C（理论恒等式）
    # 用数值验证并拆分两部分对 Sharpe 的贡献
    port_T_half = 0.5 * port_T
    port_C_half = 0.5 * port_C
    port_sum_check = port_T_half + port_C_half
    check_mae = float((port_P - port_sum_check).abs().dropna().mean())

    print("\n" + "-" * 88)
    print("PnL 归因（组合层）")
    print("-" * 88)
    ann_T_half = port_T_half.dropna().mean() * 252
    ann_C_half = port_C_half.dropna().mean() * 252
    ann_P = port_P.dropna().mean() * 252
    print(f"  TSMOM 贡献的年化收益（0.5×T）：{ann_T_half:+.2%}")
    print(f"  Carry 贡献的年化收益（0.5×C）：{ann_C_half:+.2%}")
    print(f"  Pool 年化收益（验证和）       ：{ann_P:+.2%}  (MAE vs 半和={check_mae:.2e})")
    tsmom_share = ann_T_half / ann_P if ann_P != 0 else np.nan
    print(f"  TSMOM 贡献占比                 ：{tsmom_share:.0%}")

    # ---------- 一致性 ----------
    print("\n" + "-" * 88)
    print("两引擎一致性（同日都有信号的子样本）")
    print("-" * 88)
    ag_mean = summary["agree_rate"].mean()
    opp_mean = summary["opposite_rate"].mean()
    print(f"  平均同意率：{ag_mean:.0%}（包括都=0 的日子）")
    print(f"  平均相反率：{opp_mean:.0%}（严格 +1/-1 对立）")
    top_opp = summary.nlargest(3, "opposite_rate")[["symbol", "opposite_rate", "T_sharpe", "C_sharpe", "P_sharpe"]]
    print(f"  打架最严重的 3 个品种：")
    for _, r in top_opp.iterrows():
        print(f"    {r['symbol']:>4}  opp={r['opposite_rate']:.0%}  "
              f"T={r['T_sharpe']:+.2f}  C={r['C_sharpe']:+.2f}  P={r['P_sharpe']:+.2f}")

    # ---------- 评估口径 ----------
    print("\n" + "-" * 88)
    single_engine_best = max(mT["sharpe"], mC["sharpe"])
    gain_vs_best = mP["sharpe"] - single_engine_best
    gain_vs_bh = mP["sharpe"] - mBH["sharpe"]
    print(f"  Pool - max(T, C) Sharpe = {gain_vs_best:+.2f}   "
          f"{'✅ 双引擎 > 单引擎' if gain_vs_best > 0 else '❌ 没赢单引擎'}")
    print(f"  Pool - B&H Sharpe       = {gain_vs_bh:+.2f}   "
          f"{'✅ 赢 B&H' if gain_vs_bh > 0 else '❌ 不及 B&H'}")

    # ---------- 画图 ----------
    fig, axes = plt.subplots(3, 1, figsize=(14, 12),
                             gridspec_kw={"height_ratios": [2, 1, 1]})

    ax = axes[0]
    bh_nav = (1 + port_bh.fillna(0)).cumprod()
    T_nav = (1 + port_T.fillna(0)).cumprod()
    C_nav = (1 + port_C.fillna(0)).cumprod()
    P_nav = (1 + port_P.fillna(0)).cumprod()
    ax.plot(bh_nav.index, bh_nav.values,
            label=f"B&H 等权   Sharpe={mBH['sharpe']:+.2f}  NAV={mBH['nav_end']:.2f}",
            color="gray", lw=1.2)
    ax.plot(T_nav.index, T_nav.values,
            label=f"TSMOM vt   Sharpe={mT['sharpe']:+.2f}  NAV={mT['nav_end']:.2f}",
            color="steelblue", lw=1.5, ls="--")
    ax.plot(C_nav.index, C_nav.values,
            label=f"Carry vt A  Sharpe={mC['sharpe']:+.2f}  NAV={mC['nav_end']:.2f}",
            color="crimson", lw=1.5, ls="--")
    ax.plot(P_nav.index, P_nav.values,
            label=f"Pooled      Sharpe={mP['sharpe']:+.2f}  NAV={mP['nav_end']:.2f}",
            color="darkgreen", lw=2.4)
    ax.axhline(1.0, color="black", lw=0.4, alpha=0.5)
    ax.set_title("双引擎 Pooling vs 单引擎 vs B&H")
    ax.set_ylabel("NAV (起点=1)")
    ax.grid(alpha=0.3)
    ax.legend(loc="upper left")

    ax = axes[1]
    x = np.arange(len(summary))
    w = 0.27
    ax.bar(x - w, summary["T_sharpe"], w, label="TSMOM",  color="steelblue")
    ax.bar(x,     summary["C_sharpe"], w, label="Carry",  color="crimson")
    ax.bar(x + w, summary["P_sharpe"], w, label="Pool",
           color=["#2ca02c" if s > 0 else "#d62728" for s in summary["P_sharpe"]])
    ax.axhline(0, color="black", lw=0.6)
    ax.axhline(mP["sharpe"], color="darkgreen", lw=1.5, ls="--",
               label=f"Pool 组合 Sharpe = {mP['sharpe']:+.2f}")
    ax.set_xticks(x)
    ax.set_xticklabels(summary["symbol"], rotation=45)
    ax.set_title("逐品种 Sharpe：TSMOM (蓝) / Carry (红) / Pool (绿=正·灰红=负)")
    ax.set_ylabel("Sharpe")
    ax.legend(loc="lower left", ncol=4, fontsize=8)
    ax.grid(alpha=0.3, axis="y")

    ax = axes[2]
    sorted_by_opp = summary.sort_values("opposite_rate", ascending=False).reset_index(drop=True)
    x2 = np.arange(len(sorted_by_opp))
    ax.bar(x2, sorted_by_opp["opposite_rate"] * 100, color="salmon", label="对立 (T vs C 反向)")
    ax.bar(x2, sorted_by_opp["agree_rate"] * 100, bottom=sorted_by_opp["opposite_rate"] * 100,
           color="lightsteelblue", label="同意或同 0", alpha=0.7)
    ax.set_xticks(x2)
    ax.set_xticklabels(sorted_by_opp["symbol"], rotation=45)
    ax.set_title("两引擎一致性：红=严格对立（打架）  蓝=同意 / 都 0")
    ax.set_ylabel("比例 (%)")
    ax.legend(loc="lower right")
    ax.grid(alpha=0.3, axis="y")
    ax.set_ylim(0, 100)

    plt.tight_layout()
    png_fp = OUT_DIR / "pooled_compare.png"
    plt.savefig(png_fp, dpi=120, bbox_inches="tight")
    plt.close(fig)

    print(f"\n[save] {csv_fp}")
    print(f"[save] {png_fp}")


if __name__ == "__main__":
    main()
