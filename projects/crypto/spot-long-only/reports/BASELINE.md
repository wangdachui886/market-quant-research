# BASELINE - Crypto Spot Long-Only Trend Sleeve

## 1. Role

This strategy is a spot-only, long-only trend sleeve. It does not replace DCA and does not carry a hidden BTC core.

## 2. Fixed Rule

- Universe: BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, DOGEUSDT, BNBUSDT, TRXUSDT, ADAUSDT, LINKUSDT, AVAXUSDT, NEARUSDT, LTCUSDT, AAVEUSDT, UNIUSDT
- Window: 2020-01-01 -> 2026-05-22
- Entry: close above previous 20-day high and close above previous EMA200.
- Position sizing: at entry, invest `min(1, 40% / max(20-day realized vol, 20% vol floor))` of sleeve equity.
- Holding: fixed spot units after entry; no daily rebalancing back to target weight.
- Exit: close-based 3ATR trailing exit, confirmed on daily close.
- Cash: no yield in strategy return.
- Shorting: prohibited.
- Per-symbol tuning: prohibited.

## 3. Data

Spot OHLCV is cached in `spot_data_cache/` from Binance spot daily klines.

- BTCUSDT: spot data starts 2020-01-01
- ETHUSDT: spot data starts 2020-01-01
- SOLUSDT: spot data starts 2020-08-11
- XRPUSDT: spot data starts 2020-01-01
- DOGEUSDT: spot data starts 2020-01-01
- BNBUSDT: spot data starts 2020-01-01
- TRXUSDT: spot data starts 2020-01-01
- ADAUSDT: spot data starts 2020-01-01
- LINKUSDT: spot data starts 2020-01-01
- AVAXUSDT: spot data starts 2020-09-22
- NEARUSDT: spot data starts 2020-10-14
- LTCUSDT: spot data starts 2020-01-01
- AAVEUSDT: spot data starts 2020-10-15
- UNIUSDT: spot data starts 2020-09-17

## 4. Universe Screen

Candidates are screened before backtesting:

- Minimum history days: 1825
- Minimum data coverage: 95%
- Minimum recent median quote volume: 10,000,000 USDT over the latest 90 days
- Minimum recent median trade count: 20,000 trades per day over the latest 90 days
- Stablecoins, fiat pairs, and leveraged tokens are excluded.

## 5. Promotion Gates

- Gross edge must be visible at the universe portfolio level.
- Edge cannot be explained by only one coin or one year.
- New filters are observations first; they are not allowed into trading logic without separate OOS or walk-forward evidence.
- Cost and slippage checks happen after gross edge is established.
