# Market Quant Research Portfolio

This repository is the evidence layer for my market quant research portfolio.

The Notion portfolio is the public reading interface. This GitHub repository is the structured research archive: strategy cards, evidence maps, reproducibility notes, selected figures, source anchors, and archive decisions.

本仓库是 Notion 作品集的证据层。Notion 负责阅读体验和叙事，GitHub 负责研究结构、代码锚点、数据口径、图表来源、复现说明和归档纪律。

## Start Here

| Section | Role | Status |
|---|---|---|
| [China Convertible Bonds](projects/convertible-bonds/README.md) | Flagship structural-alpha research line | Research-frozen / pre-live validation |
| [Crypto Quant Research](projects/crypto/README.md) | Flagship high-volatility market research line | Active baseline + candidate + archives |
| [ETF Stabilizer](projects/etf-stabilizer/README.md) | Portfolio stabilizer beside the convertible-bond core | Sealed stabilizer candidate |
| [Portfolio Bridge](projects/portfolio-bridge/README.md) | Converts single-strategy evidence into portfolio construction | Current public bridge |
| [A-share Small-cap Archive](projects/a-share-small-cap-archive/README.md) | Pre-research archive and falsification evidence | Archived / observation only |
| [Code Appendix](code/README.md) | Curated scripts only, no raw data or secrets | Public code appendix |

## Repository Logic

The portfolio is not built around one lucky return curve. It is built around a repeated research process:

1. define whether the market fits real individual-investor constraints;
2. identify a plausible return source before writing strategy code;
3. test a simple baseline before adding variables;
4. evaluate costs, execution, robustness, and failure modes;
5. promote, narrow, or archive the research line.

This repository keeps that process visible. Failed or downgraded ideas are not hidden, because they explain what the final choices are not trying to do.

## Current Research Map

![Convertible bond logic](assets/convertible-bonds/cb_logic_map.svg)

The current public structure is:

- Convertible bonds and Crypto are the two flagship lines.
- ETF is a supporting portfolio-stabilizer line.
- The bridge page explains why a lower-return sleeve can still improve the full capital curve.
- A-share small-cap remains a pre-research archive, not a core public strategy line.

## Publication Boundary

This repository is for research presentation and education. It is not investment advice, solicitation, live trading instruction, or a promise that any strategy will remain profitable.

Raw data, API keys, broker/live-trading files, licensed datasets, and personal execution records should not be committed here. See [Migration Scope](docs/migration-scope.md) and [Data & Reproducibility](docs/data-and-reproducibility.md).

## Reader Path

For a quick public read, start with:

1. [Portfolio Bridge](projects/portfolio-bridge/README.md)
2. [Convertible Bonds](projects/convertible-bonds/README.md)
3. [Crypto](projects/crypto/README.md)
4. [ETF Stabilizer](projects/etf-stabilizer/README.md)

For a reviewer who wants to check research discipline, start with:

1. [Evidence Index](docs/evidence-index.md)
2. [Research Governance](docs/research-governance.md)
3. [Migration Scope](docs/migration-scope.md)
4. [GitHub Release Checklist](docs/github-release-checklist.md)

For a reviewer who wants code anchors, start with:

1. [Convertible Bonds Code](code/convertible-bonds/README.md)
2. [Crypto Spot Long-Only Code](code/crypto/spot-long-only/README.md)
3. [ETF Stabilizer Code](code/etf-stabilizer/README.md)
