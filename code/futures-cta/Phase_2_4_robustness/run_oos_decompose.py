"""Phase 2.4 · T2.5 · 诊断分解（非部署决策，仅事后归因）

承接 T2 归因（run_oos_attribute.py）的发现：
  Pool_filtered OOS 1.27 中，Top 2 贡献是 AU/AG 的纯 TSMOM（合计 72%），
  这部分是"贵金属 2023-2025 大单边"的 TSMOM 运气，不是 Carry 筛选的 edge。

本脚本做两把诊断刀（两边 universe 严格对等，apples-to-apples）：

  方法 A · 部署近似
      Pool_filtered_no_gold (17)  vs  TSMOM_only_no_gold (17)
      回答：扣掉贵金属 TSMOM 运气后，Pool_filtered 还剩多少 edge？

  方法 B · 纯学术对照（主裁判）
      Pool_on_14            vs  TSMOM_on_14
      回答：在 Carry 本该有效的 14 品种上，双引擎真的比单引擎强吗？
      这是 Phase 2.3 "双引擎分散增益" 原命题的最干净检验。

判决规则（和用户已对齐）：
  - B 是主裁判。若 Pool_on_14 <= TSMOM_on_14，则"双引擎分散增益" OOS 被证伪
  - A 是辅助理解。显示近似部署场景剥离贵金属运气后的残余

【重要】本脚本是**诊断工具**，不是新的 universe 选择：
  - 部署决策仍基于 Phase 2.4 T2：19 品种 Pool_filtered（事前经济学筛选）
  - T2.5 结果只进入 findings 文档的归因章节，不改部署策略
  - 把 T2.5 当作部署选择 = ex-post 挑选，踩红线
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

LOOKBACK = 252
LAG = 1
TARGET_VOL = 0.20
VOL_WINDOW = 60
VOL_FLOOR = 0.05
MAX_LEV = 3.0
SPLIT = pd.Timestamp("2022-12-31")

# 事前经济学筛选（KMPV 2018 + Erb-Harvey 2006）
CARRY_EXCLUDED = {"AU0", "AG0", "C0", "CF0", "SR0"}
GOLD = {"AU0", "AG0"}


def load_ret(sym: str) -> pd.Series:
    df = pd.read_csv(CLEAN_DIR / f"{sym}_clean_returns.csv", parse_dates=["date"]).set_index("date")
    return df["clean_return"].sort_index()


def load_carry(sym: str) -> pd.Series:
    df = pd.read_csv(CARRY_DIR / f"{sym}_carry.csv", parse_dates=["date"]).set_index("date")
    return df["carry"].sort_index()


def per_sym_return(sym: str, mode: str) -> pd.Series:
    """产出单品种策略日收益。

    mode:
      - "tsmom"       : 纯 TSMOM                    pos = sig_T × scale
      - "pool_full"   : 全品种 (T+C)/2             pos = (sig_T+sig_C)/2 × scale
      - "pool_filt"   : 事前经济学筛选             C/CF/SR/AU/AG 用纯 T，其他 (T+C)/2
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

    pos = sig * scale
    bt = backtest_single(ret, pos, lag_days=LAG)
    return bt["strategy_return"]


def port_from_symbols(symbols: list[str], mode: str) -> pd.Series:
    """给定品种列表和策略模式，构造等权组合收益。"""
    rets = {}
    for sym in symbols:
        try:
            rets[sym] = per_sym_return(sym, mode)
        except FileNotFoundError:
            continue
    return pd.DataFrame(rets).mean(axis=1, skipna=True).sort_index()


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


def main() -> None:
    all_syms = [row[0] for row in UNIVERSE]
    syms_19 = all_syms
    syms_17 = [s for s in all_syms if s not in GOLD]
    syms_14 = [s for s in all_syms if s not in CARRY_EXCLUDED]

    print("=" * 100)
    print("Phase 2.4 · T2.5 · 诊断分解（事后归因，非部署决策）")
    print("=" * 100)
    print(f"  universe 19      : {len(syms_19)} 品种")
    print(f"  universe 17 (no_gold) : {len(syms_17)} 品种  (剔除 AU/AG)")
    print(f"  universe 14 (carry_valid) : {len(syms_14)} 品种  (再剔除 C/CF/SR)")
    print(f"  切点             : {SPLIT.date()}")
    print(f"  参数冻结         : lookback=252  vt=20%  vw=60  lag=1")
    print()

    # 六个组合
    strategies = {
        "TSMOM_19":      ("TSMOM_only (19,  参考)",     port_from_symbols(syms_19, "tsmom")),
        "Pool_orig_19":  ("Pool_original (19, 参考)",   port_from_symbols(syms_19, "pool_full")),
        "Pool_filt_19":  ("Pool_filtered (19, T2 基准)", port_from_symbols(syms_19, "pool_filt")),
        "TSMOM_17":      ("TSMOM_only (17, A 对照)",   port_from_symbols(syms_17, "tsmom")),
        "Pool_filt_17":  ("Pool_filtered (17, A 测试)", port_from_symbols(syms_17, "pool_filt")),
        "TSMOM_14":      ("TSMOM_only (14, B 对照)",   port_from_symbols(syms_14, "tsmom")),
        "Pool_14":       ("Pool (14, B 测试 主裁)",    port_from_symbols(syms_14, "pool_full")),
    }

    # 汇总表
    rows = []
    for key, (label, port) in strategies.items():
        m = split_metrics(port)
        rows.append({
            "key": key, "label": label,
            "IS_sharpe":  m["IS"]["sharpe"],
            "OOS_sharpe": m["OOS"]["sharpe"],
            "Full_sharpe": m["Full"]["sharpe"],
            "OOS_ret":    m["OOS"]["ann_ret"],
            "OOS_vol":    m["OOS"]["ann_vol"],
            "OOS_dd":     m["OOS"]["max_dd"],
        })
    df = pd.DataFrame(rows)

    # 打印
    print("-" * 100)
    print("Sharpe 三段对比（按 key 排列）")
    print("-" * 100)
    print(f"{'key':14} {'IS':>7} {'OOS':>7} {'Full':>7}   {'OOS_ret':>8} {'OOS_vol':>8} {'OOS_dd':>8}   label")
    for _, r in df.iterrows():
        print(f"{r['key']:14} {r['IS_sharpe']:>+7.2f} {r['OOS_sharpe']:>+7.2f} {r['Full_sharpe']:>+7.2f}   "
              f"{r['OOS_ret']:>+8.1%} {r['OOS_vol']:>+8.1%} {r['OOS_dd']:>+8.1%}   {r['label']}")

    # 取出关键数字
    def oos(key): return float(df.loc[df["key"] == key, "OOS_sharpe"].iloc[0])

    a_pool  = oos("Pool_filt_17")
    a_tsmom = oos("TSMOM_17")
    b_pool  = oos("Pool_14")
    b_tsmom = oos("TSMOM_14")
    ref_orig_19 = oos("Pool_orig_19")
    ref_filt_19 = oos("Pool_filt_19")
    ref_tsmom_19 = oos("TSMOM_19")

    # 方法 A 判决
    print("\n" + "-" * 100)
    print("方法 A · 部署近似（17 vs 17，apples-to-apples）")
    print("-" * 100)
    print(f"  Pool_filtered_17  OOS Sharpe = {a_pool:+.2f}")
    print(f"  TSMOM_only_17     OOS Sharpe = {a_tsmom:+.2f}")
    delta_a = a_pool - a_tsmom
    print(f"  Δ (Pool - TSMOM)             = {delta_a:+.2f}")
    if delta_a > 0.1:
        va = "[PASS] 双引擎在非贵金属 universe 上仍有显著 OOS edge"
    elif delta_a > 0:
        va = "[WEAK] Pool 微幅占优，edge 贴近 0，说服力低"
    else:
        va = "[FAIL] Pool 不如 TSMOM，双引擎 edge 几乎全部来自贵金属 TSMOM 运气"
    print(f"  判决                        : {va}")

    # 方法 B 判决（主裁判）
    print("\n" + "-" * 100)
    print("方法 B · 纯学术对照（14 vs 14，主裁判）")
    print("-" * 100)
    print(f"  Pool_on_14        OOS Sharpe = {b_pool:+.2f}")
    print(f"  TSMOM_on_14       OOS Sharpe = {b_tsmom:+.2f}")
    delta_b = b_pool - b_tsmom
    print(f"  Δ (Pool - TSMOM)             = {delta_b:+.2f}")
    if delta_b > 0.1:
        vb = "[PASS] 在 Carry-valid universe 上，双引擎真实优于单引擎 -> 'Phase 2.3 命题' 在 OOS 成立"
    elif delta_b > 0:
        vb = "[WEAK] 微幅占优，置信度低，需要更长 OOS 或 walk-forward"
    else:
        vb = "[FAIL] Pool 不如 TSMOM -> 'Phase 2.3 双引擎分散增益' 在 OOS 被证伪"
    print(f"  判决 (主裁判)               : {vb}")

    # 最终结论
    print("\n" + "=" * 100)
    print("最终结论（以 B 为主、A 为辅）")
    print("=" * 100)
    if delta_b > 0.1:
        print("  双引擎命题 OOS 成立")
        print("  下一步建议：进入 T5 交易成本测试，成本模型套用在 Pool_filtered (19) 上")
    elif delta_b > 0:
        print("  双引擎命题 OOS 微弱成立，证据不强")
        print("  下一步建议：先写 Phase 2.4 findings 记录所有证据，再集体讨论要不要进 T5")
    else:
        print("  双引擎命题 OOS 被证伪")
        print("  下一步建议：归档 Pool 策略，Phase 2.4 主线切到 'TSMOM-only 实盘化'，T5 在 TSMOM-only 上做")

    # 归因分解（让读者看到 1.27 的结构）
    print("\n" + "-" * 100)
    print("OOS Sharpe 路径分解（从原始到筛选到剥离）")
    print("-" * 100)
    print(f"  Pool_original_19       OOS = {ref_orig_19:+.2f}   (T1 基线，未过)")
    print(f"  Pool_filtered_19       OOS = {ref_filt_19:+.2f}   (T2 事前经济学筛选后)")
    print(f"  Pool_filtered_17       OOS = {a_pool:+.2f}   (再剔除贵金属品种)")
    print(f"  Pool_on_14             OOS = {b_pool:+.2f}   (只留 Carry-valid 品种)")
    print(f"  TSMOM_only_19          OOS = {ref_tsmom_19:+.2f}   (单引擎参考)")
    print(f"  TSMOM_only_17          OOS = {a_tsmom:+.2f}   (单引擎 no_gold)")
    print(f"  TSMOM_on_14            OOS = {b_tsmom:+.2f}   (单引擎 carry_valid)")

    # 存表
    csv_fp = OUT_DIR / "oos_decompose_metrics.csv"
    df.to_csv(csv_fp, index=False, encoding="utf-8-sig")

    # 画图：OOS Sharpe 条形对比
    fig, ax = plt.subplots(figsize=(13, 6.5))
    order = ["Pool_orig_19", "Pool_filt_19", "Pool_filt_17", "Pool_14",
             "TSMOM_19", "TSMOM_17", "TSMOM_14"]
    oos_vals = [oos(k) for k in order]
    labels = [f"{k}\n(n={19 if '19' in k else (17 if '17' in k else 14)})" for k in order]
    colors = []
    for k, v in zip(order, oos_vals):
        if k.startswith("Pool"):
            colors.append("#2ca02c" if v > 0.5 else ("#ff7f0e" if v > 0.3 else "#d62728"))
        else:
            colors.append("steelblue")
    bars = ax.bar(range(len(order)), oos_vals, color=colors, edgecolor="black")
    ax.axhline(0, color="black", lw=0.6)
    ax.axhline(0.5, color="orange", lw=0.8, ls="--", alpha=0.6, label="OOS 通过线 0.50")
    ax.axhline(0.7, color="green",  lw=0.8, ls="--", alpha=0.6, label="OOS 强通过 0.70")
    for i, v in enumerate(oos_vals):
        ax.text(i, v + (0.04 if v >= 0 else -0.10), f"{v:+.2f}",
                ha="center", fontsize=11, fontweight="bold")
    ax.set_xticks(range(len(order)))
    ax.set_xticklabels(labels, fontsize=9)

    # 画对比连线：A 对比
    ax.annotate("", xy=(2, a_pool), xytext=(5, a_tsmom),
                arrowprops=dict(arrowstyle="<->", color="purple", lw=1.4, alpha=0.8))
    ax.text(3.5, (a_pool + a_tsmom) / 2 + 0.15,
            f"A · Δ = {a_pool - a_tsmom:+.2f}",
            ha="center", fontsize=10, color="purple", fontweight="bold")

    # B 对比
    ax.annotate("", xy=(3, b_pool), xytext=(6, b_tsmom),
                arrowprops=dict(arrowstyle="<->", color="darkred", lw=1.6, alpha=0.9))
    ax.text(4.5, (b_pool + b_tsmom) / 2 + 0.25,
            f"B (主裁) · Δ = {b_pool - b_tsmom:+.2f}",
            ha="center", fontsize=10.5, color="darkred", fontweight="bold")

    ax.set_ylabel("OOS Sharpe (2023-2025)")
    ax.set_title("Phase 2.4 · T2.5 · 诊断分解\n"
                 "Pool 系列（绿/橙/红按验收等级）  vs  TSMOM 系列（蓝）")
    ax.grid(alpha=0.3, axis="y")
    ax.legend(fontsize=9, loc="upper right")

    plt.tight_layout()
    fig_fp = OUT_DIR / "oos_decompose.png"
    plt.savefig(fig_fp, dpi=120, bbox_inches="tight")
    plt.close(fig)

    print(f"\n[save] {csv_fp}")
    print(f"[save] {fig_fp}")


if __name__ == "__main__":
    main()
