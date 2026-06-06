"""keep_n execution-buffer decomposition.

This research-side script compares vanilla vs fixed keep_n variants without
re-optimizing strategy signals. It decomposes each OOS segment into:
- gross return before turnover cost
- execution cost drag
- net return after 15bp/side stress
- keep_n vs vanilla gross/cost/net deltas
- extension attribution for bonds held longer by keep_n

Outputs are dependency-light: CSV, Markdown, standalone HTML, and SVG charts.
"""

from __future__ import annotations

import html
import sys
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from PIL import Image, ImageDraw, ImageFont

    HAS_PIL = True
except ModuleNotFoundError:
    Image = ImageDraw = ImageFont = None
    HAS_PIL = False

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategy.core.cb_strategy_config import StrategyParams
from strategy.core.data_access import load_issue_size_series, load_maturity_date_series
from strategy.core.portfolio import _pick_week_holdings, _week_end_dates
from strategy.core.universe import build_universes

PANEL_2017 = ROOT / "data" / "bond_daily_panel_full_v2_from20170101.csv"
OUT_DIR = ROOT / "GPT-test" / "output" / "walk_forward_gate_v1" / "keep_n_decomposition"

TOP_N = 10
KEEP_CANDIDATES: tuple[int | None, ...] = (None, 15, 20, 25, 29, 35, 40)
COST_BP_SIDE = 15.0
MAIN_ISSUE_SIZE = 300_000_000.0
RF_ANNUAL = 0.025

OOS_SEGMENTS = {
    str(year): (pd.Timestamp(year=year, month=1, day=1), pd.Timestamp(year=year, month=12, day=31))
    for year in range(2021, 2026)
}


def variant_name(keep_n: int | None) -> str:
    return "vanilla" if keep_n is None else f"keep{keep_n}"


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
        open_px = pd.to_numeric(df["cb_open"], errors="coerce")
        close_px = pd.to_numeric(df["cb_close"], errors="coerce")
        df["ret_entry"] = close_px / open_px - 1.0
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
    cost_rows = []
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
        entry_codes = new - old
        for code in sel[rd]:
            is_new = code in entry_codes
            for j in range(si, ei + 1):
                holdings_rows.append(
                    {
                        "signal_date": pd.Timestamp(rd),
                        "trade_date": pd.Timestamp(dates[j]),
                        "cb_code": code,
                        "is_entry": (j == si) and is_new,
                    }
                )
        if i >= 1:
            turnover = len(new - old) / max(len(new), 1)
            cost_rows.append(
                {
                    "signal_date": pd.Timestamp(rd),
                    "trade_date": pd.Timestamp(dates[si]),
                    "turnover": turnover,
                    "cost_pct": 2.0 * turnover * COST_BP_SIDE / 1e4,
                }
            )
    return pd.DataFrame(holdings_rows), pd.DataFrame(cost_rows)


def attach_returns_and_meta(holdings: pd.DataFrame, df: pd.DataFrame) -> pd.DataFrame:
    meta_cols = [
        "trade_date",
        "cb_code",
        "ret",
        "ret_entry",
        "cb_close",
        "conversion_premium",
        "issue_rating",
        "issue_size",
        "bond_short_name",
        "stk_code",
        "mom_20d",
    ]
    available = [c for c in meta_cols if c in df.columns]
    h = holdings.merge(df[available], on=["trade_date", "cb_code"], how="left")
    h["ret_used"] = np.where(h["is_entry"], h["ret_entry"], h["ret"])
    active_n = h.groupby("trade_date")["ret_used"].transform(lambda s: s.notna().sum())
    h["gross_contrib"] = h["ret_used"].fillna(0.0) / active_n.replace(0, np.nan)
    return h


def daily_pnl_with_cost(h: pd.DataFrame, cost_rows: pd.DataFrame) -> pd.DataFrame:
    gross = h.groupby("trade_date")["gross_contrib"].sum().rename("gross")
    cost = pd.Series(0.0, index=gross.index, name="cost")
    turnover = pd.Series(0.0, index=gross.index, name="turnover")
    if not cost_rows.empty:
        costs = cost_rows.set_index("trade_date")["cost_pct"]
        turns = cost_rows.set_index("trade_date")["turnover"]
        idx = costs.index.intersection(gross.index)
        cost.loc[idx] = -costs.loc[idx]
        turnover.loc[idx] = turns.loc[idx]
    net = (gross + cost).rename("net")
    return pd.concat([gross, cost, net, turnover], axis=1).reset_index()


def cagr(r: pd.Series) -> float:
    if len(r) < 20:
        return np.nan
    return float((1 + r).prod() ** (252 / len(r)) - 1)


def mdd(r: pd.Series) -> float:
    if len(r) < 20:
        return np.nan
    cum = (1 + r).cumprod()
    return float((cum / cum.cummax() - 1).min())


def sharpe(r: pd.Series) -> float:
    if len(r) < 20:
        return np.nan
    vol = r.std() * np.sqrt(252)
    if vol <= 0:
        return np.nan
    return float((cagr(r) - RF_ANNUAL) / vol)


def segment_metrics(daily: pd.DataFrame, seg_name: str, seg_start: pd.Timestamp, seg_end: pd.Timestamp) -> dict:
    d = daily.loc[(daily["trade_date"] >= seg_start) & (daily["trade_date"] <= seg_end)].copy()
    if len(d) < 20:
        return {"segment": seg_name, "n_days": len(d)}
    cost_drag_ann = float(d["cost"].sum() * 252 / len(d))
    turnover_days = d.loc[d["turnover"] > 0, "turnover"]
    return {
        "segment": seg_name,
        "n_days": int(len(d)),
        "gross_CAGR": cagr(d["gross"]),
        "cost_drag_ann": cost_drag_ann,
        "net_CAGR": cagr(d["net"]),
        "net_Sharpe": sharpe(d["net"]),
        "net_MDD": mdd(d["net"]),
        "weekly_turnover": float(turnover_days.mean()) if len(turnover_days) else 0.0,
        "turnover_rebalances": int(len(turnover_days)),
    }


def per_bond_attr(h: pd.DataFrame, seg_name: str, seg_start: pd.Timestamp, seg_end: pd.Timestamp, variant: str) -> pd.DataFrame:
    d = h.loc[(h["trade_date"] >= seg_start) & (h["trade_date"] <= seg_end)].copy()
    if d.empty:
        return pd.DataFrame()
    out = d.groupby("cb_code").agg(
        bond_short_name=("bond_short_name", "last"),
        issue_rating=("issue_rating", "last"),
        issue_size=("issue_size", "last"),
        holding_days=("trade_date", "count"),
        valid_days=("ret_used", lambda x: int(x.notna().sum())),
        gross_contrib=("gross_contrib", "sum"),
        entry_count=("is_entry", "sum"),
    ).reset_index()
    out["segment"] = seg_name
    out["variant"] = variant
    return out.sort_values("gross_contrib").reset_index(drop=True)


def extension_diff(attr_keep: pd.DataFrame, attr_vanilla: pd.DataFrame, keep_variant: str, seg_name: str) -> pd.DataFrame:
    if attr_keep.empty or attr_vanilla.empty:
        return pd.DataFrame()
    k = attr_keep.set_index("cb_code")[["bond_short_name", "issue_rating", "holding_days", "gross_contrib"]]
    v = attr_vanilla.set_index("cb_code")[["holding_days", "gross_contrib"]]
    common = k.index.intersection(v.index)
    out = pd.DataFrame(
        {
            "cb_code": common,
            "bond_short_name": k.loc[common, "bond_short_name"].values,
            "issue_rating": k.loc[common, "issue_rating"].values,
            "keep_days": k.loc[common, "holding_days"].values,
            "vanilla_days": v.loc[common, "holding_days"].values,
            "keep_gross_contrib": k.loc[common, "gross_contrib"].values,
            "vanilla_gross_contrib": v.loc[common, "gross_contrib"].values,
        }
    )
    out["days_delta"] = out["keep_days"] - out["vanilla_days"]
    out["gross_contrib_delta"] = out["keep_gross_contrib"] - out["vanilla_gross_contrib"]
    out["variant"] = keep_variant
    out["segment"] = seg_name
    return out.sort_values("gross_contrib_delta").reset_index(drop=True)


def add_vanilla_deltas(metrics: pd.DataFrame) -> pd.DataFrame:
    out = metrics.copy()
    base = out.loc[out["variant"] == "vanilla"].set_index("segment")
    for idx, row in out.iterrows():
        b = base.loc[row["segment"]]
        out.loc[idx, "gross_delta_vs_vanilla"] = row["gross_CAGR"] - b["gross_CAGR"]
        out.loc[idx, "cost_save_vs_vanilla"] = row["cost_drag_ann"] - b["cost_drag_ann"]
        out.loc[idx, "net_delta_vs_vanilla"] = row["net_CAGR"] - b["net_CAGR"]
        out.loc[idx, "mdd_delta_vs_vanilla"] = row["net_MDD"] - b["net_MDD"]
        out.loc[idx, "turnover_ratio_vs_vanilla"] = row["weekly_turnover"] / b["weekly_turnover"] if b["weekly_turnover"] else np.nan
    return out


def summarize_by_keep(metrics: pd.DataFrame) -> pd.DataFrame:
    d = metrics.loc[metrics["variant"] != "vanilla"].copy()
    rows = []
    for variant, g in d.groupby("variant", sort=False):
        rows.append(
            {
                "variant": variant,
                "keep_n": int(variant.replace("keep", "")),
                "median_gross_delta": g["gross_delta_vs_vanilla"].median(),
                "median_cost_save": g["cost_save_vs_vanilla"].median(),
                "median_net_delta": g["net_delta_vs_vanilla"].median(),
                "worst_net_delta": g["net_delta_vs_vanilla"].min(),
                "share_net_delta_gt0": (g["net_delta_vs_vanilla"] > 0).mean(),
                "share_turnover_lt80pct": (g["turnover_ratio_vs_vanilla"] < 0.8).mean(),
                "share_mdd_not_worse": (g["mdd_delta_vs_vanilla"] >= 0).mean(),
                "median_turnover_ratio": g["turnover_ratio_vs_vanilla"].median(),
                "median_net_sharpe": g["net_Sharpe"].median(),
            }
        )
    return pd.DataFrame(rows).sort_values("keep_n").reset_index(drop=True)


def summarize_extension(diffs: pd.DataFrame) -> pd.DataFrame:
    if diffs.empty:
        return pd.DataFrame()
    rows = []
    for (variant, segment), g in diffs.groupby(["variant", "segment"], sort=False):
        lost = g.loc[(g["days_delta"] > 0) & (g["gross_contrib_delta"] < 0)]
        won = g.loc[(g["days_delta"] > 0) & (g["gross_contrib_delta"] > 0)]
        rows.append(
            {
                "variant": variant,
                "segment": segment,
                "common_bonds": int(len(g)),
                "held_longer_lost_count": int(len(lost)),
                "held_longer_lost_sum": lost["gross_contrib_delta"].sum(),
                "held_longer_won_count": int(len(won)),
                "held_longer_won_sum": won["gross_contrib_delta"].sum(),
                "extension_net_sum": lost["gross_contrib_delta"].sum() + won["gross_contrib_delta"].sum(),
            }
        )
    return pd.DataFrame(rows)


def fmt_pct(x: float, digits: int = 2) -> str:
    if pd.isna(x):
        return ""
    return f"{x * 100:.{digits}f}%"


def color_for_value(value: float, max_abs: float) -> str:
    if pd.isna(value) or max_abs <= 0:
        return "#f3f4f6"
    z = max(-1.0, min(1.0, value / max_abs))
    if z >= 0:
        r = int(240 - 158 * z)
        g = int(253 - 67 * z)
        b = int(244 - 104 * z)
    else:
        z = abs(z)
        r = int(254 - 69 * z)
        g = int(242 - 214 * z)
        b = int(242 - 214 * z)
    return f"#{r:02x}{g:02x}{b:02x}"


def hex_to_rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def font(size: int):
    if not HAS_PIL:
        return None
    for name in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_center(draw, xyxy: tuple[float, float, float, float], text: str, fill: str, size: int = 12) -> None:
    fnt = font(size)
    box = draw.textbbox((0, 0), text, font=fnt)
    tw = box[2] - box[0]
    th = box[3] - box[1]
    x1, y1, x2, y2 = xyxy
    draw.text((x1 + (x2 - x1 - tw) / 2, y1 + (y2 - y1 - th) / 2), text, fill=fill, font=fnt)


def heatmap_png(metrics: pd.DataFrame, value_col: str, title: str, out_path: Path) -> None:
    if not HAS_PIL:
        out_path.with_suffix(out_path.suffix + ".skipped.txt").write_text("PIL is not installed\n", encoding="utf-8")
        return
    d = metrics.loc[metrics["variant"] != "vanilla"].copy()
    variants = [variant_name(k) for k in KEEP_CANDIDATES if k is not None]
    segments = list(OOS_SEGMENTS)
    pivot = d.pivot(index="variant", columns="segment", values=value_col).reindex(index=variants, columns=segments)
    max_abs = float(np.nanmax(np.abs(pivot.values))) if np.isfinite(pivot.values).any() else 1.0
    cell_w, cell_h = 112, 46
    left, top = 96, 64
    width = left + cell_w * len(segments) + 28
    height = top + cell_h * len(variants) + 34
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw.text((16, 18), title, fill="#111827", font=font(18))
    for j, seg in enumerate(segments):
        draw_center(draw, (left + j * cell_w, top - 32, left + (j + 1) * cell_w, top - 6), seg, "#374151", 12)
    for i, variant in enumerate(variants):
        y = top + i * cell_h
        draw.text((18, y + 14), variant, fill="#374151", font=font(12))
        for j, seg in enumerate(segments):
            x = left + j * cell_w
            val = pivot.loc[variant, seg]
            fill = hex_to_rgb(color_for_value(val, max_abs))
            draw.rounded_rectangle((x, y, x + cell_w - 4, y + cell_h - 4), radius=5, fill=fill, outline="#e5e7eb")
            draw_center(draw, (x, y, x + cell_w - 4, y + cell_h - 4), fmt_pct(val), "#111827", 12)
    img.save(out_path)


def summary_bar_png(summary: pd.DataFrame, out_path: Path) -> None:
    if not HAS_PIL:
        out_path.with_suffix(out_path.suffix + ".skipped.txt").write_text("PIL is not installed\n", encoding="utf-8")
        return
    d = summary.copy()
    series = [
        ("median_gross_delta", "gross", "#ef4444"),
        ("median_cost_save", "cost", "#6b7280"),
        ("median_net_delta", "net", "#22c55e"),
    ]
    width, height = 900, 420
    left, right, top, bottom = 78, 28, 58, 72
    plot_w, plot_h = width - left - right, height - top - bottom
    max_abs = float(np.nanmax(np.abs(d[[s[0] for s in series]].values)))
    max_abs = max(max_abs, 0.01)
    y0 = top + plot_h / 2
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw.text((16, 18), "Median decomposition vs vanilla", fill="#111827", font=font(18))
    for tick in [-max_abs, -max_abs / 2, 0, max_abs / 2, max_abs]:
        y = y0 - tick / max_abs * (plot_h / 2)
        draw.line((left, y, width - right, y), fill="#e5e7eb")
        draw.text((10, y - 8), fmt_pct(tick, 1), fill="#6b7280", font=font(11))
    draw.line((left, y0, width - right, y0), fill="#111827")
    group_w = plot_w / len(d)
    bar_w = min(28, group_w / 5)
    for i, row in d.iterrows():
        cx = left + group_w * (i + 0.5)
        draw_center(draw, (cx - 48, height - 40, cx + 48, height - 18), str(row["variant"]), "#374151", 12)
        for k, (col, _label, color) in enumerate(series):
            val = row[col]
            bh = abs(val) / max_abs * (plot_h / 2)
            x = cx + (k - 1) * (bar_w + 5) - bar_w / 2
            y = y0 - bh if val >= 0 else y0
            draw.rounded_rectangle((x, y, x + bar_w, y + bh), radius=2, fill=color)
    lx = left
    for _col, label, color in series:
        draw.rectangle((lx, height - 62, lx + 12, height - 50), fill=color)
        draw.text((lx + 16, height - 64), label, fill="#374151", font=font(11))
        lx += 86
    img.save(out_path)


def heatmap_svg(metrics: pd.DataFrame, value_col: str, title: str, out_path: Path) -> None:
    d = metrics.loc[metrics["variant"] != "vanilla"].copy()
    variants = [variant_name(k) for k in KEEP_CANDIDATES if k is not None]
    segments = list(OOS_SEGMENTS)
    pivot = d.pivot(index="variant", columns="segment", values=value_col).reindex(index=variants, columns=segments)
    max_abs = float(np.nanmax(np.abs(pivot.values))) if np.isfinite(pivot.values).any() else 1.0
    cell_w, cell_h = 92, 38
    left, top = 88, 52
    width = left + cell_w * len(segments) + 24
    height = top + cell_h * len(variants) + 36
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="16" y="26" font-family="Arial" font-size="16" font-weight="700">{html.escape(title)}</text>',
    ]
    for j, seg in enumerate(segments):
        x = left + j * cell_w + cell_w / 2
        parts.append(f'<text x="{x:.1f}" y="{top - 14}" text-anchor="middle" font-family="Arial" font-size="12" fill="#374151">{seg}</text>')
    for i, variant in enumerate(variants):
        y = top + i * cell_h
        parts.append(f'<text x="{left - 12}" y="{y + 24}" text-anchor="end" font-family="Arial" font-size="12" fill="#374151">{variant}</text>')
        for j, seg in enumerate(segments):
            x = left + j * cell_w
            val = pivot.loc[variant, seg]
            fill = color_for_value(val, max_abs)
            parts.append(f'<rect x="{x}" y="{y}" width="{cell_w - 2}" height="{cell_h - 2}" rx="4" fill="{fill}" stroke="#e5e7eb"/>')
            parts.append(f'<text x="{x + cell_w / 2:.1f}" y="{y + 23}" text-anchor="middle" font-family="Arial" font-size="12" fill="#111827">{fmt_pct(val)}</text>')
    parts.append("</svg>")
    out_path.write_text("\n".join(parts), encoding="utf-8")


def summary_bar_svg(summary: pd.DataFrame, out_path: Path) -> None:
    d = summary.copy()
    series = [
        ("median_gross_delta", "gross delta", "#ef4444"),
        ("median_cost_save", "cost save", "#6b7280"),
        ("median_net_delta", "net delta", "#22c55e"),
    ]
    width, height = 780, 360
    left, right, top, bottom = 70, 24, 42, 58
    plot_w, plot_h = width - left - right, height - top - bottom
    max_abs = float(np.nanmax(np.abs(d[[s[0] for s in series]].values)))
    max_abs = max(max_abs, 0.01)
    y0 = top + plot_h / 2
    group_w = plot_w / len(d)
    bar_w = min(24, group_w / 5)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="16" y="26" font-family="Arial" font-size="16" font-weight="700">Median decomposition vs vanilla</text>',
        f'<line x1="{left}" x2="{width - right}" y1="{y0}" y2="{y0}" stroke="#111827" stroke-width="1"/>',
    ]
    for tick in [-max_abs, -max_abs / 2, 0, max_abs / 2, max_abs]:
        y = y0 - tick / max_abs * (plot_h / 2)
        parts.append(f'<line x1="{left}" x2="{width - right}" y1="{y:.1f}" y2="{y:.1f}" stroke="#e5e7eb"/>')
        parts.append(f'<text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end" font-family="Arial" font-size="11" fill="#6b7280">{fmt_pct(tick, 1)}</text>')
    for i, row in d.iterrows():
        cx = left + group_w * (i + 0.5)
        parts.append(f'<text x="{cx:.1f}" y="{height - 22}" text-anchor="middle" font-family="Arial" font-size="12" fill="#374151">{row["variant"]}</text>')
        for k, (col, _label, color) in enumerate(series):
            val = row[col]
            bh = abs(val) / max_abs * (plot_h / 2)
            x = cx + (k - 1) * (bar_w + 3) - bar_w / 2
            y = y0 - bh if val >= 0 else y0
            parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w}" height="{bh:.1f}" fill="{color}" rx="2"/>')
    lx = left
    for col, label, color in series:
        parts.append(f'<rect x="{lx}" y="{height - 44}" width="10" height="10" fill="{color}"/>')
        parts.append(f'<text x="{lx + 14}" y="{height - 35}" font-family="Arial" font-size="11" fill="#374151">{label}</text>')
        lx += 120
    parts.append("</svg>")
    out_path.write_text("\n".join(parts), encoding="utf-8")


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
            text = fmt_pct(val) if col in pct_cols else ("" if pd.isna(val) else str(val))
            parts.append(f"<td>{html.escape(text)}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table>")
    return "\n".join(parts)


def dataframe_to_markdown_table(df: pd.DataFrame, pct_cols: set[str] | None = None, n: int | None = None) -> str:
    pct_cols = pct_cols or set()
    d = df.head(n).copy() if n is not None else df.copy()
    if d.empty:
        return "(empty)"
    headers = [str(c) for c in d.columns]
    rows = []
    for _, row in d.iterrows():
        vals = []
        for col in d.columns:
            val = row[col]
            if col in pct_cols:
                text = fmt_pct(val)
            elif isinstance(val, (float, np.floating)):
                text = "" if pd.isna(val) else f"{val:.6f}"
            else:
                text = "" if pd.isna(val) else str(val)
            vals.append(text)
        rows.append(vals)
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    out.extend("| " + " | ".join(r) + " |" for r in rows)
    return "\n".join(out)


def write_markdown(summary: pd.DataFrame, metrics: pd.DataFrame, extension_summary: pd.DataFrame, top_losses: pd.DataFrame, out_path: Path) -> None:
    best = summary.sort_values(["median_net_delta", "worst_net_delta"], ascending=False).iloc[0]
    robust = summary.loc[
        (summary["median_net_delta"] > 0)
        & (summary["share_net_delta_gt0"] >= 0.6)
        & (summary["share_turnover_lt80pct"] >= 0.8)
        & (summary["worst_net_delta"] > -0.02)
    ]
    lines = [
        "# keep_n decomposition",
        "",
        "Fixed setup: C_rank_mom20, top_n=10, 15bp/side, OOS 2021-2025.",
        "",
        f"- best median net delta: {best['variant']} ({fmt_pct(best['median_net_delta'])})",
        "- robust candidates: " + (", ".join(robust["variant"]) if len(robust) else "none by current gate"),
        "",
        "## Summary By keep_n",
        "",
        dataframe_to_markdown_table(
            summary,
            {
                "median_gross_delta",
                "median_cost_save",
                "median_net_delta",
                "worst_net_delta",
                "share_net_delta_gt0",
                "share_turnover_lt80pct",
                "share_mdd_not_worse",
                "median_turnover_ratio",
            },
        ),
        "",
        "## Segment Metrics",
        "",
        dataframe_to_markdown_table(
            metrics,
            {
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
            },
        ),
        "",
        "## Extension Summary",
        "",
        dataframe_to_markdown_table(
            extension_summary,
            {"held_longer_lost_sum", "held_longer_won_sum", "extension_net_sum"},
        ),
        "",
        "## Top Extension Losses",
        "",
        dataframe_to_markdown_table(top_losses, {"gross_contrib_delta"}, n=50),
        "",
        "Visual report: keep_n_decomposition_report.html",
    ]
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_html_report(summary: pd.DataFrame, metrics: pd.DataFrame, extension_summary: pd.DataFrame, top_losses: pd.DataFrame, out_path: Path) -> None:
    css = """
    body { font-family: Arial, "Microsoft YaHei", sans-serif; margin: 24px; color: #111827; background: #f9fafb; }
    h1, h2 { margin: 0 0 14px; }
    section { background: white; border: 1px solid #e5e7eb; border-radius: 8px; padding: 18px; margin: 16px 0; }
    table { border-collapse: collapse; width: 100%; font-size: 13px; }
    th, td { border-bottom: 1px solid #e5e7eb; padding: 7px 9px; text-align: right; white-space: nowrap; }
    th:first-child, td:first-child { text-align: left; }
    th { background: #f3f4f6; color: #374151; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(460px, 1fr)); gap: 16px; }
    img { max-width: 100%; height: auto; border: 1px solid #e5e7eb; border-radius: 6px; background: white; }
    .note { color: #4b5563; line-height: 1.5; }
    """
    pct_cols_summary = {
        "median_gross_delta",
        "median_cost_save",
        "median_net_delta",
        "worst_net_delta",
        "share_net_delta_gt0",
        "share_turnover_lt80pct",
        "share_mdd_not_worse",
        "median_turnover_ratio",
    }
    pct_cols_metrics = {
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
    }
    pct_cols_ext = {"held_longer_lost_sum", "held_longer_won_sum", "extension_net_sum", "gross_contrib_delta"}
    body = f"""
    <!doctype html>
    <html><head><meta charset="utf-8"><title>keep_n decomposition</title><style>{css}</style></head>
    <body>
    <h1>keep_n decomposition</h1>
    <p class="note">Fixed setup: C_rank_mom20, top_n=10, 15bp/side, OOS 2021-2025. Deltas are against vanilla.</p>
    <section class="grid">
      <div><img src="net_delta_heatmap.png" alt="net delta heatmap"></div>
      <div><img src="turnover_ratio_heatmap.png" alt="turnover ratio heatmap"></div>
      <div><img src="median_decomposition_bars.png" alt="median decomposition bars"></div>
    </section>
    <section><h2>Summary by keep_n</h2>{dataframe_to_html_table(summary, pct_cols_summary)}</section>
    <section><h2>Segment metrics</h2>{dataframe_to_html_table(metrics, pct_cols_metrics)}</section>
    <section><h2>Extension summary</h2>{dataframe_to_html_table(extension_summary, pct_cols_ext)}</section>
    <section><h2>Top extension losses</h2>{dataframe_to_html_table(top_losses, pct_cols_ext, n=30)}</section>
    </body></html>
    """
    out_path.write_text(body, encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    base, _ = prepare_base()

    variant_data = {}
    for keep_n in KEEP_CANDIDATES:
        name = variant_name(keep_n)
        holdings, cost_rows = build_weekly_holdings(base, keep_n)
        holdings = attach_returns_and_meta(holdings, base)
        daily = daily_pnl_with_cost(holdings, cost_rows)
        variant_data[name] = {"holdings": holdings, "cost_rows": cost_rows, "daily": daily, "keep_n": keep_n}
        daily.to_csv(OUT_DIR / f"daily_pnl_{name}.csv", index=False, encoding="utf-8-sig")
        print(f"built {name}: {len(daily)} daily rows")

    metric_rows = []
    attr_by_variant_segment: dict[tuple[str, str], pd.DataFrame] = {}
    for name, vd in variant_data.items():
        for seg_name, (seg_start, seg_end) in OOS_SEGMENTS.items():
            rec = segment_metrics(vd["daily"], seg_name, seg_start, seg_end)
            rec["variant"] = name
            rec["keep_n"] = vd["keep_n"] if vd["keep_n"] is not None else 10
            metric_rows.append(rec)
            attr = per_bond_attr(vd["holdings"], seg_name, seg_start, seg_end, name)
            attr_by_variant_segment[(name, seg_name)] = attr
    metrics = add_vanilla_deltas(pd.DataFrame(metric_rows))
    metrics = metrics[[
        "variant",
        "keep_n",
        "segment",
        "n_days",
        "gross_CAGR",
        "cost_drag_ann",
        "net_CAGR",
        "net_Sharpe",
        "net_MDD",
        "weekly_turnover",
        "turnover_rebalances",
        "gross_delta_vs_vanilla",
        "cost_save_vs_vanilla",
        "net_delta_vs_vanilla",
        "mdd_delta_vs_vanilla",
        "turnover_ratio_vs_vanilla",
    ]]

    diffs = []
    for keep_n in KEEP_CANDIDATES:
        if keep_n is None:
            continue
        name = variant_name(keep_n)
        for seg_name in OOS_SEGMENTS:
            diff = extension_diff(
                attr_by_variant_segment[(name, seg_name)],
                attr_by_variant_segment[("vanilla", seg_name)],
                name,
                seg_name,
            )
            if not diff.empty:
                diffs.append(diff)
    all_diffs = pd.concat(diffs, ignore_index=True) if diffs else pd.DataFrame()
    extension_summary = summarize_extension(all_diffs)
    top_losses = (
        all_diffs.loc[(all_diffs["days_delta"] > 0) & (all_diffs["gross_contrib_delta"] < 0)]
        .sort_values("gross_contrib_delta")
        .head(50)
        .reset_index(drop=True)
        if not all_diffs.empty
        else pd.DataFrame()
    )
    summary = summarize_by_keep(metrics)

    metrics.to_csv(OUT_DIR / "segment_metrics.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(OUT_DIR / "summary_by_keep.csv", index=False, encoding="utf-8-sig")
    extension_summary.to_csv(OUT_DIR / "extension_summary.csv", index=False, encoding="utf-8-sig")
    all_diffs.to_csv(OUT_DIR / "extension_diff_by_bond.csv", index=False, encoding="utf-8-sig")
    top_losses.to_csv(OUT_DIR / "top_extension_losses.csv", index=False, encoding="utf-8-sig")

    heatmap_svg(metrics, "net_delta_vs_vanilla", "Net CAGR delta vs vanilla", OUT_DIR / "net_delta_heatmap.svg")
    heatmap_svg(metrics, "turnover_ratio_vs_vanilla", "Turnover ratio vs vanilla", OUT_DIR / "turnover_ratio_heatmap.svg")
    summary_bar_svg(summary, OUT_DIR / "median_decomposition_bars.svg")
    heatmap_png(metrics, "net_delta_vs_vanilla", "Net CAGR delta vs vanilla", OUT_DIR / "net_delta_heatmap.png")
    heatmap_png(metrics, "turnover_ratio_vs_vanilla", "Turnover ratio vs vanilla", OUT_DIR / "turnover_ratio_heatmap.png")
    summary_bar_png(summary, OUT_DIR / "median_decomposition_bars.png")
    write_markdown(summary, metrics, extension_summary, top_losses, OUT_DIR / "keep_n_decomposition_summary.md")
    write_html_report(summary, metrics, extension_summary, top_losses, OUT_DIR / "keep_n_decomposition_report.html")

    print(f"wrote outputs to {OUT_DIR}")


if __name__ == "__main__":
    main()
