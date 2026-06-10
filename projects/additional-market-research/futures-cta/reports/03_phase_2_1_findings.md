# Phase 2.1 findings：Tushare 全品种数据底座

**时间**：2026-04
**产出**：`data_cache/tushare/clean/{SYMBOL}_clean_returns.csv` × 19 个品种

---

## 1. 最终结论

**19 个品种全部通过自洽检验，数据可用于后续策略研究**。

| 硬标准 | 状态 |
|---|---|
| 合约完整性（n_contracts_failed == 0） | ✅ 19/19 |
| 换月次数在品种合理范围 | ✅ 19/19 |

描述性指标（不参与 pass/fail，但需要理解其含义）：

- `n_extreme_5pct`：品种波动性的直接体现
- `gap_pct`：硬拼接与 clean 的差，反映品种期限结构（正 = Backwardation，负 = Contango）

---

## 2. 关键决策及其依据

### 决策 1：放弃 AkShare，改用 Tushare Pro

**依据**：
- 新浪/AkShare 的"连续主力"是硬拼接数据，M0 豆粕 raw vs clean gap = +78%（NAV 末值差 78 个百分点）
- Sina API 限速严格，无法扩展到 19 品种
- Tushare Pro 提供 `fut_mapping` 表，日频主力合约识别完全可信

### 决策 2：用"收益率拼接"而非"前复权价格"

**依据**：
- 收益率拼接逻辑简单（换月日 return = NaN，同合约内正常算），不需要维护复权因子
- 自拼 clean NAV vs Tushare 自家的硬拼接 M.DCE：gap = +107.4%（豆粕），同向复现了 AkShare 的 +78% gap → **双源三角验证算法正确**

### 决策 3：验收规则按品种差异化（不做统一阈值）

**依据**：第一次跑完 06 出 14 个 WARN，定位后发现：
- 4 个因期限结构平而 `gap < 5%`（CU/AL/TA/AG）
- 9 个因品种本身高波动而 `极端日 ≥ 15`（I/J/SC/P/RU/HC/TA/MA/AG）
- 1 个贵金属品种因主力规则变化（AU 进入双数月制）

**这些都不是数据问题，是"用豆粕的特性外推成统一阈值"的错误**。修正方案：只保留两条硬标准（合约完整 + 换月次数合理），其他指标降为描述性。

### 决策 4：玉米范围放宽到 (2.5, 4.0)

**依据**：08 脚本诊断发现玉米除 1/5/9 外，3 月和 7 月合约也偶尔任主力（青黄不接期 + 夏季深加工）。每段最短 11 天，无回跳、无短段 —— **真实市场规则，不是 mapping 噪声**。

---

## 3. clean returns 的语义边界（非常重要）

**clean returns = 合约内逐日价格运动，同时剔除了"假跳空"和"真实 roll yield"两项**。

| 用途 | 度量 | 说明 |
|---|---|---|
| 信号研究（趋势、均值回归、波动等） | **clean returns** | 正确口径，只关注价格趋势本身 |
| 真实总收益（持仓到期的盈亏） | clean + 换月 roll yield | Phase 2.3 增强项 |
| 硬拼接 NAV | ❌ 永远不要用 | 方向性错误（把假跳空当真涨跌） |

**典型案例 RU0 橡胶**：
- Clean NAV = 0.24（-76%）
- 硬拼接 NAV ≈ 0.67（看似 -33%）
- 真实多头持仓 ≈ clean（Contango 的 roll yield 是真实损失）
- 硬拼接是虚高

---

## 4. 19 品种的长期分类（供策略研究参考）

基于 9 年 clean NAV + gap 方向：

| 分类 | 品种 | 特征 |
|---|---|---|
| 强 Backwardation 多头 | M, P, Y, RB, HC, J, I, AU, AG | clean NAV 大幅上行，gap 强正 |
| 弱 Backwardation | SR, CU, ZN | clean NAV 温和上行，gap 小正 |
| 平水 / 震荡 | C, CF, TA, AL | gap 接近 0，方向不确定 |
| Contango 拖累 | MA, RU, SC | 长期 Contango，clean NAV 跌 |

这张分类将直接影响 TSMOM 的假设：**多头 bias 品种更适合做趋势跟随（趋势 + carry 共振），Contango 品种空头更有把握**。

---

## 5. 代码产物清单（按用途分三类）

### 🟢 生产（被 Phase 2.2 及以后继续使用）

| 文件 | 作用 |
|---|---|
| `Phase_2_1_tushare/pipeline.py` | 可复用数据管道模块 |
| `Phase_2_1_tushare/build_universe.py` | 主执行：19 品种批量拉取 + 质量报告 |

### 🟡 一次性探测 `Phase_2_1_tushare/probes/`

| 文件 | 作用 |
|---|---|
| `probe_tushare_api.py` | Tushare token + API 最小连通性验证 |
| `probe_symbol_format.py` | 19 品种 ts_code 约定批量验证 |

### 🔵 一次性验证（留档凭证）`Phase_2_1_tushare/validations/`

| 文件 | 作用 |
|---|---|
| `pilot_M_pull.py` | 豆粕单品种端到端试点（现已被 build_universe 取代） |
| `crosscheck_vs_akshare.py` | Tushare vs AkShare 交叉验证 |
| `diagnose_dominant_gap.py` | 跨源主力识别差异诊断 |
| `self_check.py` | Tushare 自洽检验（换月 + NaN + 极端日 + 同源 raw-vs-clean） |
| `inspect_extreme_days.py` | 高波动品种视觉抽查 |
| `diagnose_C_switches.py` | 玉米换月次数偏高根因诊断 |

**三类的使用频率**：
- 生产 = 每次数据更新都跑
- 探测 = 换 token / 加交易所时参考
- 验证 = "回头看为什么相信这份数据"时再跑一次

---

## 6. 可迁移到加密合约的部分

这个 phase 的成果在 Phase 1（加密）里几乎可以原样复用：

- 主力/次主力合约识别方法（例如 Binance perpetual 主力基于持仓量/成交量）
- "收益率拼接"对付合约换月（季度合约 BTCUSDT quarterly → next quarterly）
- raw vs clean 的 gap 诊断逻辑
- 按品种差异化验收的思路

**学期货是在锻炼严谨，学加密是在赚钱** —— 这两个技能是一套的。
