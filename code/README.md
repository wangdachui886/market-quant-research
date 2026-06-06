# Code Appendix

This directory contains a small, curated set of scripts that directly support the public portfolio claims.

It is not a full migration of every local research folder. Raw data, caches, `.env` files, broker/live files, and large historical output dumps are intentionally excluded.

## Included

| Directory | What it contains | Why it is included |
|---|---|---|
| `convertible-bonds/` | Sealed `top12_keep37` pre-live core | Directly supports the China Convertible Bond flagship line |
| `crypto/spot-long-only/` | Spot Long-Only baseline and final predeployment validation | Directly supports the active Crypto baseline |
| `etf-stabilizer/` | ETF Stabilizer V1.1 target-weight logic and sanitized params | Directly supports the portfolio stabilizer line |

## Not Included In v0.2

- Smart DCA raw script: useful candidate, but it still fetches Binance data directly and writes a local `.cache`.
- A-share small-cap scripts: archived as pre-research, not a public core line.
- Old convertible-bond v1.0 strategy modules: superseded by the `top12_keep37` pre-live core for public positioning.
- Full historical research sweeps and figure generators.

## Data Policy

The code uses local data paths, but this repository does not commit raw data. Put any private or regenerated data into untracked local folders such as `data/` or `spot_data_cache/`.

