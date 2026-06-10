"""Phase 2.2 · 极简回测引擎（Phase 2.4 增加成本支持）

单品种通用；多品种组合通过外部循环叠加。

核心契约：
  输入：clean_returns (Series) + signal (Series) [+ cost_bp: float]
  输出：position / strategy_return / NAV / metrics

关键细节：
  - 信号必须滞后 1 天（避免未来函数）
  - 换月日收益 NaN 透传，累积 NAV 时用 fillna(0) 跳过
  - 指标计算全部基于 dropna 后的有效日收益

Phase 2.4 修正（修法 B，向后兼容）：
  - 新增 cost_bp 参数（默认 0，等价于 Phase 2.2/2.3 原始行为）
  - 成本公式：daily_cost = cost_bp × 1e-4 × |position.diff()|
    （按仓位每日绝对变化扣费；vol-target 缩放和方向翻转都算）
  - n_trades 重新定义为"方向翻转次数"（含进出空仓）：
    n_trades = int(np.sign(position).diff().abs().sum() / 2)
    而不是 Phase 2.2 原始的"任意仓位变化次数"（会把 vol-target 每日缩放算作交易）
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def backtest_single(
    clean_returns: pd.Series,
    signal: pd.Series,
    lag_days: int = 1,
    cost_bp: float = 0.0,
) -> dict:
    """单品种回测。

    Parameters
    ----------
    clean_returns : pd.Series
        日频 clean returns（换月日 NaN）
    signal : pd.Series
        同 index；可以是离散 {-1,0,+1} 或连续值（vol-target 乘积）
    lag_days : int, default 1
        信号滞后天数。必须 ≥ 1 否则有未来函数风险。
    cost_bp : float, default 0.0
        单边交易成本，单位 bp（1 bp = 0.01%）。
        成本模型：daily_cost = cost_bp × 1e-4 × |position.diff()|
        position 变化 1.0（例如 -1 → 0 或 0 → +1）、cost_bp = 2 → 扣 2bp NAV。
        cost_bp = 0 时回退到 Phase 2.2/2.3 的原始无成本行为。

    Returns
    -------
    dict
      position : pd.Series   实际持仓（信号滞后后）
      strategy_return : pd.Series  策略日收益（已扣成本，NaN 日透传）
      strategy_nav : pd.Series     策略累积 NAV
      bh_nav : pd.Series            Buy & Hold 基准 NAV
      metrics : dict                    评估指标（含 cost_bp / total_cost 等）
    """
    assert lag_days >= 1, "lag_days < 1 会产生未来函数"
    assert cost_bp >= 0, "cost_bp 必须 >= 0"

    position = signal.shift(lag_days).fillna(0)

    # 成本：按仓位每日绝对变化扣费，vol-target 缩放和方向翻转都算
    pos_change = position.diff().abs().fillna(0)
    daily_cost = cost_bp * 1e-4 * pos_change

    gross_ret = position * clean_returns
    strat_ret = gross_ret - daily_cost

    strat_nav = (1 + strat_ret.fillna(0)).cumprod()
    bh_nav = (1 + clean_returns.fillna(0)).cumprod()

    metrics = _compute_metrics(strat_ret, position, strat_nav, daily_cost, cost_bp)
    return {
        "position": position,
        "strategy_return": strat_ret,
        "strategy_nav": strat_nav,
        "bh_nav": bh_nav,
        "metrics": metrics,
    }


def _compute_metrics(
    strat_ret: pd.Series,
    position: pd.Series,
    strat_nav: pd.Series,
    daily_cost: pd.Series,
    cost_bp: float,
) -> dict:
    ret_valid = strat_ret.dropna()

    ann_ret = ret_valid.mean() * 252
    ann_vol = ret_valid.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else np.nan

    dd_series = strat_nav / strat_nav.cummax() - 1
    max_dd = dd_series.min()
    calmar = ann_ret / abs(max_dd) if max_dd < 0 else np.nan

    n_active = (ret_valid != 0).sum()
    hit_rate = (ret_valid > 0).sum() / n_active if n_active > 0 else np.nan

    # n_trades：方向翻转计数（含进出空仓），不再受 vol-target 每日微调污染
    # sign(pos).diff().abs() 在方向翻转处为 2、进出空仓处为 1
    # 除以 2 得到"交易事件"数（一次翻转 = 一次平仓 + 一次开仓 = 2 个事件）
    sign_diff = np.sign(position).diff().abs().fillna(0)
    n_trades = int(sign_diff.sum() / 2)

    years = (strat_ret.index.max() - strat_ret.index.min()).days / 365.25
    trades_per_year = n_trades / years if years > 0 else 0

    total_cost = float(daily_cost.sum())
    ann_cost_drag = total_cost / years if years > 0 else 0.0

    return {
        "annual_return": float(ann_ret),
        "annual_vol": float(ann_vol),
        "sharpe": float(sharpe) if pd.notna(sharpe) else np.nan,
        "max_dd": float(max_dd),
        "calmar": float(calmar) if pd.notna(calmar) else np.nan,
        "hit_rate": float(hit_rate) if pd.notna(hit_rate) else np.nan,
        "n_trades": n_trades,
        "trades_per_year": float(trades_per_year),
        "cost_bp": float(cost_bp),
        "total_cost": total_cost,
        "ann_cost_drag": float(ann_cost_drag),
    }
