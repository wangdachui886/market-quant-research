from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "code" / "convertible-bonds" / "cb_pre_live_core" / "portfolio.py"


def load_module():
    spec = importlib.util.spec_from_file_location("cb_portfolio", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PortfolioConstructionSmokeTest(unittest.TestCase):
    def test_pick_holdings_keeps_prior_name_inside_retention_buffer(self) -> None:
        module = load_module()
        snap = pd.DataFrame(
            {
                "cb_code": ["A", "B", "C", "D", "E"],
                "score": [1.0, 2.0, 3.0, 4.0, 5.0],
            }
        )
        selected = module.pick_holdings(snap, prev={"D"}, top_k=3, keep_n=4)
        self.assertEqual(selected, ["A", "B", "D"])

    def test_daily_returns_uses_entry_return_and_cost(self) -> None:
        module = load_module()
        scored = pd.DataFrame(
            {
                "trade_date": pd.to_datetime(["2020-01-02", "2020-01-02"]),
                "cb_code": ["A", "B"],
                "ret": [0.010, 0.020],
                "ret_entry": [0.005, 0.015],
            }
        )
        holdings = pd.DataFrame(
            {
                "trade_date": pd.to_datetime(["2020-01-02", "2020-01-02"]),
                "cb_code": ["A", "B"],
                "is_entry": [True, False],
                "turnover": [0.5, 0.5],
            }
        )
        out = module.daily_returns(scored, holdings, cost_one_way_bp=10)
        self.assertAlmostEqual(float(out.loc[0, "gross"]), 0.0125)
        self.assertAlmostEqual(float(out.loc[0, "cost"]), -0.0010)
        self.assertAlmostEqual(float(out.loc[0, "net"]), 0.0115)


if __name__ == "__main__":
    unittest.main()
