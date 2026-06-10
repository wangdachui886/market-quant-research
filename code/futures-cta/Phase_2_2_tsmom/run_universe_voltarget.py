"""Phase 2.2 · Step 3 · 19 品种 TSMOM + Vol-Targeting 组合回测

在 Step 2（run_universe.py，raw TSMOM 等权）之上，只改一层：仓位。

  Step 2 ：position = sign(past_252d_ret)
  Step 3 ：position = sign(past_252d_ret) × (target_vol / σ̂_60d)

其余一切不变（lookback 252，lag 1，组合层仍为动态等权）。
本脚本同时跑 raw 和 vol-target 两套，打印对比 + 一张图三条曲线。

核心问题：vol-targeting 能否把组合 Sharpe 从 0.52 推过 B&H 的 0.60？

用法：
    python Phase_2_2_tsmom/run_universe_voltarget.py

产出：
    终端：raw vs vol-target 组合对比 + 逐品种表
    outputs/tsmom_universe_voltarget_per_symbol.csv
    outputs/tsmom_universe_voltarget.png
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
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(PROJECT_ROOT))

from signals import tsmom_signal  # noqa: E402
from sizing import vol_target_scale  # noqa: E402
from backtest import backtest_single  # noqa: E402
from config import UNIVERSE  # noqa: E402

CLEAN_DIR = PROJECT_ROOT / "data_cache" / "tushare" / "clean"
OUT_DIR = HERE / "outputs"
OUT_DIR.mkdir(exist_ok=True)

LOOKBACK = 252
LAG = 1
TARGET_VOL = 0.20
VOL_WINDOW = 60
VOL_FLOOR = 0.05
MAX_LEV = 3.0


def load_clean_returns(symbol: str) -> pd.Series:
    fp = CLEAN_DIR / f"{symbol}_clean_returns.csv"
    if not fp.exists():
        raise FileNotFoundError(fp)
    df = pd.read_csv(fp, parse_dates=["date"]).set_index("date")
    s = df["clean_return"].sort_index()
    s.name = symbol
    return s


def run_one(symbol: str) -> dict:
    ret = load_clean_returns(symbol)

    direction = tsmom_signal(ret, lookback_days=LOOKBACK)
    scale = vol_target_scale(
        ret, target_vol=TARGET_VOL, window=VOL_WINDOW,
        vol_floor=VOL_FLOOR, max_leverage=MAX_LEV,
    )

    raw_position = direction
    vt_position = direction * scale

    raw = backtest_single(ret, raw_position, lag_days=LAG)
    vt = backtest_single(ret, vt_position, lag_days=LAG)

    return {
        "symbol": symbol,
        "clean_return": ret,
        "scale": scale,
        "raw": raw,
        "vt": vt,
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
    print("=" * 78)
    print(f"TSMOM + Vol-Target   N={len(symbols)}   lookback={LOOKBACK}d   "
          f"target_vol={TARGET_VOL:.0%}   vol_window={VOL_WINDOW}d   "
          f"floor={VOL_FLOOR:.0%}   max_lev={MAX_LEV}")
    print("=" * 78)

    raw_rets: dict[str, pd.Series] = {}
    vt_rets: dict[str, pd.Series] = {}
    bh_rets: dict[str, pd.Series] = {}
    scales: dict[str, pd.Series] = {}
    per_rows: list[dict] = []

    for sym in symbols:
        try:
            out = run_one(sym)
        except FileNotFoundError:
            print(f"  [skip] {sym}：无 clean_returns 文件")
            continue

        raw_rets[sym] = out["raw"]["strategy_return"]
        vt_rets[sym] = out["vt"]["strategy_return"]
        bh_rets[sym] = out["clean_return"]
        scales[sym] = out["scale"]

        raw_m = out["raw"]["metrics"]
        vt_m = out["vt"]["metrics"]
        avg_scale = out["scale"].dropna().mean()

        per_rows.append({
            "symbol": sym,
            "raw_sharpe": raw_m["sharpe"],
            "vt_sharpe": vt_m["sharpe"],
            "vt_ret": vt_m["annual_return"],
            "vt_vol": vt_m["annual_vol"],
            "vt_maxdd": vt_m["max_dd"],
            "avg_scale": float(avg_scale),
        })
        print(
            f"  [{sym:>4}]  raw Sharpe={raw_m['sharpe']:+.2f}  "
            f"→ vt Sharpe={vt_m['sharpe']:+.2f}  "
            f"(avg_scale={avg_scale:4.2f}x, vt_vol={vt_m['annual_vol']:5.1%}, "
            f"vt_MaxDD={vt_m['max_dd']:+6.1%})"
        )

    raw_df = pd.DataFrame(raw_rets).sort_index()
    vt_df = pd.DataFrame(vt_rets).sort_index()
    bh_df = pd.DataFrame(bh_rets).sort_index()

    port_raw = raw_df.mean(axis=1, skipna=True)
    port_vt = vt_df.mean(axis=1, skipna=True)
    port_bh = bh_df.mean(axis=1, skipna=True)

    raw_m = compute_port_metrics(port_raw)
    vt_m = compute_port_metrics(port_vt)
    bh_m = compute_port_metrics(port_bh)

    summary = pd.DataFrame(per_rows).sort_values("vt_sharpe", ascending=False).reset_index(drop=True)
    csv_fp = OUT_DIR / "tsmom_universe_voltarget_per_symbol.csv"
    summary.to_csv(csv_fp, index=False, encoding="utf-8-sig")

    print("\n" + "=" * 78)
    print("逐品种对比：raw → vol-targeted（按 vt_sharpe 降序）")
    print("=" * 78)
    with pd.option_context("display.float_format", "{:.3f}".format, "display.width", 160):
        print(summary.to_string(index=False))

    print("\n" + "=" * 78)
    print("组合汇总（动态等权 / 无成本）")
    print("=" * 78)
    fmt = "{:<18s} Sharpe={:+.2f}  Ret={:+6.1%}  Vol={:5.1%}  MaxDD={:+6.1%}  NAV末={:.3f}"
    print(fmt.format("  raw TSMOM",  raw_m["sharpe"], raw_m["annual_return"], raw_m["annual_vol"], raw_m["max_dd"], raw_m["nav_end"]))
    print(fmt.format("  vol-target TSMOM", vt_m["sharpe"], vt_m["annual_return"], vt_m["annual_vol"], vt_m["max_dd"], vt_m["nav_end"]))
    print(fmt.format("  B&H 等权",     bh_m["sharpe"], bh_m["annual_return"], bh_m["annual_vol"], bh_m["max_dd"], bh_m["nav_end"]))

    avg_raw = summary["raw_sharpe"].mean()
    avg_vt = summary["vt_sharpe"].mean()
    pos_raw = int((summary["raw_sharpe"] > 0).sum())
    pos_vt = int((summary["vt_sharpe"] > 0).sum())

    print("\n" + "-" * 78)
    print(f"  单品种 Sharpe 均值   raw {avg_raw:+.2f}  →  vt {avg_vt:+.2f}   (Δ={avg_vt-avg_raw:+.2f})")
    print(f"  Sharpe > 0 占比      raw {pos_raw}/{len(summary)}  →  vt {pos_vt}/{len(summary)}")
    if avg_vt > 0:
        print(f"  分散增益（vt）       = {vt_m['sharpe'] / avg_vt:.2f}x")
    print(f"  vs B&H (Sharpe=0.60) {'✅ 赢 B&H' if vt_m['sharpe'] > bh_m['sharpe'] else '❌ 仍不及 B&H'}")

    avg_scale_all = pd.DataFrame(scales).mean(axis=1).mean()
    print(f"  组合层平均总杠杆     ≈ {avg_scale_all:.2f}x  （每品种 avg_scale 的截面均值）")

    # ---------- 画图 ----------
    fig, axes = plt.subplots(
        2, 1, figsize=(13, 9),
        gridspec_kw={"height_ratios": [2, 1]},
    )

    ax = axes[0]
    bh_nav = (1 + port_bh.fillna(0)).cumprod()
    raw_nav = (1 + port_raw.fillna(0)).cumprod()
    vt_nav = (1 + port_vt.fillna(0)).cumprod()
    ax.plot(bh_nav.index, bh_nav.values,
            label=f"B&H 等权   Sharpe={bh_m['sharpe']:+.2f}  NAV={bh_m['nav_end']:.2f}",
            color="gray", lw=1.3)
    ax.plot(raw_nav.index, raw_nav.values,
            label=f"raw TSMOM   Sharpe={raw_m['sharpe']:+.2f}  NAV={raw_m['nav_end']:.2f}",
            color="lightsteelblue", lw=1.4, ls="--")
    ax.plot(vt_nav.index, vt_nav.values,
            label=f"vol-target TSMOM   Sharpe={vt_m['sharpe']:+.2f}  NAV={vt_m['nav_end']:.2f}",
            color="steelblue", lw=2.3)
    ax.axhline(1.0, color="black", lw=0.4, alpha=0.5)
    ax.set_title(f"TSMOM 组合：raw vs vol-target   "
                 f"(lookback={LOOKBACK}d, target_vol={TARGET_VOL:.0%}, vol_window={VOL_WINDOW}d)")
    ax.set_ylabel("NAV (起点=1)")
    ax.grid(alpha=0.3)
    ax.legend(loc="upper left")

    ax = axes[1]
    x = np.arange(len(summary))
    w = 0.4
    ax.bar(x - w/2, summary["raw_sharpe"], w, label="raw", color="lightsteelblue")
    ax.bar(x + w/2, summary["vt_sharpe"], w, label="vol-target",
           color=["#2ca02c" if s > 0 else "#d62728" for s in summary["vt_sharpe"]])
    ax.axhline(0, color="black", lw=0.6)
    ax.axhline(vt_m["sharpe"], color="steelblue", lw=1.5, ls="--",
               label=f"vt 组合 Sharpe = {vt_m['sharpe']:+.2f}")
    ax.axhline(bh_m["sharpe"], color="gray", lw=1.2, ls=":",
               label=f"B&H 组合 Sharpe = {bh_m['sharpe']:+.2f}")
    ax.set_xticks(x)
    ax.set_xticklabels(summary["symbol"], rotation=45)
    ax.set_title("逐品种 Sharpe 对比（灰色=raw，彩色=vol-target）")
    ax.set_ylabel("Sharpe")
    ax.legend(loc="lower left", ncol=2)
    ax.grid(alpha=0.3, axis="y")

    plt.tight_layout()
    png_fp = OUT_DIR / "tsmom_universe_voltarget.png"
    plt.savefig(png_fp, dpi=120, bbox_inches="tight")
    plt.close(fig)

    print(f"\n[save] {csv_fp}")
    print(f"[save] {png_fp}")


if __name__ == "__main__":
    main()
