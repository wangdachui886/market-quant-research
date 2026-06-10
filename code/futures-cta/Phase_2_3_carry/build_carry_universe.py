"""Phase 2.3 · Step 2 · 19 品种 Carry 构造

对 config.UNIVERSE 里每个品种：
  1) 用 carry_build.build_carry_for_symbol 算年化 carry
  2) 保存 data_cache/tushare/carry/{SYMBOL}_carry.csv
  3) 汇总到一张 quality 表并打印

同时画一张 19 小图 panel，肉眼扫一遍每个品种的 carry 长期特征。

肉眼验收（目标）：
  - 所有品种 valid_rate > 90%
  - 农产品（M/P/Y/SR/CF）大多数时间 carry ≠ 0，均值可正可负
  - 有色（CU/ZN/AL/SC）gap=1，carry 绝对值通常 < 10% 年化
  - 贵金属（AU/AG）gap=6，carry 接近无风险利率，符号相对稳定

用法：
    python Phase_2_3_carry/build_carry_universe.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import pandas as pd

matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import UNIVERSE, MAIN_MONTHS  # noqa: E402
from Phase_2_3_carry.carry_build import build_carry_for_symbol, carry_summary  # noqa: E402

OUT_CSV_DIR = PROJECT_ROOT / "data_cache" / "tushare" / "carry"
OUT_DIR = HERE / "outputs"
OUT_CSV_DIR.mkdir(parents=True, exist_ok=True)
OUT_DIR.mkdir(parents=True, exist_ok=True)


def run_one(symbol: str, name: str, sector: str, exchange: str) -> tuple[pd.DataFrame, dict]:
    product = symbol[:-1]
    main_months = MAIN_MONTHS[product]
    df = build_carry_for_symbol(
        symbol=symbol,
        exchange=exchange,
        main_months=main_months,
        project_root=PROJECT_ROOT,
    )
    out_csv = OUT_CSV_DIR / f"{symbol}_carry.csv"
    df.to_csv(out_csv, encoding="utf-8-sig")

    s = carry_summary(df)
    s["symbol"] = symbol
    s["name"] = name
    s["sector"] = sector
    s["exchange"] = exchange
    s["main_months"] = "/".join(str(m) for m in main_months)
    return df, s


def plot_panel(results: dict[str, pd.DataFrame], out_png: Path) -> None:
    n = len(results)
    ncols = 4
    nrows = (n + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(ncols * 4.5, nrows * 2.4),
                             sharex=True)
    axes = axes.flatten()

    for i, (symbol, df) in enumerate(results.items()):
        ax = axes[i]
        carry_pct = df["carry"] * 100
        ax.plot(df.index, carry_pct, color="darkorange", lw=0.5)
        ax.axhline(0, color="black", lw=0.4)
        ax.fill_between(df.index, 0, carry_pct, where=(df["carry"] > 0),
                        color="crimson", alpha=0.2)
        ax.fill_between(df.index, 0, carry_pct, where=(df["carry"] < 0),
                        color="steelblue", alpha=0.2)
        mean_c = df["carry"].mean() * 100
        ax.axhline(mean_c, color="red", lw=0.6, ls="--")
        ax.set_title(f"{symbol}  mean={mean_c:+.1f}%", fontsize=10)
        ax.tick_params(axis="y", labelsize=8)
        ax.tick_params(axis="x", labelsize=8, rotation=30)
        ax.grid(alpha=0.25)

    for j in range(n, len(axes)):
        axes[j].axis("off")

    fig.suptitle("19 品种年化 Carry 时间序列（红=Backwardation, 蓝=Contango, 红虚线=历史均值）",
                 fontsize=13, y=1.00)
    plt.tight_layout()
    plt.savefig(out_png, dpi=110, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    print("=" * 80)
    print(f"Phase 2.3 · 19 品种 Carry 构造")
    print("=" * 80)

    results: dict[str, pd.DataFrame] = {}
    summaries: list[dict] = []
    failures: list[tuple[str, str]] = []

    for symbol, name, sector, exchange, _mult in UNIVERSE:
        try:
            df, s = run_one(symbol, name, sector, exchange)
            results[symbol] = df
            summaries.append(s)
            print(f"  [{symbol:>4}] {name:<6} {sector:<6} "
                  f"valid={s['valid_rate']:.1%}  "
                  f"mean={s['mean']:+.2%}  "
                  f"median={s['median']:+.2%}  "
                  f"pos={s['pos_rate']:.0%}")
        except Exception as e:
            print(f"  [{symbol:>4}] {name:<6} ❌ 失败: {e}")
            failures.append((symbol, str(e)))

    print()
    print("=" * 80)
    print("汇总 quality 表")
    print("=" * 80)

    if summaries:
        rep = pd.DataFrame(summaries)
        cols_show = ["symbol", "name", "sector", "exchange", "main_months",
                     "n_total", "n_valid", "valid_rate",
                     "mean", "median", "q05", "q95", "pos_rate", "neg_rate",
                     "month_gaps"]
        rep = rep[cols_show]

        disp = rep.copy()
        for c in ["valid_rate", "mean", "median", "q05", "q95", "pos_rate", "neg_rate"]:
            disp[c] = disp[c].map(lambda v: f"{v:+.2%}" if pd.notna(v) else "—")
        print(disp.to_string(index=False))

        out_rep = OUT_DIR / "universe_carry_report.csv"
        rep.to_csv(out_rep, index=False, encoding="utf-8-sig")
        print(f"\n[save] {out_rep}")

    if results:
        out_panel = OUT_DIR / "universe_carry_panel.png"
        plot_panel(results, out_panel)
        print(f"[save] {out_panel}")

    if failures:
        print()
        print("=" * 80)
        print(f"❌ 失败品种 ({len(failures)} 个)")
        print("=" * 80)
        for sym, err in failures:
            print(f"  {sym}: {err}")
    else:
        print()
        print(f"✅ 19/19 品种全部成功构造 Carry")


if __name__ == "__main__":
    main()
