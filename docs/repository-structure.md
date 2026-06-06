# Repository Structure

This repository should stay readable and evidence-led. It should not become a dump of every local experiment.

## Current Layout

```text
market-quant-research/
  README.md
  requirements.txt
  docs/
    portfolio-map.md
    evidence-index.md
    data-and-reproducibility.md
    migration-scope.md
    migration-notes.md
    research-governance.md
    publication-policy.md
    github-release-checklist.md
  projects/
    convertible-bonds/
      reports/
      results/
    crypto/
      spot-long-only/
        reports/
        results/
      smart-dca-candidate/
        reports/
        results/
    etf-stabilizer/
      reports/
      results/
    cb-etf-bridge/
      reports/
      results/
    a-share-small-cap-archive/
  code/
    convertible-bonds/
      cb_pre_live_core/
      research-scripts/
    crypto/
      spot-long-only/
        research-scripts/
        spot_trend_core/
    etf-stabilizer/
  assets/
    convertible-bonds/
    crypto/
    etf-stabilizer/
    portfolio-bridge/
```

## Directory Roles

| Directory | Role |
|---|---|
| `docs/` | Cross-project map, evidence index, reproducibility policy, migration scope, governance |
| `projects/` | Reader-facing project pages, public reports, selected result CSVs |
| `code/` | Public code anchors and run-status notes |
| `assets/` | Selected figures used by project pages and evidence index |

## What Belongs In `projects/`

Each project page should answer:

- what market problem is being studied;
- why it fits or does not fit personal capital;
- what the baseline is;
- what evidence supports or weakens the idea;
- what costs, execution assumptions, and failure modes matter;
- what the current decision is: active, candidate, stabilizer, archive, or observation;
- where the public code, reports, result tables, and figures are.

## What Belongs In `code/`

Use `code/` for scripts or modules that directly support a public claim.

Each code appendix should state:

- whether it can run publicly;
- what data is needed;
- which reports/results it supports;
- what is deliberately not included.

## What Does Not Belong Here

- `.env`, API tokens, passwords, broker files, live order logs;
- raw or licensed data;
- full exchange caches;
- local Office drafts, slide decks, PDFs;
- current order plans or personal execution logs;
- abandoned strategy variants without a concise archive note.
