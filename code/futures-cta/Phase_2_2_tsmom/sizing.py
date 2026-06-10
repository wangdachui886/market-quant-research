"""Phase 2.2 · Layer 2 · 仓位缩放层

职责：接收 "方向信号"（{-1, 0, +1}），输出 "目标仓位标量"（可正可负）。
严格只负责 "押多重"，不碰 "押哪边"。

契约：
  direction : pd.Series ∈ {-1, 0, +1}
  scale     : pd.Series ≥ 0
  target_position = direction × scale

每个 sizing 函数都返回 scale 一条时间序列，外部负责相乘。
新的 sizing 规则加进来就是一个新函数，不要在现有函数里加分支。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def vol_target_scale(
    clean_returns: pd.Series,
    target_vol: float = 0.20,
    window: int = 60,
    vol_floor: float = 0.05,
    max_leverage: float = 3.0,
) -> pd.Series:
    """用滚动 σ 估计波动，缩放到 target_vol。

    scale_t = clip( target_vol / max(σ̂_t, vol_floor), 0, max_leverage )

    σ̂_t = rolling_std(clean_returns_with_NaN_dropped, window) × √252
    （rolling 到 t 的窗口已经包含 t 当日收益，外层 backtest 会再 shift(1)，无未来函数）

    为什么先 dropna：
      clean_returns 在换月日为 NaN（主动设计，防假跳空）。如果直接在原序列上
      rolling(window, min_periods=window)，则每个包含换月 NaN 的窗口都会返回
      NaN，进而 scale=NaN、仓位归零。对月换月品种（CU/ZN/AL/SC）更会导致
      scale 恒 NaN，整个品种被"静默躺平"。

      正确做法：在压缩掉 NaN 的有效序列上算 rolling std（60 个连续有效观测），
      再 reindex + ffill 回原 index，换月日继承前一天的 σ̂ 估计。

    Parameters
    ----------
    clean_returns : pd.Series
        日频 clean returns，换月日 NaN
    target_vol : float
        目标年化波动率（默认 20%）
    window : int
        估 σ 的滚动窗口（默认 60 日 ≈ 3 个月）
    vol_floor : float
        σ 下限（年化），防止低波期杠杆爆炸
    max_leverage : float
        绝对杠杆上限，硬兜底

    Returns
    -------
    pd.Series
        每日 scale 因子 ≥ 0；前 window 日为 NaN。
    """
    ret_valid = clean_returns.dropna()
    sigma_on_valid = ret_valid.rolling(window, min_periods=window).std() * np.sqrt(252)
    sigma_annual = sigma_on_valid.reindex(clean_returns.index).ffill()

    sigma_floored = sigma_annual.clip(lower=vol_floor)
    scale = target_vol / sigma_floored
    scale = scale.clip(upper=max_leverage)
    return scale
