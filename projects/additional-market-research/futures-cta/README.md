# Futures CTA Archive

Status: high-quality archive / reactivate only if capital and execution fit.

This line was archived because of deployment constraints, not because the
research signal was weak. Commodity futures showed a plausible low-correlation
trend/carry structure, but whole-lot contract granularity made the strategy
poorly suited to the current personal-capital range.

## Research Conclusion

```text
The signal structure is credible.
The personal deployment boundary is the bottleneck.
```

The useful public lesson is market-fit discipline: even a clean, low-correlation
engine should not be promoted if capital granularity distorts execution.

## Evidence Chain

| Step | Public Evidence | Code Anchor |
|---|---|---|
| Data foundation | [data pitfalls](reports/01_data_pitfalls.md), [Phase 2.1 findings](reports/03_phase_2_1_findings.md), [clean summary](results/phase-2-0-universe/14_all_symbols_clean_summary.csv) | [clean-return scripts](../../../code/futures-cta/Phase_2_0_universe/) |
| TSMOM baseline | [Phase 2.2 findings](reports/05_phase_2_2_findings.md), [TSMOM per-symbol table](results/phase-2-2-tsmom/tsmom_universe_voltarget_per_symbol.csv) | [TSMOM code](../../../code/futures-cta/Phase_2_2_tsmom/) |
| Carry and pooling | [Phase 2.3 findings](reports/07_phase_2_3_findings.md), [pooled per-symbol table](results/phase-2-3-carry/pooled_per_symbol.csv) | [carry code](../../../code/futures-cta/Phase_2_3_carry/) |
| OOS robustness | [Phase 2.4 findings](reports/08_phase_2_4_findings.md), [OOS decomposition](results/phase-2-4-robustness/oos_decompose_metrics.csv), [cost sweep](results/phase-2-4-robustness/cost_sweep_metrics.csv) | [robustness code](../../../code/futures-cta/Phase_2_4_robustness/) |
| Capital boundary | [Phase 2.4b/2.5a findings](reports/09_phase_2_4b_2_5a_findings.md), [capital ladder](results/phase-2-5-capital/capital_ladder_metrics.csv) | [capital ladder code](../../../code/futures-cta/Phase_2_5_capital/run_capital_ladder.py) |

## Key Public Metrics

### Core Baselines

| Variant | Sharpe | Return | Volatility | Max Drawdown |
|---|---:|---:|---:|---:|
| Equal-weight buy and hold | 0.60 | 7.7% | 12.8% | -20.6% |
| Vol-targeted TSMOM | 0.70 | 4.6% | 6.6% | -12.6% |
| Vol-targeted Carry | 0.68 | ~4.0% | ~6.0% | ~-12.9% |
| 0.5 TSMOM + 0.5 Carry | 0.86 | 4.3% | 5.0% | -8.9% |

### OOS Decomposition

| Test | Pool OOS Sharpe | TSMOM OOS Sharpe | Edge |
|---|---:|---:|---:|
| 19 symbols | 1.27 | 0.64 | +0.63 |
| 17 symbols, no gold/silver | 0.42 | -0.07 | +0.49 |
| 14 carry-valid symbols | 0.63 | 0.02 | +0.61 |

### Capital Ladder

| Capital | Sharpe | Net Return | Effective Positions | Interpretation |
|---|---:|---:|---:|---|
| CNY 100k | 0.31 | 0.4% | 0.3 | Structurally distorted |
| CNY 300k | 0.13 | 0.5% | 3.8 | Too sparse |
| CNY 1m | 0.18 | 0.7% | 8.6 | Still distorted |
| CNY 3m | 0.88 | 4.3% | 11.5 | First usable zone |
| CNY 10m | 1.06 | 5.6% | 13.0 | Better execution fit |

## Selected Figures

- [Clean vs raw NAV](../../../assets/futures-cta/13_M_clean_vs_raw_nav.png)
- [Raw vs clean NAV grid](../../../assets/futures-cta/15_raw_vs_clean_nav_grid.png)
- [TSMOM universe vol-targeted](../../../assets/futures-cta/tsmom_universe_voltarget.png)
- [Pooled TSMOM/Carry comparison](../../../assets/futures-cta/pooled_compare.png)
- [OOS decomposition](../../../assets/futures-cta/oos_decompose.png)
- [Capital ladder](../../../assets/futures-cta/capital_ladder.png)

## Public Boundary

The public code is inspectable-first. It expects user-supplied clean futures
return and carry panels, and it does not include credentialed data fetchers,
`.env` files, API tokens, local caches, or broker/live execution material.
