# Top-k Keep-n Focused Validation - 2026-05-08

Research-only focused validation. Original CSV files and strategy/core logic were not modified.

## Headline

- current `top10_keep29`: CAGR 18.14%, MDD -23.78%, Calmar 0.763, turnover 27.77%.
- candidate `top12_keep37`: CAGR 18.60%, MDD -18.76%, Calmar 0.992, turnover 25.52%.
- candidate delta: CAGR 0.46%, MDD 5.02%, Calmar 0.229.
- candidate leave-one-year-out Calmar win share: 100.00%.

## Top12 Keep-n Band

| keep_n | CAGR | MDD | Calmar | turnover | delta Calmar |
| --- | --- | --- | --- | --- | --- |
| 35 | 18.28% | -21.58% | 0.847 | 26.05% | 0.084 |
| 37 | 18.60% | -18.76% | 0.992 | 25.52% | 0.229 |
| 40 | 19.73% | -20.07% | 0.983 | 24.87% | 0.220 |
| 41 | 19.78% | -18.89% | 1.047 | 24.71% | 0.284 |

## Rank Drift - Key Variants

| label | rank p90 | rank max | >29 | >37 | carried share | holding days median/p90 |
| --- | --- | --- | --- | --- | --- | --- |
| `top10_keep29` | 19.000 | 29 | 0.00% | 0.00% | 75.97% | 15.000/39.900 |
| `top12_keep29` | 20.000 | 29 | 0.00% | 0.00% | 75.09% | 15.000/38.000 |
| `top10_keep37` | 23.000 | 37 | 4.62% | 0.00% | 78.50% | 15.000/41.000 |
| `top12_keep37` | 24.000 | 37 | 4.96% | 0.00% | 78.07% | 15.000/40.000 |

## Max Drawdown Windows

| window | label | total return | gross sum | cost sum |
| --- | --- | --- | --- | --- |
| top10_keep29_mdd_window | `top10_keep29` | -23.17% | -17.59% | -7.53% |
| top10_keep29_mdd_window | `top12_keep29` | -22.72% | -16.71% | -7.83% |
| top10_keep29_mdd_window | `top10_keep37` | -17.64% | -11.36% | -6.87% |
| top10_keep29_mdd_window | `top12_keep37` | -17.80% | -11.31% | -7.13% |
| top12_keep37_mdd_window | `top10_keep29` | -21.64% | -11.33% | -11.10% |
| top12_keep37_mdd_window | `top12_keep29` | -23.12% | -12.93% | -11.47% |
| top12_keep37_mdd_window | `top10_keep37` | -22.94% | -14.09% | -10.11% |
| top12_keep37_mdd_window | `top12_keep37` | -18.34% | -8.06% | -10.40% |

## Files

- `tables/full_and_annual_metrics.csv`
- `tables/rank_drift_summary.csv`
- `tables/holding_duration_summary.csv`
- `tables/leave_one_year_out.csv`
- `tables/pair_yearly_decomposition.csv`
- `tables/drawdown_window_summary.csv`
- `charts/calmar_heatmap.png`
- `charts/mdd_heatmap.png`
- `charts/rank_drift_key.png`
- `charts/key_nav_drawdown.png`
- `charts/leave_one_year_out_calmar.png`
- `charts/pair_yearly_decomposition.png`
