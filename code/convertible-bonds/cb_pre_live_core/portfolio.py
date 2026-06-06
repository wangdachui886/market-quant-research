"""Weekly portfolio construction with top_k and keep_n retention."""

from __future__ import annotations

import numpy as np
import pandas as pd


def week_end_dates(sorted_dates: np.ndarray) -> np.ndarray:
    tmp = pd.DataFrame({"d": sorted_dates})
    iso = tmp["d"].dt.isocalendar()
    tmp["yw"] = iso["year"].astype(str) + iso["week"].astype(str).str.zfill(2)
    return tmp.groupby("yw")["d"].max().sort_values().values


def pick_holdings(snap: pd.DataFrame, prev: set[str], top_k: int, keep_n: int) -> list[str]:
    if snap.empty or top_k < 1:
        return []
    s = snap.sort_values(["score", "cb_code"], ascending=[True, True]).copy()
    s["score_rank"] = np.arange(1, len(s) + 1)
    rank_map = s.set_index("cb_code")["score_rank"]
    selected: set[str] = set()
    for code in prev:
        if code in rank_map.index and int(rank_map.loc[code]) <= keep_n:
            selected.add(code)
    for code in s["cb_code"]:
        if len(selected) >= top_k:
            break
        selected.add(code)
    return s.loc[s["cb_code"].isin(selected)].head(top_k)["cb_code"].tolist()


def build_holdings(scored: pd.DataFrame, top_k: int, keep_n: int, entry_lag: int = 2) -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = np.sort(scored["trade_date"].unique())
    d2i = {d: i for i, d in enumerate(dates)}
    rbals = week_end_dates(dates)
    selections: dict[pd.Timestamp, list[str]] = {}
    prev: set[str] = set()
    rank_rows: list[dict] = []
    for rd in rbals:
        snap = scored.loc[scored["trade_date"] == rd].sort_values(["score", "cb_code"]).copy()
        if snap.empty:
            continue
        snap["score_rank"] = np.arange(1, len(snap) + 1)
        top = pick_holdings(snap, prev, top_k, keep_n)
        if not top:
            continue
        selections[pd.Timestamp(rd)] = top
        rank_map = snap.set_index("cb_code")["score_rank"]
        prev_set = set(prev)
        for code in top:
            rank_rows.append({
                "signal_date": pd.Timestamp(rd),
                "cb_code": code,
                "score_rank": int(rank_map.loc[code]),
                "is_carried": bool(code in prev_set),
            })
        prev = set(top)
    rows: list[dict] = []
    rb = sorted(selections)
    for i, rd in enumerate(rb):
        si = d2i[np.datetime64(rd)] + entry_lag
        if i + 1 < len(rb):
            ei = min(d2i[np.datetime64(rb[i + 1])] + entry_lag - 1, len(dates) - 1)
        else:
            ei = len(dates) - 1
        if si >= len(dates) or si > ei:
            continue
        old = set() if i == 0 else set(selections[rb[i - 1]])
        new = set(selections[rd])
        buys = new - old
        for code in selections[rd]:
            for j in range(si, ei + 1):
                rows.append({
                    "signal_date": rd,
                    "trade_date": pd.Timestamp(dates[j]),
                    "cb_code": code,
                    "is_entry": bool((j == si) and (code in buys)),
                    "turnover": len(buys) / max(top_k, 1) if j == si and i >= 1 else 0.0,
                })
    return pd.DataFrame(rows), pd.DataFrame(rank_rows)


def daily_returns(scored: pd.DataFrame, holdings: pd.DataFrame, cost_one_way_bp: float) -> pd.DataFrame:
    h = holdings.merge(scored[["trade_date", "cb_code", "ret", "ret_entry"]], on=["trade_date", "cb_code"], how="left")
    h["ret_used"] = np.where(h["is_entry"], h["ret_entry"], h["ret"])
    gross = h.groupby("trade_date")["ret_used"].mean().sort_index().fillna(0.0)
    turnover = h.groupby("trade_date")["turnover"].max().reindex(gross.index).fillna(0.0)
    cost = -2.0 * turnover * cost_one_way_bp / 1e4
    out = pd.DataFrame({"gross": gross, "turnover": turnover, "cost": cost, "net": gross + cost})
    return out.reset_index()
