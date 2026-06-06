# Data & Reproducibility

## Reproducibility Promise

This repository should make the research inspectable, not necessarily fully one-command reproducible from public raw data.

For each public strategy, the minimum standard is:

- fixed rules and parameters;
- data source description;
- sample window;
- execution and cost assumptions;
- selected output tables or figures;
- code/source anchors;
- known limits and failure modes.

## Data Boundary

Do not commit raw datasets unless the source is public, redistribution is allowed, and the file is small enough to serve a reader.

Use public notes instead:

```text
data source -> sample window -> fields used -> cleaning decisions -> known caveats
```

## Source Anchors

Local source paths are included in the evidence index so the research can be traced during migration. Before public release, these should either be:

- replaced by relative GitHub paths if the code is migrated;
- or kept as "local source anchors" in a private migration note, not in the public README.

## Public Code Standard

Only migrate code that is:

- readable without local secrets;
- free of API keys and private paths;
- accompanied by a short usage note;
- aligned with the public conclusion;
- not dependent on uncommittable raw data without explanation.

## Figures

Figures in `assets/` are selected reader-facing evidence. They should be treated as published exhibits, not raw output dumps.

Whenever possible, figure pages should mention:

- which script generated the figure;
- which sample window was used;
- what conclusion the figure is allowed to support;
- what it does not prove.

