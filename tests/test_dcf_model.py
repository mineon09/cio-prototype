"""
Unit tests for src/dcf_model.py - DCF 理論株価算出
"""

import unittest
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.dcf_model import (
    _get_fcf_history, _estimate_wacc, _dcf_valuation,
    _get_growth_scenarios, estimate_fair_value,
)


class TestFCFHistory(unittest.TestCase):
    def test_invalid_ticker(self):
        result = _get_fcf_history('INVALID_TICKER_XYZ')
        self.assertIsInstance(result, list)
        self.assertLess(len(result), 5)

    def test_with_date(self):
        past_date = datetime(2023, 1, 1)
        result = _get_fcf_history('AAPL', as_of_date=past_date)
        self.assertIsInstance(result, list)


class TestWACCEstimation(unittest.TestCase):
    def test_invalid_ticker(self):
        result = _estimate_wacc('INVALID_TICKER_XYZ')
        self.assertGreaterEqual(result, 3.0)
        self.assertLessEqual(result, 15.0)

    def test_valid_range(self):
        result = _estimate_wacc('AAPL')
        self.assertGreaterEqual(result, 3.0)
        self.assertLessEqual(result, 15.0)

    def test_with_macro_data(self):
        macro_data = {'us10y': 4.5}
        result = _estimate_wacc('AAPL', macro_data=macro_data)
        self.assertGreaterEqual(result, 3.0)
        self.assertLessEqual(result, 15.0)


class TestDCFValuation(unittest.TestCase):
    def test_positive_fcf(self):
        result = _dcf_valuation(fcf_latest=1e9, growth_rate=10.0, wacc=9.0,
                                 terminal_growth=2.5, years=5, shares_outstanding=1e8)
        self.assertGreater(result, 0)
        self.assertIsInstance(result, float)

    def test_negative_fcf(self):
        result = _dcf_valuation(fcf_latest=-1e9, growth_rate=10.0, wacc=9.0, shares_outstanding=1e8)
        self.assertEqual(result, 0.0)

    def test_zero_shares(self):
        result = _dcf_valuation(fcf_latest=1e9, growth_rate=10.0, wacc=9.0, shares_outstanding=0)
        self.assertEqual(result, 0.0)

    def test_wacc_less_than_terminal(self):
        result = _dcf_valuation(fcf_latest=1e9, growth_rate=10.0, wacc=2.0,
                                 terminal_growth=2.5, shares_outstanding=1e8)
        self.assertEqual(result, 0.0)

    def test_sensitivity_growth(self):
        base = _dcf_valuation(1e9, 5.0, 9.0, shares_outstanding=1e8)
        high = _dcf_valuation(1e9, 15.0, 9.0, shares_outstanding=1e8)
        self.assertGreater(high, base)

    def test_sensitivity_wacc(self):
        low = _dcf_valuation(1e9, 10.0, 7.0, shares_outstanding=1e8)
        high = _dcf_valuation(1e9, 10.0, 11.0, shares_outstanding=1e8)
        self.assertGreater(low, high)


class TestGrowthScenarios(unittest.TestCase):
    def test_no_history(self):
        result = _get_growth_scenarios('AAPL', [])
        self.assertEqual(result['bull'], 15)
        self.assertEqual(result['base'], 8)
        self.assertEqual(result['bear'], 2)

    def test_short_history(self):
        result = _get_growth_scenarios('AAPL', [100])
        self.assertEqual(result['bull'], 15)
        self.assertEqual(result['base'], 8)
        self.assertEqual(result['bear'], 2)

    def test_positive_growth(self):
        fcf_history = [160, 140, 120, 100]
        result = _get_growth_scenarios('TEST', fcf_history)
        self.assertGreater(result['bull'], result['base'])
        self.assertGreater(result['base'], result['bear'])
        self.assertLessEqual(result['bull'], 25)

    def test_negative_growth(self):
        fcf_history = [40, 60, 80, 100]
        result = _get_growth_scenarios('TEST', fcf_history)
        self.assertGreaterEqual(result['bear'], -5)

    def test_volatile_fcf(self):
        fcf_history = [1000, 100, 500, 50]
        result = _get_growth_scenarios('TEST', fcf_history)
        self.assertLessEqual(result['bull'], 25)


class TestEstimateFairValue(unittest.TestCase):
    def test_invalid_ticker(self):
        result = estimate_fair_value('INVALID_TICKER_XYZ')
        self.assertFalse(result['available'])
        self.assertIn('reason', result)

    def test_structure(self):
        result = estimate_fair_value('AAPL')
        if result.get('available'):
            self.assertIn('fair_value', result)
            self.assertIn('current_price', result)
            self.assertIn('upside', result)
            self.assertIn('margin_of_safety', result)
            self.assertIn('scenarios', result)
            self.assertIn('wacc', result)
            self.assertIn('reliability', result)
            self.assertIn(result['reliability'], ['high', 'low'])
        else:
            self.assertIn('reason', result)

    def test_with_date(self):
        past_date = datetime(2023, 1, 1)
        result = estimate_fair_value('AAPL', as_of_date=past_date)
        if result.get('available'):
            self.assertGreater(result['fair_value'], 0)


if __name__ == '__main__':
    unittest.main()
