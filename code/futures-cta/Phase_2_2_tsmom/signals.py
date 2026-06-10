"""Phase 2.2 · 信号函数库

每个信号函数的契约：
  输入：pd.Series（index=date，values=日频数据）
  输出：pd.Series（index 同输入，values ∈ {-1, 0, +1} 或 NaN）

新信号加进来就是一个新函数，不要在现有函数里加分支。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def tsmom_signal(clean_returns: pd.Series, lookback_days: int = 252) -> pd.Series:
    """时间序列动量信号：过去 N 日累积收益的符号。

    实现用累积 NAV 反推 past N 日累积收益，可以天然跳过换月日的 NaN：
    换月日 NAN 经 fillna(0) 处理后不贡献累积，相当于这一天 return=0。

    Parameters
    ----------
    clean_returns : pd.Series
        日频 clean returns（index=date，换月日为 NaN）
    lookback_days : int, default 252
        回看窗口。252 ≈ 12 个月（Moskowitz 2012 的标准选择）

    Returns
    -------
    pd.Series
        values ∈ {-1, 0, +1}，前 lookback_days 日为 NaN（无足够历史）
    """
    nav = (1 + clean_returns.fillna(0)).cumprod()
    past_cum_return = nav / nav.shift(lookback_days) - 1
    return np.sign(past_cum_return)
