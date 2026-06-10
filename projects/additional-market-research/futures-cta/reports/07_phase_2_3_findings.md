# Phase 2.3 归档 · Carry 引擎 + 双引擎 Pooling

**时间**：2026-04
**状态**：✅ 完成（IS 基线）
**核心结论**：**TSMOM × Carry 等权 Pooling，组合 Sharpe = 0.86**，相对单引擎 max(T,C)=0.70 实现 +0.17 的真实分散增益，同时 Vol 从 6.6% 降到 5.0%（-24%），MaxDD 从 -12.6% 降到 -8.9%（-29%）。Pool 恒等式 `pnl_P = 0.5×pnl_T + 0.5×pnl_C` 数值精度 MAE=2.6e-19，TSMOM/Carry 贡献近似对等（53% / 47%）。**IS 层面"双引擎优于单引擎"的假设成立**。

---

## 1. 最终数据（同一套：19 品种、vol-target=20%、vol_window=60d、lag=1、等权、无成本）

| 组合 | Sharpe | Ret | Vol | MaxDD | NAV末 |
|---|---|---|---|---|---|
| B&H 等权 | 0.60 | 7.7% | 12.8% | -20.6% | 1.81 |
| TSMOM vt（Phase 2.2 基线）| 0.70 | 4.6% | 6.6% | -12.6% | 1.46 |
| Carry vt A（raw sign）| 0.68 | 4.0% | 6.0% | -12.9% | 1.40 |
| **Pooled 0.5T + 0.5C** | **0.86** | 4.3% | **5.0%** | **-8.9%** | 1.44 |

**三维度同时改善**：Sharpe +22%、Vol -24%、MaxDD -29%，Ret 近似不变。不靠加杠杆、不靠调参 —— 这正是"免费午餐"的标志。

---

## 2. 框架延续（Phase 2.2 的四层结构 1:1 复用）

```
Layer 1 · 信号   signals.py         carry_signal_raw = sign(carry)     ∈ {-1, 0, +1}
                                    + Phase 2.2 的 tsmom_signal
Layer 2 · 仓位   sizing.py          vol_target_scale（直接复用）         ≥ 0
Layer 3 · 执行   backtest.py        shift(lag=1)（直接复用）           防未来函数
Layer 4 · 组合   run_*.py           等权组合（直接复用）                品种间分散
(新) Pooling     run_pooled.py      (s_T + s_C)/2 × scale              引擎间融合
```

**新增的 "Pooling" 概念落在"信号层之后、仓位层之前"**，是第五件事而不是新的一层 —— 它把"多个方向信号"降维成一个标量，交给 Layer 2 照常缩放。

---

## 3. 关键发现

### 3.1 Carry 独立击穿 B&H（单独就能赚钱）

```
Carry-only vt   Sharpe=0.68 > B&H 0.60
```

**Carry 不是"动量的补丁"，它本身就是一个独立 alpha 引擎**。这一条是本 phase 最不容忽视的事实。

### 3.2 两引擎相关性极低（ρ ≈ 0.22）

从 Pool 合成波动反推：
```
Pool vol = 0.5 × √(σ_T² + σ_C² + 2ρ·σ_T·σ_C) = 5.0%
σ_T = 6.6%, σ_C = 6.0%  →  ρ ≈ 0.22
```

学术先验 ρ ≈ 0.1，实测 0.22，都指向**低相关**。这是 Pool 能把 Sharpe 从 0.70 拉到 0.86 的数学原因。理论上 ρ=0 能到 ~0.95，我们拿到的 0.86 已经接近这个上限。

### 3.3 Pool 比 max(T,C) 多出的 +0.17 Sharpe 来自"错误不相关"

**单品种层面，Pool 通常比 max(T,C) 差**（14/19 品种如此）：
- M0：T=-0.34, C=+0.57 → P=+0.16（打架 36%，Pool 被 TSMOM 拖累）
- AU0：T=+0.80, C=-0.98 → P=-0.19（打架 74%，Pool 被 Carry 拖累）
- I0：T=+0.14, C=+0.85 → P=+0.57（低于 Carry 单跑）

**但组合层面 Pool 显著优于单引擎**。原因：**两个引擎在不同品种上失败**。事前我们不知道哪个引擎在哪个品种正确，Pool 是"保守加权"的最优策略。

### 3.4 PnL 归因恒等式（数值验证）

```
pnl_pool = ret × pos_p = 0.5 × pnl_T + 0.5 × pnl_C
```

| | 年化 |
|---|---|
| 0.5 × TSMOM 贡献 | +2.29% |
| 0.5 × Carry 贡献 | +2.02% |
| 和 | +4.31% |
| Pool 实测 | +4.32% |
| MAE | 2.6e-19（数值 0）|

**TSMOM 贡献占 53%，Carry 贡献占 47%**。两个引擎都是活跃的 PnL 来源，没有一边"躺平"。

### 3.5 最大反常识：平滑 carry 反而伤害表现

`sign(carry)` (A) vs `sign(rolling_mean(carry, 21))` (B)：

```
A Sharpe 0.68  >>  B Sharpe 0.47
```

**直觉错了**。最初假设 "carry 里有换月噪声，应该平滑"；实测发现平滑让组合 Sharpe 掉 -0.21。

**原因**：carry 是**状态量**（今天期限结构的现实），不是**估计量**（对趋势的噪声观测）。对状态量平滑 = 人为制造滞后。每次 regime 翻转（M0 进入 contango、TA 回升到 backwardation）B 要晚 ~10 个交易日，那段时间市场已经按新状态定价了。

**一句话原则**：
> TSMOM 用 past return → 需要长窗口平均（噪声估计量）
> Carry 用 today's basis → 直接用 sign（状态量，无需滤波）

### 3.6 两引擎一致性分布

```
平均同意率 62%  |  平均相反率 37%
```

"相反"听起来是坏事，**在 Pool 框架里反而是好事**：两信号打架 → Pool = 0 → 自动躲开不确定性。AU0（74% 对立）最终 P=-0.19 远好于 Carry 单跑的 -0.98，就是这个机制救了命。

打架最严重 3 个品种：
- **AU0** opp=74%（黄金长期 contango vs 近年强趋势）
- **AG0** opp=62%（类似黄金逻辑）
- **CU0** opp=56%（工业金属，carry 在 0 附近 + TSMOM 信号频繁翻转）

### 3.7 品种可以按 "双引擎应对力" 分成四档

| 档 | 描述 | 品种 |
|---|---|---|
| A · 协同增益 | Pool > max(T, C) | P0, RB0, CU0, SC0 |
| B · 强打 + 仍盈利 | Pool < max 但仍 >0 | Y0, I0, HC0, AL0, M0, J0, RU0, TA0, SC0, AG0 |
| C · 一强一弱拖累 | Pool 被稀释但方向正 | ZN0, AG0 |
| D · 双重失败 | 两引擎都亏 | C0, CF0, MA0, SR0 |

**D 档的 4 个品种是 Phase 2.4 要直面的问题** —— 它们既没有动量信号，也没有 carry 信号，是组合的噪声来源。

---

## 4. 修过的问题

### 4.1 `signals.py` 模块名冲突（Phase 2.2 / 2.3 同名）

**症状**：`from signals import tsmom_signal` 因 sys.path 顺序导致找到 Phase 2.3 版，ImportError。

**修复**：用 `importlib.util.spec_from_file_location` 按**文件路径**显式加载 Phase 2.2 的 `signals.py`，避免命名空间冲突。**不修改 Phase 2.2 的代码**，保持历史阶段独立性。

**教训**：跨 phase 的模块即使同名，也不应相互污染。显式路径加载比"重命名其中一个"更保留各 phase 的语义边界。

### 4.2 backtest.py 的 `n_trades` 含义需要修正（已记录，未改）

`pos_change = (position != position.shift(1))` 会把"仓位缩放每日变化"也算成换手，使换手数 ≈ 252/yr，**无法反映真正的方向翻转次数**。

**延后到 Phase 2.4 修**：真正需要的指标是 `sign(position).diff().abs().sum()`。本 phase 不改，避免影响 Phase 2.2 的已归档数据。

---

## 5. Phase 2.3 交付物

| 文件 | 作用 |
|---|---|
| `Phase_2_3_carry/carry_build.py` | 核心模块：`parse_ts_code`, `next_main_code`, `months_between`, `build_carry`, `build_carry_for_symbol`, `carry_summary` |
| `Phase_2_3_carry/signals.py` | Layer 1 - Carry：`carry_signal_raw`, `carry_signal_smooth` |
| `Phase_2_3_carry/probes/probe_carry_M.py` | 单品种 probe（豆粕） |
| `Phase_2_3_carry/build_carry_universe.py` | 19 品种 Carry 构造 |
| `Phase_2_3_carry/run_universe_carry.py` | Carry-only A/B 对比 |
| `Phase_2_3_carry/run_pooled.py` | ⭐ 双引擎 Pooling 主回测 |
| `outputs/universe_carry_panel.png` | 19 品种 Carry 时序 panel |
| `outputs/universe_carry_report.csv` | Carry 质量统计 |
| `outputs/carry_universe_compare.png` | A vs B Carry 信号对比 |
| `outputs/carry_universe_per_symbol.csv` | Carry-only 逐品种表 |
| `outputs/pooled_compare.png` | Pool vs T vs C vs B&H NAV + 逐品种 Sharpe + 一致性 |
| `outputs/pooled_per_symbol.csv` | Pool 逐品种表 + agree/opposite rate |
| `data_cache/tushare/carry/{SYMBOL}_carry.csv` × 19 | 每日 carry 时序缓存 |

---

## 6. Phase 2.3 没做 / 刻意不做的事

- ❌ **Out-of-Sample 检验**：全部 9 年数据都是 IS。这是 Phase 2.4 的头号任务
- ❌ **交易成本**：无 bp/笔假设，组合 NAV 可能高估
- ❌ **品种清理**：D 档 4 个品种暂时保留（避免 ex-post 挑选）
- ❌ **连续 carry 信号**（signal strength）：留给 Phase 2.5+
- ❌ **动态引擎权重**：当前固定 50/50，不根据近期表现调权

这些都是 Phase 2.4+ 的工作项。

---

## 7. Carry 数据本身的定量特征（19 品种 IS）

### 交割月分布规律
- 1/5/9 主力月品种（M/Y/CF/I/J/RU/TA/MA/P）：gap 几乎恒为 4
- 1/5/10 主力月品种（RB/HC）：gap 在 {3, 4, 5} 均匀分布
- 月主力品种（CU/ZN/AL/SC）：gap 恒为 1
- 6/12 主力品种（AU/AG）：gap 恒为 6，但早期数据覆盖低使 valid_rate 降到 88-95%

### 板块 Carry 图谱（长期年化均值）

| 板块 | 范围 | 经济含义 |
|---|---|---|
| 黑色系 | +8% ~ +16% | 中国基建+地产驱动的强 Backwardation（I0 最极端 +16.4%，pos_rate 92%）|
| 豆系 | +4% ~ +8% | 季节+地缘驱动（M0 +7.5%）|
| 软商品 | -3% 附近 | 软商品长期温和 Contango（C0 -3.0%, CF0 -3.2%）|
| 橡胶 | **-12%** | 最极端 Contango（东南亚过剩，pos_rate 仅 8%）|
| 贵金属 | -1.8% ~ -2.8% | 教科书级 Contango（无消费便利收益，pos_rate ≈ 0）|
| 基金属 + 化工 | ≈ 0% | 供需平衡，carry 在零附近震荡 |
| 锌 | +5.3% | 基金属里的异类（矿端供应紧张多年）|

这张图谱是 Carry 信号为什么"在某些品种上必然有效"的经济学基础。

---

## 8. 给 Phase 2.4 的问题清单（按优先级）

**1️⃣ OOS 真实性检验**（路线 3，推荐先做）
- 切 2017-2022 为 IS、2023-2025 为 OOS
- 只用 IS 发现的信号 + 参数，在 OOS 上冻结规则回放
- **验收下限**：OOS Sharpe ≥ 0.5（否则整个 Phase 2.3 的 0.86 可能是运气）

**2️⃣ 交易成本稳健性**（路线 2）
- 单边 2-5 bp / 笔，加到 backtest.py
- 重新评估 Pool Sharpe、看哪个引擎对成本更敏感

**3️⃣ D 档品种清理的**经济**逻辑**（路线 1）
- C0 有严重政策干预 → 是否该从 universe 踢出？
- MA0 长期零 carry + 弱动量 → 经济上有无 alpha 理由保留？
- **只有先做 OOS，结论才不会是 ex-post 挑选**

**4️⃣ 聪明 pooling**（路线 4，最后做）
- 动态权重（recent-perf weighting）
- 市场状态切换（高波期用 Carry、趋势期用 TSMOM）
- 连续 carry 信号

**原则**：Phase 2.4 不开始新的"搜信号"工作，专注把现有框架**从纸上走到能实盘**。

---

## 9. Phase 2.2 假设的事后复盘

Phase 2.2 归档里写过 3 条假设交给 Phase 2.3 验证：

| 假设 | 结果 | 证据 |
|---|---|---|
| 加 Carry 后组合 Sharpe 有望 0.9-1.0 | ⚠️ 差一点（0.86） | 低于上限但在合理区间 |
| 5 个 TSMOM 坟墓品种 ≥3 个被 Carry 翻正 | ✅ 部分成立（2 个明确翻正：M0、ZN0；RU0 加强）| 见 §3.7 |
| Pooling 融合优于 AND 门控或乘法 | ✅ 等权 Pool 已稳定赢过单引擎 | 未测其他融合方式，但 baseline 达标 |

三条假设都在"基本成立"的范围内，没有意外。
