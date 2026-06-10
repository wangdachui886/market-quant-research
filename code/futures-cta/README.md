# Futures CTA Code Appendix

This directory contains public code anchors for the futures CTA archive.

It is inspectable-first. Most scripts need user-supplied clean Chinese commodity
futures returns and carry series; credentialed data fetchers, `.env` files,
tokens, local caches, and broker/live execution material are intentionally not
included.

## Can This Run?

| Area | Public runnable? | Data needed |
|---|---|---|
| `Phase_2_0_universe/` | Partially | Public/credentialed futures price source, used only for clean-return construction checks |
| `Phase_2_1_tushare/pipeline.py` | As reusable functions | Caller supplies an authenticated `pro` object; no token handling is included |
| `Phase_2_2_tsmom/` | Yes after clean returns are supplied | `data_cache/tushare/clean/{SYMBOL}_clean_returns.csv` |
| `Phase_2_3_carry/` | Yes after clean returns and carry series are supplied | clean returns plus `data_cache/tushare/carry/{SYMBOL}_carry.csv` |
| `Phase_2_4_robustness/` | Yes after Phase 2.2/2.3 inputs exist | same clean/carry inputs |
| `Phase_2_5_capital/` | Yes after Phase 2.2/2.3 inputs exist | same clean/carry inputs plus contract multipliers in `config.py` |

## Script Map

| Directory | Role |
|---|---|
| `config.py` | Public static universe metadata, with no secret loading |
| `Phase_2_0_universe/` | Clean-return construction and fake-jump diagnostics |
| `Phase_2_1_tushare/pipeline.py` | Reusable clean-return functions; no credential management |
| `Phase_2_2_tsmom/` | TSMOM signal, volatility targeting, and universe baseline |
| `Phase_2_3_carry/` | Carry signal construction and pooled TSMOM/Carry tests |
| `Phase_2_4_robustness/` | OOS, cost, attribution, and decomposition scripts |
| `Phase_2_5_capital/` | Capital ladder and whole-lot feasibility analysis |

## Public Commands

These commands show the intended run order once the required clean/carry input
files are available:

```bash
python code/futures-cta/Phase_2_2_tsmom/run_universe_voltarget.py
python code/futures-cta/Phase_2_3_carry/run_universe_carry.py
python code/futures-cta/Phase_2_3_carry/run_pooled.py
python code/futures-cta/Phase_2_4_robustness/run_oos_filtered.py
python code/futures-cta/Phase_2_4_robustness/run_oos_decompose.py
python code/futures-cta/Phase_2_4_robustness/run_cost_sweep.py
python code/futures-cta/Phase_2_5_capital/run_capital_ladder.py
```

See the project archive: [Futures CTA](../../projects/additional-market-research/futures-cta/README.md).
