from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "code" / "etf-stabilizer" / "etf_stabilizer_v1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("etf_stabilizer_v1", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def make_prices(a_share: np.ndarray, sp500: np.ndarray) -> pd.DataFrame:
    dates = pd.date_range("2020-01-01", periods=len(a_share), freq="B")
    return pd.DataFrame(
        {
            "510300.SH": a_share,
            "513500.SH": sp500,
            "511010.SH": np.linspace(100.0, 103.0, len(a_share)),
            "518880.SH": np.linspace(100.0, 106.0, len(a_share)),
        },
        index=dates,
    )


class ETFStabilizerSmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()

    def test_normal_equity_weights_are_20_20_40_20(self) -> None:
        prices = make_prices(
            np.linspace(100.0, 140.0, 300),
            np.linspace(100.0, 150.0, 300),
        )
        weights = self.module.target_weights(prices, prices.index[-1])
        self.assertAlmostEqual(weights["510300.SH"], 0.20)
        self.assertAlmostEqual(weights["513500.SH"], 0.20)
        self.assertAlmostEqual(weights["511010.SH"], 0.40)
        self.assertAlmostEqual(weights["518880.SH"], 0.20)

    def test_failed_equity_moves_to_bond_and_gold_fallback(self) -> None:
        prices = make_prices(
            np.linspace(120.0, 90.0, 300),
            np.linspace(100.0, 150.0, 300),
        )
        weights = self.module.target_weights(prices, prices.index[-1])
        self.assertNotIn("510300.SH", weights)
        self.assertAlmostEqual(weights["513500.SH"], 0.20)
        self.assertAlmostEqual(weights["511010.SH"], 0.56)
        self.assertAlmostEqual(weights["518880.SH"], 0.24)

    def test_cross_border_premium_blocks_sp500_sleeve(self) -> None:
        prices = make_prices(
            np.linspace(100.0, 140.0, 300),
            np.linspace(100.0, 150.0, 300),
        )
        nav = pd.DataFrame({"513500.SH": prices["513500.SH"] / 1.10}, index=prices.index)
        weights = self.module.target_weights(prices, prices.index[-1], nav_prices=nav)
        self.assertAlmostEqual(weights["510300.SH"], 0.20)
        self.assertNotIn("513500.SH", weights)
        self.assertAlmostEqual(weights["511010.SH"], 0.56)
        self.assertAlmostEqual(weights["518880.SH"], 0.24)

    def test_portfolio_overlay_defaults_to_70_30(self) -> None:
        weights = self.module.portfolio_overlay_weights()
        self.assertAlmostEqual(weights["convertible_bond_top12_keep37"], 0.70)
        self.assertAlmostEqual(weights["etf_stabilizer_v1"], 0.30)


if __name__ == "__main__":
    unittest.main()
