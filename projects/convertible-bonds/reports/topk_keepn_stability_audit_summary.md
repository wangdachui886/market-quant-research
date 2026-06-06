# Top-k Keep-n Stability Audit - 2026-05-08

Non-parameter robustness audit. This is not a new optimization pass.

## Rebalance Weekday Shift

| weekday | top12_keep37 CAGR | MDD | Calmar | delta Calmar vs current same weekday |
| --- | --- | --- | --- | --- |
| Mon | 17.77% | -20.19% | 0.880 | 0.188 |
| Tue | 20.39% | -22.27% | 0.915 | 0.141 |
| Wed | 18.23% | -28.88% | 0.631 | -0.114 |
| Thu | 15.19% | -23.13% | 0.657 | -0.118 |
| Fri | 18.60% | -18.76% | 0.992 | 0.229 |

## Execution Lag Shift

| entry lag | top12_keep37 CAGR | MDD | Calmar | delta Calmar vs current same lag |
| --- | --- | --- | --- | --- |
| T+1 | 20.34% | -22.39% | 0.908 | 0.098 |
| T+2 | 18.60% | -18.76% | 0.992 | 0.229 |
| T+3 | 17.29% | -24.97% | 0.692 | 0.042 |

## Rank / Retention Audit

- `top12_keep37` rank mean/median/p75/p90: 10.190 / 7.000 / 14.000 / 24.000.
- `top12_keep37` rank > top_k share: 28.94%; rank > top_k+10 share: 11.77%.
- `top12_keep37` rank > 29 share: 4.93%; rank > 37 share: 0.00%.
- `top12_keep37` holding days median/p90/max: 15.000 / 40.000 / 269.
- `top12_keep37` rank 30-37 contribution sum: 17.56%.

| label | rank p90 | >29 | >37 | median holding days | >=60d day share | rank30-37 contribution |
| --- | --- | --- | --- | --- | --- | --- |
| `top10_keep29` | 19.000 | 0.00% | 0.00% | 15.000 | 17.49% | 0.00% |
| `top12_keep37` | 24.000 | 4.93% | 0.00% | 15.000 | 22.18% | 17.56% |
| `top12_keep40` | 25.000 | 6.44% | 1.47% | 16.000 | 22.74% | 14.28% |
| `top12_keep41` | 26.000 | 6.77% | 1.84% | 16.000 | 22.46% | 14.36% |

## Files

- `tables/rebalance_weekday_metrics.csv`
- `tables/execution_lag_metrics.csv`
- `tables/rank_audit_summary.csv`
- `tables/rank_bin_contribution.csv`
- `tables/worst_retained_episodes.csv`
- `tables/best_retained_episodes.csv`
- `charts/rebalance_weekday_calmar_delta.png`
- `charts/execution_lag_calmar_delta.png`
- `charts/rank_audit_key.png`
- `charts/rank_bin_contribution.png`
