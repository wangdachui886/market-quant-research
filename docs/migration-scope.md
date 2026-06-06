# Migration Scope

## Public Core

| Line | Include | Why |
|---|---|---|
| Convertible Bonds | Strategy card, final metrics, result CSVs, research reports, pre-live core, selected historical research scripts | Strongest non-Crypto flagship line; complete evidence chain |
| Crypto Spot Long-Only | Market triage, scripts 01-11, reports, selected result CSVs, final validation, operational core | Active Crypto baseline with public-data path |
| Smart DCA | Candidate reports and selected result table | Candidate accumulation framework, not a finalized code appendix |
| ETF Stabilizer | Strategy card, final core, params, reports, selected result CSVs | Supporting stabilizer line for portfolio construction |
| CB + ETF Bridge | Integration note and combined-portfolio tables | Connects the CB core and ETF sleeve without overstating it as the whole portfolio bridge |

## Archive / Optional Satellite

| Line | Public Decision |
|---|---|
| A-share Small-cap | Archive as pre-research / observation; do not present as deployable core |
| Convertible-bond MA / breadth defense | Archive as observation; not a sealed timing alpha |
| ETF right-side sleeve | Archive as mechanism test; did not beat same-vol buy-and-hold cleanly |
| Crypto short leg / single-venue funding / grid / BOX / regime filter | Archive as strategy-triage evidence |

## Keep Private Or Out Of Repo

- raw market data and caches;
- live/pre-live broker operations;
- `.env` files, API keys, access tokens, passwords, and other secrets;
- paid or restricted data;
- current order plans and personal execution logs;
- intermediate Office documents, slide decks, PDFs, and build artifacts;
- old folders whose conclusions are superseded and not summarized.

Internal migration notes live in [Migration Notes](migration-notes.md).
