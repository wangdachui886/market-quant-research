# GitHub Release Checklist

## Before Creating The Remote Repository

- Choose repo visibility: public portfolio repo or private staging repo first.
- Choose repository name. Current local default: `market-quant-research-portfolio`.
- Decide whether source-code migration is part of v1 or a later release.
- Confirm whether Windows local source paths should remain in public docs or be moved to a private migration note.

## Content Checks

- README explains the relationship between Notion and GitHub.
- Each main project has a public decision label.
- Key figures render from `assets/`.
- Evidence tables match the latest Notion portfolio claims.
- Archive pages do not sound like hidden strategy promotions.
- A-share small-cap remains archive / observation only.

## Safety Checks

- No `.env`, API token, broker file, live order log, or personal execution log.
- No raw data cache or restricted dataset.
- No Office draft files.
- No claims of trading advice, live-readiness, or guaranteed future performance.
- `.gitignore` blocks common sensitive and heavy file types.

## Suggested First GitHub Release

Version: `v0.1-portfolio-structure`

Scope:

- portfolio-level README;
- repository structure docs;
- migration scope and evidence index;
- four public project sections;
- selected figures only.
- curated code appendix only: convertible-bond final core, Crypto Spot Long-Only baseline/validation, ETF Stabilizer core.

Do not include:

- raw data;
- full old research folders;
- live/pre-live broker materials;
- uncleaned code with local paths or secrets.

## Suggested Second Release

Version: `v0.2-code-appendix`

Scope:

- selected clean strategy modules;
- minimal usage notes;
- reproducibility appendix;
- public sample outputs;
- optional notebook-free scripts.

Only add code after each file can be understood by an external reader without the original local workstation.
