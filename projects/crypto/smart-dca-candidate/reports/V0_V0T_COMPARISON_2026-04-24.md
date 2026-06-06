# Smart DCA v0 vs v0t (2026-04-24)

## Test Setup

- Pool: `100,000 / 3 = 33,333 USDT`
- Trade window: `2020-01-01` to latest
- Data warmup start: `2017-08-17`
- Fee: `0.05%`
- Baseline: fixed weekly DCA

## Key Results

| Metric | Smart v0 | Smart v0t | Baseline |
|---|---:|---:|---:|
| End NAV (USDT) | 289,281.92 | 278,707.99 | 131,205.89 |
| CAGR | 40.78% | 39.95% | 24.22% |
| Sharpe | 1.018 | 1.019 | 0.711 |
| Calmar | 0.745 | 0.707 | 0.366 |
| Max DD % | -54.71% | -56.49% | -66.10% |
| Max DD $ | -210,574.01 | -179,119.65 | -104,227.68 |
| Avg buy $/BTC | 15,733.64 | 15,733.64 | 19,748.01 |
| End inv $/BTC | 19,406.05 | 19,990.18 | 19,748.01 |
| # SELL trades | 17 | 31 | 0 |

## Interpretation

- v0t captures more moderate-overheat exits (`MM > 1.5`) and increases sell count.
- v0t improves cash buffer and reduces max drawdown in dollar terms.
- v0 keeps slightly higher final NAV and Calmar in this sample.
- Both v0 and v0t strongly beat baseline on risk-adjusted performance and accumulation cost.

## Output Artifacts

- `outputs/smart_dca_v0t/smart_dca_v0t_nav.png`
- `outputs/smart_dca_v0t/smart_dca_v0t_trades_v0.png`
- `outputs/smart_dca_v0t/smart_dca_v0t_trades_v0t.png`
- `outputs/smart_dca_v0t/smart_dca_v0t_trades.csv`
