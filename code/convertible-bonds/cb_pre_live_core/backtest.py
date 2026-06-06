"""End-to-end pre-live backtest."""

from __future__ import annotations

from .config import FinalConfig
from .data import load_issue_sizes, load_maturity_dates, load_panel
from .metrics import calc_metrics
from .portfolio import build_holdings, daily_returns
from .signal import add_score_and_returns
from .universe import build_layer1


def run_backtest(cfg: FinalConfig | None = None):
    cfg = cfg or FinalConfig()
    raw = load_panel(cfg)
    issue_sizes = load_issue_sizes(cfg)
    maturity_dates = load_maturity_dates(cfg)
    universe = build_layer1(raw, issue_sizes, maturity_dates, cfg)
    scored = add_score_and_returns(universe)
    holdings, ranks = build_holdings(scored, cfg.top_k, cfg.keep_n, cfg.entry_lag)
    daily = daily_returns(scored, holdings, cfg.cost_one_way_bp)
    metrics = calc_metrics(daily.set_index("trade_date")["net"], cfg.rf_annual)
    return {"daily": daily, "holdings": holdings, "ranks": ranks, "metrics": metrics}
