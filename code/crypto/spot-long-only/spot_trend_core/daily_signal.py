from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

try:
    from .config import DEFAULT_CONFIG
    from .data_io import load_cache_dir
    from .portfolio import build_portfolio_order_plan
    from .signals import generate_latest_snapshot
    from .state import load_states
except ImportError:  # Allows direct execution: python Core/daily_signal.py
    import sys

    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from Core.config import DEFAULT_CONFIG
    from Core.data_io import load_cache_dir
    from Core.portfolio import build_portfolio_order_plan
    from Core.signals import generate_latest_snapshot
    from Core.state import load_states


def _recent_quote_volume(df: pd.DataFrame, days: int = 20) -> float | None:
    if "QuoteVolume" not in df.columns:
        return None
    value = df["QuoteVolume"].tail(days).median()
    if pd.isna(value):
        return None
    return float(value)


def run_daily_signal(
    data_dir: str | Path,
    total_equity: float,
    out: str | Path,
    state_path: str | Path | None = None,
    estimate_with_close: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    data = load_cache_dir(data_dir, symbols=DEFAULT_CONFIG.symbols)
    states = load_states(state_path) if state_path else {}

    snapshots = [
        generate_latest_snapshot(symbol, df, config=DEFAULT_CONFIG)
        for symbol, df in data.items()
    ]

    current_units = {symbol: states.get(symbol).units for symbol in states if states.get(symbol)}
    prices = {snap.symbol: snap.close for snap in snapshots if estimate_with_close and snap.close}
    quote_volumes = {symbol: _recent_quote_volume(df) for symbol, df in data.items()}

    plans = build_portfolio_order_plan(
        snapshots=snapshots,
        total_equity=total_equity,
        current_units_by_symbol=current_units,
        execution_price_by_symbol=prices,
        quote_volume_by_symbol=quote_volumes,
        config=DEFAULT_CONFIG,
    )

    signal_df = pd.DataFrame([snapshot.to_dict() for snapshot in snapshots])
    order_df = pd.DataFrame([plan.to_dict() for plan in plans])

    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    order_df.to_csv(out_path, index=False, encoding="utf-8-sig")
    signal_df.to_csv(out_path.with_name(f"{out_path.stem}_signals.csv"), index=False, encoding="utf-8-sig")
    return signal_df, order_df


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate close-confirmed spot long-only signals and order plan.")
    parser.add_argument("--data-dir", required=True, help="Directory containing *_spot_daily.csv files.")
    parser.add_argument("--total-equity", required=True, type=float, help="Total account equity in quote currency.")
    parser.add_argument("--out", required=True, help="CSV path for the order plan output.")
    parser.add_argument("--state", default=None, help="Optional JSON state file with current units by symbol.")
    parser.add_argument(
        "--estimate-with-close",
        action="store_true",
        help="Estimate units with signal close. Live execution should still use next-open order prices.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_daily_signal(
        data_dir=args.data_dir,
        total_equity=args.total_equity,
        out=args.out,
        state_path=args.state,
        estimate_with_close=args.estimate_with_close,
    )


if __name__ == "__main__":
    main()
