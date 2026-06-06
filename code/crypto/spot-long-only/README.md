# Crypto Spot Long-Only Code Appendix

This appendix contains the scripts behind the public Crypto active baseline.

## Public Role

The strategy is a spot-only, long-only trend sleeve:

```text
entry: close above prior 20-day high and above prior EMA200
exit: close-based 3ATR trailing exit
sizing: volatility-scaled at entry
cash: idle when no sleeve signal exists
shorting: prohibited
per-symbol tuning: prohibited
```

## Files

| File | Role |
|---|---|
| `02_spot_universe_baseline.py` | Baseline universe screening, Binance daily spot data fetch/cache, signal generation, baseline report |
| `10_final_predeployment_validation.py` | Execution-lag, cost, period, data-integrity, and liquidity-capacity validation |

## Data Boundary

The baseline script fetches public Binance spot daily klines and caches them under:

```text
code/crypto/spot-long-only/spot_data_cache/
```

That cache is ignored by `.gitignore` and should not be committed.

## Why Smart DCA Is Not Here Yet

Smart DCA remains a public candidate in the docs, but the raw script also fetches external data and writes a local `.cache`. It should be cleaned into a separate appendix before publication.

