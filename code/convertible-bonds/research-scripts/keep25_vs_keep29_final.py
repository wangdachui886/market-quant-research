"""Final keep25 vs keep29 comparison.

This script does not search for new parameters. It compares the two candidate
execution buffers under:
- yearly OOS segments
- cost stress grid
- scenarios that remove strong tailwind years

Outputs are split into tables, daily, charts, and report folders.
"""

from __future__ import annotations

import html
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from keep_n_decomposition import (
    RF_ANNUAL,
    build_weekly_holdings,
    attach_returns_and_meta,
    cagr,
    font,
    fmt_pct,
    mdd,
    prepare_base,
    sharpe,
    variant_name,
)

OUT_ROOT = ROOT / "GPT-test" / "output" / "walk_forward_gate_v1" / "keep25_vs_keep29_final"
TABLE_DIR = OUT_ROOT / "tables"
DAILY_DIR = OUT_ROOT / "daily"
CHART_DIR = OUT_ROOT / "charts"
REPORT_DIR = OUT_ROOT / "report"

VARIANTS: tuple[int | None, ...] = (None, 25, 29)
COST_GRID = (0.0, 5.0, 10.0, 15.0, 20.0, 25.0)
MAIN_COST = 15.0
OOS_SEGMENTS = {
    str(year): (pd.Timestamp(year=year, month=1, day=1), pd.Timestamp(year=year, month=12, day=31))
    for year in range(2021, 2026)
}
SCENARIOS = {
    "all_2021_2025": ["2021", "2022", "2023", "2024", "2025"],
    "ex_2025": ["2021", "2022", "2023", "2024"],
    "ex_2024_2025": ["2021", "2022", "2023"],
    "weak_2022_2023": ["2022", "2023"],
}


def ensure_dirs() -> None:
    for d in (TABLE_DIR, DAILY_DIR, CHART_DIR, REPORT_DIR):
        d.mkdir(parents=True, exist_ok=True)


def daily_pnl_at_cost(h: pd.DataFrame, cost_rows: pd.DataFrame, cost_bp: float) -> pd.DataFrame:
    gross = h.groupby("trade_date")["gross_contrib"].sum().rename("gross")
    cost = pd.Series(0.0, index=gross.index, name="cost")
    turnover = pd.Series(0.0, index=gross.index, name="turnover")
    if not cost_rows.empty:
        turns = cost_rows.set_index("trade_date")["turnover"]
        idx = turns.index.intersection(gross.index)
        turnover.loc[idx] = turns.loc[idx]
        cost.loc[idx] = -2.0 * turns.loc[idx] * cost_bp / 1e4
    net = (gross + cost).rename("net")
    return pd.concat([gross, cost, net, turnover], axis=1).reset_index()


def segment_record(daily: pd.DataFrame, variant: str, keep_n: int, cost_bp: float, segment: str, start: pd.Timestamp, end: pd.Timestamp) -> dict:
    d = daily.loc[(daily["trade_date"] >= start) & (daily["trade_date"] <= end)].copy()
    turnover_days = d.loc[d["turnover"] > 0, "turnover"]
    return {
        "variant": variant,
        "keep_n": keep_n,
        "cost_bp": cost_bp,
        "segment": segment,
        "n_days": int(len(d)),
        "gross_CAGR": cagr(d["gross"]),
        "cost_drag_ann": float(d["cost"].sum() * 252 / len(d)) if len(d) else np.nan,
        "net_CAGR": cagr(d["net"]),
        "net_Sharpe": sharpe(d["net"]),
        "net_MDD": mdd(d["net"]),
        "weekly_turnover": float(turnover_days.mean()) if len(turnover_days) else 0.0,
        "turnover_rebalances": int(len(turnover_days)),
    }


def add_deltas(metrics: pd.DataFrame) -> pd.DataFrame:
    out = metrics.copy()
    vanilla = out.loc[out["variant"] == "vanilla"].set_index(["cost_bp", "segment"])
    for idx, row in out.iterrows():
        b = vanilla.loc[(row["cost_bp"], row["segment"])]
        out.loc[idx, "gross_delta_vs_vanilla"] = row["gross_CAGR"] - b["gross_CAGR"]
        out.loc[idx, "cost_save_vs_vanilla"] = row["cost_drag_ann"] - b["cost_drag_ann"]
        out.loc[idx, "net_delta_vs_vanilla"] = row["net_CAGR"] - b["net_CAGR"]
        out.loc[idx, "mdd_delta_vs_vanilla"] = row["net_MDD"] - b["net_MDD"]
        out.loc[idx, "turnover_ratio_vs_vanilla"] = row["weekly_turnover"] / b["weekly_turnover"] if b["weekly_turnover"] else np.nan
    return out


def direct_25_minus_29(metrics: pd.DataFrame) -> pd.DataFrame:
    rows = []
    keys = ["cost_bp", "segment"]
    k25 = metrics.loc[metrics["variant"] == "keep25"].set_index(keys)
    k29 = metrics.loc[metrics["variant"] == "keep29"].set_index(keys)
    common = k25.index.intersection(k29.index)
    for key in common:
        a = k25.loc[key]
        b = k29.loc[key]
        rows.append(
            {
                "cost_bp": key[0],
                "segment": key[1],
                "gross_CAGR_delta_25_minus_29": a["gross_CAGR"] - b["gross_CAGR"],
                "cost_drag_delta_25_minus_29": a["cost_drag_ann"] - b["cost_drag_ann"],
                "net_CAGR_delta_25_minus_29": a["net_CAGR"] - b["net_CAGR"],
                "net_Sharpe_delta_25_minus_29": a["net_Sharpe"] - b["net_Sharpe"],
                "net_MDD_delta_25_minus_29": a["net_MDD"] - b["net_MDD"],
                "turnover_delta_25_minus_29": a["weekly_turnover"] - b["weekly_turnover"],
            }
        )
    return pd.DataFrame(rows).sort_values(["cost_bp", "segment"]).reset_index(drop=True)


def scenario_summary(metrics: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for scenario, segments in SCENARIOS.items():
        for cost_bp in COST_GRID:
            d = metrics.loc[(metrics["cost_bp"] == cost_bp) & (metrics["segment"].isin(segments))]
            pair = d.loc[d["variant"].isin(["keep25", "keep29"])]
            for variant, g in pair.groupby("variant", sort=False):
                other = "keep29" if variant == "keep25" else "keep25"
                other_g = pair.loc[pair["variant"] == other].set_index("segment")
                wins = []
                for r in g.itertuples():
                    wins.append(float(r.net_CAGR > other_g.loc[r.segment, "net_CAGR"]))
                rows.append(
                    {
                        "scenario": scenario,
                        "cost_bp": cost_bp,
                        "variant": variant,
                        "segments": ",".join(segments),
                        "median_net_CAGR": g["net_CAGR"].median(),
                        "worst_net_CAGR": g["net_CAGR"].min(),
                        "median_net_Sharpe": g["net_Sharpe"].median(),
                        "median_net_delta_vs_vanilla": g["net_delta_vs_vanilla"].median(),
                        "share_net_delta_gt_vanilla": (g["net_delta_vs_vanilla"] > 0).mean(),
                        "median_turnover": g["weekly_turnover"].median(),
                        "win_share_vs_other": float(np.mean(wins)) if wins else np.nan,
                    }
                )
    return pd.DataFrame(rows)


def draw_text(draw, xy: tuple[float, float], text: str, size: int = 12, fill: str = "#111827") -> None:
    draw.text(xy, text, fill=fill, font=font(size))


def save_grouped_bar(
    data: pd.DataFrame,
    x_col: str,
    y_cols: list[tuple[str, str, str]],
    title: str,
    ylabel: str,
    out_path: Path,
) -> None:
    from PIL import Image, ImageDraw

    width, height = 980, 460
    left, right, top, bottom = 78, 28, 58, 68
    plot_w, plot_h = width - left - right, height - top - bottom
    values = data[[c for c, _label, _color in y_cols]].to_numpy(dtype=float)
    max_abs = max(float(np.nanmax(np.abs(values))), 0.01)
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (16, 18), title, 18)
    y0 = top + plot_h / 2
    for tick in [-max_abs, -max_abs / 2, 0, max_abs / 2, max_abs]:
        y = y0 - tick / max_abs * (plot_h / 2)
        draw.line((left, y, width - right, y), fill="#e5e7eb")
        draw_text(draw, (10, y - 8), fmt_pct(tick, 1), 11, "#6b7280")
    draw.line((left, y0, width - right, y0), fill="#111827")
    draw_text(draw, (16, top - 24), ylabel, 11, "#6b7280")

    group_w = plot_w / len(data)
    bar_w = min(28, group_w / (len(y_cols) + 2))
    for i, row in data.reset_index(drop=True).iterrows():
        cx = left + group_w * (i + 0.5)
        label = str(row[x_col])
        box = draw.textbbox((0, 0), label, font=font(12))
        draw_text(draw, (cx - (box[2] - box[0]) / 2, height - 38), label, 12, "#374151")
        for k, (col, _label, color) in enumerate(y_cols):
            val = float(row[col])
            bh = abs(val) / max_abs * (plot_h / 2)
            x = cx + (k - (len(y_cols) - 1) / 2) * (bar_w + 5) - bar_w / 2
            y = y0 - bh if val >= 0 else y0
            draw.rounded_rectangle((x, y, x + bar_w, y + bh), radius=2, fill=color)

    lx = left
    for _col, label, color in y_cols:
        draw.rectangle((lx, height - 60, lx + 12, height - 48), fill=color)
        draw_text(draw, (lx + 16, height - 62), label, 11, "#374151")
        lx += 112
    img.save(out_path)


def save_line_chart(data: pd.DataFrame, title: str, out_path: Path) -> None:
    from PIL import Image, ImageDraw

    width, height = 900, 440
    left, right, top, bottom = 76, 120, 58, 62
    plot_w, plot_h = width - left - right, height - top - bottom
    variants = ["vanilla", "keep25", "keep29"]
    colors = {"vanilla": "#9ca3af", "keep25": "#2563eb", "keep29": "#16a34a"}
    piv = data.pivot(index="cost_bp", columns="variant", values="median_net_CAGR").sort_index()
    max_abs = max(float(np.nanmax(np.abs(piv[variants].to_numpy()))), 0.01)
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (16, 18), title, 18)
    for tick in [-max_abs, -max_abs / 2, 0, max_abs / 2, max_abs]:
        y = top + plot_h / 2 - tick / max_abs * (plot_h / 2)
        draw.line((left, y, width - right, y), fill="#e5e7eb")
        draw_text(draw, (10, y - 8), fmt_pct(tick, 1), 11, "#6b7280")
    costs = list(piv.index)
    x_pos = {c: left + i * plot_w / (len(costs) - 1) for i, c in enumerate(costs)}
    for c in costs:
        x = x_pos[c]
        draw.line((x, top, x, top + plot_h), fill="#f3f4f6")
        draw_text(draw, (x - 10, height - 36), f"{int(c)}", 11, "#374151")
    draw_text(draw, (left + plot_w / 2 - 28, height - 18), "cost bp/side", 11, "#6b7280")
    for variant in variants:
        pts = []
        for c in costs:
            val = float(piv.loc[c, variant])
            x = x_pos[c]
            y = top + plot_h / 2 - val / max_abs * (plot_h / 2)
            pts.append((x, y))
        draw.line(pts, fill=colors[variant], width=3)
        for x, y in pts:
            draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=colors[variant])
    ly = top + 10
    for variant in variants:
        draw.line((width - right + 22, ly + 7, width - right + 48, ly + 7), fill=colors[variant], width=3)
        draw_text(draw, (width - right + 54, ly), variant, 12, "#374151")
        ly += 24
    img.save(out_path)


def dataframe_to_html_table(df: pd.DataFrame, pct_cols: set[str], n: int | None = None) -> str:
    d = df.head(n).copy() if n is not None else df.copy()
    parts = ["<table>", "<thead><tr>"]
    for col in d.columns:
        parts.append(f"<th>{html.escape(str(col))}</th>")
    parts.append("</tr></thead><tbody>")
    for _, row in d.iterrows():
        parts.append("<tr>")
        for col in d.columns:
            val = row[col]
            if col in pct_cols:
                text = fmt_pct(val)
            elif isinstance(val, (float, np.floating)):
                text = "" if pd.isna(val) else f"{val:.4f}"
            else:
                text = "" if pd.isna(val) else str(val)
            parts.append(f"<td>{html.escape(text)}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table>")
    return "\n".join(parts)


def dataframe_to_md(df: pd.DataFrame, pct_cols: set[str], n: int | None = None) -> str:
    d = df.head(n).copy() if n is not None else df.copy()
    if d.empty:
        return "(empty)"
    lines = ["| " + " | ".join(map(str, d.columns)) + " |", "| " + " | ".join(["---"] * len(d.columns)) + " |"]
    for _, row in d.iterrows():
        vals = []
        for col in d.columns:
            val = row[col]
            if col in pct_cols:
                vals.append(fmt_pct(val))
            elif isinstance(val, (float, np.floating)):
                vals.append("" if pd.isna(val) else f"{val:.6f}")
            else:
                vals.append("" if pd.isna(val) else str(val))
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


def write_reports(metrics15: pd.DataFrame, direct15: pd.DataFrame, scenario15: pd.DataFrame, cost_summary: pd.DataFrame) -> None:
    pct_cols = {
        "gross_CAGR",
        "cost_drag_ann",
        "net_CAGR",
        "net_MDD",
        "weekly_turnover",
        "gross_delta_vs_vanilla",
        "cost_save_vs_vanilla",
        "net_delta_vs_vanilla",
        "mdd_delta_vs_vanilla",
        "turnover_ratio_vs_vanilla",
        "gross_CAGR_delta_25_minus_29",
        "cost_drag_delta_25_minus_29",
        "net_CAGR_delta_25_minus_29",
        "net_MDD_delta_25_minus_29",
        "turnover_delta_25_minus_29",
        "median_net_CAGR",
        "worst_net_CAGR",
        "median_net_delta_vs_vanilla",
        "share_net_delta_gt_vanilla",
        "median_turnover",
        "win_share_vs_other",
    }
    md = [
        "# keep25 vs keep29 final comparison",
        "",
        "Fixed setup: C_rank_mom20, top_n=10, OOS 2021-2025. This is a candidate comparison, not a parameter search.",
        "",
        "## 15bp Segment Metrics",
        dataframe_to_md(metrics15, pct_cols),
        "",
        "## keep25 minus keep29 at 15bp",
        dataframe_to_md(direct15, pct_cols),
        "",
        "## Scenario Summary at 15bp",
        dataframe_to_md(scenario15, pct_cols),
        "",
        "## Cost Sensitivity Summary",
        dataframe_to_md(cost_summary, pct_cols),
        "",
        "Visual report: report/keep25_vs_keep29_report.html",
    ]
    (REPORT_DIR / "keep25_vs_keep29_summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    css = """
    body { font-family: Arial, "Microsoft YaHei", sans-serif; margin: 24px; color: #111827; background: #f9fafb; }
    h1, h2 { margin: 0 0 14px; }
    section { background: white; border: 1px solid #e5e7eb; border-radius: 8px; padding: 18px; margin: 16px 0; }
    table { border-collapse: collapse; width: 100%; font-size: 13px; }
    th, td { border-bottom: 1px solid #e5e7eb; padding: 7px 9px; text-align: right; white-space: nowrap; }
    th:first-child, td:first-child { text-align: left; }
    th { background: #f3f4f6; color: #374151; }
    img { max-width: 100%; height: auto; border: 1px solid #e5e7eb; border-radius: 6px; background: white; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(520px, 1fr)); gap: 16px; }
    .note { color: #4b5563; line-height: 1.5; }
    """
    body = f"""
    <!doctype html><html><head><meta charset="utf-8"><title>keep25 vs keep29</title><style>{css}</style></head>
    <body>
    <h1>keep25 vs keep29 final comparison</h1>
    <p class="note">Fixed strategy, no new parameter search. Main cost stress is 15bp/side.</p>
    <section class="grid">
      <div><img src="../charts/net_cagr_15bp_by_segment.png" alt="net CAGR 15bp"></div>
      <div><img src="../charts/direct_delta_25_minus_29_15bp.png" alt="direct delta"></div>
      <div><img src="../charts/cost_sensitivity_median_net.png" alt="cost sensitivity"></div>
      <div><img src="../charts/scenario_median_delta_15bp.png" alt="scenario summary"></div>
    </section>
    <section><h2>15bp segment metrics</h2>{dataframe_to_html_table(metrics15, pct_cols)}</section>
    <section><h2>keep25 minus keep29 at 15bp</h2>{dataframe_to_html_table(direct15, pct_cols)}</section>
    <section><h2>scenario summary at 15bp</h2>{dataframe_to_html_table(scenario15, pct_cols)}</section>
    <section><h2>cost sensitivity summary</h2>{dataframe_to_html_table(cost_summary, pct_cols)}</section>
    </body></html>
    """
    (REPORT_DIR / "keep25_vs_keep29_report.html").write_text(body, encoding="utf-8")


def main() -> None:
    ensure_dirs()
    base, _ = prepare_base()

    variant_inputs = {}
    for keep_n in VARIANTS:
        name = variant_name(keep_n)
        holdings, cost_rows = build_weekly_holdings(base, keep_n)
        h = attach_returns_and_meta(holdings, base)
        variant_inputs[name] = {"holdings": h, "cost_rows": cost_rows, "keep_n": keep_n if keep_n is not None else 10}
        print(f"built holdings for {name}: {len(h)} holding rows")

    metric_rows = []
    cost_summary_rows = []
    for cost_bp in COST_GRID:
        cost_daily = {}
        for name, obj in variant_inputs.items():
            daily = daily_pnl_at_cost(obj["holdings"], obj["cost_rows"], cost_bp)
            cost_daily[name] = daily
            daily.to_csv(DAILY_DIR / f"daily_pnl_{name}_{int(cost_bp)}bp.csv", index=False, encoding="utf-8-sig")
            for seg, (start, end) in OOS_SEGMENTS.items():
                metric_rows.append(segment_record(daily, name, obj["keep_n"], cost_bp, seg, start, end))
        for name, daily in cost_daily.items():
            parts = []
            for seg, (start, end) in OOS_SEGMENTS.items():
                d = daily.loc[(daily["trade_date"] >= start) & (daily["trade_date"] <= end)]
                parts.append({"segment": seg, "net_CAGR": cagr(d["net"]), "net_Sharpe": sharpe(d["net"])})
            p = pd.DataFrame(parts)
            cost_summary_rows.append(
                {
                    "cost_bp": cost_bp,
                    "variant": name,
                    "median_net_CAGR": p["net_CAGR"].median(),
                    "worst_net_CAGR": p["net_CAGR"].min(),
                    "median_net_Sharpe": p["net_Sharpe"].median(),
                }
            )

    metrics = add_deltas(pd.DataFrame(metric_rows))
    direct = direct_25_minus_29(metrics)
    scenarios = scenario_summary(metrics)
    cost_summary = pd.DataFrame(cost_summary_rows)

    metrics.to_csv(TABLE_DIR / "segment_metrics_all_costs.csv", index=False, encoding="utf-8-sig")
    metrics.loc[metrics["cost_bp"] == MAIN_COST].to_csv(TABLE_DIR / "segment_metrics_15bp.csv", index=False, encoding="utf-8-sig")
    direct.to_csv(TABLE_DIR / "keep25_minus_keep29_all_costs.csv", index=False, encoding="utf-8-sig")
    direct.loc[direct["cost_bp"] == MAIN_COST].to_csv(TABLE_DIR / "keep25_minus_keep29_15bp.csv", index=False, encoding="utf-8-sig")
    scenarios.to_csv(TABLE_DIR / "scenario_summary_all_costs.csv", index=False, encoding="utf-8-sig")
    scenarios.loc[scenarios["cost_bp"] == MAIN_COST].to_csv(TABLE_DIR / "scenario_summary_15bp.csv", index=False, encoding="utf-8-sig")
    cost_summary.to_csv(TABLE_DIR / "cost_sensitivity_summary.csv", index=False, encoding="utf-8-sig")

    metrics15 = metrics.loc[(metrics["cost_bp"] == MAIN_COST) & (metrics["variant"].isin(["vanilla", "keep25", "keep29"]))].copy()
    net_piv = metrics15.pivot(index="segment", columns="variant", values="net_CAGR").reset_index()
    save_grouped_bar(
        net_piv,
        "segment",
        [("vanilla", "vanilla", "#9ca3af"), ("keep25", "keep25", "#2563eb"), ("keep29", "keep29", "#16a34a")],
        "Net CAGR by segment at 15bp",
        "net CAGR",
        CHART_DIR / "net_cagr_15bp_by_segment.png",
    )
    direct15 = direct.loc[direct["cost_bp"] == MAIN_COST].copy()
    save_grouped_bar(
        direct15,
        "segment",
        [
            ("gross_CAGR_delta_25_minus_29", "gross", "#ef4444"),
            ("cost_drag_delta_25_minus_29", "cost", "#6b7280"),
            ("net_CAGR_delta_25_minus_29", "net", "#22c55e"),
        ],
        "keep25 minus keep29 at 15bp",
        "delta",
        CHART_DIR / "direct_delta_25_minus_29_15bp.png",
    )
    save_line_chart(cost_summary, "Median net CAGR by cost stress", CHART_DIR / "cost_sensitivity_median_net.png")
    scenario15 = scenarios.loc[(scenarios["cost_bp"] == MAIN_COST) & (scenarios["variant"].isin(["keep25", "keep29"]))].copy()
    scen_piv = scenario15.pivot(index="scenario", columns="variant", values="median_net_delta_vs_vanilla").reset_index()
    save_grouped_bar(
        scen_piv,
        "scenario",
        [("keep25", "keep25", "#2563eb"), ("keep29", "keep29", "#16a34a")],
        "Scenario median net delta vs vanilla at 15bp",
        "median delta",
        CHART_DIR / "scenario_median_delta_15bp.png",
    )

    write_reports(metrics15, direct15, scenario15, cost_summary)
    print(f"wrote outputs to {OUT_ROOT}")


if __name__ == "__main__":
    main()
