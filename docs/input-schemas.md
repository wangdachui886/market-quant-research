# Input Schemas

This repository does not redistribute raw private or licensed market data. The schemas below document the minimum public input shape needed to inspect or adapt the code anchors.

## Convertible Bond Panel

Expected shape: one row per convertible bond per trading date.

| Column | Type | Meaning |
|---|---|---|
| `trade_date` | date-like | Trading date used for signal and return alignment |
| `cb_code` | string | Convertible bond identifier |
| `cb_close` | float | Convertible bond close price |
| `conversion_premium` | float | Conversion premium used in cross-sectional ranking |
| `underlying_close` | float | Underlying stock close price |
| `score` | float | Final ascending rank score; lower is better |
| `ret` | float | Daily holding return after the entry day |
| `ret_entry` | float | Entry-day return used after the configured execution lag |
| `is_tradable_day` | bool/int | Whether the bond is tradable on the date |
| `in_strong_redeem_window` | bool/int | Point-in-time strong-call risk flag |
| `issue_size` | float | Issue size or remaining scale used for liquidity/quality filters |
| `maturity_days` | int | Days to maturity |

The public pre-live core mainly needs `trade_date`, `cb_code`, `score`, `ret`, and `ret_entry` after upstream filters have already been applied.

## ETF Stabilizer Close Prices

Expected shape: `pandas.DataFrame` indexed by date.

Required close-price columns:

| Column | Asset Role |
|---|---|
| `510300.SH` | A-share broad equity sleeve |
| `513500.SH` | S&P 500 / cross-border equity sleeve |
| `511010.SH` | Treasury ETF / defensive bond fallback |
| `518880.SH` | Gold ETF / diversifier |

Optional execution backup:

| Column | Asset Role |
|---|---|
| `511360.SH` | Short-financing ETF backup; not the long-window research default |

## ETF NAV Prices

Expected shape: `pandas.DataFrame` indexed by date.

Optional NAV columns:

| Column | Use |
|---|---|
| `513500.SH` | Cross-border premium filter, calculated as `close / nav - 1` |

If NAV is unavailable, the public function logic does not block the trade by default. A production integration may choose to fail closed.

## Crypto Spot Daily Klines

The public research scripts can fetch Binance spot daily klines. Generated local cache files should remain untracked.

Minimum OHLCV-style columns after loading:

| Column | Type |
|---|---|
| `open_time` or `date` | date-like |
| `open` | float |
| `high` | float |
| `low` | float |
| `close` | float |
| `volume` | float |
| `quote_volume` | float |
| `trade_count` | int |

No API key is required for the public Binance daily kline endpoint used by the research scripts.

## Futures CTA Clean Returns

Expected shape: one CSV per futures symbol, indexed or keyed by date.

Minimum columns:

| Column | Type | Meaning |
|---|---|---|
| `date` | date-like | Trading date |
| `clean_return` | float | Daily return after dominant-contract switching has been adjusted to avoid hard-splice jumps |
| `dominant` | string, optional | Dominant contract identifier used on the date |
| `is_switch` | bool/int, optional | Whether the date is a dominant-contract switch date |

Carry scripts additionally expect:

| Column | Type | Meaning |
|---|---|---|
| `date` | date-like | Trading date |
| `carry` | float | Annualized near-vs-next contract carry estimate |

The public archive does not include Tushare tokens, `.env` files, local
`data_cache/` contents, or credentialed pull scripts.

## A-share Small-cap Processed Ports

Expected shape: yearly or panel CSVs generated from user-supplied raw A-share
market and finance files.

Core market columns:

| Column | Type | Meaning |
|---|---|---|
| `trade_date` | date-like | Trading date |
| `code` | string | Stock identifier |
| `close` / `adj_close` | float | Close or adjusted close |
| `amount` | float | Trading amount |
| `float_market_cap` | float | Float market capitalization used for size ranking |
| `is_st` | bool/int | ST or special-treatment flag |
| `is_limit_up` / `is_limit_down_est` | bool/int | Conservative limit-state estimates |

Execution-state columns:

| Column | Type | Meaning |
|---|---|---|
| `has_bar` | bool/int | Whether the stock has a market bar on the execution date |
| `can_buy_on_bar` | bool/int | Conservative buy feasibility flag |
| `can_sell_on_bar` | bool/int | Conservative sell feasibility flag |
| `feature_date` | date-like | Date when the signal is observed |
| `exec_date` | date-like | Earliest execution date after the signal |

Annual finance PIT columns:

| Column | Type | Meaning |
|---|---|---|
| `code` | string | Stock identifier |
| `report_period` | date-like/string | Financial reporting period |
| `pit_anchor_date` | date-like | Original announcement or correction-disclosure date |
| `effective_trade_date` | date-like | First trading date when the financial record is usable |
| `pe` / `pb` / `ps` | float, optional | Valuation fields used for diagnostics such as RPE |
