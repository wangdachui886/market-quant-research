"""Phase 2.3 · Layer 1 · Carry 方向信号

输入：单品种 carry 年化序列（build_carry_universe.py 产出的 'carry' 列）
输出：∈ {-1, 0, +1, NaN} 的方向信号

两种实现：
  - carry_signal_raw     : sign(carry_t)
  - carry_signal_smooth  : sign(rolling_mean(carry, window))

为什么会需要 smooth 版本：
  1) 主力换月当日：近月合约突然变成下一个，basis 几何跳变，carry 可能瞬间翻正/翻负，
     纯 sign 会让策略第二天就反向开仓，徒增换手
  2) carry 本身在 ~0 附近时（比如 CU、MA、TA），sign 会在正负之间高频抖动
  3) 21 日 ≈ 1 个月平滑，保留"季度级"carry 趋势，过滤单日噪声

注意：rolling mean 在 carry NaN 日会失效。我们采取"dropna → 算滚动均值 → reindex ffill"
的做法，与 sizing.vol_target_scale 一致，避免 NaN 日让 window 作废。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def carry_signal_raw(carry: pd.Series) -> pd.Series:
    """方案 A：纯 sign。

    Parameters
    ----------
    carry : pd.Series
        年化 carry，index 为 trade_date

    Returns
    -------
    pd.Series
        ∈ {-1, 0, +1, NaN}
    """
    return np.sign(carry)


def carry_signal_smooth(carry: pd.Series, window: int = 21) -> pd.Series:
    """方案 B：rolling_mean 平滑后再取 sign。

    σ̂_carry_t 的计算：
      1) carry.dropna() → rolling(window).mean()
      2) reindex 回原 index，换月日的 NaN 日继承前一个有效均值（ffill）
      3) 最终对平滑序列取 sign

    Parameters
    ----------
    carry : pd.Series
        年化 carry，换月日可能为 NaN
    window : int, default 21
        平滑窗口（日）。21 ≈ 1 个月交易日。

    Returns
    -------
    pd.Series
        ∈ {-1, 0, +1, NaN}；前 window-1 日为 NaN。
    """
    valid = carry.dropna()
    smoothed_valid = valid.rolling(window, min_periods=window).mean()
    smoothed = smoothed_valid.reindex(carry.index).ffill()
    return np.sign(smoothed)
