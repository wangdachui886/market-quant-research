# Phase 2.2 归档 · TSMOM 基线

**时间**：2026-04
**状态**：✅ 完成
**核心结论**：**单信号 TSMOM + vol-targeting，19 品种等权组合 Sharpe = 0.70**，稳定打过 B&H（0.60）；但单品种 5/19 仍负 Sharpe，需引入独立信号源（Phase 2.3 Carry）突破天花板。

---

## 1. 最终数据（都是同一套 lookback=252d、lag=1d、等权组合、无成本）

| 组合 | Sharpe | Ret | Vol | MaxDD | NAV末 |
|---|---|---|---|---|---|
| raw TSMOM（±1 仓位）| **0.52** | 4.0% | 7.8% | -16.7% | 1.38 |
| **vol-target TSMOM**（target=20%, window=60d）| **0.70** | 4.6% | 6.6% | -12.6% | 1.46 |
| B&H 等权 | 0.60 | 7.7% | 12.8% | -20.6% | 1.81 |

**同风险水平下**（把 vt 组合加杠杆到 B&H 的 12.8% vol，≈1.94×）：
- vt 等效 Ret ≈ 8.9%（> B&H 7.7%）
- vt 等效 MaxDD ≈ -24.5%（略差于 B&H -20.6%）

Sharpe 层面稳定赢，绝对收益层面 tie。TSMOM 作为独立策略**站住脚**。

---

## 2. 分层框架（贯穿 Phase 2.2 → 未来）

```
Layer 1 · 信号    signals.py        ∈ {-1, 0, +1}  — 方向/入场/离场/换向
Layer 2 · 仓位    sizing.py         ≥ 0            — 风险预算
Layer 3 · 执行    backtest.py       shift(lag)     — 防未来函数
Layer 4 · 组合    run_universe*.py  权重规则       — 品种间分散
```

**强制约束**：每个 Layer 只回答自己的问题，互不侵入。新信号 = Layer 1 加函数；新权重规则 = Layer 4 加函数。**不在任一函数内部加 if/else 分支**。

---

## 3. 关键发现

### 3.1 分散增益 ≈ 3×，组合 Sharpe 天花板在 0.8 附近

代入 $\text{Sharpe}_P \approx \overline{\text{Sharpe}_i} / \sqrt{\bar\rho + (1-\bar\rho)/N}$，反解出策略收益间平均相关性 $\bar\rho \approx 0.09$。继续调 Layer 2（EWMA、vol_window）预期只能把 0.70 推到 0.75。**要突破必须加独立信号源**。

### 3.2 vol-target 的两重价值

- **静态**：把 I0/J0/SC0（σ=33%）压到 target，避免少数高噪品种主导
- **动态**：每品种内部在高波段自动降仓（TA0 avg_scale=1.00× 但 Sharpe 从 0.18→0.48，纯粹是动态调仓的功劳）

### 3.3 vol-target **救不了**方向信号错的品种

5 个品种 vt 后仍负 Sharpe：**M0 / SR0 / CF0 / MA0 / ZN0**。

共性：**均值回归或强季节性**（豆粕受 USDA 报告、白糖受出糖周期、棉花受种植季、甲醇长期 contango、锌区间震荡）。TSMOM 捕捉"涨则继续涨"，在这些 regime 下是负 EV。

这是**信号层（Layer 1）问题**，调仓位层（Layer 2）无济于事。

### 3.4 修过的重要 bug

**sizing.py 的 `min_periods=window` 对带 NaN 的序列过严**

- 月换月品种（CU/ZN/AL/SC）在 60 日窗口里必含 NaN（2.86 个/窗口期望）→ scale 恒 NaN → 仓位恒 0 → vt_vol = 0%
- 季换月品种在约 50% 窗口含 1 个 NaN → 仓位在一半时间被归零 → vt_vol 只有 target 的一半（10% vs 20%）

**修复**：先 `dropna` 压缩序列做 rolling，再 `reindex + ffill` 回原 index。换月日继承前一天的 σ̂ 估计。

**教训**：clean_returns 里的 NaN 是 Phase 2.1 的设计选择（防假跳空），所有**滚动窗口计算都要显式处理**，不能依赖 pandas 默认行为。

---

## 4. Phase 2.2 交付物

| 文件 | 作用 |
|---|---|
| `Phase_2_2_tsmom/signals.py` | Layer 1：`tsmom_signal(returns, lookback=252)` |
| `Phase_2_2_tsmom/sizing.py` | Layer 2：`vol_target_scale(returns, target_vol, window, floor, max_lev)` |
| `Phase_2_2_tsmom/backtest.py` | Layer 3：`backtest_single(returns, target_position, lag=1)` |
| `Phase_2_2_tsmom/run_single.py` | CF0 单品种 TSMOM 基线（Step 1） |
| `Phase_2_2_tsmom/run_universe.py` | 19 品种 raw TSMOM 组合（Step 2） |
| `Phase_2_2_tsmom/run_universe_voltarget.py` | 19 品种 vt TSMOM 组合 + 对比（Step 3） |
| `outputs/tsmom_universe.png` | raw 组合 NAV 图 + 各品种 Sharpe |
| `outputs/tsmom_universe_voltarget.png` | raw vs vt 对比 NAV + 逐品种 bar |
| `outputs/tsmom_universe_per_symbol.csv` | raw 各品种指标表 |
| `outputs/tsmom_universe_voltarget_per_symbol.csv` | vt 各品种指标表 |

---

## 5. Phase 2.2 没做 / 不要做的事

- ❌ **Lookback sweep**：固定 252d。调参会过拟合，且已证明"加独立信号"比"调参"收益大
- ❌ **交易成本**：年换仓 ~4 次，单边 2bp 影响 <0.1%，对大结论无干扰
- ❌ **Detrended 信号检验**：TSMOM 赚钱原因明确（Sharpe 分布与品种趋势性一致），没有必要
- ❌ **截面 TSMOM / XSMOM**：19 品种太少，学术建议 ≥50

---

## 6. 交给 Phase 2.3 的明确假设

1. **加 Carry 信号（独立 alpha）后，组合 Sharpe 有望到 0.9-1.0**（基于 corr(TSMOM, Carry) ≈ 0.1 的学术先验）
2. **5 个 TSMOM 坟墓品种中，至少有 3 个会被 Carry 翻正**（M0/CF0/SR0 有显著期限结构信号，MA0 长期 contango 可被 short-carry 捕捉）
3. **Pooling 融合（$s_{\text{combined}} = (s_{\text{tsmom}} + s_{\text{carry}}) / 2$）优于 AND 门控或乘法**

详见 `docs/06_phase_2_3_plan.md`。
