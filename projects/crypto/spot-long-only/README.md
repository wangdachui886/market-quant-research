# Crypto Spot Long-Only Trend Sleeve

## Current Decision

Status: active public baseline.

This is the Crypto line currently strong enough to keep as a public baseline. It is designed to participate in right-tail trend moves without using short exposure, leverage, per-symbol tuning, or intraday execution assumptions.

## Rule Summary

```text
Universe: liquid major Binance spot pairs
Entry: close above prior 20-day high and prior EMA200
Exit: close-based 3ATR trailing stop
Sizing: volatility-scaled at entry
Cash: idle when no sleeve signal exists
Shorting: prohibited
Per-symbol tuning: prohibited
```

## Research Process

| Stage | Script | Report | Result Tables |
|---|---|---|---|
| Structure review | [01](../../../code/crypto/spot-long-only/research-scripts/01_spot_long_only_structure_review.py) | n/a | n/a |
| Universe baseline | [02](../../../code/crypto/spot-long-only/research-scripts/02_spot_universe_baseline.py) | [baseline report](reports/02_spot_universe_baseline_report.md) | [baseline results](results/baseline/) |
| Attribution | [03](../../../code/crypto/spot-long-only/research-scripts/03_spot_baseline_attribution.py) | [attribution report](reports/03_spot_baseline_attribution_report.md) | [attribution results](results/attribution/) |
| Pool comparison | [04](../../../code/crypto/spot-long-only/research-scripts/04_pool_comparison.py) | [pool comparison report](reports/04_pool_comparison_report.md) | [pool results](results/pool-comparison/) |
| Robustness | [05](../../../code/crypto/spot-long-only/research-scripts/05_pool_robustness.py), [06](../../../code/crypto/spot-long-only/research-scripts/06_normalized_pool_compare.py) | [robustness report](reports/05_pool_robustness_report.md), [normalized comparison](reports/06_normalized_pool_compare_report.md) | [robustness results](results/robustness/) |
| Mechanism and walk-forward | [07](../../../code/crypto/spot-long-only/research-scripts/07_mechanism_explanation.py), [08](../../../code/crypto/spot-long-only/research-scripts/08_walk_forward_time_slice.py) | [mechanism](reports/07_mechanism_explanation_report.md), [walk-forward](reports/08_walk_forward_time_slice_report.md) | [walk-forward results](results/walk-forward/) |
| Deployment boundary | [09](../../../code/crypto/spot-long-only/research-scripts/09_boundary_deployment_tests.py), [10](../../../code/crypto/spot-long-only/research-scripts/10_final_predeployment_validation.py) | [boundary tests](reports/09_boundary_deployment_tests_report.md), [final validation](reports/10_final_predeployment_validation_report.md) | [boundary tests](results/boundary-tests/), [final validation](results/final-validation/) |
| Buy-and-hold comparison and failure rules | [11](../../../code/crypto/spot-long-only/research-scripts/11_buy_hold_static_compare.py) | [buy-hold comparison](reports/11_buy_hold_static_compare_report.md), [universe rules](reports/12_universe_management_rules.md), [failure conditions](reports/13_strategy_failure_conditions.md) | [buy-hold comparison](results/buy-hold-compare/) |

## Engineering Anchor

The cleaned operational-style core lives at:

- [spot_trend_core](../../../code/crypto/spot-long-only/spot_trend_core/)

The research scripts remain script-like because they preserve the research process. Future work can modularize them without changing the public evidence chain.
