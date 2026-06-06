# Migration Scope

## Priority 1: Public Core

These are necessary for the first GitHub release.

| Line | Include | Why |
|---|---|---|
| Convertible bonds | Strategy card, final metrics, sealed decision, time-split/rolling robustness, execution boundary, archive map | Strongest non-Crypto flagship line; complete evidence chain |
| Crypto | Market reality, strategy triage, Spot Long-Only baseline, Smart DCA candidate, archived observations | Shows high-volatility market understanding and falsification discipline |
| ETF Stabilizer | Stabilizer rule card, portfolio evidence, allocation sensitivity, common-window/data boundary, archive variants | Shows portfolio construction rather than only alpha search |
| Portfolio bridge | 70/30 combined portfolio logic and monitoring focus | Connects the portfolio into one research system |
| Code appendix | Convertible-bond `top12_keep37` core, Crypto Spot Long-Only baseline/validation, ETF target-weight logic | Gives GitHub enough code evidence without dumping every local experiment |

## Priority 2: Evidence Backfill

These can be added after the first release.

| Source | Public Form |
|---|---|
| Convertible-bond historical strategy source | Clean code appendix or selected reusable modules |
| Convertible-bond final research outputs | Curated tables and short evidence notes |
| Crypto Spot Long-Only final reports | Spot Long-Only technical appendix |
| Smart DCA research docs | Smart DCA appendix |
| ETF Stabilizer final implementation archive | ETF Stabilizer implementation appendix |

## Priority 3: Archive / Optional Satellite

These should remain lower profile.

| Line | Public Decision |
|---|---|
| A-share small-cap | Archive as pre-research / observation; do not present as deployable core |
| Convertible-bond MA / breadth defense | Archive as observation; not a sealed timing alpha |
| ETF right-side sleeve | Archive as mechanism test; did not beat same-vol buy-and-hold cleanly |
| Crypto short leg / single-venue funding / grid / BOX / regime filter | Archive as strategy-triage evidence |

## Code Included In The Current Scaffold

| Public Code Directory | Source | Decision |
|---|---|---|
| `code/convertible-bonds/` | Convertible-bond pre-live core | Included; closest to current `top12_keep37` public conclusion |
| `code/crypto/spot-long-only/` | Crypto Spot Long-Only final scripts | Included; active Crypto baseline and final validation |
| `code/etf-stabilizer/` | ETF Stabilizer final core and sanitized params | Included; compact executable stabilizer logic |
| Smart DCA raw script | Smart DCA raw research script | Not included yet; candidate needs cleanup because it fetches data and writes local cache |
| A-share small-cap scripts | A-share small-cap pre-research scripts | Not included; archived pre-research, not core public code |

## Keep Private Or Out Of Repo

- raw market data and caches;
- live/pre-live broker operations;
- `.env` files and API keys;
- paid or restricted data;
- personal execution logs;
- intermediate Office documents;
- old folders whose conclusions are superseded and not summarized.
