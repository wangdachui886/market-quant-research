# Code Appendix

This directory contains public code anchors that directly support the portfolio claims.

It is not a full migration of every local research folder. Raw data, caches, `.env` files, API credentials, broker/live files, current order plans, and large historical dumps are intentionally excluded.

## Can This Run?

| Directory | Public runnable? | Data needed | Public role |
|---|---|---|---|
| [convertible-bonds](convertible-bonds/README.md) | Partially | User-supplied convertible-bond CSVs | Final pre-live core and historical research scripts |
| [crypto/spot-long-only](crypto/spot-long-only/README.md) | Yes for public-data research scripts | Internet access for Binance daily klines | Active Crypto baseline and validation chain |
| [etf-stabilizer](etf-stabilizer/README.md) | Yes as function logic | User-supplied close/NAV DataFrames | ETF sleeve target-weight logic |

## Included

| Directory | What it contains | Why it is included |
|---|---|---|
| `convertible-bonds/cb_pre_live_core/` | Current `top12_keep37` pre-live core | Directly supports the China Convertible Bond flagship line |
| `convertible-bonds/research-scripts/` | Earlier keep_n, cost, walk-forward, and attribution research scripts | Shows the research path behind the final candidate |
| `crypto/spot-long-only/research-scripts/` | Spot Long-Only research process scripts 01-11 | Connects reports, figures, and result CSVs |
| `crypto/spot-long-only/spot_trend_core/` | Cleaned operational-style core modules | Shows engineering structure beyond one-off scripts |
| `etf-stabilizer/` | ETF Stabilizer target-weight logic and sanitized params | Directly supports the portfolio stabilizer line |

## Not Included

- Smart DCA raw script: candidate line, not yet cleaned into a public code appendix.
- A-share small-cap scripts: archived pre-research, not a current public core line.
- Raw data loaders that require private credentials or licensed datasets.
- Full old research folders, caches, logs, Office files, slide decks, PDFs, and current order plans.

## Data Policy

Put private or regenerated data into untracked local folders such as `data/`, `raw_data/`, `spot_data_cache/`, or other ignored paths. Do not commit secrets or live trading material.
