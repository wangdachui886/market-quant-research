# Code Appendix

This directory contains public code anchors that directly support the portfolio claims.

It is not a full migration of every local research folder. Raw data, caches, `.env` files, API credentials, broker/live files, current order plans, and large historical dumps are intentionally excluded.

## Can This Run?

| Directory | Public runnable? | Data needed | Public role |
|---|---|---|---|
| [convertible-bonds](convertible-bonds/README.md) | Partially | User-supplied convertible-bond CSVs | Final pre-live core and historical research scripts |
| [crypto/spot-long-only](crypto/spot-long-only/README.md) | Yes for public-data research scripts | Internet access for Binance daily klines | Active Crypto baseline and validation chain |
| [etf-stabilizer](etf-stabilizer/README.md) | Yes as function logic | User-supplied close/NAV DataFrames | ETF sleeve target-weight logic |
| [futures-cta](futures-cta/README.md) | Partially | User-supplied clean futures returns and carry series | Archived low-correlation CTA market-fit study |
| [a-share-small-cap](a-share-small-cap/README.md) | Partially | User-supplied A-share raw/processed PIT panels | Archived small-cap gross-engine and risk-fit study |

Run the lightweight public smoke tests with:

```bash
python -m unittest discover -s tests
```

On Windows, `py -m unittest discover -s tests` is equivalent if `python` points to the Microsoft Store placeholder.

For expected user-supplied input columns, see [Input Schemas](../docs/input-schemas.md).

## Included

| Directory | What it contains | Why it is included |
|---|---|---|
| `convertible-bonds/cb_pre_live_core/` | Current `top12_keep37` pre-live core | Directly supports the China Convertible Bond flagship line |
| `convertible-bonds/research-scripts/` | Earlier keep_n, cost, walk-forward, and attribution research scripts | Shows the research path behind the final candidate |
| `crypto/spot-long-only/research-scripts/` | Spot Long-Only research process scripts 01-11 | Connects reports, figures, and result CSVs |
| `crypto/spot-long-only/spot_trend_core/` | Cleaned operational-style core modules | Shows engineering structure beyond one-off scripts |
| `etf-stabilizer/` | ETF Stabilizer target-weight logic and sanitized params | Directly supports the portfolio stabilizer line |
| `futures-cta/` | Clean returns, TSMOM, Carry, OOS, cost, and capital-ladder scripts | Supports the Futures CTA archive |
| `a-share-small-cap/` | Data audit, processed ports, stateful baseline, RPE, guard, and size-ladder scripts | Supports the A-share Small-cap archive |

Some research scripts contain Chinese report and figure labels because they generate China-market or local research exhibits. Public run notes, code README files, and reusable module docstrings should remain English-first.

## Not Included

- Smart DCA raw script: candidate line, not yet cleaned into a public code appendix.
- Credentialed futures pull/probe scripts and local futures caches.
- Raw A-share data, processed private panels, and large stock-level event dumps.
- Raw data loaders that require private credentials or licensed datasets.
- Full old research folders, caches, logs, Office files, slide decks, PDFs, and current order plans.

## Data Policy

Put private or regenerated data into untracked local folders such as `data/`, `raw_data/`, `spot_data_cache/`, or other ignored paths. Do not commit secrets or live trading material.
