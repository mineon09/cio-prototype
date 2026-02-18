
import sys
import os
import pandas as pd
import unittest
from unittest.mock import MagicMock

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from strategies import BaseStrategy, LongStrategy, BounceStrategy, BreakoutStrategy
from analyzers import *

class TestReviewFeedback(unittest.TestCase):
    
    def test_regime_override(self):
        """1. Verify Regime Override -> Buying Threshold logic."""
        config = {
            "signals": {
                "BUY": {
                    "min_score": 6.5,
                    "regime_overrides": {
                        "RISK_ON": {"min_score": 5.5},
                        "RISK_OFF": {"min_score": 7.5}
                    }
                }
            }
        }
        strat = BaseStrategy("test", config)
        
        # Test Default
        self.assertEqual(strat.get_buy_threshold("NEUTRAL"), 6.5, "Default check failed")
        # Test RISK_ON
        self.assertEqual(strat.get_buy_threshold("RISK_ON"), 5.5, "RISK_ON check failed")
        # Test RISK_OFF
        self.assertEqual(strat.get_buy_threshold("RISK_OFF"), 7.5, "RISK_OFF check failed")
        print("✅ Regime Override Logic: OK")

    def test_bounce_ma75_nan(self):
        """2. Verify Bounce Strategy handles MA75 NaN correctly (ma75_ok = False)."""
        config = {"strategies": {"bounce": {"enabled_regimes": ["NEUTRAL"]}}}
        strat = BounceStrategy("bounce", config)
        
        # Mock Data with NaN MA75
        daily_data = pd.DataFrame({'Close': [100.0] * 100})
        # Force rolling mean to be NaN (e.g. not enough data)
        # But here we just mock the rolling().mean().iloc[-1] behavior by checking logic directly?
        # No, let's create data that yields NaN for 75-day MA
        short_data = pd.DataFrame({'Close': [100.0] * 10}) # Only 10 days
        
        row = pd.Series({'fundamental': 10.0, 'regime': 'NEUTRAL', 'score': 8.0})
        ta = MagicMock()
        ta.check_rsi_condition.return_value = True
        ta.check_bollinger_touch.return_value = (True, 0.0)
        ta.check_volume_spike.return_value = True
        
        # Should return False because MA75 is NaN -> ma75_ok = False
        should_buy = strat.should_buy(row, short_data, ta)
        self.assertFalse(should_buy, "Bounce should NOT buy when MA75 is NaN")
        print("✅ Bounce MA75 NaN Safety: OK")

    def test_breakout_atr_trailing(self):
        """3. Verify Breakout Strategy has ATR Trailing implementation."""
        config = {
            "exit_strategy": {
                "breakout": {
                    "atr_trailing_activation_pct": 3.0,
                    "atr_trailing_multiplier": 1.5
                }
            }
        }
        strat = BreakoutStrategy("breakout", config)
        
        # Scenario: Profit > 3.0%, price drops below ATR trail
        ctx = {
            'buy_price': 100.0,
            'entry_date': '2024-01-01',
            'entry_atr': 2.0,
            'trailing_high': 105.0 # +5% profit, activated
        }
        
        # Stop price = 105 - (2.0 * 1.5) = 105 - 3.0 = 102.0
        # Current price drops to 101.0 -> Should Sell
        row = pd.Series({'price': 101.0, 'low': 101.0, 'high': 101.0, 'date': '2024-01-10'})
        daily_data = pd.DataFrame() # Not used for ATR check
        ta = MagicMock()
        
        sell, reason, price = strat.should_sell(row, daily_data, ta, ctx)
        self.assertTrue(sell, "Breakout should sell on ATR Trailing")
        self.assertIn("ATR Trailing", reason, "Reason should be ATR Trailing")
        print("✅ Breakout ATR Trailing: OK")

    def test_perfect_order_bonus(self):
        """4. Verify Perfect Order Bonus in analyzers.py."""
        metrics = {'roe': 15.0} # Good fundamental
        technical = {
            'perfect_order': True, # TRIGGER BONUS
            'rsi': 50,
            'ma25_deviation': 0,
            'ma75_deviation': 0,
            'bb_position': 50,
            'volume_ratio': 1.0
        }
        
        # Without perfect order
        technical_no = technical.copy()
        technical_no['perfect_order'] = False
        
        # Run scoring
        card_no = generate_scorecard(metrics, technical_no, sector="")
        score_no = card_no['technical']['score']
        
        card_yes = generate_scorecard(metrics, technical, sector="")
        score_yes = card_yes['technical']['score']
        
        # Expect score_yes > score_no (by 0.5)
        self.assertGreater(score_yes, score_no, "Perfect Order should increase technical score")
        self.assertAlmostEqual(score_yes - score_no, 0.5, delta=0.1, msg="Bonus should be +0.5")
        print("✅ Perfect Order Bonus: OK")

if __name__ == '__main__':
    unittest.main(failfast=True, verbosity=2)
