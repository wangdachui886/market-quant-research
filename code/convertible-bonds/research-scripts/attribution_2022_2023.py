"""P&L attribution for 2022 and 2023 OOS segments, with full cost decomposition.

Decomposes:
- per-bond gross_contrib (no cost smearing)
- daily __COST__ row (2 * turnover * 15bp on execution date)
- gross / cost / net at portfolio level
- keep29 vs vanilla difference (holding-day extension, contrib delta)
- alpha/beta on net returns
- calendar concentration (worst days/weeks on net)

Net CAGR / MDD are cross-checked against walk-forward segment_metrics.
Does NOT modify any strategy code.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    HAS_MATPLOTLIB = True
except ModuleNotFoundError:
    plt = None
    HAS_MATPLOTLIB = False

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategy.core.cb_strategy_config import StrategyParams
from strategy.core.data_access import load_issue_size_series, load_maturity_date_series
from strategy.core.portfolio import _pick_week_holdings, _week_end_dates
from strategy.core.universe import build_universes

PANEL_2017 = ROOT / "data" / "bond_daily_panel_full_v2_from20170101.csv"
OUT_DIR = ROOT / "GPT-test" / "output" / "walk_forward_gate_v1" / "attribution_2022_2023"
WF_METRICS = ROOT / "GPT-test" / "output" / "walk_forward_gate_v1" / "full_2017" / "segment_metrics.csv"

TOP_N = 10
KEEP_N = 29
COST_BP_SIDE = 15.0
MAIN_ISSUE_SIZE = 300_000_000.0

OOS_SEGMENTS = {
    "2022": (pd.Timestamp("2022-01-01"), pd.Timestamp("2022-12-31")),
    "2023": (pd.Timestamp("2023-01-01"), pd.Timestamp("2023-12-31")),
}


def load_raw_panel() -> pd.DataFrame:
    raw = pd.read_csv(PANEL_2017, dtype={"cb_code": str, "stk_code": str, "trade_date": str}, low_memory=False)
    raw["trade_date"] = pd.to_datetime(raw["trade_date"], format="%Y%m%d")
    for col in ("is_tradable_day", "in_delisting_period"):
        if raw[col].dtype == object:
            raw[col] = raw[col].str.lower() == "true"
        else:
            raw[col] = raw[col].astype(bool)
    return raw


def prepare_base() -> tuple[pd.DataFrame, StrategyParams]:
    params = StrategyParams(
        top_n=TOP_N,
        min_issue_size=MAIN_ISSUE_SIZE,
        cb_close_min=80.0,
        cb_close_max=None,
        min_days_to_maturity=180,
        redeem_notice_csv=None,
    )
    raw = load_raw_panel()
    issue_sizes = load_issue_size_series()
    maturity_dates = load_maturity_date_series()
    df, _ = build_universes(raw, issue_sizes, params, maturity_dates)
    df = df.sort_values(["cb_code", "trade_date"]).copy()
    df["ret"] = df.groupby("cb_code")["cb_close"].pct_change()
    if "cb_open" in df.columns:
        df["ret_entry"] = pd.to_numeric(df["cb_close"], errors="coerce") / pd.to_numeric(df["cb_open"], errors="coerce") - 1.0
    else:
        df["ret_entry"] = df["ret"]
    mom_col = "stock_close_adj" if "stock_close_adj" in df.columns else "stock_close"
    df["mom_20d"] = df.groupby("stk_code")[mom_col].pct_change(20)
    rank_price = df.groupby("trade_date")["cb_close"].rank(pct=True, ascending=True)
    rank_premium = df.groupby("trade_date")["conversion_premium"].rank(pct=True, ascending=True)
    rank_mom = df.groupby("trade_date")["mom_20d"].rank(pct=True, ascending=False)
    df["score"] = rank_price + rank_premium + rank_mom
    df["issue_size"] = df["cb_code"].map(issue_sizes)
    return df.loc[df["score"].notna()].copy(), params


def build_weekly_holdings(df: pd.DataFrame, keep_n: int | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (per-day holdings table, rebalance-level cost rows)."""
    dates = np.sort(df["trade_date"].unique())
    d2i = {d: i for i, d in enumerate(dates)}
    rbals = _week_end_dates(dates)

    sel: dict = {}
    prev: set[str] = set()
    for rd in rbals:
        snap = df.loc[df["trade_date"] == rd]
        top = _pick_week_holdings(snap, prev, TOP_N, keep_n=keep_n)
        if top:
            sel[rd] = top
            prev = set(top)

    rb = sorted(sel)
    holdings_rows = []
    cost_rows = []
    for i, rd in enumerate(rb):
        si = d2i[rd] + 2
        if i + 1 < len(rb):
            ei = min(d2i[rb[i + 1]] + 1, len(dates) - 1)
        else:
            ei = len(dates) - 1
        if si >= len(dates) or si > ei:
            continue
        old = set() if i == 0 else set(sel[rb[i - 1]])
        new = set(sel[rd])
        for code in sel[rd]:
            is_new = code in (new - old)
            for j in range(si, ei + 1):
                holdings_rows.append({
                    "signal_date": pd.Timestamp(rd),
                    "trade_date": pd.Timestamp(dates[j]),
                    "cb_code": code,
                    "is_entry": (j == si) and is_new,
                })
        if i >= 1:
            turnover = len(new - old) / max(len(new), 1)
            cost_pct = 2.0 * turnover * COST_BP_SIDE / 1e4
            cost_rows.append({
                "trade_date": pd.Timestamp(dates[si]),
                "turnover": turnover,
                "cost_pct": cost_pct,
            })
    return pd.DataFrame(holdings_rows), pd.DataFrame(cost_rows)


def attach_returns_and_meta(holdings: pd.DataFrame, df: pd.DataFrame) -> pd.DataFrame:
    meta_cols = ["trade_date", "cb_code", "ret", "ret_entry", "cb_close",
                 "conversion_premium", "issue_rating", "issue_size",
                 "bond_short_name", "stk_code", "mom_20d"]
    available = [c for c in meta_cols if c in df.columns]
    h = holdings.merge(df[available], on=["trade_date", "cb_code"], how="left")
    h["ret_used"] = np.where(h["is_entry"], h["ret_entry"], h["ret"])
    active_n = h.groupby("trade_date")["ret_used"].transform(lambda s: s.notna().sum())
    h["gross_contrib"] = h["ret_used"].fillna(0.0) / active_n.replace(0, np.nan)
    return h


def daily_pnl_with_cost(h: pd.DataFrame, cost_rows: pd.DataFrame) -> pd.DataFrame:
    """Daily portfolio gross/cost/net."""
    gross = h.groupby("trade_date")["gross_contrib"].sum().rename("gross")
    cost = pd.Series(0.0, index=gross.index, name="cost")
    if not cost_rows.empty:
        c = cost_rows.set_index("trade_date")["cost_pct"]
        c = c.reindex(gross.index, fill_value=0.0)
        cost = (-c).rename("cost")
    net = (gross + cost).rename("net")
    out = pd.concat([gross, cost, net], axis=1).reset_index()
    return out


def per_bond_attribution(h: pd.DataFrame, seg_name: str, variant: str) -> pd.DataFrame:
    g = h.groupby("cb_code").agg(
        bond_short_name=("bond_short_name", "last"),
        issue_rating=("issue_rating", "last"),
        issue_size=("issue_size", "last"),
        stk_code=("stk_code", "last"),
        holding_days=("trade_date", "count"),
        gross_contrib=("gross_contrib", "sum"),
        mean_daily_ret=("ret_used", "mean"),
        worst_daily_ret=("ret_used", "min"),
        entry_count=("is_entry", "sum"),
    ).reset_index()
    g["segment"] = seg_name
    g["variant"] = variant
    return g.sort_values("gross_contrib", ascending=True).reset_index(drop=True)


def common_characteristics(worst: pd.DataFrame, best: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label, d in [("worst_20", worst), ("best_20", best)]:
        rows.append({
            "group": label,
            "count": len(d),
            "median_issue_size_yi": d["issue_size"].median() / 1e8 if d["issue_size"].notna().any() else np.nan,
            "mean_holding_days": d["holding_days"].mean(),
            "gross_contrib_sum": d["gross_contrib"].sum(),
            "rating_mode": d["issue_rating"].mode().iloc[0] if not d["issue_rating"].mode().empty else "",
            "mean_worst_daily_ret": d["worst_daily_ret"].mean(),
        })
    return pd.DataFrame(rows)


def calendar_with_dd(daily: pd.DataFrame, seg_name: str) -> pd.DataFrame:
    cal = daily.copy()
    cal["segment"] = seg_name
    cal["cum_net"] = (1 + cal["net"]).cumprod()
    cal["drawdown_net"] = cal["cum_net"] / cal["cum_net"].cummax() - 1.0
    cal["week"] = cal["trade_date"].dt.isocalendar().week.astype(int)
    cal["year"] = cal["trade_date"].dt.year
    return cal


def worst_periods(cal: pd.DataFrame, n_days: int = 5, n_weeks: int = 5) -> tuple[pd.DataFrame, pd.DataFrame]:
    worst_days = cal.nsmallest(n_days, "net")[["trade_date", "gross", "cost", "net", "drawdown_net"]].copy()
    weekly = cal.groupby(["year", "week"]).agg(
        week_start=("trade_date", "min"),
        week_end=("trade_date", "max"),
        gross_w=("gross", lambda x: (1 + x).prod() - 1),
        cost_w=("cost", "sum"),
        net_w=("net", lambda x: (1 + x).prod() - 1),
        n_days=("trade_date", "count"),
    ).reset_index()
    worst_weeks = weekly.nsmallest(n_weeks, "net_w").copy()
    return worst_days, worst_weeks


def alpha_beta_decomposition(daily: pd.DataFrame, bench_df: pd.DataFrame, seg_start, seg_end) -> dict:
    bench = bench_df.groupby("trade_date")["ret"].mean()
    d_filtered = daily.loc[(daily["trade_date"] >= seg_start) & (daily["trade_date"] <= seg_end)].copy()
    d = d_filtered.set_index("trade_date")
    b = bench.reindex(d.index).fillna(0.0)
    if len(d) < 20:
        return {k: np.nan for k in ("beta", "alpha_ann", "r2", "port_cagr", "bench_cagr",
                                    "beta_contrib_cagr", "residual_cagr", "n_days",
                                    "gross_cagr", "cost_drag_ann")}
    cov = np.cov(d["net"], b)
    beta = cov[0, 1] / cov[1, 1] if cov[1, 1] > 0 else np.nan
    alpha_daily = (d["net"] - beta * b).mean()
    alpha_ann = alpha_daily * 252
    ss_res = ((d["net"] - beta * b - alpha_daily) ** 2).sum()
    ss_tot = ((d["net"] - d["net"].mean()) ** 2).sum()
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan
    n = len(d)
    port_cagr = (1 + d["net"]).prod() ** (252 / n) - 1
    gross_cagr = (1 + d["gross"]).prod() ** (252 / n) - 1
    bench_cagr = (1 + b).prod() ** (252 / n) - 1
    cost_drag_ann = d["cost"].sum() * 252 / n
    return {
        "beta": float(beta),
        "alpha_ann": float(alpha_ann),
        "r2": float(r2),
        "port_cagr": float(port_cagr),
        "gross_cagr": float(gross_cagr),
        "bench_cagr": float(bench_cagr),
        "beta_contrib_cagr": float(beta * bench_cagr),
        "residual_cagr": float(port_cagr - beta * bench_cagr),
        "cost_drag_ann": float(cost_drag_ann),
        "n_days": int(n),
    }


def calc_seg_metrics(daily: pd.DataFrame, seg_start, seg_end) -> dict:
    d_filtered = daily.loc[(daily["trade_date"] >= seg_start) & (daily["trade_date"] <= seg_end)].copy()
    d = d_filtered.set_index("trade_date")
    if len(d) < 20:
        return {"n_days": 0}
    n = len(d)
    cum_net = (1 + d["net"]).cumprod()
    cagr = cum_net.iloc[-1] ** (252 / n) - 1
    vol = d["net"].std() * np.sqrt(252)
    sharpe = (cagr - 0.025) / vol if vol > 0 else 0
    dd = cum_net / cum_net.cummax() - 1
    return {"n_days": n, "net_cagr": cagr, "net_sharpe": sharpe, "net_mdd": float(dd.min())}


def keep29_vs_vanilla_diff(attr_keep: pd.DataFrame, attr_van: pd.DataFrame, seg_name: str) -> pd.DataFrame:
    """For bonds held by both variants: holding day delta and contrib delta."""
    k = attr_keep.set_index("cb_code")[["bond_short_name", "issue_rating", "holding_days", "gross_contrib"]]
    v = attr_van.set_index("cb_code")[["holding_days", "gross_contrib"]]
    common = k.index.intersection(v.index)
    out = pd.DataFrame({
        "cb_code": common,
        "bond_short_name": k.loc[common, "bond_short_name"].values,
        "issue_rating": k.loc[common, "issue_rating"].values,
        "keep_days": k.loc[common, "holding_days"].values,
        "vanilla_days": v.loc[common, "holding_days"].values,
        "keep_contrib": k.loc[common, "gross_contrib"].values,
        "vanilla_contrib": v.loc[common, "gross_contrib"].values,
    })
    out["days_delta"] = out["keep_days"] - out["vanilla_days"]
    out["contrib_delta"] = out["keep_contrib"] - out["vanilla_contrib"]
    out["segment"] = seg_name
    return out.sort_values("contrib_delta").reset_index(drop=True)


def load_wf_truth() -> pd.DataFrame:
    if not WF_METRICS.exists():
        return pd.DataFrame()
    df = pd.read_csv(WF_METRICS)
    df["segment"] = df["segment"].astype(str)
    return df.loc[df["variant"].isin(["keep29", "vanilla"])][["variant", "segment", "CAGR", "Sharpe", "MDD"]]


def plot_calendar(cal: pd.DataFrame, seg_name: str, variant: str, out_path: Path) -> None:
    if not HAS_MATPLOTLIB:
        out_path.with_suffix(out_path.suffix + ".skipped.txt").write_text("matplotlib is not installed\n", encoding="utf-8")
        return
    plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, axes = plt.subplots(3, 1, figsize=(13, 8), sharex=True)
    axes[0].bar(cal["trade_date"], cal["gross"] * 100, width=1.5,
                color=np.where(cal["gross"] >= 0, "#22c55e", "#ef4444"))
    axes[0].axhline(0, color="black", lw=0.6)
    axes[0].set_ylabel("gross (%)")
    axes[0].set_title(f"{seg_name} {variant} daily P&L: gross / cost / net")
    axes[0].grid(True, alpha=0.2, axis="y")

    axes[1].bar(cal["trade_date"], cal["cost"] * 100, width=1.5, color="#9ca3af")
    axes[1].set_ylabel("cost (%)")
    axes[1].grid(True, alpha=0.2, axis="y")

    axes[2].fill_between(cal["trade_date"], cal["drawdown_net"] * 100, 0, alpha=0.4, color="#ef4444")
    axes[2].set_ylabel("DD net (%)")
    axes[2].grid(True, alpha=0.2, axis="y")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_top_contributors(worst: pd.DataFrame, best: pd.DataFrame, seg_name: str, variant: str, out_path: Path) -> None:
    if not HAS_MATPLOTLIB:
        out_path.with_suffix(out_path.suffix + ".skipped.txt").write_text("matplotlib is not installed\n", encoding="utf-8")
        return
    plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    for ax, data, title, color in [
        (axes[0], worst, f"{seg_name} {variant} top 20 GROSS loss", "#ef4444"),
        (axes[1], best, f"{seg_name} {variant} top 20 GROSS gain", "#22c55e"),
    ]:
        labels = data["cb_code"] + "\n" + data["bond_short_name"].fillna("").str[:4]
        ax.barh(np.arange(len(data)), data["gross_contrib"] * 100, color=color)
        ax.set_yticks(np.arange(len(data)))
        ax.set_yticklabels(labels, fontsize=7)
        ax.set_xlabel("gross contribution (%)")
        ax.set_title(title)
        ax.axvline(0, color="black", lw=0.6)
        ax.grid(True, alpha=0.2, axis="x")
        ax.invert_yaxis()
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_keep_vs_vanilla(diff: pd.DataFrame, seg_name: str, out_path: Path) -> None:
    if not HAS_MATPLOTLIB:
        out_path.with_suffix(out_path.suffix + ".skipped.txt").write_text("matplotlib is not installed\n", encoding="utf-8")
        return
    plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, ax = plt.subplots(figsize=(11, 6))
    sc = ax.scatter(diff["days_delta"], diff["contrib_delta"] * 100,
                    c=diff["contrib_delta"] * 100, cmap="RdYlGn", s=40, alpha=0.7)
    plt.colorbar(sc, ax=ax, label="contrib delta (%)")
    ax.axhline(0, color="black", lw=0.6)
    ax.axvline(0, color="black", lw=0.6)
    ax.set_xlabel("holding days delta (keep29 - vanilla)")
    ax.set_ylabel("gross contrib delta (%, keep29 - vanilla)")
    ax.set_title(f"{seg_name} keep29 vs vanilla: extension days vs contrib delta\n"
                 f"(top-left: held longer & lost more = bad; top-right: held longer & gained = good)")
    worst5 = diff.head(5)
    for _, r in worst5.iterrows():
        ax.annotate(r["cb_code"], (r["days_delta"], r["contrib_delta"] * 100), fontsize=7)
    ax.grid(True, alpha=0.2)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def write_summary(results: dict, wf_truth: pd.DataFrame, out_path: Path) -> None:
    lines = ["# Attribution: 2022 & 2023 OOS segments (gross / cost / net)", ""]
    lines.append("Setup: C_rank_mom20, top_n=10, keep_n=29, cost=15bp/side, issue_size>=3e8, redeem PIT.")
    lines.append("Cost model: execution day deduction `2 * turnover * 15bp / 1e4`, NOT smeared per bond.")
    lines.append("")

    if not wf_truth.empty:
        lines.append("## Walk-forward truth (cross-check)")
        lines.append("")
        lines.append("| variant | segment | CAGR | Sharpe | MDD |")
        lines.append("|---|---|---|---|---|")
        for _, r in wf_truth.iterrows():
            if r["segment"] in ("2022", "2023"):
                lines.append(f"| {r['variant']} | {r['segment']} | {r['CAGR']:.2%} | {r['Sharpe']:.2f} | {r['MDD']:.2%} |")
        lines.append("")

    for seg_name, segr in results.items():
        lines.append(f"## {seg_name}")
        lines.append("")
        for variant, r in segr.items():
            sm = r["seg_metrics"]
            ab = r["alpha_beta"]
            lines.append(f"### {variant}")
            lines.append("")
            lines.append(f"- recomputed net: CAGR={sm.get('net_cagr', 0):.2%}, "
                         f"Sharpe={sm.get('net_sharpe', 0):.2f}, MDD={sm.get('net_mdd', 0):.2%}")
            lines.append(f"- gross CAGR={ab['gross_cagr']:.2%}, cost drag (ann)={ab['cost_drag_ann']:.2%}, "
                         f"net CAGR={ab['port_cagr']:.2%}")
            lines.append(f"- beta vs bench={ab['beta']:.3f}, R2={ab['r2']:.3f}, alpha (net, ann)={ab['alpha_ann']:.2%}")
            lines.append(f"- beta contrib CAGR={ab['beta_contrib_cagr']:.2%}, residual={ab['residual_cagr']:.2%}, "
                         f"bench CAGR={ab['bench_cagr']:.2%}")
            chars = r["characteristics"]
            for _, row in chars.iterrows():
                lines.append(f"- {row['group']}: median issue_size {row['median_issue_size_yi']:.1f}亿, "
                             f"rating mode={row['rating_mode']}, "
                             f"gross contrib sum={row['gross_contrib_sum']:.2%}")
            wd = r["worst_days"]
            lines.append(f"- worst 5 net days: " + ", ".join(
                wd["trade_date"].dt.strftime("%Y-%m-%d") + " " +
                (wd["net"] * 100).round(2).astype(str) + "%"
            ))
            ww = r["worst_weeks"]
            lines.append(f"- worst 5 net weeks: " + ", ".join(
                ww["week_start"].dt.strftime("%Y-%m-%d") + "~" +
                ww["week_end"].dt.strftime("%m-%d") + " " +
                (ww["net_w"] * 100).round(2).astype(str) + "%"
            ))
            attr = r["per_bond"]
            top5 = attr.head(5)
            lines.append("- top 5 gross loss: " + ", ".join(
                top5["cb_code"] + "(" + (top5["gross_contrib"] * 100).round(2).astype(str) + "%)"
            ))
            lines.append("")

        if "diff" in segr.get("keep29", {}):
            diff = segr["keep29"]["diff"]
            lines.append(f"### {seg_name} keep29 vs vanilla diff")
            lines.append("")
            lines.append(f"- common bonds: {len(diff)}")
            held_longer_lost = diff.loc[(diff["days_delta"] > 0) & (diff["contrib_delta"] < 0)]
            held_longer_won = diff.loc[(diff["days_delta"] > 0) & (diff["contrib_delta"] > 0)]
            lines.append(f"- bonds held LONGER by keep29 and LOST more: {len(held_longer_lost)}, "
                         f"sum extra loss: {held_longer_lost['contrib_delta'].sum():.2%}")
            lines.append(f"- bonds held LONGER by keep29 and GAINED more: {len(held_longer_won)}, "
                         f"sum extra gain: {held_longer_won['contrib_delta'].sum():.2%}")
            top5_bad = held_longer_lost.sort_values("contrib_delta").head(5)
            lines.append("- top 5 keep29 extra loss bonds: " + ", ".join(
                top5_bad["cb_code"] + "(+" + top5_bad["days_delta"].astype(str) + "d, " +
                (top5_bad["contrib_delta"] * 100).round(2).astype(str) + "%)"
            ))
            lines.append("")

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_variant(base: pd.DataFrame, seg_name: str, seg_start, seg_end, keep_n, variant_name: str) -> dict:
    holdings, cost_rows = build_weekly_holdings(base, keep_n)
    holdings = attach_returns_and_meta(holdings, base)

    h = holdings.loc[(holdings["trade_date"] >= seg_start) & (holdings["trade_date"] <= seg_end)].copy()
    cost_seg = cost_rows.loc[(cost_rows["trade_date"] >= seg_start) & (cost_rows["trade_date"] <= seg_end)].copy()
    if h.empty:
        return {}

    daily = daily_pnl_with_cost(h, cost_seg)
    daily = daily.loc[(daily["trade_date"] >= seg_start) & (daily["trade_date"] <= seg_end)].copy()
    cal = calendar_with_dd(daily, seg_name)

    attr = per_bond_attribution(h, seg_name, variant_name)
    worst, best = attr.head(20).copy(), attr.tail(20).iloc[::-1].copy()
    chars = common_characteristics(worst, best)
    worst_days, worst_weeks = worst_periods(cal)
    bench_df = base[["trade_date", "ret"]].copy()
    ab = alpha_beta_decomposition(daily, bench_df, seg_start, seg_end)
    sm = calc_seg_metrics(daily, seg_start, seg_end)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    suffix = f"{seg_name}_{variant_name}"
    attr.to_csv(OUT_DIR / f"per_bond_attribution_{suffix}.csv", index=False, encoding="utf-8-sig")
    chars.to_csv(OUT_DIR / f"characteristics_{suffix}.csv", index=False, encoding="utf-8-sig")
    cal.to_csv(OUT_DIR / f"calendar_{suffix}.csv", index=False, encoding="utf-8-sig")
    worst_days.to_csv(OUT_DIR / f"worst_days_{suffix}.csv", index=False, encoding="utf-8-sig")
    worst_weeks.to_csv(OUT_DIR / f"worst_weeks_{suffix}.csv", index=False, encoding="utf-8-sig")
    daily.to_csv(OUT_DIR / f"daily_pnl_{suffix}.csv", index=False, encoding="utf-8-sig")

    plot_calendar(cal, seg_name, variant_name, OUT_DIR / f"calendar_{suffix}.png")
    plot_top_contributors(worst, best, seg_name, variant_name, OUT_DIR / f"top_contributors_{suffix}.png")

    return {
        "per_bond": attr,
        "characteristics": chars,
        "worst_days": worst_days,
        "worst_weeks": worst_weeks,
        "alpha_beta": ab,
        "seg_metrics": sm,
        "daily": daily,
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    base, _ = prepare_base()

    results = {}
    for seg_name, (seg_start, seg_end) in OOS_SEGMENTS.items():
        seg_results = {}
        for variant_name, kn in [("keep29", KEEP_N), ("vanilla", None)]:
            r = run_variant(base, seg_name, seg_start, seg_end, kn, variant_name)
            if r:
                seg_results[variant_name] = r
                ab = r["alpha_beta"]
                sm = r["seg_metrics"]
                print(f"  {seg_name}/{variant_name}: gross={ab['gross_cagr']:.2%}, "
                      f"cost={ab['cost_drag_ann']:.2%}, net={ab['port_cagr']:.2%}, "
                      f"sharpe={sm.get('net_sharpe', 0):.2f}, beta={ab['beta']:.2f}, alpha={ab['alpha_ann']:.2%}")
        if "keep29" in seg_results and "vanilla" in seg_results:
            diff = keep29_vs_vanilla_diff(seg_results["keep29"]["per_bond"],
                                          seg_results["vanilla"]["per_bond"], seg_name)
            diff.to_csv(OUT_DIR / f"keep29_vs_vanilla_diff_{seg_name}.csv", index=False, encoding="utf-8-sig")
            plot_keep_vs_vanilla(diff, seg_name, OUT_DIR / f"keep29_vs_vanilla_diff_{seg_name}.png")
            seg_results["keep29"]["diff"] = diff
        results[seg_name] = seg_results

    wf_truth = load_wf_truth()
    write_summary(results, wf_truth, OUT_DIR / "attribution_summary.md")
    print(f"wrote outputs to {OUT_DIR}")


if __name__ == "__main__":
    main()
