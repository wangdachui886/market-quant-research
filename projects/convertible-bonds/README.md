# China Convertible Bonds

![Research logic](../../assets/convertible-bonds/cb_logic_map.svg)

## Thesis

China convertible bonds are a small-capital, low-frequency quant market where personal capital can sometimes fit better than large institutional capital.

This line studies whether a structurally constrained market can support a research-frozen, executable candidate built from credit-aware dual-low logic, underlying-stock momentum, turnover control, and realistic execution assumptions.

## Current Decision

Status: research-frozen candidate, pre-live validation required.

```text
top12_keep37
weekly rebalance
T+2 execution assumption
15 bps one-way cost
C_rank_mom20 = price rank + premium rank + underlying stock 20-day momentum rank
buy top 12; retain existing holdings while still within top 37
```

![Final NAV and drawdown](../../assets/convertible-bonds/cb_01_final_nav_drawdown.png)

## Evidence Snapshot

| Strategy | CAGR | Max Drawdown | Calmar | Sharpe | Turnover |
|---|---:|---:|---:|---:|---:|
| Original `top10_keep29` | 18.14% | -23.78% | 0.763 | 0.937 | 27.77% |
| Final `top12_keep37` | 18.60% | -18.76% | 0.992 | 0.974 | 25.52% |
| Vanilla baseline | 10.24% | -28.51% | 0.359 | n/a | n/a |
| Equal-weight benchmark | 11.08% | -20.21% | 0.548 | n/a | n/a |

![Final scorecard](../../assets/convertible-bonds/cb_02_final_scorecard.png)

## Research Chain

| Stage | Public Evidence |
|---|---|
| Market fit and strategy frame | [01 Strategy Framework](reports/01_strategy_framework.md), [02 Research Journey](reports/02_research_journey_0_to_1_to_1plus.md) |
| Final performance | [03 Final Performance Report](reports/03_final_performance_report.md), [00 Sealed Final](reports/00_SEALED_FINAL.md) |
| Pre-live and technical assessment | [04 Pre-live Playbook](reports/04_pre_live_playbook.md), [05 Technical Assessment](reports/05_technical_assessment.md), [06 Capital and Risk Plan](reports/06_capital_and_risk_plan.md) |
| Robustness and retention audit | [Focused Validation](reports/topk_keepn_focused_validation_summary.md), [Stability Audit](reports/topk_keepn_stability_audit_summary.md) |
| Code path | [pre-live core](../../code/convertible-bonds/README.md), [historical research scripts](../../code/convertible-bonds/research-scripts/) |
| Result tables | [final outputs](results/final/), [validation tables](results/validation/) |

## Boundaries

This is not a mature live product. It still needs pre-live checks around fills, strong-call data, liquidity, rank drift, data updates, and operational discipline.

The strategy remains long-only and still carries convertible-bond/equity beta. ETF is used at portfolio level because internal MA/breadth switches were not strong enough to seal.

![Archive decision map](../../assets/convertible-bonds/cb_17_archive_decision_map.png)

## Public Evidence Anchors

- [Evidence Index](../../docs/evidence-index.md)
- [Data & Reproducibility](../../docs/data-and-reproducibility.md)
- [CB + ETF Bridge](../cb-etf-bridge/README.md)
