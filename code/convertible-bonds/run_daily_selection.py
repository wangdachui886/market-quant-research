from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cb_pre_live_core.config import FinalConfig
from cb_pre_live_core.data import load_issue_sizes, load_maturity_dates, load_panel
from cb_pre_live_core.portfolio import pick_holdings
from cb_pre_live_core.signal import add_score_and_returns
from cb_pre_live_core.universe import build_layer1


def main() -> None:
    cfg = FinalConfig()
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    raw = load_panel(cfg)
    universe = build_layer1(raw, load_issue_sizes(cfg), load_maturity_dates(cfg), cfg)
    scored = add_score_and_returns(universe)
    latest = scored["trade_date"].max()
    snap = scored.loc[scored["trade_date"] == latest].sort_values(["score", "cb_code"]).copy()
    selected = pick_holdings(snap, set(), cfg.top_k, cfg.keep_n)
    cols = ["trade_date", "cb_code", "cb_close", "conversion_premium", "mom_20d", "score"]
    if "cb_name" in snap.columns:
        cols.insert(2, "cb_name")
    out = snap.loc[snap["cb_code"].isin(selected), cols].copy()
    out = out.sort_values(["score", "cb_code"])
    out.to_csv(cfg.output_dir / "latest_selection_no_prev_holdings.csv", index=False, encoding="utf-8-sig")
    print(f"latest signal date: {pd.Timestamp(latest).date()}")
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
