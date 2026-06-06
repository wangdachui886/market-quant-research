# Convertible Bonds Code Appendix

This appendix contains the final pre-live research core for the public `top12_keep37` convertible-bond candidate, plus selected historical research scripts that explain how the final candidate was reached.

## Can This Run?

| Component | Public runnable? | Data needed |
|---|---|---|
| `run_final_backtest.py` and `cb_pre_live_core/` | Partially | User-supplied convertible-bond panel, issue-size table, maturity-date table, and strong-call data |
| `run_daily_selection.py` | Partially | Same private data inputs; do not treat output as live instruction |
| `research-scripts/` | Inspectable, not standalone | Older private strategy package and private panel data |

## Public Role

This is the code path closest to the public conclusion:

```text
top_k = 12
keep_n = 37
C_rank_mom20 = price rank + premium rank + underlying stock 20-day momentum rank
weekly rebalance
T+2 execution assumption
15 bps one-way cost
```

## Current Core Files

| File | Role |
|---|---|
| `cb_pre_live_core/config.py` | Sealed parameters and relative data/output paths |
| `cb_pre_live_core/data.py` | Panel, issue-size, maturity-date loading |
| `cb_pre_live_core/universe.py` | Layer1 filters, including PIT strong-call notice filter |
| `cb_pre_live_core/signal.py` | `C_rank_mom20` scoring |
| `cb_pre_live_core/portfolio.py` | Weekly top-k/keep-n portfolio construction |
| `cb_pre_live_core/metrics.py` | CAGR, volatility, Sharpe, MDD, Calmar |
| `run_final_backtest.py` | Rebuild final daily returns, holdings, rank audit, and metrics |
| `run_daily_selection.py` | Generate a no-previous-holdings selection snapshot for local review only |

## Research Scripts

| File | Role |
|---|---|
| `research-scripts/run_walk_forward_gate.py` | Walk-forward gate and keep_n sensitivity |
| `research-scripts/keep_n_decomposition.py` | Retention-buffer decomposition |
| `research-scripts/keep25_vs_keep29_final.py` | Earlier keep_n candidate comparison |
| `research-scripts/real_cost_scan.py` | Cost-model sensitivity |
| `research-scripts/attribution_2022_2023.py` | 2022/2023 attribution diagnostics |

These scripts preserve research process. They are not advertised as one-command public runs.

## Reports And Results

- Project page: [Convertible Bonds](../../projects/convertible-bonds/README.md)
- Reports: [projects/convertible-bonds/reports](../../projects/convertible-bonds/reports/)
- Result CSVs: [projects/convertible-bonds/results](../../projects/convertible-bonds/results/)

## Governance

Do not add MA switches, maturity365, price75, liquidity hard filters, or other defensive modules into this core. New research should live in a separate archive or experiment folder.
