"""Phase 2.4 · T2 归因验证（进 T5 之前的"防麻痹"检查）

Pool_filtered OOS Sharpe = 1.27（比 IS 1.10 还高）这件事太漂亮，不能直接信。
在进入 T5 交易成本测试之前，用纯事后归因回答两个问题：

  Q1 · 年度集中度：1.27 是三年都撑得住，还是某一年的尖刺？
       → 把 OOS 拆成 2023 / 2024 / 2025，各自算 Sharpe / Ret / Vol / MaxDD

  Q2 · 品种集中度：1.27 是 Top 3 品种独扛，还是分散贡献？
       → 把 OOS 年化收益按 19 个品种拆，排序 + 累积贡献比例

判据（任何一条 fail 都值得警惕）：
  - 三年 Sharpe 至少有 2 年 > 0.5
  - Top 3 品种贡献的 ann_ret 占比 < 70%（不是"独扛"）
  - 后 1/3 品种（6 个）不是集体拖累（ann_ret 不能全是负的）

本脚本不改任何策略参数，纯粹拆解 run_oos_filtered.py 已经产出的同一套数据。
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
CARRY_EXCLUDED = {"AU0", "AG0", "C0", "CF0", "SR0"}


def load_ret(sym: str) -> pd.Series:
    df = pd.read_csv(CLEAN_DIR / f"{sym}_clean_returns.csv", parse_dates=["date"]).set_index("date")
    return df["clean_return"].sort_index()


def load_carry(sym: str) -> pd.Series:
    df = pd.read_csv(CARRY_DIR / f"{sym}_carry.csv", parse_dates=["date"]).set_index("date")
    return df["carry"].sort_index()


def build_filt_ret(sym: str) -> pd.Series:
    """产出 Pool_filtered 下单品种的策略日收益（和 run_oos_filtered.py 完全一致）。"""
    ret = load_ret(sym)
    carry = load_carry(sym).reindex(ret.index)
    sig_t = tsmom_signal(ret, lookback_days=LOOKBACK).fillna(0)
    sig_c = carry_signal_raw(carry).fillna(0)
    scale = vol_target_scale(
        ret, target_vol=TARGET_VOL, window=VOL_WINDOW,
        vol_floor=VOL_FLOOR, max_leverage=MAX_LEV,
    )
    if sym in CARRY_EXCLUDED:
        sig = sig_t
    else:
        sig = (sig_t + sig_c) / 2.0
    pos = sig * scale
    bt = backtest_single(ret, pos, lag_days=LAG)
    return bt["strategy_return"]


def period_metrics(r: pd.Series) -> dict:
    r = r.dropna()
    if len(r) < 10:
        return {"sharpe": np.nan, "ann_ret": np.nan, "ann_vol": np.nan, "max_dd": np.nan, "n_days": 0}
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
        "n_days":  int(len(r)),
    }


def main() -> None:
    symbols = [row[0] for row in UNIVERSE]
    meta = {row[0]: (row[1], row[2]) for row in UNIVERSE}

    per_sym: dict[str, pd.Series] = {}
    for sym in symbols:
        try:
            per_sym[sym] = build_filt_ret(sym)
        except FileNotFoundError as e:
            print(f"  [skip] {sym}: {e}")
            continue

    port = pd.DataFrame(per_sym).mean(axis=1, skipna=True).sort_index()
    oos_port = port.loc[SPLIT + pd.Timedelta(days=1):]

    print("=" * 100)
    print("Phase 2.4 · T2 归因验证（Pool_filtered OOS = 1.27 的内部一致性）")
    print("=" * 100)
    print(f"  OOS 天数 : {len(oos_port.dropna())}")
    print(f"  OOS 区间 : {oos_port.index.min().date()}  →  {oos_port.index.max().date()}")
    print(f"  切点     : {SPLIT.date()}  (IS <= split < OOS)")
    print()

    # ================================================================
    # Q1 · 年度拆解
    # ================================================================
    print("-" * 100)
    print("Q1 · 年度 Sharpe 拆解（Pool_filtered OOS）")
    print("-" * 100)
    yearly = []
    for year, r_year in oos_port.groupby(oos_port.index.year):
        m = period_metrics(r_year)
        yearly.append({"year": int(year), **m})
    yearly_df = pd.DataFrame(yearly).set_index("year")
    print(f"\n{'year':>6} {'n_days':>7} {'sharpe':>8} {'ann_ret':>9} {'ann_vol':>9} {'max_dd':>9}")
    for year, row in yearly_df.iterrows():
        print(f"{year:>6} {row['n_days']:>7.0f} "
              f"{row['sharpe']:>+8.2f} {row['ann_ret']:>+9.1%} "
              f"{row['ann_vol']:>+9.1%} {row['max_dd']:>+9.1%}")

    n_good_years = int((yearly_df["sharpe"] > 0.5).sum())
    n_years = len(yearly_df)
    worst_year_sh = yearly_df["sharpe"].min()
    worst_year = yearly_df["sharpe"].idxmin()
    best_year_sh = yearly_df["sharpe"].max()
    best_year = yearly_df["sharpe"].idxmax()

    print(f"\n  Sharpe > 0.5 的年份        : {n_good_years}/{n_years}")
    print(f"  最差年份 ({worst_year})     : Sharpe = {worst_year_sh:+.2f}")
    print(f"  最好年份 ({best_year})      : Sharpe = {best_year_sh:+.2f}")
    print(f"  年度 Sharpe 极差           : {best_year_sh - worst_year_sh:+.2f}")

    verdict_y = "[PASS]" if (n_good_years >= max(1, n_years - 1) and worst_year_sh > 0) else "[WARN]"
    print(f"  Q1 判据（>=2/3 年 Sharpe>0.5 且最差年>0） : {verdict_y}")

    # ================================================================
    # Q2 · 品种贡献拆解（基于等权组合 → contribution = ann_ret_sym / N）
    # ================================================================
    print("\n" + "-" * 100)
    print("Q2 · 品种贡献拆解（Pool_filtered OOS 年化收益 = 各品种 ann_ret / 19 之和）")
    print("-" * 100)
    N = len(per_sym)
    rows = []
    for sym, ret_full in per_sym.items():
        r_oos = ret_full.loc[SPLIT + pd.Timedelta(days=1):]
        m = period_metrics(r_oos)
        rows.append({
            "symbol":   sym,
            "name":     meta[sym][0],
            "sector":   meta[sym][1],
            "carry_ex": sym in CARRY_EXCLUDED,
            "sharpe":   m["sharpe"],
            "ann_ret":  m["ann_ret"],
            "contrib":  m["ann_ret"] / N,  # 对组合年化收益的绝对贡献
        })
    sym_df = pd.DataFrame(rows).sort_values("contrib", ascending=False)

    port_ann = oos_port.mean() * 252
    print(f"\n  组合 OOS 年化收益 (实测)    : {port_ann:+.2%}")
    print(f"  sum(contrib) 校验           : {sym_df['contrib'].sum():+.2%}  (应与上行相等)")
    print()
    print(f"  {'rank':>4} {'sym':5} {'name':6} {'sector':6} {'cx':3} {'sharpe':>7} {'ann_ret':>8} {'contrib':>8} {'cum%':>6}")

    cum = 0.0
    for i, row in enumerate(sym_df.itertuples(), 1):
        cum += row.contrib
        cx_mark = "EX " if row.carry_ex else ""
        print(f"  {i:>4} {row.symbol:5} {row.name:6} {row.sector:6} {cx_mark:3} "
              f"{row.sharpe:>+7.2f} {row.ann_ret:>+8.1%} {row.contrib:>+8.2%} "
              f"{cum / port_ann:>6.0%}")

    top3_contrib = sym_df.head(3)["contrib"].sum()
    top5_contrib = sym_df.head(5)["contrib"].sum()
    bot6_contrib = sym_df.tail(6)["contrib"].sum()
    n_positive = int((sym_df["contrib"] > 0).sum())
    n_negative = int((sym_df["contrib"] < 0).sum())

    print(f"\n  Top 3 品种贡献占组合 ann_ret : {top3_contrib / port_ann:>5.0%}  ({top3_contrib:+.2%})")
    print(f"  Top 5 品种贡献占组合 ann_ret : {top5_contrib / port_ann:>5.0%}  ({top5_contrib:+.2%})")
    print(f"  Bottom 6 品种贡献占组合     : {bot6_contrib / port_ann:>+5.0%}  ({bot6_contrib:+.2%})")
    print(f"  贡献为正的品种数            : {n_positive}/{N}")
    print(f"  贡献为负的品种数            : {n_negative}/{N}")

    verdict_c1 = "[PASS]" if top3_contrib / port_ann < 0.70 else "[WARN]"
    verdict_c2 = "[PASS]" if bot6_contrib >= 0 else "[WARN]"
    print(f"  Q2 判据 1 (Top 3 贡献 < 70%)     : {verdict_c1}")
    print(f"  Q2 判据 2 (Bottom 6 集体不拖累)  : {verdict_c2}")

    # ================================================================
    # 汇总判断
    # ================================================================
    print("\n" + "=" * 100)
    print("归因总判断")
    print("=" * 100)
    all_pass = (
        n_good_years >= max(1, n_years - 1)
        and worst_year_sh > 0
        and top3_contrib / port_ann < 0.70
        and bot6_contrib >= 0
    )
    if all_pass:
        print("  [PASS] 年度稳定 + 贡献分散：Pool_filtered 的 OOS 1.27 是内部一致的 edge")
        print("         → 建议进入 T5 交易成本测试")
    else:
        print("  [WARN] 至少一条判据失败，1.27 的 edge 不够分散或不够稳定")
        print("         → 进 T5 之前先回看本脚本的拆解表，判断是否需要再筛 universe")

    # ================================================================
    # 存表 + 画图
    # ================================================================
    yearly_df.to_csv(OUT_DIR / "oos_attribute_yearly.csv", encoding="utf-8-sig")
    sym_df.to_csv(OUT_DIR / "oos_attribute_per_symbol.csv", index=False, encoding="utf-8-sig")

    fig, axes = plt.subplots(1, 2, figsize=(16, 6.5), gridspec_kw={"width_ratios": [1, 1.6]})

    # 左：年度 Sharpe 柱
    ax = axes[0]
    years = yearly_df.index.tolist()
    shs = yearly_df["sharpe"].values
    colors = ["#2ca02c" if s > 0.5 else ("#ff7f0e" if s > 0 else "#d62728") for s in shs]
    ax.bar(range(len(years)), shs, color=colors, edgecolor="black")
    ax.axhline(0.5, color="orange", lw=0.8, ls="--", alpha=0.6, label="OOS 通过线 0.50")
    ax.axhline(0, color="black", lw=0.6)
    ax.axhline(float(oos_port.mean() * 252 / (oos_port.std() * np.sqrt(252))),
               color="darkgreen", lw=1.2, ls=":", alpha=0.7, label=f"OOS 整体 Sharpe")
    ax.set_xticks(range(len(years)))
    ax.set_xticklabels([str(y) for y in years])
    for i, s in enumerate(shs):
        ax.text(i, s + (0.05 if s >= 0 else -0.12), f"{s:+.2f}",
                ha="center", fontsize=10, fontweight="bold")
    ax.set_title(f"Q1 · Pool_filtered OOS 年度 Sharpe\n(共 {n_years} 年；Sharpe>0.5 的年份 {n_good_years}/{n_years})")
    ax.set_ylabel("Sharpe")
    ax.grid(alpha=0.3, axis="y")
    ax.legend(fontsize=9, loc="lower right")

    # 右：品种贡献条形（sorted）
    ax = axes[1]
    y = np.arange(len(sym_df))
    contribs = sym_df["contrib"].values
    bar_colors = ["#d62728" if s else ("#2ca02c" if c > 0 else "#808080")
                  for c, s in zip(contribs, sym_df["carry_ex"])]
    # 标成：Carry_ex 红边、正贡献绿、负贡献灰
    face_colors = ["#2ca02c" if c > 0 else "#d62728" for c in contribs]
    edge_colors = ["black" if s else "none" for s in sym_df["carry_ex"]]
    line_w = [1.8 if s else 0.0 for s in sym_df["carry_ex"]]
    ax.barh(y, contribs, color=face_colors,
            edgecolor=edge_colors, linewidth=line_w)
    for i, (v, sym, carry_ex) in enumerate(
        zip(contribs, sym_df["symbol"].values, sym_df["carry_ex"].values)
    ):
        label = f"{sym} {'(ex)' if carry_ex else ''}"
        ax.text(v + (0.0008 if v >= 0 else -0.0008), i, label,
                va="center", ha="left" if v >= 0 else "right", fontsize=9)
    ax.axvline(0, color="black", lw=0.6)
    ax.set_yticks(y)
    ax.set_yticklabels([f"{r.name}({r.symbol})" for _, r in sym_df.iterrows()], fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("单品种对组合 OOS 年化收益的贡献（ann_ret_sym / 19）")
    ax.set_title(f"Q2 · 品种贡献排序\n(组合 OOS ann_ret = {port_ann:+.2%};  "
                 f"Top3 贡献 {top3_contrib/port_ann:.0%};  '(ex)' = Carry-excluded 纯 TSMOM)")
    ax.grid(alpha=0.3, axis="x")

    plt.tight_layout()
    fig_fp = OUT_DIR / "oos_attribute.png"
    plt.savefig(fig_fp, dpi=120, bbox_inches="tight")
    plt.close(fig)

    print(f"\n[save] {OUT_DIR / 'oos_attribute_yearly.csv'}")
    print(f"[save] {OUT_DIR / 'oos_attribute_per_symbol.csv'}")
    print(f"[save] {fig_fp}")


if __name__ == "__main__":
    main()
