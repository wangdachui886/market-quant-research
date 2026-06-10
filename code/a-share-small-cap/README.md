# A-share Small-cap Code Appendix

This directory contains public code anchors for the archived A-share small-cap
research line.

It is not a public one-command reproduction package. The scripts expect
user-supplied raw A-share market/finance files and processed point-in-time
panels that are private or not redistributed here.

## Can This Run?

| Area | Public runnable? | Data needed |
|---|---|---|
| `scripts/data_audit.py` | Yes after local raw data is supplied | A-share daily market files and finance tables |
| `scripts/build_processed_data.py` | Yes after local raw data is supplied | same raw data, written into local `processed/` ports |
| `research/pre_research/run_pre_research_v1.py` | Partially | processed market ports and annual finance PIT panel |
| `research/pre_research/run_pre_research_v2_stateful_portfolio.py` | Partially | processed ports plus stateful execution constraints |
| `research/pre_research/run_baseline_drawdown_anatomy_v2.py` | Partially | baseline outputs and processed execution-state data |
| `research/pre_research/run_rpe_factor_v1.py` | Partially | RPE inputs from annual finance PIT panel |
| `research/pre_research/run_rpe_stateful_portfolio_v1.py` | Partially | RPE signal plus stateful portfolio engine |
| `research/pre_research/run_execution_liquidity_guard_v1.py` | Partially | stateful portfolio plus execution/liquidity guard inputs |
| `research/pre_research/run_size_exposure_ladder_v1.py` | Partially | stateful portfolio plus size-bucket definitions |

## Research Order

```bash
python code/a-share-small-cap/scripts/data_audit.py
python code/a-share-small-cap/scripts/build_processed_data.py
python code/a-share-small-cap/research/pre_research/run_pre_research_v1.py
python code/a-share-small-cap/research/pre_research/run_pre_research_v2_stateful_portfolio.py
python code/a-share-small-cap/research/pre_research/run_baseline_drawdown_anatomy_v2.py
python code/a-share-small-cap/research/pre_research/run_rpe_factor_v1.py
python code/a-share-small-cap/research/pre_research/run_rpe_stateful_portfolio_v1.py
python code/a-share-small-cap/research/pre_research/run_execution_liquidity_guard_v1.py
python code/a-share-small-cap/research/pre_research/run_size_exposure_ladder_v1.py
```

## Included / Excluded

Included:

- data audit and processed-port builders;
- stateful baseline, drawdown anatomy, RPE, guard, and size-ladder scripts;
- selected reports, summary CSVs, and figures in the project archive.

Excluded:

- raw daily stock files and finance tables;
- `processed/` private panels;
- large stock-level event dumps;
- broker files, current order plans, and live execution material.

See the project archive: [A-share Small-cap](../../projects/additional-market-research/a-share-small-cap/README.md).
