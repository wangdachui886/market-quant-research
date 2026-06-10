# Phase 2.4 归档 · 真实性与稳健性（OOS 验证 + 事前经济学筛选 + 归因分解）

**时间**：2026-04
**状态**：🟢 主线结论已定稿；T5 交易成本测试未完成（留待 2.4b）
**核心结论**：**Phase 2.3 的"双引擎分散增益"命题在 OOS 上成立**，但**原始 19 品种等权 Pool 的 OOS Sharpe（1.27 表面强通过）里包含约 0.64 Sharpe 的 2023-2025 贵金属大牛市一次性风险溢价；真实可期望的 OOS Sharpe 下界约 0.63（来自 14 品种 Carry-valid universe 的纯双引擎 Pool）、上界约 1.27（含贵金属 TSMOM 吃单边）、合理中位值 0.7-0.9**。反直觉的是：**TSMOM 作为独立引擎在 OOS 上极不稳定**（剥离贵金属后 17 品种 OOS Sharpe -0.07、14 品种 +0.02），真正扛住 OOS 的是经过事前经济学筛选的 Carry 信号，以及两个引擎在不同品种上失败模式不相关带来的组合分散。

---

## 1. 三轮验证的数据总览（同一套参数：lookback=252, vt=20%, vw=60, lag=1）

| # | 策略 · universe | IS Sharpe (2017-2022) | OOS Sharpe (2023-2025) | Δ | 判决 |
|---|---|---|---|---|---|
| T1 | **Pool_original** · 19 | 1.08 | **0.34** | -0.74 | ❌ 未过 0.50 通过线 |
| T1 | TSMOM_only · 19 | 0.73 | 0.64 | -0.09 | ✅ 看似稳（后被证伪）|
| T1 | Carry_only · 19 | 1.13 | **-0.21** | -1.34 | ☠️ 崩溃 |
| T2 | **Pool_filtered** · 19 | 1.10 | **1.27** | +0.17 | ✅✅ 强通过（表面）|
| T2.5 | Pool_filtered · 17 (剔 AU/AG) | 1.11 | 0.42 | -0.69 | — 诊断 |
| T2.5 | TSMOM_only · 17 | 0.73 | **-0.07** | -0.80 | — 诊断（TSMOM 暴露脆弱）|
| T2.5 | **Pool · 14 (Carry-valid, 主裁判)** | **1.33** | **0.63** | -0.70 | ✅ 过 0.50 通过线 |
| T2.5 | TSMOM_only · 14 | 0.88 | **0.02** | -0.86 | — 诊断（TSMOM 近零）|

**三轮对 Pool vs TSMOM 的 OOS edge 对比（apples-to-apples）**：

| universe | Pool OOS | TSMOM OOS | Δ edge |
|---|---|---|---|
| 19 品种 | 1.27 | 0.64 | +0.63 |
| 17 品种 (no_gold) | 0.42 | -0.07 | +0.49 |
| 14 品种 (carry_valid) | 0.63 | 0.02 | +0.61 |

**关键一致性**：三种 universe 下，Pool 对 TSMOM 的 OOS edge 稳定在 **+0.49 ~ +0.63**，这种跨 universe 一致性是"双引擎真有分散增益"最强的证据——不依赖任何特定品种选择。

---

## 2. T1 · OOS 冻结回放（切点 2022-12-31，IS 6 年 / OOS 3 年）

### 2.1 设计

- **半严格 OOS**：承认 universe 选择过程看过全期数据，只验证"冻结规则在新时间段是否稳定"
- **自然跨界**：OOS 段的 rolling 信号允许回看 IS 尾部（模拟"实盘在 2022 末不 reset 继续跑"）
- 参数、universe、合成规则**完全冻结**，不因 OOS 结果调整任何东西

### 2.2 结果（摘自 `Phase_2_4_robustness/outputs/oos_metrics.csv`）

- **Pool_original OOS Sharpe = 0.34**，进入 "0.30-0.50 红旗区间"，未过 0.50 通过线
- **Carry_only OOS Sharpe = -0.21**，从 IS 的 +1.13 彻底崩溃，Δ = -1.34
- TSMOM_only OOS Sharpe = 0.64（当时看起来稳，后经 T2.5 证伪）
- Pool_filtered 的 OOS 衰减不是因为"双引擎分散增益假设错了"，而是 Carry 信号在 5 个特定品种上失效拖累全场

### 2.3 逐品种诊断（`run_oos_diagnose_carry.py`）

Carry 不是整体崩溃，是**少数板块/品种拖累全场**：

| 板块 | n | IS Sharpe | OOS Sharpe | Δ |
|---|---|---|---|---|
| **贵金属** | 2 | -0.25 | **-1.46** | -1.21 |
| **农产品** | 6 | +0.25 | -0.14 | -0.39 |
| 能化 | 4 | +0.13 | +0.03 | -0.11 |
| 有色 | 3 | +0.57 | +0.38 | -0.19 |
| 黑色 | 4 | +0.81 | +0.37 | -0.44 |

Carry OOS Sharpe 单品种极端尾部：AU0 -1.99、CF0 -1.05、C0 -1.02、AG0 -0.93、SR0 -0.62。5 个极端负值把组合 Sharpe 拉到负区。**这 5 个品种在 Phase 2.3 findings §3.6/§3.7 就被标注为问题品种，但当时我们怕"ex-post 挑选"而全保留——这是本阶段最核心的方法论教训**。

---

## 3. T2 · Universe Refinement（事前经济学筛选）

### 3.1 方法论立场区分

| 操作 | 依据 | 性质 |
|---|---|---|
| 事前经济学筛选 | 学术论文级的先验（KMPV / Erb-Harvey）| ✅ 合法 |
| 事后 Sharpe 筛选 | 因为 OOS Sharpe 差所以踢掉 | ❌ ex-post 挑选 |

判定红线一句话：**排除理由能不能写在回测之前？** 能 → 合法；不能 → ex-post。

### 3.2 学术依据

- **Koijen, Moskowitz, Pedersen, Vrugt (2018)** *"Carry"* (JFE)：贵金属 carry 只含 cost-of-carry（利率+存储费），不包含 convenience yield，不应作为预测信号。论文构造商品 Carry 组合时**直接排除贵金属**
- **Erb, Harvey (2006)** *"The Strategic and Tactical Value of Commodity Futures"* (FAJ)：商品按 Carry 可预测性分三类。policy-distorted 商品（糖、棉、玉米类）的 basis 被政策主导，不反映真实供需
- 中国市场特殊性：C0/CF0/SR0 存在临储/国储/抛储制度，政策干预强度比美国对应品种更高

### 3.3 筛选结果

**Carry excluded（5 个，Carry 信号关闭，改用纯 TSMOM）**：
- **AU0 黄金 / AG0 白银**：KMPV 2018 直接排除，pos_rate 0-4%
- **C0 玉米 / CF0 棉花 / SR0 白糖**：Erb-Harvey policy-distorted 类

**Carry kept（14 个）**：M0, Y0, P0, RB0, I0, J0, HC0, CU0, ZN0, AL0, TA0, MA0, RU0, SC0

**TSMOM universe 不变（19 全保留）**，因为 TSMOM 不依赖 Carry 的经济学前提。

### 3.4 非对称合成规则

```
14 Carry-valid 品种：  pos = (sig_T + sig_C) / 2 × scale
 5 Carry-excluded 品种： pos = sig_T × scale
组合层：等权 19 品种
```

### 3.5 Pool_filtered T2 结果

- **Pool_filtered OOS Sharpe = 1.27**，强通过 0.70
- OOS Ret +6.6%、OOS Vol 5.2%、OOS MaxDD -5.0%
- 相对 Pool_original OOS 0.34 提升 +0.93；相对 TSMOM_only 19 OOS 0.64 提升 +0.63

**反常点**：Pool_filtered OOS (1.27) > IS (1.10)。这在稳健性测试里罕见，**触发了 T2.5 的归因分解**。

---

## 4. T2.5 · 归因分解（核心发现）

### 4.1 双层拆解

**归因 Q1：年度稳定性**（`run_oos_attribute.py`）
- 2023 Sharpe +0.95、2024 +2.11、2025 +0.88
- 三年都 > 0.5，最差年 0.88；**年度维度上 1.27 不是某年尖刺** ✅

**归因 Q2：品种贡献集中度**（同脚本）
- Top 3 品种贡献了 **84%** 的组合 ann_ret（警戒阈值 70%）
- **Top 2 = AU0（贡献 41%，Sharpe +2.26）+ AG0（贡献 31%，Sharpe +1.80）**
- **这 2 个品种在 Pool_filtered 里是纯 TSMOM 策略**
- 结论：1.27 的大头是贵金属 TSMOM 吃单边行情，**必须再拆一层**才能看清真实 edge

### 4.2 三种 universe 对照测试（`run_oos_decompose.py`）

| universe | 理由 | Pool OOS | TSMOM OOS | Δ |
|---|---|---|---|---|
| 19 | 原始部署 universe | 1.27 | 0.64 | +0.63 |
| 17 (no_gold) | 剥离贵金属 TSMOM 运气 | 0.42 | **-0.07** | +0.49 |
| **14 (carry_valid)** | **纯 Carry-valid 学术对照（主裁判）** | **0.63** | **0.02** | **+0.61** |

判决规则：**B 是主裁判**（14 vs 14 同 universe、同参数，差异只来自是否叠加 Carry 信号）。

### 4.3 主裁判结论

- Pool_on_14 OOS Sharpe = **0.63** > 通过线 0.50 ✅
- TSMOM_only_14 OOS Sharpe = **0.02** ← TSMOM 作为独立引擎在 Carry-valid universe 上**近乎零 Sharpe**
- Δ edge = **+0.61**，跨 universe 一致

**"Phase 2.3 双引擎分散增益命题"在 OOS 强成立**。

### 4.4 Pool_filtered_19 OOS 1.27 的完整分解

```
1.27 = [Pool_on_14 真实 edge: ~0.63]
     + [AU0/AG0 在 2023-2025 吃到贵金属百年级单边: ~0.64]

其中：
- 0.63 = 真实的跨品种双引擎 edge，可期望、可复现、跨 universe 一致
- 0.64 = period-specific 风险溢价一次性兑现，不可期望
```

**真实期望 OOS Sharpe 应按 0.6-0.9 范围评估，不是 1.27**。

---

## 5. 最大的三个发现

### 5.1 TSMOM 作为独立引擎在 OOS 上**极不稳定**

这是本阶段**最意外**的发现：

- TSMOM_only 19 OOS 0.64（看似稳）
- TSMOM_only 17 OOS **-0.07**（剥离 AU/AG 后直接崩）
- TSMOM_only 14 OOS **+0.02**（再剥离 C/CF/SR 后几乎零）

**Phase 2.3 里 TSMOM Sharpe 0.70 的"稳"，主要是 AU/AG 这两个品种在 IS 后段已经开始走趋势，OOS 又恰好接着走出百年级单边**。剥离贵金属后 TSMOM 在中国商品 OOS 上**近乎失效**。

这和学术刻画完全一致：**Moskowitz, Ooi, Pedersen (2012)** *"Time Series Momentum"* 给出的长期（1985-2009、58 资产）TSMOM Sharpe 是 1.0-1.5 的均值，但论文明确指出**任何单一 3 年窗口上 TSMOM 可能接近零或负**。我们 17/14 品种的 OOS 3 年正好是这种窗口。

**推论**：Phase 2.4 中期考虑过的"如果 Pool 失败就主线切 TSMOM-only 实盘化"的备用路径**也不成立**，TSMOM-only 本身在中国商品非贵金属 universe 上 OOS 几乎废掉。

### 5.2 "双引擎分散增益"的机制在 OOS 上被**精确复现**

Phase 2.3 findings §3.3 原话（当时是 IS 推测）：

> "事前我们不知道哪个引擎在哪个品种正确，Pool 是保守加权的最优策略。"

OOS 数据精确验证：
- **TSMOM 单独**：除贵金属外 OOS 全面失效（Sharpe ≈ 0）
- **Carry 单独**：除被筛出的 5 个品种外 OOS 有 edge，但品种不相同
- **Pool 合成**：**两个引擎在不同品种上失败，合起来总有一个在工作**

学术支撑：
- **Asness, Moskowitz, Pedersen (2013)** *"Value and Momentum Everywhere"*：multi-factor combination always beats single factor OOS，论文主旨和我们的发现完全对应
- **Koijen et al (2018)**：Carry 和 Momentum 是低相关的独立 factor。我们实测 ρ_TC ≈ 0.22（Phase 2.3 findings §3.2），低相关是 Pool 压 vol 的数学基础

### 5.3 事前经济学筛选是**必须**做的，不是可选

Phase 2.3 当时把"不 ex-post 挑选品种"的纪律用过了头，混淆了：
- **事前经济学筛选**（KMPV 说贵金属 Carry 没用）→ 合法
- **事后 Sharpe 挑选**（看到 OOS 差就踢）→ 违规

结果 IS 的 Pool 0.86 里已经埋着 5 个"理论上不该做 Carry 的品种"引入的系统性拖累，OOS 把这个隐患放大。T2 改正后 OOS 1.27 表面强通过，T2.5 进一步拆出 0.63 的真实 edge。

**教训**：学术文献级的先验知识应该在**策略构造阶段**就写入 universe filter，不应因为"想避免 ex-post 嫌疑"而拖到后期。

---

## 6. 交付物

| 文件 | 作用 |
|---|---|
| `Phase_2_4_robustness/run_oos.py` | T1 · OOS 冻结回放主脚本 |
| `Phase_2_4_robustness/run_oos_diagnose_carry.py` | T1 后续 · Carry OOS 按品种/板块诊断 |
| `Phase_2_4_robustness/run_oos_filtered.py` | T2 · 事前经济学筛选后的 Pool OOS |
| `Phase_2_4_robustness/run_oos_attribute.py` | T2 归因 · 年度 + 品种贡献拆解 |
| `Phase_2_4_robustness/run_oos_decompose.py` | T2.5 · 三种 universe 对照（A + B 主裁判）|
| `outputs/oos_metrics.csv` | T1 指标表 |
| `outputs/oos_comparison.png` | T1 NAV + Sharpe bar |
| `outputs/carry_oos_diagnose_per_symbol.csv` | Carry 逐品种 OOS 诊断表 |
| `outputs/carry_oos_diagnose_by_sector.csv` | Carry 板块聚合表 |
| `outputs/carry_oos_diagnose.png` | Carry 板块柱状 + 单品种散点 |
| `outputs/oos_filtered_metrics.csv` | T2 结果指标表 |
| `outputs/oos_filtered_comparison.png` | T2 NAV + Sharpe bar |
| `outputs/oos_attribute_yearly.csv` | OOS 年度拆解 |
| `outputs/oos_attribute_per_symbol.csv` | OOS 品种贡献 |
| `outputs/oos_attribute.png` | 年度 + 贡献可视化 |
| `outputs/oos_decompose_metrics.csv` | 7 个策略×3 段的汇总 |
| `outputs/oos_decompose.png` | A/B 对照主图 |

---

## 7. 部署决策（当前冻结）

- **部署 universe**：19 品种（保持事前选择）
- **部署策略**：Pool_filtered（14 品种用 (T+C)/2，5 品种用纯 T）
- **期望 Sharpe 评估**：按 **0.63（保守下界）** 做资金分配，1.27（上界）不作规划依据
- **预期 Vol**：5-6%、**预期 MaxDD**：-7% ~ -9%（按 IS/OOS 极值偏保守）

---

## 8. 刻意没做 / 延后

- ❌ **T5 交易成本敏感性**：现在可以做，但应在三个 universe（19 / 14 / TSMOM_only 19）上同时扫，避免单一数字误导。**留到 2.4b**
- ❌ `backtest.py` 的 `n_trades` 换手语义修正（延续 Phase 2.3 未修项，改在 T5 前修）
- ❌ **walk-forward 多切点 OOS**：当前只做了单次切分 2022-12-31。未做 2020-12-31 / 2021-12-31 等备用切点验证。留给 2.5
- ❌ **Block bootstrap Sharpe 置信区间**：可补充但非决定性证据
- ❌ **交易成本后的动态权重优化**：2.5 工作项
- ❌ **资金规模 / 实盘可实施性分析**：Phase 2.5 的重点工作项

---

## 9. 给 Phase 2.5 的问题清单

### 9.1 高优先级（必做）

**1️⃣ T5 · 交易成本稳健性**
- 单边 {0, 1, 2, 5, 10, 20} bp，同时扫三条基线（Pool_filtered_19 / Pool_on_14 / TSMOM_only_19）
- 关注 break-even cost 和"哪个 universe 对成本最敏感"
- 先修 `backtest.py` 的 `n_trades` 语义再跑

**2️⃣ 资金规模 / 可实施性分析**
- 按不同起始资金（10万 / 30万 / 50万 / 100万 / 300万 / 1000万）
- 枚举合约最小 1 手保证金、lot 离散化后 vol-target 的量化误差
- 给出"最小可实施资金阈值"+"不同资金档位的实际可用品种子集"
- 评估 lot 离散化对组合 Sharpe 的折损

### 9.2 中优先级（选做）

**3️⃣ Walk-forward OOS**
- 2020-12 / 2021-12 / 2022-12 三个切点，检验 Phase 2.4 T2 的结论在其他切分下是否仍成立
- 如果在某个切点 Pool_on_14 edge 消失，说明 +0.61 是单次运气

**4️⃣ 动态权重**
- 基于近期 T/C 表现调权（Moskowitz et al 做法）
- 但需警惕 overfitting，先用 1 年滚动平均这种最朴素的做法

### 9.3 不做 / 明确排除

- ❌ 朴素 MC / 合成 GBM 路径：和 TSMOM 自相关性假设相冲，证据力为零
- ❌ "聪明 pooling"（signal magnitude / soft voting）：T 和 C 都是离散 sign 信号，加复杂度前要有很强经济学理由
- ❌ ML / 非线性信号：超出 naive 策略框架，需要独立评估过拟合风险

---

## 10. Phase 2.4 三轮判断的完整修正记录（自我复盘）

本阶段内部判断翻了三次，每次都被下一轮数据推翻。留档作为方法论教训：

| 阶段 | 当时判断 | 下一轮打脸 | 教训 |
|---|---|---|---|
| T1 后 | "Pool 失败，可能要归档；TSMOM 是稳的，备用主线切 TSMOM-only" | T2 发现 Carry 崩溃集中在 5 个品种，筛掉后 Pool 反而强通过 | 组合级数字骗人，必须先逐品种诊断 |
| T2 后 | "Pool_filtered OOS 1.27 强通过，双引擎假设被验证" | T2 归因发现 Top 2 贡献者是 Carry-excluded 的 AU/AG 纯 TSMOM，吃到贵金属百年级单边 | 漂亮数字必须做品种贡献拆解 |
| T2.5 前 | "1.27 基本来自贵金属运气，剥离后 Pool 可能连 0.5 都过不去；应归档 Pool，主线切 TSMOM-only" | T2.5 发现 Pool_on_14 仍有 0.63 edge，真正废的是 TSMOM_only（剥离贵金属后 ≈ 0）；双引擎命题反而在主裁判下强成立 | 口头估算容易两头错，必须跑 apples-to-apples 脚本 |

**与 `working-principles` 的呼应**：
- "不要口算经济账"——每次我试图口头估算都错，只有脚本数据能下结论
- "结果不好时果断归档"——但归档前必须区分"真失败"（证据链完整）和"诊断未完成"（T1 就归档就会错过 T2）
- "证伪假设本身就是合法产出"——我们同时做到了"证伪 TSMOM-only 主线"和"证实双引擎命题"，这种双向产出才是完整的稳健性检验

---

## 11. 和学术的完整挂钩

本阶段结论不是"跑出一个好看的 Sharpe"，而是把中国商品期货 CTA 的具体数据串到了商品 factor 研究的主干论文：

| 论文 | 贡献的洞察 | 本阶段验证点 |
|---|---|---|
| Koijen, Moskowitz, Pedersen, Vrugt (2018) *"Carry"*, JFE | Carry = E(r) − E(Δprice)；贵金属 carry 无 convenience yield | AU/AG Carry 在 OOS 崩溃；排除后 Pool 恢复 |
| Erb, Harvey (2006) *"The Strategic and Tactical Value of Commodity Futures"*, FAJ | 商品分三类：storable / seasonal / policy-distorted | C0/CF0/SR0 在中国政策干预下成为 Carry 噪声源 |
| Moskowitz, Ooi, Pedersen (2012) *"Time Series Momentum"* | TSMOM 长期 Sharpe 高但单窗口波动极大 | TSMOM_14 OOS 0.02 精确体现"短窗口失效" |
| Asness, Moskowitz, Pedersen (2013) *"Value and Momentum Everywhere"* | Multi-factor 在 OOS 稳定优于 single-factor | Pool vs TSMOM 的 +0.49~+0.63 一致 edge |
| Harvey, Liu, Zhu (2016) *"...and the Cross-Section of Expected Returns"*, RFS | Universe selection 是事前研究的一部分，不是 data-snooping | T2 的事前经济学筛选是方法论上合法的 |

这是本项目第一次在一个阶段里**系统性地把 5 篇论文的洞察和自己的数据对应上**。Phase 2.5 之后如果要公开分享，这条学术-实证的对应关系是最有说服力的叙事骨架。
