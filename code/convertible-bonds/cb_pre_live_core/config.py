"""Configuration for the sealed convertible-bond research appendix.

The public repo intentionally does not include raw panel data. The default
paths point to local, untracked folders under this code appendix; override them
when running the scripts against your own licensed or regenerated data.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


CODE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = CODE_ROOT / "data"
DEFAULT_OUTPUT_DIR = CODE_ROOT / "output"


@dataclass(frozen=True)
class FinalConfig:
    data_dir: Path = DEFAULT_DATA_DIR
    panel_csv: Path = DEFAULT_DATA_DIR / "bond_daily_panel_full_v2_2017.csv"
    issue_size_csv: Path = DEFAULT_DATA_DIR / "cb_basic_static.csv"
    fallback_issue_size_csv: Path = DEFAULT_DATA_DIR / "cb_basic_issue_size.csv"
    redeem_notice_csv: Path = DEFAULT_DATA_DIR / "cb_redeem_notice_pit.csv"
    output_dir: Path = DEFAULT_OUTPUT_DIR
    top_k: int = 12
    keep_n: int = 37
    min_issue_size: float = 300_000_000.0
    cb_close_min: float = 80.0
    cb_close_max: float | None = None
    min_days_to_maturity: int = 180
    cost_one_way_bp: float = 15.0
    rf_annual: float = 0.025
    entry_lag: int = 2
