"""
Unit tests for select_competitors() — ルールベース拡張のテスト
"""

import unittest
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data_fetcher import select_competitors


class TestSelectCompetitorsRuleBased(unittest.TestCase):
    """config.json の sector_competitors を優先的に使用するテスト"""

    def test_technology_jp_returns_rule_based(self):
        """日本株 Technology → ルールベースが返る"""
        target = {"ticker": "6758.T", "name": "Sony", "sector": "Technology"}
        result = select_competitors(target, macro_data={"regime": "RISK_ON"})
        self.assertEqual(result["ai_model"], "Rule-based (config)")
        self.assertIn("6861.T", result["direct"])
        self.assertNotIn("6758.T", result["direct"])  # 自分自身は除外

    def test_technology_us_returns_rule_based(self):
        """米国株 Technology → ルールベースが返る"""
        target = {"ticker": "NVDA", "name": "NVIDIA", "sector": "Technology"}
        result = select_competitors(target, macro_data={"regime": "NEUTRAL"})
        self.assertEqual(result["ai_model"], "Rule-based (config)")
        self.assertIn("MSFT", result["direct"])

    def test_financial_jp_with_macro(self):
        """日本株 Financial Services + macro → ルールベースが返る（旧バグ修正確認）"""
        target = {"ticker": "8306.T", "name": "MUFG", "sector": "Financial Services"}
        result = select_competitors(target, macro_data={"regime": "RISK_OFF"})
        self.assertIn("Rule-based", result["ai_model"])
        # 自分自身(8306.T)は除外される
        self.assertNotIn("8306.T", result["direct"])

    def test_healthcare_us(self):
        """米国株 Healthcare → ルールベース"""
        target = {"ticker": "JNJ", "name": "J&J", "sector": "Healthcare"}
        result = select_competitors(target)
        self.assertIn("Rule-based", result["ai_model"])
        self.assertNotIn("JNJ", result["direct"])

    def test_energy_jp(self):
        """日本株 Energy → ルールベース（新規追加セクター確認）"""
        target = {"ticker": "5020.T", "name": "ENEOS", "sector": "Energy"}
        result = select_competitors(target, macro_data={"regime": "RATE_HIKE"})
        self.assertIn("Rule-based", result["ai_model"])
        self.assertNotIn("5020.T", result["direct"])

    def test_consumer_cyclical_us(self):
        """米国株 Consumer Cyclical → ルールベース"""
        target = {"ticker": "TSLA", "name": "Tesla", "sector": "Consumer Cyclical"}
        result = select_competitors(target)
        self.assertIn("Rule-based", result["ai_model"])
        self.assertNotIn("TSLA", result["direct"])
        self.assertIn("AMZN", result["direct"])

    def test_macro_regime_in_reasoning(self):
        """マクロレジームが NEUTRAL/UNAVAILABLE 以外の場合 reasoning に追記される"""
        target = {"ticker": "8035.T", "name": "Tokyo Electron", "sector": "Technology"}
        result = select_competitors(target, macro_data={"regime": "RISK_OFF"})
        self.assertIn("RISK_OFF", result["reasoning"])

    def test_macro_neutral_not_in_reasoning(self):
        """NEUTRAL はreasoningに追記されない"""
        target = {"ticker": "8035.T", "name": "Tokyo Electron", "sector": "Technology"}
        result = select_competitors(target, macro_data={"regime": "NEUTRAL"})
        self.assertNotIn("NEUTRAL", result["reasoning"])

    def test_no_macro_still_rule_based(self):
        """macro_data なしでもルールベースが使われる"""
        target = {"ticker": "AAPL", "name": "Apple", "sector": "Technology"}
        result = select_competitors(target, macro_data=None)
        self.assertIn("Rule-based", result["ai_model"])

    @patch("src.data_fetcher.call_gemini")
    def test_unknown_sector_falls_back_to_ai(self, mock_gemini):
        """未知セクター → AI フォールバック"""
        mock_gemini.return_value = (
            {"direct": ["XXX"], "substitute": ["YYY"], "benchmark": ["ZZZ"], "reasoning": "test"},
            "gemini-2.5-flash"
        )
        target = {"ticker": "TEST", "name": "Unknown Corp", "sector": "Alien Biometrics"}
        # AI フォールバックパスに入ることを確認（call_gemini が呼ばれる）
        with patch("src.data_fetcher.yf") as mock_yf:
            # yf.Ticker().history() が空でないDataFrameを返す
            import pandas as pd
            mock_yf.Ticker.return_value.history.return_value = pd.DataFrame({"Close": [100]})
            result = select_competitors(target, macro_data={"regime": "NEUTRAL"})
        mock_gemini.assert_called_once()
        self.assertEqual(result["ai_model"], "gemini-2.5-flash")


if __name__ == "__main__":
    unittest.main()
