"""Rolling walk-forward gate test for C_rank_mom20 + keep29.

This is a research-side script. It does not change sealed strategy code.
Outputs are written under GPT-test/output/walk_forward_gate_v1.
"""

from __future__ import annotations

import json
import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

try:
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
from strategy.core.portfolio import _pick_week_holdings, _week_end_dates, build_positions, calc_metrics
from strategy.core.cb_strategy_config import PANEL_CSV
from strategy.core.universe import build_universes, load_panel_csv

OUT_DIR = ROOT / "GPT-test" / "output" / "walk_forward_gate_v1"

TOP_N = 10
KEEP_MAIN = 29
KEEP_SENSITIVITY = (20, 25, 29, 35, 40)
COST_BP_SIDE = 15.0
MAIN_ISSUE_SIZE = 300_000_000.0

WF_FIRST_OOS_YEAR = 2021
WF_IS_YEARS = 3
MIN_IS_DAYS = 500
MIN_OOS_DAYS = 120
MIN_READY_SEGMENTS = 5


@dataclass(frozen=True)
class GateThresholds:
    min_seg_sharpe: float = -0.3
    min_seg_cagr: float = -0.08
    min_seg_mdd: float = -0.25
    max_mdd_underperform_pp: float = -0.08
    share_sharpe_pos: float = 0.70
    share_sharpe_ge_03: float = 0.50
    median_sharpe: float = 0.40
    median_excess_sharpe: float = 0.0
    share_keep29_sharpe_ge_vanilla: float = 0.70
    share_keep29_turnover_lt_80pct: float = 0.90


def pct(x: float) -> str:
    return "nan" if pd.isna(x) else f"{x:.2%}"


def fmt(x: float) -> str:
    return "nan" if pd.isna(x) else f"{x:.3f}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run walk-forward gate v1.")
    parser.add_argument("--panel-csv", default="", help=f"default: {PANEL_CSV}")
    parser.add_argument("--out-dir", default="", help=f"default: {OUT_DIR}")
    return parser.parse_args()


def load_raw_panel(panel_csv: str) -> pd.DataFrame:
    if not panel_csv:
        return load_panel_csv()
    raw = pd.read_csv(panel_csv, dtype={"cb_code": str, "stk_code": str, "trade_date": str})
    raw["trade_date"] = pd.to_datetime(raw["trade_date"], format="%Y%m%d")
    for col in ("is_tradable_day", "in_delisting_period"):
        if raw[col].dtype == object:
            raw[col] = raw[col].str.lower() == "true"
        else:
            raw[col] = raw[col].astype(bool)
    return raw


def prepare_base(panel_csv: str) -> tuple[pd.DataFrame, StrategyParams]:
    params = StrategyParams(
        top_n=TOP_N,
        min_issue_size=MAIN_ISSUE_SIZE,
        cb_close_min=80.0,
        cb_close_max=None,
        min_days_to_maturity=180,
        redeem_notice_csv=None,
    )
    raw = load_raw_panel(panel_csv)
    issue_sizes = load_issue_size_series()
    maturity_dates = load_maturity_date_series()
    df, _ = build_universes(raw, issue_sizes, params, maturity_dates)
    df = df.sort_values(["cb_code", "trade_date"]).copy()
    df["ret"] = df.groupby("cb_code")["cb_close"].pct_change()
    if "cb_open" in df.columns:
        open_px = pd.to_numeric(df["cb_open"], errors="coerce")
        close_px = pd.to_numeric(df["cb_close"], errors="coerce")
        df["ret_entry"] = close_px / open_px - 1.0
    else:
        df["ret_entry"] = df["ret"]
    mom_col = "stock_close_adj" if "stock_close_adj" in df.columns else "stock_close"
    df["mom_20d"] = df.groupby("stk_code")[mom_col].pct_change(20)
    df["score"] = score_rank_mom20(df)
    return df, params


def score_rank_mom20(df: pd.DataFrame) -> pd.Series:
    rank_price = df.groupby("trade_date")["cb_close"].rank(pct=True, ascending=True)
    rank_premium = df.groupby("trade_date")["conversion_premium"].rank(pct=True, ascending=True)
    rank_mom = df.groupby("trade_date")["mom_20d"].rank(pct=True, ascending=False)
    return rank_price + rank_premium + rank_mom


def portfolio_returns(
    base: pd.DataFrame,
    params: StrategyParams,
    keep_n: int | None,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    d = base.loc[base["score"].notna()].copy()
    port, bench, turnover, _n = build_positions(
        d,
        base,
        params.top_n,
        cost_one_way_bp=COST_BP_SIDE,
        keep_n=keep_n,
    )
    return port, bench, turnover_by_execution_date(d, params.top_n, keep_n)


def turnover_by_execution_date(df: pd.DataFrame, top_n: int, keep_n: int | None) -> pd.Series:
    """Weekly replacement ratio indexed by simulated execution date (signal + 2)."""
    dates = np.sort(df["trade_date"].unique())
    d2i = {d: i for i, d in enumerate(dates)}
    rbals = _week_end_dates(dates)

    sel = {}
    prev: set[str] = set()
    for rd in rbals:
        snap = df.loc[df["trade_date"] == rd]
        top = _pick_week_holdings(snap, prev, top_n, keep_n)
        if top:
            sel[rd] = top
            prev = set(top)

    rows = []
    rb = sorted(sel)
    for i in range(1, len(rb)):
        si = d2i[rb[i]] + 2
        if si >= len(dates):
            continue
        old, new = set(sel[rb[i - 1]]), set(sel[rb[i]])
        rows.append((pd.Timestamp(dates[si]), len(new - old) / max(len(new), 1)))
    if not rows:
        return pd.Series(dtype=float)
    out = pd.DataFrame(rows, columns=["trade_date", "turnover"])
    return out.groupby("trade_date")["turnover"].mean().sort_index()


def segment_turnover(turnovers: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> tuple[float, int]:
    if turnovers.empty:
        return 0.0, 0
    part = turnovers.loc[(turnovers.index >= start) & (turnovers.index <= end)]
    if part.empty:
        return 0.0, 0
    return float(part.mean()), int(len(part))


def excess_sharpe(port: pd.Series, bench: pd.Series) -> float:
    common = port.index.intersection(bench.index)
    if len(common) < 20:
        return np.nan
    ex = port.loc[common] - bench.loc[common]
    vol = ex.std() * np.sqrt(252)
    return float(ex.mean() * 252 / vol) if vol > 0 else np.nan


def planned_segments(data_end: pd.Timestamp) -> pd.DataFrame:
    rows = []
    for oos_year in range(WF_FIRST_OOS_YEAR, data_end.year + 1):
        is_start = pd.Timestamp(year=oos_year - WF_IS_YEARS, month=1, day=1)
        is_end = pd.Timestamp(year=oos_year - 1, month=12, day=31)
        oos_start = pd.Timestamp(year=oos_year, month=1, day=1)
        oos_end = pd.Timestamp(year=oos_year, month=12, day=31)
        if oos_year == data_end.year:
            oos_end = min(oos_end, data_end)
        rows.append(
            {
                "segment": str(oos_year),
                "is_start": is_start,
                "is_end": is_end,
                "oos_start": oos_start,
                "oos_end": oos_end,
            }
        )
    return pd.DataFrame(rows)


def count_days_between(index: pd.DatetimeIndex, start: pd.Timestamp, end: pd.Timestamp) -> int:
    return int(((index >= start) & (index <= end)).sum())


def attach_segment_coverage(segments: pd.DataFrame, ret_index: pd.DatetimeIndex) -> pd.DataFrame:
    out = segments.copy()
    out["is_days"] = [count_days_between(ret_index, r.is_start, r.is_end) for r in out.itertuples()]
    out["oos_days"] = [count_days_between(ret_index, r.oos_start, r.oos_end) for r in out.itertuples()]
    out["eligible"] = (out["is_days"] >= MIN_IS_DAYS) & (out["oos_days"] >= MIN_OOS_DAYS)
    out["status"] = np.where(out["eligible"], "eligible", "insufficient_data")
    return out


def segment_metrics(
    name: str,
    returns: pd.Series,
    bench: pd.Series,
    turnovers: pd.Series,
    segments: pd.DataFrame,
    params: StrategyParams,
) -> pd.DataFrame:
    rows = []
    for r in segments.itertuples():
        part = returns.loc[(returns.index >= r.oos_start) & (returns.index <= r.oos_end)]
        b = bench.loc[(bench.index >= r.oos_start) & (bench.index <= r.oos_end)]
        turnover, turnover_n = segment_turnover(turnovers, r.oos_start, r.oos_end)
        rec = metric_record(name, r.segment, part, params, turnover, turnover_n)
        bm = calc_metrics(b, params.rf_annual)
        rec.update(
            {
                "is_days": int(r.is_days),
                "oos_days": int(r.oos_days),
                "eligible": bool(r.eligible),
                "status": r.status,
                "bench_CAGR": bm["CAGR"],
                "bench_Sharpe": bm["Sharpe"],
                "bench_MDD": bm["MDD"],
                "excess_CAGR": rec["CAGR"] - bm["CAGR"],
                "excess_Sharpe": excess_sharpe(part, b),
            }
        )
        rows.append(rec)
    return pd.DataFrame(rows)


def metric_record(
    name: str,
    segment: str,
    returns: pd.Series,
    params: StrategyParams,
    turnover: float,
    turnover_n: int,
) -> dict:
    m = calc_metrics(returns, params.rf_annual)
    return {
        "variant": name,
        "segment": segment,
        "n_days": len(returns),
        "CAGR": m["CAGR"],
        "Vol": m["Vol"],
        "Sharpe": m["Sharpe"],
        "MDD": m["MDD"],
        "Calmar": m["Calmar"],
        "WinW": m["WinW"],
        "turnover_weekly": turnover,
        "turnover_rebalances": turnover_n,
    }


def evaluate_gate_a(main: pd.DataFrame, th: GateThresholds) -> pd.DataFrame:
    rows = []
    for r in main.itertuples():
        broken = gate_a_broken_items(r, th)
        action = gate_a_action(r, broken, th)
        rows.append(
            {
                "segment": r.segment,
                "broken_items": ",".join(broken),
                "gate_a_action": action,
                "gate_a_pass": action != "fail",
                "mdd_vs_bench_pp": r.MDD - r.bench_MDD,
            }
        )
    return pd.DataFrame(rows)


def gate_a_broken_items(row, th: GateThresholds) -> list[str]:
    out = []
    if row.Sharpe < th.min_seg_sharpe:
        out.append("Sharpe")
    if row.CAGR < th.min_seg_cagr:
        out.append("CAGR")
    if row.MDD < th.min_seg_mdd:
        out.append("MDD")
    return out


def gate_a_action(row, broken: list[str], th: GateThresholds) -> str:
    if len(broken) == 0:
        return "pass"
    if len(broken) == 3:
        return "fail"
    if broken == ["MDD"]:
        if (row.MDD - row.bench_MDD) < th.max_mdd_underperform_pp:
            return "fail"
        return "conditional_pass"
    if "MDD" in broken and (row.MDD - row.bench_MDD) < th.max_mdd_underperform_pp:
        return "fail"
    return "warning_pass"


def summarize_gate_b(main: pd.DataFrame, th: GateThresholds) -> pd.DataFrame:
    d = main.loc[main["eligible"]].copy()
    rows = []
    rows.append(gate_row("B_share_sharpe_gt0", (d["Sharpe"] > 0).mean(), th.share_sharpe_pos, ">="))
    rows.append(gate_row("B_share_sharpe_ge_0_3", (d["Sharpe"] >= 0.3).mean(), th.share_sharpe_ge_03, ">="))
    rows.append(gate_row("B_median_sharpe", d["Sharpe"].median(), th.median_sharpe, ">="))
    rows.append(gate_row("B_median_excess_sharpe", d["excess_Sharpe"].median(), th.median_excess_sharpe, ">"))
    return pd.DataFrame(rows)


def summarize_gate_c(metrics: pd.DataFrame, th: GateThresholds) -> pd.DataFrame:
    d = metrics.loc[metrics["eligible"] & metrics["variant"].isin(["vanilla", "keep29"])].copy()
    p = d.pivot(index="segment", columns="variant", values=["Sharpe", "MDD", "turnover_weekly"])
    share_sharpe = (p[("Sharpe", "keep29")] >= p[("Sharpe", "vanilla")]).mean()
    share_turn = (p[("turnover_weekly", "keep29")] < p[("turnover_weekly", "vanilla")] * 0.8).mean()
    mdd_ok_value = abs(p[("MDD", "keep29")].median()) <= abs(p[("MDD", "vanilla")].median())
    rows = [
        gate_row("C_share_keep29_sharpe_ge_vanilla", share_sharpe, th.share_keep29_sharpe_ge_vanilla, ">="),
        gate_row("C_share_keep29_turnover_lt_80pct", share_turn, th.share_keep29_turnover_lt_80pct, ">="),
        {"gate": "C_keep29_median_abs_mdd_le_vanilla", "value": bool(mdd_ok_value), "threshold": True, "op": "==", "pass": bool(mdd_ok_value)},
    ]
    return pd.DataFrame(rows)


def gate_row(name: str, value: float, threshold: float, op: str) -> dict:
    ok = value >= threshold if op == ">=" else value > threshold
    return {"gate": name, "value": value, "threshold": threshold, "op": op, "pass": bool(ok)}


def overall_gate_summary(metrics: pd.DataFrame, gate_a: pd.DataFrame, th: GateThresholds) -> pd.DataFrame:
    main = metrics.loc[(metrics["variant"] == "keep29") & metrics["eligible"]].copy()
    b = summarize_gate_b(main, th)
    c = summarize_gate_c(metrics, th)
    a_ok = bool(gate_a.loc[gate_a["segment"].isin(main["segment"]), "gate_a_pass"].all()) if len(main) else False
    data_ready = int(len(main)) >= MIN_READY_SEGMENTS
    rows = [{"gate": "DATA_READY_eligible_segments", "value": int(len(main)), "threshold": MIN_READY_SEGMENTS, "op": ">=", "pass": data_ready}]
    rows.append({"gate": "A_all_eligible_segments_survive", "value": a_ok, "threshold": True, "op": "==", "pass": a_ok})
    return pd.concat([pd.DataFrame(rows), b, c], ignore_index=True)


def plot_segment_dashboard(metrics: pd.DataFrame, out_path: Path) -> None:
    if skip_plot_if_needed(out_path):
        return
    d = metrics.loc[metrics["variant"].isin(["vanilla", "keep29"])].copy()
    segs = sorted(d["segment"].unique())
    x = np.arange(len(segs))
    fig, axes = plt.subplots(2, 2, figsize=(13, 8))
    plot_bars(axes[0, 0], d, segs, "Sharpe", "OOS net Sharpe")
    plot_bars(axes[0, 1], d, segs, "CAGR", "OOS net CAGR", pct_axis=True)
    plot_bars(axes[1, 0], d, segs, "MDD", "OOS MDD", pct_axis=True)
    plot_bars(axes[1, 1], d, segs, "excess_Sharpe", "OOS excess Sharpe vs bench")
    for ax in axes.ravel():
        ax.set_xticks(x)
        ax.set_xticklabels(segs, rotation=0)
        ax.grid(True, axis="y", alpha=0.25)
    fig.suptitle("Walk-forward gate dashboard", fontsize=13, weight="bold")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_bars(ax, data: pd.DataFrame, segs: list[str], col: str, title: str, pct_axis: bool = False) -> None:
    width = 0.36
    for i, name in enumerate(["vanilla", "keep29"]):
        vals = data.loc[data["variant"] == name].set_index("segment").reindex(segs)[col]
        shown = vals * 100 if pct_axis else vals
        ax.bar(np.arange(len(segs)) + (i - 0.5) * width, shown, width=width, label=name)
    ax.axhline(0, color="black", lw=0.7)
    ax.set_title(title)
    ax.legend(fontsize=8)
    if pct_axis:
        ax.set_ylabel("%")


def plot_keep_heatmap(metrics: pd.DataFrame, out_path: Path) -> None:
    if skip_plot_if_needed(out_path):
        return
    d = metrics.loc[metrics["variant"].str.startswith("keep")].copy()
    d["keep_n"] = d["variant"].str.replace("keep", "", regex=False).astype(int)
    p = d.pivot(index="keep_n", columns="segment", values="Sharpe").sort_index()
    fig, ax = plt.subplots(figsize=(10, 4.8))
    im = ax.imshow(p.values, aspect="auto", cmap="RdYlGn", vmin=-1.0, vmax=1.5)
    ax.set_xticks(np.arange(len(p.columns)))
    ax.set_xticklabels(p.columns)
    ax.set_yticks(np.arange(len(p.index)))
    ax.set_yticklabels(p.index)
    ax.set_xlabel("OOS segment")
    ax.set_ylabel("keep_n")
    ax.set_title("keep_n sensitivity: OOS net Sharpe")
    for i in range(p.shape[0]):
        for j in range(p.shape[1]):
            ax.text(j, i, fmt(p.iloc[i, j]), ha="center", va="center", fontsize=8)
    fig.colorbar(im, ax=ax, label="Sharpe")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_nav(nav: pd.DataFrame, out_path: Path) -> None:
    if skip_plot_if_needed(out_path):
        return
    fig, ax = plt.subplots(figsize=(11, 5))
    for col in nav.columns:
        ax.plot(nav.index, nav[col], label=col, lw=1.6)
    ax.set_title("Full available sample NAV")
    ax.set_ylabel("NAV")
    ax.grid(True, alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def skip_plot_if_needed(out_path: Path) -> bool:
    if HAS_MATPLOTLIB:
        return False
    marker = out_path.with_suffix(out_path.suffix + ".skipped.txt")
    marker.write_text("Skipped plot: matplotlib is not installed in this Python environment.\n", encoding="utf-8")
    return True


def cb_call_raw_coverage() -> pd.DataFrame:
    path = ROOT / "data" / "cb_call_raw.csv"
    if not path.exists():
        return pd.DataFrame(columns=["year", "rows", "bonds"])
    raw = pd.read_csv(path, dtype=str, low_memory=False)
    if raw.empty or "ann_date" not in raw.columns:
        return pd.DataFrame(columns=["year", "rows", "bonds"])
    out = raw.assign(year=raw["ann_date"].str[:4]).groupby("year")["ts_code"].agg(["count", "nunique"])
    return out.rename(columns={"count": "rows", "nunique": "bonds"}).reset_index()


def redeem_notice_pit_coverage() -> pd.DataFrame:
    path = ROOT / "data" / "cb_redeem_notice_pit.csv"
    if not path.exists():
        return pd.DataFrame(columns=["year", "rows", "bonds"])
    raw = pd.read_csv(path, dtype=str, low_memory=False)
    if raw.empty or not {"cb_code", "notice_date"}.issubset(raw.columns):
        return pd.DataFrame(columns=["year", "rows", "bonds"])
    notice_date = pd.to_datetime(raw["notice_date"], errors="coerce")
    d = raw.loc[notice_date.notna()].copy()
    if d.empty:
        return pd.DataFrame(columns=["year", "rows", "bonds"])
    d["year"] = notice_date.loc[notice_date.notna()].dt.year.astype(str)
    out = d.groupby("year")["cb_code"].agg(["count", "nunique"])
    return out.rename(columns={"count": "rows", "nunique": "bonds"}).reset_index()


def write_summary(
    cb_call_coverage: pd.DataFrame,
    pit_coverage: pd.DataFrame,
    metrics: pd.DataFrame,
    gate: pd.DataFrame,
    gate_a: pd.DataFrame,
    path: Path,
) -> None:
    main = metrics.loc[(metrics["variant"] == "keep29") & metrics["eligible"]].copy()
    lines = ["# Walk-forward gate v1 summary", ""]
    lines.extend(summary_context(cb_call_coverage, pit_coverage, main))
    lines.extend(["", "## Gate Result"])
    for _, r in gate.iterrows():
        lines.append(f"- {r['gate']}: value={r['value']} {r['op']} {r['threshold']} -> {'PASS' if r['pass'] else 'FAIL'}")
    lines.extend(["", "## Gate A Segment Actions"])
    for _, r in gate_a.iterrows():
        lines.append(f"- {r['segment']}: {r['gate_a_action']} (broken={r['broken_items'] or 'none'})")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def summary_context(cb_call_coverage: pd.DataFrame, pit_coverage: pd.DataFrame, main: pd.DataFrame) -> list[str]:
    lines = [
        "Fixed setup:",
        f"- rolling window: 3y IS / 1y OOS / 1y step, first OOS={WF_FIRST_OOS_YEAR}",
        f"- strategy: C_rank_mom20, top_n={TOP_N}, keep_n={KEEP_MAIN}, cost={COST_BP_SIDE:g} bp/side",
        f"- eligible segment rule: IS days >= {MIN_IS_DAYS}, OOS days >= {MIN_OOS_DAYS}",
        f"- eligible segments currently found: {len(main)}",
    ]
    if not cb_call_coverage.empty:
        lines.append(
            "- current cb_call_raw year coverage: "
            + ", ".join(f"{r.year}:{int(r.rows)}" for r in cb_call_coverage.itertuples())
        )
    if not pit_coverage.empty:
        lines.append(
            "- current cb_redeem_notice_pit year coverage: "
            + ", ".join(f"{r.year}:{int(r.rows)}" for r in pit_coverage.itertuples())
        )
    if not HAS_MATPLOTLIB:
        lines.append("- plots skipped: matplotlib is not installed in this Python environment")
    return lines


def save_run_config(path: Path) -> None:
    payload = {
        "top_n": TOP_N,
        "keep_main": KEEP_MAIN,
        "keep_sensitivity": KEEP_SENSITIVITY,
        "cost_bp_side": COST_BP_SIDE,
        "issue_size": MAIN_ISSUE_SIZE,
        "window": {"is_years": WF_IS_YEARS, "oos_years": 1, "step_years": 1},
        "gate_thresholds": GateThresholds().__dict__,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    args = parse_args()
    out_dir = Path(args.out_dir) if args.out_dir else OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    th = GateThresholds()
    base, params = prepare_base(args.panel_csv)
    data_end = pd.Timestamp(base["trade_date"].max())

    variants = {"vanilla": None, "keep29": KEEP_MAIN}
    variants.update({f"keep{k}": k for k in KEEP_SENSITIVITY if k != KEEP_MAIN})
    returns, bench, turnovers = {}, None, {}
    for name, keep_n in variants.items():
        port, b, turnover = portfolio_returns(base, params, keep_n)
        returns[name] = port
        turnovers[name] = turnover
        bench = b if bench is None else bench

    segments = attach_segment_coverage(planned_segments(data_end), pd.DatetimeIndex(bench.index))
    all_metrics = []
    for name, port in returns.items():
        all_metrics.append(segment_metrics(name, port, bench, turnovers[name], segments, params))
    metrics = pd.concat(all_metrics, ignore_index=True)

    main_metrics = metrics.loc[(metrics["variant"] == "keep29") & metrics["eligible"]].copy()
    gate_a = evaluate_gate_a(main_metrics, th) if len(main_metrics) else pd.DataFrame(columns=["segment", "gate_a_pass", "gate_a_action", "broken_items"])
    gate = overall_gate_summary(metrics, gate_a, th)
    cb_call_coverage = cb_call_raw_coverage()
    pit_coverage = redeem_notice_pit_coverage()

    nav = pd.DataFrame({name: (1.0 + ret).cumprod() for name, ret in returns.items() if name in ("vanilla", "keep29")})
    nav["bench"] = (1.0 + bench).cumprod()

    segments.to_csv(out_dir / "segment_coverage.csv", index=False, encoding="utf-8-sig")
    metrics.to_csv(out_dir / "segment_metrics.csv", index=False, encoding="utf-8-sig")
    gate_a.to_csv(out_dir / "gate_a_segment_actions.csv", index=False, encoding="utf-8-sig")
    gate.to_csv(out_dir / "gate_summary.csv", index=False, encoding="utf-8-sig")
    cb_call_coverage.to_csv(out_dir / "redeem_call_year_coverage.csv", index=False, encoding="utf-8-sig")
    cb_call_coverage.to_csv(out_dir / "cb_call_raw_year_coverage.csv", index=False, encoding="utf-8-sig")
    pit_coverage.to_csv(out_dir / "redeem_notice_pit_year_coverage.csv", index=False, encoding="utf-8-sig")
    nav.to_csv(out_dir / "nav_full_available_sample.csv", encoding="utf-8-sig")
    save_run_config(out_dir / "run_config.json")
    write_summary(cb_call_coverage, pit_coverage, metrics, gate, gate_a, out_dir / "summary.md")

    plot_segment_dashboard(metrics, out_dir / "wf_gate_dashboard.png")
    plot_keep_heatmap(metrics, out_dir / "keepn_sharpe_heatmap.png")
    plot_nav(nav, out_dir / "nav_full_available_sample.png")
    print(f"wrote outputs to {out_dir}")


if __name__ == "__main__":
    main()
