"""
Unit tests for src/strategies.py - 戦略ロジック
"""

import unittest
import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.strategies import LongStrategy, BounceStrategy, BreakoutStrategy
from src.analyzers import TechnicalAnalyzer
import pandas as pd
import numpy as np


def create_test_data(days=100, trend='neutral'):
    np.random.seed(42)
    dates = pd.date_range(end=datetime.now(), periods=days, freq='D')
    if trend == 'uptrend':
        returns = np.random.randn(days) * 0.02 + 0.005
    elif trend == 'downtrend':
        returns = np.random.randn(days) * 0.02 - 0.005
    else:
        returns = np.random.randn(days) * 0.02
    prices = 1000 * np.cumprod(1 + returns)
    return pd.DataFrame({
        'Open': prices * (1 + np.random.randn(days) * 0.005),
        'High': prices * (1 + np.abs(np.random.randn(days) * 0.015)),
        'Low': prices * (1 - np.abs(np.random.randn(days) * 0.015)),
        'Close': prices,
        'Volume': np.random.randint(1000000, 5000000, days),
    }, index=dates)


class TestLongStrategy(unittest.TestCase):
    def setUp(self):
        self.config = {
            'signals': {
                'BUY': {'min_score': 6.5, 'min_fundamental': 5.0,
                        'premium_quality_override': {'enabled': True, 'min_fundamental': 8.0, 'min_score': 5.5}},
                'SELL': {'max_score': 3.5},
            },
            'exit_strategy': {'long': {'watch_zone_exit': {'enabled': True, 'score_threshold': 4.5, 'consecutive_months': 3}}},
        }
        self.strategy = LongStrategy('long', self.config)

    def test_high_score_entry(self):
        row = pd.Series({'score': 8.0, 'fundamental': 7.5, 'regime': 'NEUTRAL'})
        result = self.strategy.analyze_entry(row, pd.DataFrame(), None)
        self.assertTrue(result['is_entry'])

    def test_low_score_no_entry(self):
        row = pd.Series({'score': 4.0, 'fundamental': 3.5, 'regime': 'NEUTRAL'})
        result = self.strategy.analyze_entry(row, pd.DataFrame(), None)
        self.assertFalse(result['is_entry'])

    def test_premium_quality_override(self):
        row = pd.Series({'score': 6.0, 'fundamental': 9.0, 'regime': 'NEUTRAL'})
        result = self.strategy.analyze_entry(row, pd.DataFrame(), None)
        self.assertTrue(result['is_entry'])

    def test_fundamental_min_check(self):
        row = pd.Series({'score': 7.5, 'fundamental': 4.0, 'regime': 'NEUTRAL'})
        result = self.strategy.analyze_entry(row, pd.DataFrame(), None)
        self.assertFalse(result['is_entry'])

    def test_should_sell_watch_zone(self):
        row = pd.Series({'score': 4.0, 'price': 1000})
        ctx = {'low_score_months': 3}
        should_sell, reason, price = self.strategy.should_sell(row, pd.DataFrame(), None, ctx)
        self.assertTrue(should_sell)

    def test_should_sell_score_deterioration(self):
        row = pd.Series({'score': 3.0, 'price': 1000})
        ctx = {}
        should_sell, reason, price = self.strategy.should_sell(row, pd.DataFrame(), None, ctx)
        self.assertTrue(should_sell)


class TestBounceStrategy(unittest.TestCase):
    def setUp(self):
        self.config = {
            'signals': {'BUY': {'min_score': 6.5}},
            'strategies': {
                'bounce': {
                    'enabled': True,
                    'enabled_regimes': ['NEUTRAL', 'RISK_ON'],
                    'entry': {'fundamental_min': 5.0, 'rsi_threshold': 35, 'bb_std': 2.0, 'volume_multiplier': 1.3},
                    'exit': {'hard_stop_pct': -2.5, 'take_profit_pct': 5.0, 'time_stop_bars': 7,
                             'atr_trailing_multiplier': 1.5, 'rsi_exit_threshold': 65},
                },
            },
        }
        self.df = create_test_data(days=100)
        self.ta = TechnicalAnalyzer(self.df)
        self.strategy = BounceStrategy('bounce', self.config)

    def test_fundamental_filter(self):
        row = pd.Series({'fundamental': 3.0, 'regime': 'NEUTRAL'})
        result = self.strategy.analyze_entry(row, self.df, self.ta)
        self.assertFalse(result['is_entry'])

    def test_regime_filter(self):
        row = pd.Series({'fundamental': 6.0, 'regime': 'RISK_OFF'})
        result = self.strategy.analyze_entry(row, self.df, self.ta)
        self.assertFalse(result['is_entry'])

    def test_should_sell_stop_loss(self):
        row = pd.Series({'price': 975, 'low': 970, 'high': 980, 'date': datetime.now()})
        ctx = {'buy_price': 1000, 'entry_date': datetime.now() - timedelta(days=5),
               'entry_atr': 20, 'trailing_high': 1000}
        should_sell, reason, price = self.strategy.should_sell(row, self.df, self.ta, ctx)
        self.assertTrue(should_sell)

    def test_should_sell_take_profit(self):
        row = pd.Series({'price': 1050, 'low': 1045, 'high': 1055, 'date': datetime.now()})
        ctx = {'buy_price': 1000, 'entry_date': datetime.now() - timedelta(days=5),
               'entry_atr': 20, 'trailing_high': 1055}
        should_sell, reason, price = self.strategy.should_sell(row, self.df, self.ta, ctx)
        self.assertTrue(should_sell)


class TestBreakoutStrategy(unittest.TestCase):
    def setUp(self):
        self.config = {
            'signals': {'BUY': {'min_score': 6.5}},
            'strategies': {
                'breakout': {
                    'enabled': True,
                    'enabled_regimes': ['NEUTRAL', 'RISK_ON'],
                    'entry': {'fundamental_min': 4.0, 'gc_lookback_days': 5,
                              'volume_multiplier': 1.5, 'require_bullish_close': True},
                    'exit': {'stop_loss_atr_multiplier': 3.0, 'take_profit_pct': 10.0,
                             'atr_trailing_activation_pct': 3.0, 'chandelier_tight_mult': 1.5,
                             'chandelier_mid_mult': 2.0, 'chandelier_loose_mult': 2.5,
                             'exit_on_death_cross': True, 'ma_short': 10, 'ma_long': 20},
                },
            },
        }
        self.df = create_test_data(days=100, trend='uptrend')
        self.ta = TechnicalAnalyzer(self.df)
        self.strategy = BreakoutStrategy('breakout', self.config)

    def test_fundamental_filter(self):
        row = pd.Series({'fundamental': 3.0, 'regime': 'NEUTRAL'})
        result = self.strategy.analyze_entry(row, self.df, self.ta)
        self.assertFalse(result['is_entry'])

    def test_entry_returns_dict(self):
        row = pd.Series({'fundamental': 6.0, 'regime': 'NEUTRAL'})
        result = self.strategy.analyze_entry(row, self.df, self.ta)
        self.assertIsInstance(result, dict)
        self.assertIn('is_entry', result)
        self.assertIn('details', result)


if __name__ == '__main__':
    unittest.main()
