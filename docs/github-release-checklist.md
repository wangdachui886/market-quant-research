# GitHub Release Checklist

## Content Checks

- README explains the relationship between Notion and GitHub.
- README starts from the whole portfolio map, not from a single strategy line.
- CB + ETF Bridge is clearly scoped to the convertible-bond core and ETF sleeve.
- Each main project has a public decision label.
- Key figures render from `assets/`.
- Evidence tables match the latest public portfolio claims.
- Archive pages do not sound like hidden strategy promotions.
- A-share small-cap remains archive / observation only.
- Every code appendix states `Can this run?` and lists data requirements.

## Evidence Checks

- Public claims link to reports, result CSVs, code paths, and figures.
- `docs/evidence-index.md` contains public evidence only.
- Internal source-family or migration notes stay in `docs/migration-notes.md`.
- Result CSVs are selected evidence tables, not full raw-data dumps.
- Current selections, current order plans, and personal execution records are excluded.

## Safety Checks

- No `.env`, API key, access token, bearer token, password, or secret string.
- No broker file, live order log, personal execution log, or current order plan.
- No raw data cache or restricted dataset.
- No `spot_data_cache/`, `.cache/`, `__pycache__/`, or logs.
- No Office draft files, slide decks, PDFs, or build artifacts.
- No claims of trading advice, live-readiness, or guaranteed future performance.
- `.gitignore` blocks common sensitive and heavy file types.

## Suggested Release Scope

Version: `v0.3-evidence-and-code-backfill`

Scope:

- portfolio-level README and map;
- corrected CB + ETF bridge naming;
- public evidence index;
- requirements and minimal run notes;
- selected reports and result CSVs;
- curated code appendix for convertible bonds, Crypto Spot Long-Only, and ETF Stabilizer;
- Smart DCA candidate documentation only.

Do not include:

- raw data;
- full old research folders;
- live/pre-live broker materials;
- uncleaned code with local paths or secrets.
