# Data & Reproducibility

## Reproducibility Promise

This repository is inspectable-first. It does not promise that every strategy can be reproduced from public raw data with one command.

The minimum public standard is:

- fixed rules and parameters;
- data source description;
- sample window;
- execution and cost assumptions;
- selected output tables and figures;
- code anchors;
- known limits and failure modes.

## Minimal Environment

```bash
pip install -r requirements.txt
```

Core Python dependencies:

```text
pandas
numpy
matplotlib
Pillow
```

## Can This Run?

| Module | Public runnable? | Data needed |
|---|---|---|
| Crypto Spot Long-Only research scripts | Yes, for the public-data scripts | Internet access for Binance daily klines |
| Crypto Spot Long-Only operational core | Partially | User-supplied OHLCV cache or generated spot data |
| Convertible Bonds pre-live core | Partially | User-supplied convertible-bond panel, issue-size table, maturity/strong-call data |
| Convertible Bonds historical research scripts | Inspectable, not standalone | Older private strategy package and private panel data |
| ETF Stabilizer | Yes as function logic | User-supplied close/NAV DataFrames |
| Smart DCA | Documentation only for now | Raw script not yet migrated as public code |

## Data Boundary

Do not commit raw datasets unless the source is public, redistribution is allowed, and the file is small enough to help a reader.

Allowed public result files:

- aggregated metrics tables;
- summary CSVs;
- generated daily return series;
- validation tables;
- small candidate result tables;
- selected figures that support a public claim.

Excluded files:

- `.env`, tokens, API keys, passwords, broker credentials;
- raw or licensed market data;
- full caches such as `spot_data_cache/` and `.cache/`;
- live order plans, broker files, personal execution logs;
- Office documents, PDFs, slide decks, and temporary build outputs.

## Figures

Figures in `assets/` are selected published exhibits. They should be connected to a report, code path, or result table in [Evidence Index](evidence-index.md).
