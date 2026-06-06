# Repository Structure

This repository should stay small, readable, and evidence-led. It should not become a dump of every local experiment.

## Target Layout

```text
market-quant-research-portfolio/
  README.md
  docs/
    repository-structure.md
    migration-scope.md
    evidence-index.md
    data-and-reproducibility.md
    research-governance.md
    publication-policy.md
  projects/
    convertible-bonds/
      README.md
    crypto/
      README.md
    etf-stabilizer/
      README.md
    portfolio-bridge/
      README.md
    a-share-small-cap-archive/
      README.md
  assets/
    convertible-bonds/
    crypto/
    etf-stabilizer/
    portfolio-bridge/
```

## What Belongs In `projects/`

Each project page should answer:

- What market problem is being studied?
- Why does it fit or not fit personal capital?
- What is the baseline?
- What evidence supports or weakens the idea?
- What are the costs, execution assumptions, and failure modes?
- What is the current decision: active, candidate, stabilizer, archive, or observation?
- Where are the source code and outputs in the local research tree?

## What Belongs In `assets/`

Only selected reader-facing figures belong here:

- strategy logic maps;
- final scorecards;
- key equity/drawdown charts;
- robustness and parameter-neighborhood charts;
- archive decision maps.

Avoid uploading large figure dumps. A GitHub reader should see the evidence chain, not every internal diagnostic.

## What Does Not Belong Here

- `.env`, API tokens, broker files, live order logs;
- raw or licensed data;
- full exchange caches;
- local Office drafts;
- temporary GPT-test directories unless converted into a clean evidence note;
- strategy variants that were abandoned without a concise archive note.

