# Smart DCA Archive Note

Date: 2026-04-24

## Final Decision

- Keep `v0t` as the active Smart DCA variant.
- Keep `v0` as legacy baseline for strategy-level comparison.
- Keep `v0.1` and `v0.2` as archived experiments only.

## Why v0t

- v0t only changes the sell side of v0 by adding one mild-overheat tier:
  - `MM > 1.5` => sell `5%` of sellable BTC.
- This directly addresses the post-ETF regime concern: `MM > 1.8` occurs less often.
- Buy logic remains unchanged, so complexity and overfitting risk stay low.

## Separation Rule

- Strategy code lives in script files (for now: `smart_dca_v0.py`).
- Research conclusions and decisions live in `docs/`.
- Backtest outputs (charts, csv) live in `outputs/`.

Current output folder used by script:

- `outputs/smart_dca_v0t/`
