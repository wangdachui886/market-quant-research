from __future__ import annotations

import importlib.util
import math
import sys
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "code" / "convertible-bonds" / "cb_pre_live_core" / "metrics.py"


def load_module():
    spec = importlib.util.spec_from_file_location("cb_metrics", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class MetricsSmokeTest(unittest.TestCase):
    def test_calc_metrics_returns_expected_keys_and_drawdown(self) -> None:
        module = load_module()
        dates = pd.date_range("2020-01-01", periods=120, freq="B")
        returns = pd.Series([0.004, -0.002, 0.001, -0.006] * 30, index=dates)
        metrics = module.calc_metrics(returns, rf_annual=0.0)
        self.assertEqual(set(metrics), {"CAGR", "Vol", "Sharpe", "MDD", "Calmar", "WinW"})
        self.assertLessEqual(metrics["MDD"], 0.0)
        self.assertTrue(math.isfinite(metrics["CAGR"]))
        self.assertTrue(math.isfinite(metrics["Vol"]))

    def test_short_series_returns_nan_metrics(self) -> None:
        module = load_module()
        metrics = module.calc_metrics(pd.Series([0.01, -0.01]))
        self.assertTrue(all(math.isnan(value) for value in metrics.values()))


if __name__ == "__main__":
    unittest.main()
