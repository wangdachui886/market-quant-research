# Migration Notes

This file records migration scope for maintainers. Public readers can start from [Evidence Index](evidence-index.md) instead.

## What Was Publicly Migrated

| Line | Migrated Public Materials |
|---|---|
| Convertible Bonds | Current pre-live core code, selected historical research scripts, final reports, validation tables, final daily returns, final holdings, rank audit, and selected figures |
| Crypto Spot Long-Only | Research scripts 01-11, final operational core, public reports, selected result CSVs, and selected figures |
| Smart DCA | Documentation and one candidate result table only; raw script remains out until it is cleaned |
| ETF Stabilizer | Final core code, params, strategy reports, selected result CSVs, and selected figures |
| CB + ETF Bridge | Bridge report and selected combined-portfolio result CSVs |

## Intentionally Excluded

- `.env`, API keys, tokens, passwords, and secrets;
- raw convertible-bond panels, licensed market data, full ETF data directories, and full exchange caches;
- `spot_data_cache/`, `.cache/`, `__pycache__/`, logs, Office files, PDFs, and slide decks;
- broker/live-trading files, current order plans, and personal execution records;
- old scripts whose conclusions are superseded and not explained by a public archive note.

## Current Public Boundary

The repository is inspectable-first. Some modules can run with public data, while others require user-supplied CSVs or DataFrames because raw data is not redistributed here.

The next useful migration pass would be:

1. modularize Crypto Spot Long-Only into smaller reusable modules;
2. clean Smart DCA into a dedicated code appendix if it remains public;
3. add small sample input schemas for convertible-bond and ETF modules;
4. keep the public evidence index free of local-path language.
