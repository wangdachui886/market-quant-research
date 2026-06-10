# Evidence Index

This file maps public claims to public GitHub evidence. Internal migration scope lives in [Migration Notes](migration-notes.md).

## Convertible Bonds

| Public Claim | Reports | Result Tables / Code | Figures |
|---|---|---|---|
| Market fit and strategy framework | [01 Strategy Framework](../projects/convertible-bonds/reports/01_strategy_framework.md), [02 Research Journey](../projects/convertible-bonds/reports/02_research_journey_0_to_1_to_1plus.md) | [research scripts](../code/convertible-bonds/research-scripts/) | [logic map](../assets/convertible-bonds/cb_logic_map.svg) |
| Final `top12_keep37` candidate | [03 Final Performance](../projects/convertible-bonds/reports/03_final_performance_report.md), [00 Sealed Final](../projects/convertible-bonds/reports/00_SEALED_FINAL.md) | [final metrics](../projects/convertible-bonds/results/final/final_metrics.json), [final daily returns](../projects/convertible-bonds/results/final/final_daily_returns.csv), [final holdings](../projects/convertible-bonds/results/final/final_holdings.csv) | [NAV/drawdown](../assets/convertible-bonds/cb_01_final_nav_drawdown.png), [scorecard](../assets/convertible-bonds/cb_02_final_scorecard.png) |
| Cost, execution, and retention robustness | [focused validation](../projects/convertible-bonds/reports/topk_keepn_focused_validation_summary.md), [stability audit](../projects/convertible-bonds/reports/topk_keepn_stability_audit_summary.md) | [cost stress](../projects/convertible-bonds/results/validation/final_cost_stress_0_25bp.csv), [execution lag](../projects/convertible-bonds/results/validation/execution_lag_metrics.csv), [weekday stress](../projects/convertible-bonds/results/validation/rebalance_weekday_metrics.csv), [rank audit](../projects/convertible-bonds/results/validation/rank_audit_summary.csv) | [top-k/keep-n heatmap](../assets/convertible-bonds/cb_09_topk_keepn_calmar_heatmap.png), [time split](../assets/convertible-bonds/cb_21_time_split_robustness.png), [rolling window](../assets/convertible-bonds/cb_22_rolling_window_robustness.png) |
| Archive discipline | [technical assessment](../projects/convertible-bonds/reports/05_technical_assessment.md) | [rank bin contribution](../projects/convertible-bonds/results/validation/rank_bin_contribution.csv), [drawdown windows](../projects/convertible-bonds/results/validation/drawdown_window_summary.csv) | [archive decision map](../assets/convertible-bonds/cb_17_archive_decision_map.png) |

Key public metrics:

| Strategy | CAGR | Max Drawdown | Calmar | Sharpe | Turnover |
|---|---:|---:|---:|---:|---:|
| Final `top12_keep37` | 18.60% | -18.76% | 0.992 | 0.974 | 25.52% |
| Original `top10_keep29` | 18.14% | -23.78% | 0.763 | 0.937 | 27.77% |
| Vanilla baseline | 10.24% | -28.51% | 0.359 | n/a | n/a |

## Crypto Spot Long-Only

| Public Claim | Reports | Result Tables / Code | Figures |
|---|---|---|---|
| Public-data baseline and universe screening | [baseline report](../projects/crypto/spot-long-only/reports/02_spot_universe_baseline_report.md), [BASELINE](../projects/crypto/spot-long-only/reports/BASELINE.md) | [research scripts](../code/crypto/spot-long-only/research-scripts/), [baseline metrics](../projects/crypto/spot-long-only/results/baseline/baseline_metrics.csv), [universe screen](../projects/crypto/spot-long-only/results/baseline/universe_screen.csv) | [strategy triage](../assets/crypto/00_strategy_triage_decision_matrix.png) |
| Attribution and pool robustness | [attribution report](../projects/crypto/spot-long-only/reports/03_spot_baseline_attribution_report.md), [pool comparison](../projects/crypto/spot-long-only/reports/04_pool_comparison_report.md), [pool robustness](../projects/crypto/spot-long-only/reports/05_pool_robustness_report.md) | [attribution summary](../projects/crypto/spot-long-only/results/attribution/attribution_summary.csv), [pool metrics](../projects/crypto/spot-long-only/results/pool-comparison/pool_metrics.csv), [robustness tables](../projects/crypto/spot-long-only/results/robustness/) | [risk efficiency alpha](../assets/crypto/06_risk_efficiency_alpha.png), [rolling evidence](../assets/crypto/07_risk_efficiency_rolling.png) |
| Execution, cost, data integrity, and liquidity | [boundary tests](../projects/crypto/spot-long-only/reports/09_boundary_deployment_tests_report.md), [final validation](../projects/crypto/spot-long-only/reports/10_final_predeployment_validation_report.md) | [final validation tables](../projects/crypto/spot-long-only/results/final-validation/), [boundary test tables](../projects/crypto/spot-long-only/results/boundary-tests/) | [failure condition matrix](../assets/crypto/11_failure_condition_matrix.png) |
| Buy-and-hold comparison and failure rules | [buy-hold comparison](../projects/crypto/spot-long-only/reports/11_buy_hold_static_compare_report.md), [universe rules](../projects/crypto/spot-long-only/reports/12_universe_management_rules.md), [failure conditions](../projects/crypto/spot-long-only/reports/13_strategy_failure_conditions.md) | [buy-hold summary](../projects/crypto/spot-long-only/results/buy-hold-compare/11_buyhold_summary.csv), [operational core](../code/crypto/spot-long-only/spot_trend_core/) | [hypothesis tree](../assets/crypto/research_hypothesis_tree.svg) |

Key Spot Long-Only public evidence:

| Variant | CAGR | Sharpe | MDD | Calmar | Avg Exposure |
|---|---:|---:|---:|---:|---:|
| Same close gross | 44.32% | 1.82 | -24.10% | 1.84 | 19.83% |
| Next open gross | 44.28% | 1.82 | -24.09% | 1.84 | 19.83% |
| Next open 15bp | 43.42% | 1.79 | -24.90% | 1.74 | 19.84% |

## Smart DCA Candidate

| Public Claim | Reports | Result Tables | Figures |
|---|---|---|---|
| Candidate accumulation framework | [V0 vs V0T comparison](../projects/crypto/smart-dca-candidate/reports/V0_V0T_COMPARISON_2026-04-24.md), [archive note](../projects/crypto/smart-dca-candidate/reports/ARCHIVE_NOTE.md) | [Smart DCA v0t trades](../projects/crypto/smart-dca-candidate/results/smart_dca_v0t_trades.csv) | [Smart DCA evidence](../assets/crypto/01_smart_dca_vs_fixed_dca_evidence.png), [deployment map](../assets/crypto/02_smart_dca_deployment_map.png) |

This line is documentation/candidate only until the raw script is cleaned into a public code appendix.

## ETF Stabilizer

| Public Claim | Reports | Result Tables / Code | Figures |
|---|---|---|---|
| Stabilizer role and rule card | [strategy card](../projects/etf-stabilizer/reports/ETF_Stabilizer_V1_策略卡.md), [final combo validation](../projects/etf-stabilizer/reports/01_final_combo_validation_zh.md) | [ETF code](../code/etf-stabilizer/README.md), [lookback stability](../projects/etf-stabilizer/results/etf_equity_switch_lookback_stability_summary.csv) | [role map](../assets/etf-stabilizer/etf_01_role_map_bilingual.png), [rule card](../assets/etf-stabilizer/etf_03_stabilizer_rule_card.png) |
| Fallback variants and archive discipline | [short fallback validation](../projects/etf-stabilizer/reports/02_short_fallback_validation_zh.md), [fallback gold shift](../projects/etf-stabilizer/reports/04_fallback_gold_shift_test_zh.md), [archive note](../projects/etf-stabilizer/reports/研究归档说明.md) | [fallback result tables](../projects/etf-stabilizer/results/) | [combo evidence](../assets/etf-stabilizer/etf_05_combo_evidence.png), [archive map](../assets/etf-stabilizer/etf_07_archive_map.png) |

## CB + ETF Bridge

| Public Claim | Reports | Result Tables | Figures |
|---|---|---|---|
| ETF sleeve improves the full capital curve beside the CB core | [CB integration note](../projects/cb-etf-bridge/reports/可转债整合说明.md), [combo validation](../projects/cb-etf-bridge/reports/01_final_combo_validation_zh.md) | [combo practical table](../projects/cb-etf-bridge/results/etf_final_cb_combo_practical.csv), [common-window summary](../projects/cb-etf-bridge/results/etf_final_cb_common_window_summary.csv), [decision table](../projects/cb-etf-bridge/results/etf_final_cb_decision.csv) | [portfolio bridge](../assets/portfolio-bridge/portfolio_bridge.svg) |

## Additional Market Research Archive

These lines are serious research archives, not flagship candidates.

### Futures CTA

Public decision:

```text
Archive because personal capital granularity failed.
Do not promote now, even though the signal structure is credible.
```

| Public Claim | Reports | Result Tables / Code | Figures |
|---|---|---|---|
| Clean futures return construction matters; hard-spliced contracts create fake jumps | [data pitfalls](../projects/additional-market-research/futures-cta/reports/01_data_pitfalls.md), [Phase 2.1 findings](../projects/additional-market-research/futures-cta/reports/03_phase_2_1_findings.md) | [clean summary](../projects/additional-market-research/futures-cta/results/phase-2-0-universe/14_all_symbols_clean_summary.csv), [clean-return code](../code/futures-cta/Phase_2_0_universe/) | [clean vs raw NAV](../assets/futures-cta/13_M_clean_vs_raw_nav.png), [raw vs clean grid](../assets/futures-cta/15_raw_vs_clean_nav_grid.png) |
| TSMOM and Carry both showed usable standalone structure | [TSMOM findings](../projects/additional-market-research/futures-cta/reports/05_phase_2_2_findings.md), [Carry findings](../projects/additional-market-research/futures-cta/reports/07_phase_2_3_findings.md) | [TSMOM table](../projects/additional-market-research/futures-cta/results/phase-2-2-tsmom/tsmom_universe_voltarget_per_symbol.csv), [pooled table](../projects/additional-market-research/futures-cta/results/phase-2-3-carry/pooled_per_symbol.csv), [CTA code](../code/futures-cta/README.md) | [TSMOM figure](../assets/futures-cta/tsmom_universe_voltarget.png), [pooled figure](../assets/futures-cta/pooled_compare.png) |
| Pooling improved OOS risk efficiency, but headline should be decomposed | [robustness findings](../projects/additional-market-research/futures-cta/reports/08_phase_2_4_findings.md) | [OOS metrics](../projects/additional-market-research/futures-cta/results/phase-2-4-robustness/oos_filtered_metrics.csv), [OOS decomposition](../projects/additional-market-research/futures-cta/results/phase-2-4-robustness/oos_decompose_metrics.csv), [cost sweep](../projects/additional-market-research/futures-cta/results/phase-2-4-robustness/cost_sweep_metrics.csv) | [OOS decomposition](../assets/futures-cta/oos_decompose.png), [cost sweep](../assets/futures-cta/cost_sweep.png) |
| First usable personal-capital zone was roughly CNY 3m+ | [capital findings](../projects/additional-market-research/futures-cta/reports/09_phase_2_4b_2_5a_findings.md) | [capital ladder metrics](../projects/additional-market-research/futures-cta/results/phase-2-5-capital/capital_ladder_metrics.csv), [capital verdict](../projects/additional-market-research/futures-cta/results/phase-2-5-capital/capital_ladder_verdict.csv), [capital code](../code/futures-cta/Phase_2_5_capital/run_capital_ladder.py) | [capital ladder](../assets/futures-cta/capital_ladder.png) |

Key public metrics:

| Test | Result |
|---|---:|
| 0.5 TSMOM + 0.5 Carry Sharpe | 0.86 |
| 19-symbol Pool OOS Sharpe | 1.27 |
| 17-symbol no-gold/silver OOS edge vs TSMOM | +0.49 |
| 14-symbol carry-valid OOS edge vs TSMOM | +0.61 |
| CNY 3m capital-ladder Sharpe | 0.88 |
| CNY 10m capital-ladder Sharpe | 1.06 |

### A-share Small-cap

Public decision:

```text
Archive as observation / future optional satellite.
Do not promote to core strategy research now.
```

| Public Claim | Reports | Result Tables / Code | Figures |
|---|---|---|---|
| The low-frequency small-cap gross engine was strong | [stateful baseline](../projects/additional-market-research/a-share-small-cap/reports/pre_research_v2_stateful_portfolio_zh.md) | [stateful summary](../projects/additional-market-research/a-share-small-cap/results/stateful-baseline/stateful_summary.csv), [stateful daily returns](../projects/additional-market-research/a-share-small-cap/results/stateful-baseline/stateful_daily_returns.csv), [baseline code](../code/a-share-small-cap/research/pre_research/run_pre_research_v2_stateful_portfolio.py) | [stateful NAV](../assets/a-share-small-cap/stateful_portfolio_nav.png), [stateful drawdown](../assets/a-share-small-cap/stateful_portfolio_drawdown.png) |
| Drawdown and sell-fail risk were structural, not only a few bad stocks | [drawdown anatomy](../projects/additional-market-research/a-share-small-cap/reports/baseline_drawdown_anatomy_v2_zh.md) | [risk-source summary](../projects/additional-market-research/a-share-small-cap/results/drawdown-anatomy/risk_source_period_summary.csv), [loss concentration](../projects/additional-market-research/a-share-small-cap/results/drawdown-anatomy/code_loss_concentration.csv), [drawdown code](../code/a-share-small-cap/research/pre_research/run_baseline_drawdown_anatomy_v2.py) | [forced loss share](../assets/a-share-small-cap/baseline_v2_forced_loss_share.png), [market-style drawdown](../assets/a-share-small-cap/baseline_v2_market_style_drawdown.png) |
| RPE had signal evidence but failed to replace the baseline portfolio | [RPE diagnostic](../projects/additional-market-research/a-share-small-cap/reports/rpe_factor_v1_diagnostics_zh.md), [RPE stateful](../projects/additional-market-research/a-share-small-cap/reports/rpe_stateful_portfolio_v1_zh.md) | [RPE IC](../projects/additional-market-research/a-share-small-cap/results/rpe-diagnostics/rpe_ic_full.csv), [RPE pass/fail](../projects/additional-market-research/a-share-small-cap/results/rpe-stateful/rpe_stateful_pass_fail_checks.csv), [RPE code](../code/a-share-small-cap/research/pre_research/run_rpe_stateful_portfolio_v1.py) | [RPE NAV](../assets/a-share-small-cap/rpe_stateful_nav.png), [RPE drawdown](../assets/a-share-small-cap/rpe_stateful_drawdown.png) |
| RPE did not improve future quality in the tested branch | [RPE failure anatomy](../projects/additional-market-research/a-share-small-cap/reports/rpe_failure_anatomy_v1_zh.md) | [future fundamentals](../projects/additional-market-research/a-share-small-cap/results/rpe-failure-anatomy/future_fundamental_by_strategy.csv), [failure code](../code/a-share-small-cap/research/pre_research/run_rpe_failure_anatomy_v1.py) | [future profit YoY](../assets/a-share-small-cap/future_profit_yoy_by_strategy.png) |
| Execution/liquidity guards and size migration did not solve core-book risk fit | [guard report](../projects/additional-market-research/a-share-small-cap/reports/execution_liquidity_guard_v1_zh.md), [size ladder report](../projects/additional-market-research/a-share-small-cap/reports/size_exposure_ladder_v1_zh.md) | [guard summary](../projects/additional-market-research/a-share-small-cap/results/execution-liquidity-guard/guard_summary.csv), [size ladder summary](../projects/additional-market-research/a-share-small-cap/results/size-exposure-ladder/size_ladder_summary.csv), [A-share code](../code/a-share-small-cap/README.md) | [guard NAV](../assets/a-share-small-cap/execution_liquidity_guard_v1_nav.png), [size ladder Calmar](../assets/a-share-small-cap/size_ladder_calmar.png) |

Key public metrics:

| Metric | Baseline |
|---|---:|
| Annualized return | 30.72% |
| 30bps cost annualized return | 27.27% |
| Max drawdown | -66.97% |
| Worst 12m | -59.36% |
| 2016-2018 annualized return | -15.78% |
| 2016-2018 max drawdown | -56.75% |
| Sell fail rate | 11.83% |
