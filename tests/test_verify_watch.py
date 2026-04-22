"""
tests/test_verify_watch.py — WATCHシグナル方向性フィードバックのテスト
"""
import unittest
import sys
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from verify_predictions import verify_entry


def _make_entry(total_score=5.0, signal="WATCH", entry_price=100.0, days_ago=60):
    """テスト用エントリーを生成"""
    # 実際のresults.jsonと同じ '%Y-%m-%d %H:%M' 形式を使用
    date_str = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M")
    return {
        "date": date_str,
        "signal": signal,
        "total_score": total_score,
        "technical_data": {"current_price": entry_price},
    }


class TestWatchSignalFeedback(unittest.TestCase):
    """WATCHシグナルでもtotal_scoreに基づいてsignal_hitが設定されることを検証"""

    @patch("verify_predictions.get_price_on_date")
    def test_watch_high_score_price_up(self, mock_price):
        """WATCH + total_score=6.5 + 株価上昇 → signal_hit=True"""
        mock_price.return_value = 110.0  # +10%
        entry = _make_entry(total_score=6.5, entry_price=100.0, days_ago=60)
        updated, changed = verify_entry("TEST", entry, [30], dry_run=False)
        self.assertTrue(changed)
        v30 = updated.get("verified_30d")
        self.assertIsNotNone(v30)
        self.assertTrue(v30["signal_hit"])  # スコア高い + 上昇 = 命中

    @patch("verify_predictions.get_price_on_date")
    def test_watch_high_score_price_down(self, mock_price):
        """WATCH + total_score=6.5 + 株価下落 → signal_hit=False"""
        mock_price.return_value = 90.0  # -10%
        entry = _make_entry(total_score=6.5, entry_price=100.0, days_ago=60)
        updated, changed = verify_entry("TEST", entry, [30], dry_run=False)
        self.assertTrue(changed)
        v30 = updated.get("verified_30d")
        self.assertIsNotNone(v30)
        self.assertFalse(v30["signal_hit"])  # スコア高い + 下落 = ミス

    @patch("verify_predictions.get_price_on_date")
    def test_watch_low_score_price_down(self, mock_price):
        """WATCH + total_score=3.5 + 株価下落 → signal_hit=True"""
        mock_price.return_value = 85.0  # -15%
        entry = _make_entry(total_score=3.5, entry_price=100.0, days_ago=60)
        updated, changed = verify_entry("TEST", entry, [30], dry_run=False)
        self.assertTrue(changed)
        v30 = updated.get("verified_30d")
        self.assertIsNotNone(v30)
        self.assertTrue(v30["signal_hit"])  # スコア低い + 下落 = 命中

    @patch("verify_predictions.get_price_on_date")
    def test_watch_low_score_price_up(self, mock_price):
        """WATCH + total_score=3.5 + 株価上昇 → signal_hit=False"""
        mock_price.return_value = 115.0  # +15%
        entry = _make_entry(total_score=3.5, entry_price=100.0, days_ago=60)
        updated, changed = verify_entry("TEST", entry, [30], dry_run=False)
        self.assertTrue(changed)
        v30 = updated.get("verified_30d")
        self.assertIsNotNone(v30)
        self.assertFalse(v30["signal_hit"])  # スコア低い + 上昇 = ミス

    @patch("verify_predictions.get_price_on_date")
    def test_watch_neutral_score(self, mock_price):
        """WATCH + total_score=5.0 → signal_hit=None (完全ニュートラル)"""
        mock_price.return_value = 110.0  # +10%
        entry = _make_entry(total_score=5.0, entry_price=100.0, days_ago=60)
        updated, changed = verify_entry("TEST", entry, [30], dry_run=False)
        self.assertTrue(changed)
        v30 = updated.get("verified_30d")
        self.assertIsNotNone(v30)
        self.assertIsNone(v30["signal_hit"])  # ニュートラル → 判定不能

    @patch("verify_predictions.get_price_on_date")
    def test_buy_signal_unchanged(self, mock_price):
        """BUYシグナルの従来動作が維持されること"""
        mock_price.return_value = 120.0  # +20%
        entry = _make_entry(total_score=7.0, signal="BUY", entry_price=100.0, days_ago=60)
        updated, changed = verify_entry("TEST", entry, [30], dry_run=False)
        self.assertTrue(changed)
        v30 = updated.get("verified_30d")
        self.assertTrue(v30["signal_hit"])

    @patch("verify_predictions.get_price_on_date")
    def test_sell_signal_unchanged(self, mock_price):
        """SELLシグナルの従来動作が維持されること"""
        mock_price.return_value = 85.0  # -15%
        entry = _make_entry(total_score=3.0, signal="SELL", entry_price=100.0, days_ago=60)
        updated, changed = verify_entry("TEST", entry, [30], dry_run=False)
        self.assertTrue(changed)
        v30 = updated.get("verified_30d")
        self.assertTrue(v30["signal_hit"])


if __name__ == "__main__":
    unittest.main()
