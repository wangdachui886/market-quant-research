# Convertible Bonds Code Appendix

This appendix contains the final pre-live research core for the public `top12_keep37` convertible-bond candidate.

## Public Role

This is the code path closest to the Notion/GitHub public conclusion:

```text
top_k = 12
keep_n = 37
C_rank_mom20 = price rank + premium rank + underlying stock 20-day momentum rank
weekly rebalance
T+2 execution assumption
15 bps one-way cost
```

## Files

| File | Role |
|---|---|
| `cb_pre_live_core/config.py` | Sealed parameters and local data/output paths |
| `cb_pre_live_core/data.py` | Panel, issue-size, maturity-date loading |
| `cb_pre_live_core/universe.py` | Layer1 filters, including PIT strong-call notice filter |
| `cb_pre_live_core/signal.py` | `C_rank_mom20` scoring |
| `cb_pre_live_core/portfolio.py` | Weekly top-k/keep-n portfolio construction |
| `cb_pre_live_core/metrics.py` | CAGR, volatility, Sharpe, MDD, Calmar |
| `run_final_backtest.py` | Rebuild final daily returns, holdings, rank audit, and metrics |
| `run_daily_selection.py` | Generate latest no-previous-holdings selection snapshot |

## Data Boundary

Raw panel data is not included. The default config expects local files under:

```text
code/convertible-bonds/data/
```

That folder is ignored by `.gitignore`.

## Governance

Do not add MA switches, maturity365, price75, liquidity hard filters, or other defensive modules into this core. New research should live in a separate archive or experiment folder.

