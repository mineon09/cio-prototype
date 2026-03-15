"""
Unit tests for src/analyzers.py - 4 軸スコアリングエンジン
"""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.analyzers import (
    score_fundamental, score_valuation, score_technical, score_qualitative,
    resolve_sector_profile, TechnicalAnalyzer, _safe, _clamp,
)
import pandas as pd
import numpy as np


class TestHelperFunctions(unittest.TestCase):
    def test_safe_none(self):
        result = _safe(None, default=0)
        self.assertEqual(result, 0)

    def test_safe_nan(self):
        result = _safe(float('nan'), default=0)
        self.assertEqual(result, 0)

    def test_safe_valid(self):
        result = _safe(10.5, default=0)
        self.assertEqual(result, 10.5)

    def test_clamp_in_range(self):
        self.assertEqual(_clamp(5.0), 5.0)

    def test_clamp_below(self):
        self.assertEqual(_clamp(-5.0), 0.0)

    def test_clamp_above(self):
        self.assertEqual(_clamp(15.0), 10.0)


class TestSectorProfile(unittest.TestCase):
    def test_technology(self):
        name, _, _, _, _ = resolve_sector_profile("Technology")
        self.assertEqual(name, "high_growth")

    def test_healthcare(self):
        name, _, _, _, _ = resolve_sector_profile("Healthcare")
        self.assertEqual(name, "healthcare")

    def test_financial(self):
        name, _, _, _, _ = resolve_sector_profile("Financial Services")
        self.assertEqual(name, "financial")

    def test_unknown(self):
        name, _, _, _, _ = resolve_sector_profile("Unknown")
        self.assertEqual(name, "default")


class TestFundamentalScoring(unittest.TestCase):
    def test_high_roe(self):
        metrics = {'roe': 20.0, 'op_margin': 15.0, 'equity_ratio': 50.0}
        result = score_fundamental(metrics, sector="Technology")
        self.assertGreater(result['score'], 7.0)

    def test_low_roe(self):
        metrics = {'roe': 2.0, 'op_margin': 3.0, 'equity_ratio': 20.0}
        result = score_fundamental(metrics, sector="Technology")
        self.assertLess(result['score'], 5.0)

    def test_negative_roe(self):
        metrics = {'roe': -5.0, 'op_margin': -2.0, 'equity_ratio': 30.0}
        result = score_fundamental(metrics)
        self.assertLess(result['score'], 5.0)

    def test_empty_metrics(self):
        result = score_fundamental({})
        self.assertEqual(result['score'], 0.0)


class TestValuationScoring(unittest.TestCase):
    def test_cheap_stock(self):
        metrics = {'per': 8.0, 'pbr': 0.8, 'dividend_yield': 4.0}
        result = score_valuation(metrics)
        self.assertGreater(result['score'], 7.0)

    def test_expensive_stock(self):
        metrics = {'per': 50.0, 'pbr': 5.0, 'dividend_yield': 0.5}
        result = score_valuation(metrics)
        self.assertLess(result['score'], 5.0)

    def test_with_analyst_target(self):
        metrics = {'per': 15.0, 'pbr': 1.5}
        technical = {'current_price': 1000, 'analyst_target': 1300}
        result = score_valuation(metrics, technical=technical)
        self.assertGreater(result['score'], 6.0)

    def test_with_dcf_data(self):
        metrics = {'per': 15.0, 'pbr': 1.5}
        dcf_data = {'available': True, 'upside': 25.0, 'fair_value': 1250, 'current_price': 1000}
        result = score_valuation(metrics, dcf_data=dcf_data)
        self.assertGreater(result['score'], 6.0)


class TestTechnicalScoring(unittest.TestCase):
    def test_oversold(self):
        technical = {'rsi': 25, 'ma25_deviation': -12.0, 'ma75_deviation': -5.0,
                     'bb_position': 15, 'volume_ratio': 1.5, 'current_price': 1000}
        result = score_technical(technical)
        self.assertGreater(result['score'], 7.0)

    def test_overbought(self):
        technical = {'rsi': 75, 'ma25_deviation': 15.0, 'ma75_deviation': 20.0,
                     'bb_position': 90, 'volume_ratio': 0.8, 'current_price': 1000}
        result = score_technical(technical)
        self.assertLess(result['score'], 4.0)

    def test_neutral(self):
        technical = {'rsi': 50, 'ma25_deviation': 0.0, 'ma75_deviation': 2.0,
                     'bb_position': 50, 'volume_ratio': 1.0, 'current_price': 1000}
        result = score_technical(technical)
        self.assertAlmostEqual(result['score'], 5.0, delta=1.5)

    def test_no_data(self):
        result = score_technical({})
        self.assertEqual(result['score'], 5.0)


class TestQualitativeScoring(unittest.TestCase):
    def test_strong_moat(self):
        yuho_data = {
            'available': True,
            'moat': {'type': 'ブランド', 'durability': '高', 'source': 'test', 'description': 'test'},
            'risk_top3': [],
            'management_tone': {'overall': '強気', 'key_phrases': ['成長'], 'detail': 'test'},
        }
        result = score_qualitative(yuho_data)
        self.assertGreater(result['score'], 7.0)

    def test_high_risks(self):
        yuho_data = {
            'available': True,
            'moat': {'type': 'なし', 'durability': '低', 'source': '', 'description': ''},
            'risk_top3': [
                {'risk': '1', 'severity': '高', 'detail': 'd'},
                {'risk': '2', 'severity': '高', 'detail': 'd'},
                {'risk': '3', 'severity': '高', 'detail': 'd'},
            ],
        }
        result = score_qualitative(yuho_data)
        self.assertLess(result['score'], 4.0)

    def test_no_data(self):
        result = score_qualitative(None)
        self.assertEqual(result['score'], 5.0)
        result = score_qualitative({'available': False})
        self.assertEqual(result['score'], 5.0)


class TestTechnicalAnalyzer(unittest.TestCase):
    def setUp(self):
        dates = pd.date_range('2024-01-01', periods=100, freq='D')
        np.random.seed(42)
        returns = np.random.randn(100) * 0.02
        prices = 1000 * np.cumprod(1 + returns)
        self.df = pd.DataFrame({
            'Open': prices * (1 + np.random.randn(100) * 0.01),
            'High': prices * (1 + np.abs(np.random.randn(100) * 0.02)),
            'Low': prices * (1 - np.abs(np.random.randn(100) * 0.02)),
            'Close': prices,
            'Volume': np.random.randint(1000000, 5000000, 100),
        }, index=dates)

    def test_rsi_condition(self):
        ta = TechnicalAnalyzer(self.df)
        result = ta.check_rsi_condition(threshold=30, period=9, condition="below")
        self.assertIn(result, [True, False])

    def test_bollinger_touch(self):
        ta = TechnicalAnalyzer(self.df)
        is_touching, pct = ta.check_bollinger_touch(sigma=2.0, period=20)
        self.assertIn(is_touching, [True, False])
        self.assertIsInstance(pct, float)
        self.assertGreaterEqual(pct, 0.0)
        self.assertLessEqual(pct, 1.0)

    def test_volume_spike(self):
        ta = TechnicalAnalyzer(self.df)
        result = ta.check_volume_spike(multiplier=1.3, period=20)
        self.assertIn(result, [True, False])

    def test_high_breakout(self):
        ta = TechnicalAnalyzer(self.df)
        result = ta.check_high_breakout(period=20)
        self.assertIn(result, [True, False])

    def test_ma_alignment(self):
        ta = TechnicalAnalyzer(self.df)
        result = ta.check_ma_alignment()
        self.assertIn(result, [True, False])


if __name__ == '__main__':
    unittest.main()
