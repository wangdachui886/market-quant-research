"""Phase 2.1 · 数据管道通用模块

从 01_pull_M_via_tushare.py 抽出来的可复用函数，供 06 推广使用。
算法内容与 01 完全一致（已在 M 品种上验证过，见 04 的 +107% gap）。
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd

START_DATE = "20170101"
END_DATE = "20260101"
SLEEP_SEC = 0.15


def fetch_mapping(pro, ts_code: str, cache_dir: Path) -> pd.DataFrame:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir / f"{ts_code.replace('.', '_')}_mapping.csv"
    if cache.exists():
        return pd.read_csv(cache, dtype={"trade_date": str})
    df = pro.fut_mapping(ts_code=ts_code, start_date=START_DATE, end_date=END_DATE)
    df = df.sort_values("trade_date").reset_index(drop=True)
    df.to_csv(cache, index=False)
    return df


def fetch_daily(pro, ts_code: str, cache_dir: Path, verbose: bool = True) -> pd.DataFrame | None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir / f"{ts_code}.csv"
    if cache.exists():
        return pd.read_csv(cache, dtype={"trade_date": str})
    try:
        df = pro.fut_daily(ts_code=ts_code, start_date=START_DATE, end_date=END_DATE)
    except Exception as e:
        if verbose:
            print(f"    [FAIL] {ts_code}: {type(e).__name__}: {e}")
        return None
    if df is None or df.empty:
        return None
    df = df.sort_values("trade_date").reset_index(drop=True)
    df.to_csv(cache, index=False)
    time.sleep(SLEEP_SEC)
    return df


def fetch_all_contracts(pro, codes: list[str], cache_dir: Path) -> tuple[dict, dict]:
    data = {}
    stats = {"cached": 0, "api": 0, "fail": 0, "total": len(codes)}
    for code in codes:
        hit = (cache_dir / f"{code}.csv").exists()
        df = fetch_daily(pro, code, cache_dir)
        if df is None:
            stats["fail"] += 1
            continue
        data[code] = df
        stats["cached" if hit else "api"] += 1
    return data, stats


def build_clean_returns(
    mapping: pd.DataFrame, contracts: dict[str, pd.DataFrame]
) -> pd.DataFrame:
    close_panel = pd.DataFrame({
        code: df.set_index("trade_date")["close"]
        for code, df in contracts.items()
    })
    close_panel.index = pd.to_datetime(close_panel.index)
    close_panel = close_panel.sort_index()

    dominant = (
        mapping.set_index(pd.to_datetime(mapping["trade_date"]))["mapping_ts_code"]
        .sort_index()
    )
    dominant = dominant.reindex(close_panel.index).ffill()

    clean = pd.Series(np.nan, index=close_panel.index, name="clean_return")
    for i in range(1, len(close_panel)):
        dom = dominant.iloc[i]
        if not isinstance(dom, str) or dom not in close_panel.columns:
            continue
        c_today = close_panel[dom].iloc[i]
        c_prev = close_panel[dom].iloc[i - 1]
        if pd.notna(c_today) and pd.notna(c_prev) and c_prev > 0:
            clean.iloc[i] = c_today / c_prev - 1

    is_switch = (dominant != dominant.shift(1)) & dominant.notna() & dominant.shift(1).notna()
    clean[is_switch] = np.nan

    out = pd.DataFrame({
        "dominant": dominant,
        "clean_return": clean,
        "is_switch": is_switch.astype(int),
    })
    out["clean_nav"] = (1 + out["clean_return"].fillna(0)).cumprod()
    out.index.name = "date"
    return out
