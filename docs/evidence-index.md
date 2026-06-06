# Evidence Index

This file maps the public GitHub pages back to the current local evidence anchors.

## Convertible Bonds

| Public Topic | Evidence Anchor | Public Role |
|---|---|---|
| Market fit and research path | Notion convertible-bond hub draft | Reader-facing hub draft |
| Final strategy card | Notion convertible-bond core evidence page | Main evidence page |
| Sealed/final research files | Convertible-bond final research archive | Final outputs and research archive |
| Strategy source | Convertible-bond historical strategy source | Code source, not all public by default |
| Public code appendix | `code/convertible-bonds/` | Migrated `top12_keep37` pre-live core |
| Historical sealed note | Convertible-bond sealed decision note | Historical research decision |
| Defense archive | Convertible-bond defense research archive | Archive / observation |

Key public metrics:

| Strategy | CAGR | Max Drawdown | Calmar | Sharpe | Turnover |
|---|---:|---:|---:|---:|---:|
| Final `top12_keep37` | 18.60% | -18.76% | 0.992 | 0.974 | 25.52% |
| Original `top10_keep29` | 18.14% | -23.78% | 0.763 | 0.937 | 27.77% |
| Vanilla baseline | 10.24% | -28.51% | 0.359 | n/a | n/a |

## Crypto

| Public Topic | Evidence Anchor | Public Role |
|---|---|---|
| Hub archive | Crypto Research Hub archive note | Current public positioning |
| Spot Long-Only baseline | Crypto Spot Long-Only baseline report | Fixed-rule definition |
| Final predeployment validation | Crypto Spot Long-Only final validation report | Execution/cost/data/liquidity evidence |
| Public code appendix | `code/crypto/spot-long-only/` | Migrated active baseline scripts |
| Failure conditions | Crypto Spot Long-Only failure-condition report | Governance and future review rules |
| Smart DCA | Smart DCA v0/v0t comparison note | Candidate accumulation evidence |

Key Spot Long-Only public evidence:

| Variant | CAGR | Sharpe | MDD | Calmar | Avg Exposure |
|---|---:|---:|---:|---:|---:|
| Same close gross | 44.32% | 1.82 | -24.10% | 1.84 | 19.83% |
| Next open gross | 44.28% | 1.82 | -24.09% | 1.84 | 19.83% |
| Next open 15bp | 43.42% | 1.79 | -24.90% | 1.74 | 19.84% |

## ETF Stabilizer

| Public Topic | Evidence Anchor | Public Role |
|---|---|---|
| Hub draft | ETF Stabilizer hub draft | Reader-facing hub draft |
| Evidence and variants | ETF Stabilizer evidence page | Public evidence page |
| Final implementation archive | ETF Stabilizer final implementation archive | Strategy card, code, reports |
| Public code appendix | `code/etf-stabilizer/` | Migrated target-weight logic |
| Right-side ETF sleeve | ETF right-side sleeve mechanism test | Archived mechanism test |

Key public metrics:

| Portfolio | CAGR | MDD | Calmar | Correlation to CB |
|---|---:|---:|---:|---:|
| CB only | 18.60% | -18.76% | 0.99 | 1.00 |
| 70% CB + 30% ETF Stabilizer | 15.49% | -10.77% | 1.44 | 0.25 |
| 70% CB + 30% Treasury fallback | 15.35% | -10.92% | 1.41 | 0.26 |

## A-share Small-cap Archive

| Public Topic | Evidence Anchor | Public Role |
|---|---|---|
| Pre-research report | A-share small-cap pre-research report | Gross-edge diagnostic |
| Final archive | A-share small-cap low-frequency archive note | Public decision boundary |

Public decision:

```text
Archive as observation / future optional satellite.
Do not promote to core strategy research now.
```
