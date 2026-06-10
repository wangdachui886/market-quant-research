"""Phase 2.3 · Carry 构造核心模块

从 Tushare 的 mapping + 单合约 settle 价构造"近月 vs 次主力月"年化 carry。

被以下脚本引用：
  - probes/probe_carry_M.py     （单品种验证）
  - build_carry_universe.py     （19 品种推广）
  - signals.py（未来）          （从 carry 计算 carry_signal）

核心思想：
  carry = (near_settle / far_settle - 1) × (12 / month_gap)

其中 far 是 near 合约之后的"下一个主力月合约"，month_gap 是两者交割月的差。
在主力月集 {1,5,9} 下通常 gap=4；{6,12} 下 gap=6；全月 {1..12} 下 gap=1。
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd


# --------------------------------------------------------------------------
# 交易所代码映射：config.UNIVERSE 用的名字 ↔ Tushare 数据文件里的后缀
# --------------------------------------------------------------------------
# mapping 文件和 ts_code 后缀的实际取值
EXCHANGE_CODE_MAP = {
    "DCE":  "DCE",
    "CZCE": "ZCE",   # 注意：CZCE 在 Tushare 里是 "ZCE"
    "SHFE": "SHF",   # 注意：SHFE 在 Tushare 里是 "SHF"
    "INE":  "INE",
}

TS_CODE_PAT = re.compile(r"^([A-Z]+)(\d{4})\.([A-Z]+)$")


# --------------------------------------------------------------------------
# ts_code 解析 / 下一主力月推断
# --------------------------------------------------------------------------
def parse_ts_code(ts_code: str) -> tuple[str, int, int, str]:
    """'M2405.DCE' → ('M', 2024, 5, 'DCE')"""
    m = TS_CODE_PAT.match(ts_code)
    if m is None:
        raise ValueError(f"Bad ts_code: {ts_code}")
    prod, yymm, exch = m.group(1), m.group(2), m.group(3)
    year = 2000 + int(yymm[:2])
    month = int(yymm[2:])
    return prod, year, month, exch


def next_main_code(near_code: str, main_months: list[int]) -> str:
    """在给定主力月集里找 near 合约之后的"下一个主力月合约"。

    规则：
      - 若 main_months 里有 m > near.month，取最小的那个，同年
      - 否则 → 跨年到 main_months[0]

    例：
      M2405.DCE, [1,5,9]   → M2409.DCE
      M2409.DCE, [1,5,9]   → M2501.DCE
      AU2406.SHF, [6,12]   → AU2412.SHF
      CU2503.SHF, range(1,13) → CU2504.SHF
      C2407.DCE, [1,5,9]   → C2409.DCE   （不规则 main 也能处理）
    """
    prod, year, month, exch = parse_ts_code(near_code)
    mains_after = [m for m in main_months if m > month]
    if mains_after:
        next_year, next_month = year, mains_after[0]
    else:
        next_year, next_month = year + 1, main_months[0]
    return f"{prod}{next_year % 100:02d}{next_month:02d}.{exch}"


def months_between(near_code: str, far_code: str) -> int:
    """两个合约交割月的月数差（far - near）。"""
    _, y1, m1, _ = parse_ts_code(near_code)
    _, y2, m2, _ = parse_ts_code(far_code)
    return (y2 - y1) * 12 + (m2 - m1)


# --------------------------------------------------------------------------
# 数据加载 + carry 构造
# --------------------------------------------------------------------------
def load_contract_panel(contracts_dir: Path) -> dict[str, pd.Series]:
    """读取某品种目录下所有单合约的 settle 列。

    返回：{ts_code: Series(index=trade_date, values=settle)}
    """
    panel = {}
    for fp in sorted(contracts_dir.glob("*.csv")):
        df = pd.read_csv(fp, dtype={"trade_date": str})
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        s = df.set_index("trade_date")["settle"].sort_index()
        ts_code = fp.stem
        s.name = ts_code
        panel[ts_code] = s
    return panel


def build_carry(
    mapping: pd.DataFrame,
    contracts: dict[str, pd.Series],
    main_months: list[int],
) -> pd.DataFrame:
    """按日期循环，构造 near/far settle + basis + 年化 carry。

    输入：
      mapping     — 列 [trade_date, mapping_ts_code]（trade_date 是 str 'YYYYMMDD' 或已解析）
      contracts   — load_contract_panel 的输出
      main_months — 主力月列表，比如 [1,5,9]

    输出 DataFrame columns：
      date (index), near_code, far_code, month_gap,
      near_settle, far_settle, basis, carry
    """
    mapping = mapping.copy()
    mapping["trade_date"] = pd.to_datetime(mapping["trade_date"], format="%Y%m%d")
    mapping = mapping.sort_values("trade_date").set_index("trade_date")

    near_codes = mapping["mapping_ts_code"]

    rows = []
    for date, near_code in near_codes.items():
        if not isinstance(near_code, str):
            continue

        far_code = next_main_code(near_code, main_months)
        gap = months_between(near_code, far_code)

        near_settle = contracts.get(near_code, pd.Series(dtype=float)).get(date, np.nan)
        far_settle = contracts.get(far_code, pd.Series(dtype=float)).get(date, np.nan)

        if pd.isna(near_settle) or pd.isna(far_settle) or far_settle <= 0 or gap <= 0:
            carry = np.nan
            basis = np.nan
        else:
            basis = near_settle - far_settle
            carry = (near_settle / far_settle - 1.0) * (12.0 / gap)

        rows.append({
            "date": date,
            "near_code": near_code,
            "far_code": far_code,
            "month_gap": gap,
            "near_settle": near_settle,
            "far_settle": far_settle,
            "basis": basis,
            "carry": carry,
        })

    return pd.DataFrame(rows).set_index("date")


# --------------------------------------------------------------------------
# 便捷入口：按 symbol 一键构造
# --------------------------------------------------------------------------
def build_carry_for_symbol(
    symbol: str,
    exchange: str,
    main_months: list[int],
    project_root: Path,
) -> pd.DataFrame:
    """一键对单个 symbol（如 'M0'）从缓存里读 mapping + contracts，返回 carry 表。

    约定路径：
      mapping:   data_cache/tushare/mapping/{PRODUCT}_{EXCH_CODE}_mapping.csv
      contracts: data_cache/tushare/contracts/{SYMBOL}/*.csv

    其中 PRODUCT = symbol[:-1]（去掉末尾 '0'），EXCH_CODE 由 EXCHANGE_CODE_MAP 翻译。
    """
    product = symbol[:-1]  # 'M0' → 'M'
    exch_code = EXCHANGE_CODE_MAP[exchange]

    mapping_fp = project_root / "data_cache" / "tushare" / "mapping" / f"{product}_{exch_code}_mapping.csv"
    contracts_dir = project_root / "data_cache" / "tushare" / "contracts" / symbol

    if not mapping_fp.exists():
        raise FileNotFoundError(f"mapping 文件不存在：{mapping_fp}")
    if not contracts_dir.exists():
        raise FileNotFoundError(f"contracts 目录不存在：{contracts_dir}")

    mapping = pd.read_csv(mapping_fp, dtype={"trade_date": str})
    contracts = load_contract_panel(contracts_dir)

    return build_carry(mapping, contracts, main_months)


# --------------------------------------------------------------------------
# 汇总统计（给 probe + universe 共用）
# --------------------------------------------------------------------------
def carry_summary(df: pd.DataFrame) -> dict:
    """返回一行 dict，含 carry 分布的描述性统计。"""
    n_total = len(df)
    valid = df.dropna(subset=["carry"])
    n_valid = len(valid)
    if n_valid == 0:
        return {
            "n_total": n_total, "n_valid": 0, "valid_rate": 0.0,
            "mean": np.nan, "median": np.nan,
            "q05": np.nan, "q95": np.nan,
            "min": np.nan, "max": np.nan,
            "pos_rate": np.nan, "neg_rate": np.nan,
            "month_gaps": "",
        }

    return {
        "n_total":    n_total,
        "n_valid":    n_valid,
        "valid_rate": n_valid / n_total,
        "mean":       float(valid["carry"].mean()),
        "median":     float(valid["carry"].median()),
        "q05":        float(valid["carry"].quantile(0.05)),
        "q95":        float(valid["carry"].quantile(0.95)),
        "min":        float(valid["carry"].min()),
        "max":        float(valid["carry"].max()),
        "pos_rate":   float((valid["carry"] > 0).sum() / n_valid),
        "neg_rate":   float((valid["carry"] < 0).sum() / n_valid),
        "month_gaps": str(valid["month_gap"].value_counts().sort_index().to_dict()),
    }
