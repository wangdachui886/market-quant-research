"""Realistic cost scan for C_rank_mom20 execution buffers.

The prior gate uses a flat 15bp/side stress. This script separates:
- flat cost grid: 0/5/10/15/20/25 bp per side
- PIT liquidity/size tiered models using trailing 20-day cb_amount and issue_size

Transaction costs are charged on the actual rebalance execution date and on the
actual changed names: sells + buys. No alpha or selection rule is changed.
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
    TOP_N,
    _pick_week_holdings,
    _week_end_dates,
    attach_returns_and_meta,
    cagr,
    font,
    fmt_pct,
    mdd,
    prepare_base,
    sharpe,
    variant_name,
)

OUT_ROOT = ROOT / "GPT-test" / "output" / "walk_forward_gate_v1" / "real_cost_scan"
TABLE_DIR = OUT_ROOT / "tables"
DAILY_DIR = OUT_ROOT / "daily"
CHART_DIR = OUT_ROOT / "charts"
REPORT_DIR = OUT_ROOT / "report"

VARIANTS: tuple[int | None, ...] = (None, 25, 29)
FLAT_COSTS = (0.0, 5.0, 10.0, 15.0, 20.0, 25.0)
TIER_MODELS = ("tier_base", "tier_stress")
ALL_MODELS = tuple(f"flat_{int(x)}bp" for x in FLAT_COSTS) + TIER_MODELS
MODEL_ORDER = list(ALL_MODELS)
OOS_SEGMENTS = {
    str(year): (pd.Timestamp(year=year, month=1, day=1), pd.Timestamp(year=year, month=12, day=31))
    for year in range(2021, 2026)
}


def ensure_dirs() -> None:
    for d in (TABLE_DIR, DAILY_DIR, CHART_DIR, REPORT_DIR):
        d.mkdir(parents=True, exist_ok=True)


def enrich_cost_inputs(base: pd.DataFrame) -> pd.DataFrame:
    out = base.sort_values(["cb_code", "trade_date"]).copy()
    out["cb_amount"] = pd.to_numeric(out.get("cb_amount"), errors="coerce")
    out["adv20_amount"] = out.groupby("cb_code")["cb_amount"].transform(
        lambda s: s.rolling(20, min_periods=5).mean().shift(1)
    )
    return out


def build_holdings_and_events(df: pd.DataFrame, keep_n: int | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = np.sort(df["trade_date"].unique())
    d2i = {d: i for i, d in enumerate(dates)}
    rbals = _week_end_dates(dates)

    sel: dict[pd.Timestamp, list[str]] = {}
    prev: set[str] = set()
    for rd in rbals:
        snap = df.loc[df["trade_date"] == rd]
        top = _pick_week_holdings(snap, prev, TOP_N, keep_n=keep_n)
        if top:
            sel[rd] = top
            prev = set(top)

    holdings_rows = []
    event_rows = []
    rb = sorted(sel)
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
        buys = sorted(new - old)
        sells = sorted(old - new)
        for code in sel[rd]:
            is_new = code in buys
            for j in range(si, ei + 1):
                holdings_rows.append(
                    {
                        "signal_date": pd.Timestamp(rd),
                        "trade_date": pd.Timestamp(dates[j]),
                        "cb_code": code,
                        "is_entry": (j == si) and is_new,
                    }
                )
        if i >= 1 and (buys or sells):
            event_rows.append(
                {
                    "signal_date": pd.Timestamp(rd),
                    "trade_date": pd.Timestamp(dates[si]),
                    "buy_codes": ",".join(buys),
                    "sell_codes": ",".join(sells),
                    "buy_count": len(buys),
                    "sell_count": len(sells),
                    "turnover": len(buys) / TOP_N,
                }
            )
    return pd.DataFrame(holdings_rows), pd.DataFrame(event_rows)


def tier_bp(rows: pd.DataFrame, model: str) -> pd.Series:
    adv = pd.to_numeric(rows["adv20_amount"], errors="coerce")
    size = pd.to_numeric(rows["issue_size"], errors="coerce")
    if model == "tier_base":
        out = pd.Series(25.0, index=rows.index)
        out.loc[(size >= 1.5e9) & (adv >= 3000)] = 5.0
        out.loc[(out == 25.0) & (size >= 8e8) & (adv >= 1000)] = 10.0
        out.loc[(out == 25.0) & (size >= 5e8) & (adv >= 300)] = 15.0
        return out
    if model == "tier_stress":
        out = pd.Series(35.0, index=rows.index)
        out.loc[(size >= 1.5e9) & (adv >= 3000)] = 8.0
        out.loc[(out == 35.0) & (size >= 8e8) & (adv >= 1000)] = 15.0
        out.loc[(out == 35.0) & (size >= 5e8) & (adv >= 300)] = 22.0
        return out
    if model.startswith("flat_"):
        bp = float(model.replace("flat_", "").replace("bp", ""))
        return pd.Series(bp, index=rows.index)
    raise ValueError(f"unknown cost model: {model}")


def cost_for_codes(cost_table: pd.DataFrame, trade_date: pd.Timestamp, codes: list[str], model: str) -> pd.Series:
    if not codes:
        return pd.Series(dtype=float)
    idx = pd.MultiIndex.from_product([[trade_date], codes], names=["trade_date", "cb_code"])
    rows = cost_table.reindex(idx).reset_index()
    bp = tier_bp(rows, model)
    return bp.fillna(35.0)


def event_costs(events: pd.DataFrame, cost_table: pd.DataFrame, model: str) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame(columns=["trade_date", "cost_pct", "turnover", "avg_buy_bp", "avg_sell_bp", "model"])
    rows = []
    for ev in events.itertuples():
        buys = [x for x in str(ev.buy_codes).split(",") if x]
        sells = [x for x in str(ev.sell_codes).split(",") if x]
        buy_bp = cost_for_codes(cost_table, ev.trade_date, buys, model)
        sell_bp = cost_for_codes(cost_table, ev.trade_date, sells, model)
        total_bp_weighted = buy_bp.sum() + sell_bp.sum()
        rows.append(
            {
                "signal_date": ev.signal_date,
                "trade_date": ev.trade_date,
                "buy_count": ev.buy_count,
                "sell_count": ev.sell_count,
                "turnover": ev.turnover,
                "avg_buy_bp": float(buy_bp.mean()) if len(buy_bp) else 0.0,
                "avg_sell_bp": float(sell_bp.mean()) if len(sell_bp) else 0.0,
                "cost_pct": float(total_bp_weighted / TOP_N / 1e4),
                "model": model,
            }
        )
    return pd.DataFrame(rows)


def daily_pnl(h: pd.DataFrame, costs: pd.DataFrame) -> pd.DataFrame:
    gross = h.groupby("trade_date")["gross_contrib"].sum().rename("gross")
    cost = pd.Series(0.0, index=gross.index, name="cost")
    turnover = pd.Series(0.0, index=gross.index, name="turnover")
    avg_bp = pd.Series(0.0, index=gross.index, name="avg_event_bp")
    if not costs.empty:
        c = costs.groupby("trade_date").agg(
            cost_pct=("cost_pct", "sum"),
            turnover=("turnover", "sum"),
            avg_event_bp=("avg_buy_bp", "mean"),
        )
        idx = c.index.intersection(gross.index)
        cost.loc[idx] = -c.loc[idx, "cost_pct"]
        turnover.loc[idx] = c.loc[idx, "turnover"]
        avg_bp.loc[idx] = c.loc[idx, "avg_event_bp"]
    net = (gross + cost).rename("net")
    return pd.concat([gross, cost, net, turnover, avg_bp], axis=1).reset_index()


def segment_record(daily: pd.DataFrame, variant: str, keep_n: int, model: str, segment: str, start: pd.Timestamp, end: pd.Timestamp) -> dict:
    d = daily.loc[(daily["trade_date"] >= start) & (daily["trade_date"] <= end)].copy()
    turnover_days = d.loc[d["turnover"] > 0, "turnover"]
    return {
        "model": model,
        "variant": variant,
        "keep_n": keep_n,
        "segment": segment,
        "n_days": int(len(d)),
        "gross_CAGR": cagr(d["gross"]),
        "cost_drag_ann": float(d["cost"].sum() * 252 / len(d)) if len(d) else np.nan,
        "net_CAGR": cagr(d["net"]),
        "net_Sharpe": sharpe(d["net"]),
        "net_MDD": mdd(d["net"]),
        "weekly_turnover": float(turnover_days.mean()) if len(turnover_days) else 0.0,
        "turnover_rebalances": int(len(turnover_days)),
        "avg_event_bp": float(d.loc[d["avg_event_bp"] > 0, "avg_event_bp"].mean()) if (d["avg_event_bp"] > 0).any() else 0.0,
    }


def add_vanilla_deltas(metrics: pd.DataFrame) -> pd.DataFrame:
    out = metrics.copy()
    base = out.loc[out["variant"] == "vanilla"].set_index(["model", "segment"])
    for idx, row in out.iterrows():
        b = base.loc[(row["model"], row["segment"])]
        out.loc[idx, "gross_delta_vs_vanilla"] = row["gross_CAGR"] - b["gross_CAGR"]
        out.loc[idx, "cost_save_vs_vanilla"] = row["cost_drag_ann"] - b["cost_drag_ann"]
        out.loc[idx, "net_delta_vs_vanilla"] = row["net_CAGR"] - b["net_CAGR"]
        out.loc[idx, "mdd_delta_vs_vanilla"] = row["net_MDD"] - b["net_MDD"]
    return out


def gate_summary(metrics: pd.DataFrame) -> pd.DataFrame:
    rows = []
    d = metrics.loc[metrics["variant"].isin(["keep25", "keep29"])].copy()
    for (model, variant), g in d.groupby(["model", "variant"], sort=False):
        rows.append(
            {
                "model": model,
                "variant": variant,
                "share_sharpe_gt0": (g["net_Sharpe"] > 0).mean(),
                "share_sharpe_ge_0_3": (g["net_Sharpe"] >= 0.3).mean(),
                "median_sharpe": g["net_Sharpe"].median(),
                "median_net_CAGR": g["net_CAGR"].median(),
                "worst_net_CAGR": g["net_CAGR"].min(),
                "median_cost_drag": g["cost_drag_ann"].median(),
                "gate_B_share_gt0_pass_70": (g["net_Sharpe"] > 0).mean() >= 0.7,
            }
        )
    return pd.DataFrame(rows)


def draw_text(draw, xy: tuple[float, float], text: str, size: int = 12, fill: str = "#111827") -> None:
    draw.text(xy, text, fill=fill, font=font(size))


def save_bar_chart(data: pd.DataFrame, x_col: str, series: list[tuple[str, str, str]], title: str, out_path: Path, percent: bool = True) -> None:
    from PIL import Image, ImageDraw

    width, height = 1020, 460
    left, right, top, bottom = 78, 28, 58, 86
    plot_w, plot_h = width - left - right, height - top - bottom
    vals = data[[s[0] for s in series]].to_numpy(dtype=float)
    max_abs = max(float(np.nanmax(np.abs(vals))), 0.01)
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (16, 18), title, 18)
    y0 = top + plot_h if vals.min() >= 0 else top + plot_h / 2
    scale_h = plot_h if vals.min() >= 0 else plot_h / 2
    ticks = [0, max_abs / 2, max_abs] if vals.min() >= 0 else [-max_abs, -max_abs / 2, 0, max_abs / 2, max_abs]
    for tick in ticks:
        y = y0 - tick / max_abs * scale_h
        draw.line((left, y, width - right, y), fill="#e5e7eb")
        label = fmt_pct(tick, 1) if percent else f"{tick:.2f}"
        draw_text(draw, (8, y - 8), label, 11, "#6b7280")
    draw.line((left, y0, width - right, y0), fill="#111827")
    group_w = plot_w / len(data)
    bar_w = min(28, group_w / (len(series) + 2))
    for i, row in data.reset_index(drop=True).iterrows():
        cx = left + group_w * (i + 0.5)
        label = str(row[x_col])
        box = draw.textbbox((0, 0), label, font=font(11))
        draw_text(draw, (cx - (box[2] - box[0]) / 2, height - 58), label, 11, "#374151")
        for k, (col, _label, color) in enumerate(series):
            val = float(row[col])
            bh = abs(val) / max_abs * scale_h
            x = cx + (k - (len(series) - 1) / 2) * (bar_w + 5) - bar_w / 2
            y = y0 - bh if val >= 0 else y0
            draw.rounded_rectangle((x, y, x + bar_w, y + bh), radius=2, fill=color)
    lx = left
    for _col, label, color in series:
        draw.rectangle((lx, height - 30, lx + 12, height - 18), fill=color)
        draw_text(draw, (lx + 16, height - 32), label, 11, "#374151")
        lx += 124
    img.save(out_path)


def save_heatmap(data: pd.DataFrame, row_col: str, col_col: str, value_col: str, title: str, out_path: Path, percent: bool = False) -> None:
    from PIL import Image, ImageDraw

    rows = list(data[row_col].drop_duplicates())
    cols = list(data[col_col].drop_duplicates())
    piv = data.pivot(index=row_col, columns=col_col, values=value_col).reindex(index=rows, columns=cols)
    vals = piv.to_numpy(dtype=float)
    max_abs = max(float(np.nanmax(np.abs(vals))), 0.01)
    cell_w, cell_h = 106, 42
    left, top = 116, 68
    width = left + cell_w * len(cols) + 30
    height = top + cell_h * len(rows) + 32
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw_text(draw, (16, 18), title, 18)
    for j, col in enumerate(cols):
        draw_text(draw, (left + j * cell_w + 20, top - 28), str(col), 11, "#374151")
    for i, row in enumerate(rows):
        y = top + i * cell_h
        draw_text(draw, (16, y + 13), str(row), 11, "#374151")
        for j, col in enumerate(cols):
            val = piv.loc[row, col]
            z = 0.0 if pd.isna(val) else max(-1.0, min(1.0, float(val) / max_abs))
            if z >= 0:
                fill = (220 - int(70 * z), 252 - int(50 * z), 231 - int(70 * z))
            else:
                z = abs(z)
                fill = (254 - int(30 * z), 226 - int(130 * z), 226 - int(130 * z))
            x = left + j * cell_w
            draw.rounded_rectangle((x, y, x + cell_w - 4, y + cell_h - 4), radius=5, fill=fill, outline="#e5e7eb")
            txt = fmt_pct(val) if percent else f"{val:.2f}"
            box = draw.textbbox((0, 0), txt, font=font(11))
            draw_text(draw, (x + (cell_w - 4 - (box[2] - box[0])) / 2, y + 13), txt, 11, "#111827")
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


def write_reports(gates: pd.DataFrame, metrics: pd.DataFrame) -> None:
    pct_cols = {
        "share_sharpe_gt0",
        "share_sharpe_ge_0_3",
        "median_net_CAGR",
        "worst_net_CAGR",
        "median_cost_drag",
        "gross_CAGR",
        "cost_drag_ann",
        "net_CAGR",
        "net_MDD",
        "weekly_turnover",
        "gross_delta_vs_vanilla",
        "cost_save_vs_vanilla",
        "net_delta_vs_vanilla",
        "mdd_delta_vs_vanilla",
    }
    key_models = ["flat_5bp", "flat_10bp", "flat_15bp", "tier_base", "tier_stress"]
    gate_key = order_by_model(gates.loc[gates["model"].isin(key_models)].copy())
    metrics_key = order_by_model(metrics.loc[(metrics["model"].isin(key_models)) & (metrics["variant"].isin(["keep25", "keep29"]))].copy())
    md = [
        "# Real cost scan",
        "",
        "Fixed strategy; no alpha/rule changes. Tiered models use trailing 20-day cb_amount shifted by one day plus issue_size.",
        "",
        "## Gate Summary",
        dataframe_to_md(gate_key, pct_cols),
        "",
        "## Segment Metrics Key Models",
        dataframe_to_md(metrics_key, pct_cols),
        "",
        "Visual report: real_cost_scan_report.html",
    ]
    (REPORT_DIR / "real_cost_scan_summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")

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
    <!doctype html><html><head><meta charset="utf-8"><title>Real cost scan</title><style>{css}</style></head>
    <body>
    <h1>Real cost scan</h1>
    <p class="note">Flat grid plus PIT liquidity/size tiered cost models. Transaction cost is charged on changed names, buys plus sells.</p>
    <section class="grid">
      <div><img src="../charts/gate_share_sharpe_gt0.png" alt="gate share"></div>
      <div><img src="../charts/keep29_sharpe_heatmap.png" alt="keep29 sharpe heatmap"></div>
      <div><img src="../charts/median_cost_drag.png" alt="median cost drag"></div>
      <div><img src="../charts/median_net_cagr.png" alt="median net cagr"></div>
    </section>
    <section><h2>Gate summary</h2>{dataframe_to_html_table(gate_key, pct_cols)}</section>
    <section><h2>Segment metrics key models</h2>{dataframe_to_html_table(metrics_key, pct_cols)}</section>
    </body></html>
    """
    (REPORT_DIR / "real_cost_scan_report.html").write_text(body, encoding="utf-8")


def order_by_model(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["model"] = pd.Categorical(out["model"], categories=MODEL_ORDER, ordered=True)
    sort_cols = ["model"]
    if "variant" in out.columns:
        sort_cols.append("variant")
    if "segment" in out.columns:
        sort_cols.append("segment")
    out = out.sort_values(sort_cols).copy()
    out["model"] = out["model"].astype(str)
    return out.reset_index(drop=True)


def main() -> None:
    ensure_dirs()
    base, _ = prepare_base()
    base = enrich_cost_inputs(base)
    cost_table = base.set_index(["trade_date", "cb_code"])[["issue_size", "adv20_amount"]]

    variant_inputs = {}
    for keep_n in VARIANTS:
        name = variant_name(keep_n)
        holdings, events = build_holdings_and_events(base, keep_n)
        h = attach_returns_and_meta(holdings, base)
        variant_inputs[name] = {"holdings": h, "events": events, "keep_n": keep_n if keep_n is not None else 10}
        events.to_csv(TABLE_DIR / f"rebalance_events_{name}.csv", index=False, encoding="utf-8-sig")
        print(f"built {name}: {len(h)} holding rows, {len(events)} rebalance events")

    metric_rows = []
    event_cost_rows = []
    for model in ALL_MODELS:
        for name, obj in variant_inputs.items():
            costs = event_costs(obj["events"], cost_table, model)
            costs["variant"] = name
            event_cost_rows.append(costs)
            daily = daily_pnl(obj["holdings"], costs)
            daily["model"] = model
            daily["variant"] = name
            daily.to_csv(DAILY_DIR / f"daily_pnl_{name}_{model}.csv", index=False, encoding="utf-8-sig")
            for segment, (start, end) in OOS_SEGMENTS.items():
                metric_rows.append(segment_record(daily, name, obj["keep_n"], model, segment, start, end))

    metrics = order_by_model(add_vanilla_deltas(pd.DataFrame(metric_rows)))
    gates = order_by_model(gate_summary(metrics))
    all_event_costs = pd.concat(event_cost_rows, ignore_index=True) if event_cost_rows else pd.DataFrame()

    metrics.to_csv(TABLE_DIR / "segment_metrics_all_models.csv", index=False, encoding="utf-8-sig")
    gates.to_csv(TABLE_DIR / "gate_summary_by_model.csv", index=False, encoding="utf-8-sig")
    all_event_costs.to_csv(TABLE_DIR / "event_costs_all_models.csv", index=False, encoding="utf-8-sig")

    gate_chart = order_by_model(gates.loc[gates["variant"].isin(["keep25", "keep29"])]).pivot(index="model", columns="variant", values="share_sharpe_gt0").reset_index()
    gate_chart["model"] = pd.Categorical(gate_chart["model"], categories=MODEL_ORDER, ordered=True)
    gate_chart = gate_chart.sort_values("model").astype({"model": str})
    save_bar_chart(
        gate_chart,
        "model",
        [("keep25", "keep25", "#2563eb"), ("keep29", "keep29", "#16a34a")],
        "Share of OOS segments with Sharpe > 0",
        CHART_DIR / "gate_share_sharpe_gt0.png",
    )
    hmap = order_by_model(metrics.loc[metrics["variant"] == "keep29", ["model", "segment", "net_Sharpe"]].copy())
    save_heatmap(hmap, "model", "segment", "net_Sharpe", "keep29 net Sharpe by cost model", CHART_DIR / "keep29_sharpe_heatmap.png")

    med = gates.pivot(index="model", columns="variant", values="median_cost_drag").reindex(MODEL_ORDER).reset_index()
    save_bar_chart(
        med,
        "model",
        [("keep25", "keep25", "#2563eb"), ("keep29", "keep29", "#16a34a")],
        "Median annual cost drag",
        CHART_DIR / "median_cost_drag.png",
    )
    med_net = gates.pivot(index="model", columns="variant", values="median_net_CAGR").reindex(MODEL_ORDER).reset_index()
    save_bar_chart(
        med_net,
        "model",
        [("keep25", "keep25", "#2563eb"), ("keep29", "keep29", "#16a34a")],
        "Median net CAGR by cost model",
        CHART_DIR / "median_net_cagr.png",
    )

    write_reports(gates, metrics)
    print(f"wrote outputs to {OUT_ROOT}")


if __name__ == "__main__":
    main()
