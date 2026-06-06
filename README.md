# Market Quant Research Portfolio

This repository is the technical evidence layer for my market quant research portfolio.

Notion is the public reading interface. GitHub is the inspectable research archive: code, selected result tables, research reports, evidence maps, reproducibility notes, and archive decisions.

中文说明：本仓库是 Notion 量化研究作品集的技术证据层；Notion 偏叙事和阅读体验，GitHub 偏代码锚点、结果表、图表来源和复现边界。

See [DISCLAIMER](DISCLAIMER.md) and [LICENSE](LICENSE) before reusing any material.

## Start Here

| Section | Role | Current Status |
|---|---|---|
| [Portfolio Map](docs/portfolio-map.md) | One-page map of the whole research portfolio | Entry point |
| [China Convertible Bonds](projects/convertible-bonds/README.md) | Flagship structural-alpha research line | Research-frozen / pre-live validation |
| [Crypto Quant Research](projects/crypto/README.md) | Flagship high-volatility market research line | Active baseline + candidate + archives |
| [ETF Stabilizer](projects/etf-stabilizer/README.md) | Supporting portfolio-stabilizer sleeve | Sealed stabilizer candidate |
| [CB + ETF Bridge](projects/cb-etf-bridge/README.md) | Bridge between the convertible-bond core and ETF sleeve | Portfolio construction evidence |
| [A-share Small-cap Archive](projects/a-share-small-cap-archive/README.md) | Pre-research archive and falsification evidence | Archived / observation only |
| [Code Appendix](code/README.md) | Public code anchors and run-status notes | Inspectable code appendix |

## Portfolio Research Map

The portfolio is not one strategy page with several attachments. It is a research system with different roles:

| Layer | Research Line | What It Proves |
|---|---|---|
| Flagship A | Convertible Bonds | Market fit, structural edge, cost/execution realism, robustness, and pre-live discipline |
| Flagship B | Crypto Spot Long-Only | High-volatility market triage, right-tail participation, failure boundaries, and public-data validation |
| Candidate | Smart DCA | Accumulation discipline for capital that already wants BTC exposure; not a finished alpha claim |
| Supporting Sleeve | ETF Stabilizer | Portfolio-level drawdown control and allocation thinking, not standalone alpha hunting |
| Bridge | CB + ETF | How a lower-return sleeve can improve the total capital curve beside the convertible-bond core |
| Archive | A-share Small-cap and failed modules | Evidence that weak or unfitted ideas are narrowed or archived instead of over-optimized |

The convertible-bond logic map now lives inside the [Convertible Bonds project](projects/convertible-bonds/README.md), because it explains that line specifically, not the whole portfolio.

## Research Process

Across markets, the process is:

1. define whether the market fits real individual-investor constraints;
2. identify a plausible return source before writing strategy code;
3. test a simple baseline before adding variables;
4. evaluate costs, execution, robustness, and failure modes;
5. promote, narrow, or archive the research line.

Failed or downgraded ideas stay visible because they explain what the final choices are not trying to do.

## Language Policy

GitHub root pages and code-related files are English-first, with short Chinese notes only where they help explain China-market context. Internal research reports, China-market notes, and figures may keep Chinese or bilingual wording. The goal is not full bilingual duplication; it is a clean public code/research archive that remains readable for technical and international reviewers while preserving the local-market reasoning.

## Minimal Run Path

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests
python code/crypto/spot-long-only/research-scripts/02_spot_universe_baseline.py
python code/crypto/spot-long-only/research-scripts/10_final_predeployment_validation.py
python code/convertible-bonds/run_final_backtest.py
```

On Windows, `py -m pip ...` and `py -m unittest ...` are equivalent if `python` points to the Microsoft Store placeholder.

The Crypto Spot Long-Only scripts can fetch public Binance daily klines. Convertible-bond and ETF modules need user-supplied local CSV/DataFrame inputs because the raw data is private, licensed, or not redistributed here. See [Data & Reproducibility](docs/data-and-reproducibility.md) and [Input Schemas](docs/input-schemas.md).

## Reader Path

For a quick public read:

1. [Portfolio Map](docs/portfolio-map.md)
2. [Convertible Bonds](projects/convertible-bonds/README.md)
3. [Crypto](projects/crypto/README.md)
4. [ETF Stabilizer](projects/etf-stabilizer/README.md)
5. [CB + ETF Bridge](projects/cb-etf-bridge/README.md)

For a reviewer checking research discipline:

1. [Research Governance](docs/research-governance.md)
2. [Evidence Index](docs/evidence-index.md)
3. [Data & Reproducibility](docs/data-and-reproducibility.md)
4. [Input Schemas](docs/input-schemas.md)
5. [Migration Notes](docs/migration-notes.md)

For a reviewer checking code:

1. [Code Appendix](code/README.md)
2. [Convertible Bonds Code](code/convertible-bonds/README.md)
3. [Crypto Spot Long-Only Code](code/crypto/spot-long-only/README.md)
4. [ETF Stabilizer Code](code/etf-stabilizer/README.md)

## Publication Boundary

This repository is for research presentation and education. It is not investment advice, solicitation, live trading instruction, or a promise that any strategy will remain profitable.

Raw data, API keys, broker/live-trading files, `.env` files, licensed datasets, personal execution records, and current order plans should not be committed here.
