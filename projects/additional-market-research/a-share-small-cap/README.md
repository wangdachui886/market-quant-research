# A-share Small-cap Archive

Status: archived / observation only.

This archive covers one narrow branch: low-frequency, long-only A-share
small-cap exposure. The gross engine was strong, but execution frictions,
suspensions/no-bar states, sell-fail risk, and weak-market beta made the line
unsuitable for the current core portfolio.

## Research Conclusion

```text
Strong gross return is not enough.
The risk structure did not fit the core book.
```

This is market knowledge, not a current flagship strategy. Future reuse should
be observation or optional satellite only unless a new market-risk module can
improve Calmar without destroying the gross edge.

## Evidence Chain

| Step | Public Evidence | Code Anchor |
|---|---|---|
| Data and stateful baseline | [stateful baseline report](reports/pre_research_v2_stateful_portfolio_zh.md), [summary table](results/stateful-baseline/stateful_summary.csv) | [baseline scripts](../../../code/a-share-small-cap/research/pre_research/) |
| Drawdown anatomy | [drawdown anatomy report](reports/baseline_drawdown_anatomy_v2_zh.md), [risk-source summary](results/drawdown-anatomy/risk_source_period_summary.csv) | [drawdown script](../../../code/a-share-small-cap/research/pre_research/run_baseline_drawdown_anatomy_v2.py) |
| RPE factor diagnostic | [RPE factor report](reports/rpe_factor_v1_diagnostics_zh.md), [IC summary](results/rpe-diagnostics/rpe_ic_full.csv), [quintile return summary](results/rpe-diagnostics/rpe_quintile_return_summary.csv) | [RPE diagnostic script](../../../code/a-share-small-cap/research/pre_research/run_rpe_factor_v1.py) |
| RPE portfolio test | [RPE stateful report](reports/rpe_stateful_portfolio_v1_zh.md), [pass/fail checks](results/rpe-stateful/rpe_stateful_pass_fail_checks.csv) | [RPE portfolio script](../../../code/a-share-small-cap/research/pre_research/run_rpe_stateful_portfolio_v1.py) |
| RPE failure anatomy | [RPE failure report](reports/rpe_failure_anatomy_v1_zh.md), [future fundamentals](results/rpe-failure-anatomy/future_fundamental_by_strategy.csv) | [failure anatomy script](../../../code/a-share-small-cap/research/pre_research/run_rpe_failure_anatomy_v1.py) |
| Execution/liquidity guard | [guard report](reports/execution_liquidity_guard_v1_zh.md), [guard summary](results/execution-liquidity-guard/guard_summary.csv) | [guard script](../../../code/a-share-small-cap/research/pre_research/run_execution_liquidity_guard_v1.py) |
| Size migration ladder | [size ladder report](reports/size_exposure_ladder_v1_zh.md), [size ladder summary](results/size-exposure-ladder/size_ladder_summary.csv) | [size ladder script](../../../code/a-share-small-cap/research/pre_research/run_size_exposure_ladder_v1.py) |

## Key Public Metrics

### Stateful Baseline

| Metric | Baseline |
|---|---:|
| Annualized return | 30.72% |
| 30bps cost annualized return | 27.27% |
| Max drawdown | -66.97% |
| Worst 12m | -59.36% |
| 2016-2018 annualized return | -15.78% |
| 2016-2018 max drawdown | -56.75% |
| Sell fail rate | 11.83% |

### RPE Result

RPE means current PE relative to the stock's own historical median PE. It had
real signal evidence, but it did not replace the baseline portfolio.

| Variant | Ann. Return | 30bps Ann. Return | Max DD | 2016-2018 Ann. | Sell Fail |
|---|---:|---:|---:|---:|---:|
| Baseline | 30.72% | 27.27% | -66.97% | -15.78% | 11.83% |
| RPE top100 | 26.23% | 24.51% | -69.05% | -16.32% | 15.78% |
| Size-controlled RPE | 27.98% | 26.00% | -68.65% | -14.38% | 14.24% |

### Size Migration

| Bucket | Ann. Return | Max DD | Calmar |
|---|---:|---:|---:|
| p10-50 baseline | 30.72% | -66.97% | 0.46 |
| p20-30 | 27.57% | -69.94% | 0.39 |
| p30-40 | 22.80% | -69.38% | 0.33 |
| p50-70 | 16.69% | -72.44% | 0.23 |
| largest top100 | 12.28% | -69.26% | 0.18 |

## Selected Figures

- [Stateful NAV](figures/stateful_portfolio_nav.png)
- [Stateful drawdown](figures/stateful_portfolio_drawdown.png)
- [Forced-state PnL](figures/stateful_forced_state_pnl.png)
- [RPE stateful NAV](figures/rpe_stateful_nav.png)
- [RPE stateful drawdown](figures/rpe_stateful_drawdown.png)
- [Future profit YoY by strategy](figures/future_profit_yoy_by_strategy.png)
- [Execution/liquidity guard NAV](figures/execution_liquidity_guard_v1_nav.png)
- [Size ladder Calmar](figures/size_ladder_calmar.png)

## Public Boundary

The public archive includes research scripts and selected result tables, but not
raw market data, processed private panels, full stock-level event dumps, broker
files, current order plans, or any credentialed data source.
