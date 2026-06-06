# Spot Trend Core

This directory contains the reusable core modules for the Crypto Spot Long-Only trend sleeve.

It is an engineering anchor, not a live trading bot. It does not connect to exchanges, does not submit orders, and does not store credentials.

## Modules

| File | Role |
|---|---|
| `config.py` | Fixed pool, parameters, cost assumptions, execution timing |
| `data_io.py` | Load OHLCV CSV files from a user-supplied cache directory |
| `indicators.py` | Upper breakout, EMA, ATR, and realized-volatility features |
| `signals.py` | Entry, hold, and exit signal generation |
| `portfolio.py` | Sleeve-level portfolio and order-plan calculation |
| `schema.py` | Data structures for signals and order plans |
| `state.py` | Optional local state persistence |
| `daily_signal.py` | CLI-style daily signal entry point |

## Usage Sketch

```bash
python code/crypto/spot-long-only/spot_trend_core/daily_signal.py \
  --data-dir code/crypto/spot-long-only/spot_data_cache \
  --total-equity 100000 \
  --out code/crypto/spot-long-only/local_order_plan.csv
```

The output path above is only an example. Order plans and live execution files should remain local and untracked.

## Data Boundary

Expected input is daily OHLCV CSV data for the configured spot symbols. Public research scripts can generate Binance daily kline caches, but generated caches are ignored by `.gitignore` and should not be committed.

## Live Boundary

This core only prepares signals and sizing logic. It intentionally excludes:

- exchange authentication;
- API keys or tokens;
- order submission;
- account synchronization;
- broker/exchange logs;
- live monitoring and alerting.
