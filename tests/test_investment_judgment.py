"""
Unit tests for src/investment_judgment.py
==========================================
投資判断エンジンの単体テスト
"""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.investment_judgment import (
    InvestmentJudgment,
    APIJudgmentEngine,
    ToolJudgmentEngine,
    DualJudgmentEngine,
    create_judgment_engine,
)


class TestInvestmentJudgment(unittest.TestCase):
    """InvestmentJudgment データクラスのテスト"""

    def test_create_judgment(self):
        """基本的な投資判断の作成"""
        judgment = InvestmentJudgment(
            signal='BUY',
            score=7.5,
            confidence=0.8,
            reasoning='テスト理由',
        )
        self.assertEqual(judgment.signal, 'BUY')
        self.assertEqual(judgment.score, 7.5)
        self.assertEqual(judgment.confidence, 0.8)

    def test_default_values(self):
        """デフォルト値のテスト"""
        judgment = InvestmentJudgment(
            signal='WATCH',
            score=5.0,
            confidence=0.5,
            reasoning='テスト',
        )
        self.assertEqual(judgment.position_size, 0.1)
        self.assertEqual(judgment.holding_period, 'medium')
        self.assertEqual(judgment.risks, [])
        self.assertEqual(judgment.catalysts, [])

    def test_to_dict(self):
        """辞書への変換"""
        judgment = InvestmentJudgment(
            signal='BUY',
            score=7.0,
            confidence=0.7,
            reasoning='テスト',
        )
        d = judgment.to_dict()
        self.assertEqual(d['signal'], 'BUY')
        self.assertIn('score', d)

    def test_to_json(self):
        """JSON への変換"""
        judgment = InvestmentJudgment(
            signal='SELL',
            score=3.0,
            confidence=0.6,
            reasoning='テスト',
        )
        json_str = judgment.to_json()
        self.assertIn('SELL', json_str)
        self.assertIn('score', json_str)


class TestToolJudgmentEngine(unittest.TestCase):
    """ToolJudgmentEngine のテスト"""

    def setUp(self):
        """テストデータの準備"""
        self.engine = ToolJudgmentEngine()
        
        self.ticker_data = {
            'ticker': '7203.T',
            'name': 'Toyota Motor',
            'sector': 'Consumer Cyclical',
            'metrics': {
                'roe': 10.5,
                'per': 10.0,
                'pbr': 1.2,
                'op_margin': 8.5,
                'equity_ratio': 40.0,
                'dividend_yield': 2.8,
            },
            'technical': {
                'current_price': 2850,
                'rsi': 45,
                'ma25_deviation': -2.5,
                'bb_position': 35,
                'volatility': 0.25,
            },
            'scores': {
                'fundamental': {'score': 7.5},
                'valuation': {'score': 6.0},
                'technical': {'score': 5.5},
                'qualitative': {'score': 7.0},
                'total_score': 6.5,
            },
        }
        
        self.yuho_data = {
            'risk_top3': [
                {'risk': '為替リスク', 'severity': '高'},
                {'risk': '原材料価格高騰', 'severity': '中'},
            ],
        }
        
        self.macro_data = {
            'regime': 'RISK_ON',
        }

    def test_judge_buy_signal(self):
        """BUY シグナルの判定"""
        self.ticker_data['scores']['total_score'] = 7.5
        result = self.engine.judge(self.ticker_data, yuho_data=self.yuho_data)
        self.assertEqual(result.signal, 'BUY')
        self.assertGreater(result.score, 6.0)

    def test_judge_watch_signal(self):
        """WATCH シグナルの判定"""
        self.ticker_data['scores']['total_score'] = 5.5
        result = self.engine.judge(self.ticker_data)
        self.assertEqual(result.signal, 'WATCH')

    def test_judge_sell_signal(self):
        """SELL シグナルの判定"""
        self.ticker_data['scores']['total_score'] = 3.0
        result = self.engine.judge(self.ticker_data)
        self.assertEqual(result.signal, 'SELL')

    def test_entry_price_calculation(self):
        """エントリー価格の計算"""
        result = self.engine.judge(self.ticker_data)
        self.assertIsNotNone(result.entry_price)
        self.assertGreater(result.entry_price, 2000)

    def test_stop_loss_calculation(self):
        """損切り価格の計算"""
        self.ticker_data['scores']['total_score'] = 7.5
        result = self.engine.judge(self.ticker_data)
        if result.entry_price:
            self.assertIsNotNone(result.stop_loss)
            self.assertLess(result.stop_loss, result.entry_price)

    def test_position_size_calculation(self):
        """ポジションサイズの計算"""
        self.ticker_data['scores']['total_score'] = 8.0
        result = self.engine.judge(self.ticker_data)
        self.assertGreater(result.position_size, 0.0)
        self.assertLessEqual(result.position_size, 0.20)

    def test_risk_extraction(self):
        """リスク要因の抽出"""
        result = self.engine.judge(self.ticker_data, yuho_data=self.yuho_data)
        self.assertGreater(len(result.risks), 0)

    def test_get_model_name(self):
        """モデル名の取得"""
        self.assertEqual(self.engine.get_model_name(), 'Tool-RuleBased')


class TestAPIJudgmentEngine(unittest.TestCase):
    """APIJudgmentEngine のテスト"""

    def test_create_gemini_engine(self):
        """Gemini エンジンの作成"""
        engine = APIJudgmentEngine(model='gemini')
        self.assertEqual(engine.get_model_name(), 'API-gemini')

    def test_create_qwen_engine(self):
        """Qwen エンジンの作成"""
        engine = APIJudgmentEngine(model='qwen', api_key='test_key')
        self.assertEqual(engine.get_model_name(), 'API-qwen')

    def test_parse_response_valid_json(self):
        """有効な JSON レスポンスのパース"""
        engine = APIJudgmentEngine(model='gemini')
        response_text = '''
        {
            "signal": "BUY",
            "score": 7.5,
            "confidence": 0.8,
            "reasoning": "テスト理由",
            "entry_price": 2850,
            "stop_loss": 2700,
            "take_profit": 3100,
            "position_size": 0.1,
            "holding_period": "medium",
            "risks": ["リスク 1", "リスク 2"],
            "catalysts": ["カタリスト 1"]
        }
        '''
        judgment = engine._parse_response(response_text)
        self.assertEqual(judgment.signal, 'BUY')
        self.assertEqual(judgment.score, 7.5)
        self.assertEqual(len(judgment.risks), 2)

    def test_parse_response_with_markdown(self):
        """マークダウン付き JSON のパース"""
        engine = APIJudgmentEngine(model='gemini')
        response_text = '''
        以下の通り判断します：
        ```json
        {
            "signal": "WATCH",
            "score": 5.0,
            "confidence": 0.5,
            "reasoning": "様子見"
        }
        ```
        '''
        judgment = engine._parse_response(response_text)
        self.assertEqual(judgment.signal, 'WATCH')

    def test_parse_response_fallback(self):
        """パース失敗時のフォールバック"""
        engine = APIJudgmentEngine(model='gemini')
        response_text = '無効なレスポンス'
        judgment = engine._parse_response(response_text)
        self.assertEqual(judgment.signal, 'WATCH')
        self.assertEqual(judgment.confidence, 0.3)


class TestDualJudgmentEngine(unittest.TestCase):
    """DualJudgmentEngine のテスト"""

    def setUp(self):
        """テストセットアップ"""
        self.api_engine = APIJudgmentEngine(model='gemini')
        self.tool_engine = ToolJudgmentEngine()
        self.dual_engine = DualJudgmentEngine(self.api_engine, self.tool_engine)
        
        self.ticker_data = {
            'ticker': '7203.T',
            'name': 'Toyota Motor',
            'sector': 'Consumer Cyclical',
            'metrics': {
                'roe': 10.5,
                'per': 10.0,
                'pbr': 1.2,
            },
            'technical': {
                'current_price': 2850,
                'rsi': 45,
            },
            'scores': {
                'fundamental': {'score': 7.5},
                'valuation': {'score': 6.0},
                'technical': {'score': 5.5},
                'qualitative': {'score': 7.0},
                'total_score': 6.5,
            },
        }

    def test_judge_returns_all_results(self):
        """両エンジンの結果を返す"""
        # API エンジンをモック（実際には API 呼び出ししない）
        from unittest.mock import patch
        
        with patch.object(self.api_engine, 'judge') as mock_api:
            mock_api.return_value = InvestmentJudgment(
                signal='BUY', score=7.5, confidence=0.8, reasoning='API 理由'
            )
            
            results = self.dual_engine.judge(self.ticker_data)
            
            self.assertIn('api_judgment', results)
            self.assertIn('tool_judgment', results)
            self.assertIn('consensus', results)
            self.assertIn('confidence', results)
            self.assertIn('disagreement', results)
            self.assertIn('final_recommendation', results)

    def test_consensus_agreement(self):
        """合意時の判定"""
        from unittest.mock import patch
        
        with patch.object(self.api_engine, 'judge') as mock_api:
            mock_api.return_value = InvestmentJudgment(
                signal='BUY', score=7.5, confidence=0.8, reasoning='API'
            )
            
            # ツールも BUY を返すようにスコア調整
            self.ticker_data['scores']['total_score'] = 7.5
            
            results = self.dual_engine.judge(self.ticker_data)
            
            self.assertEqual(results['consensus'], 'BUY')
            self.assertFalse(results['disagreement'])

    def test_consensus_disagreement(self):
        """不一致時の判定"""
        from unittest.mock import patch
        
        with patch.object(self.api_engine, 'judge') as mock_api:
            mock_api.return_value = InvestmentJudgment(
                signal='BUY', score=7.5, confidence=0.8, reasoning='API'
            )
            
            # ツールは WATCH を返すようにスコア調整
            self.ticker_data['scores']['total_score'] = 5.5
            
            results = self.dual_engine.judge(self.ticker_data)
            
            self.assertTrue(results['disagreement'])
            # 不一致時は WATCH に
            self.assertEqual(results['consensus'], 'WATCH')

    def test_compare_and_report(self):
        """比較レポートの生成"""
        from unittest.mock import patch
        
        with patch.object(self.api_engine, 'judge') as mock_api:
            mock_api.return_value = InvestmentJudgment(
                signal='BUY', score=7.5, confidence=0.8, reasoning='API 理由'
            )
            
            self.ticker_data['scores']['total_score'] = 7.5
            
            report = self.dual_engine.compare_and_report(self.ticker_data)
            
            self.assertIn('投資判断比較レポート', report)
            self.assertIn('API 判断', report)
            self.assertIn('ツール判断', report)
            self.assertIn('合意判定', report)


class TestCreateJudgmentEngine(unittest.TestCase):
    """ファクトリ関数のテスト"""

    def test_create_api_engine(self):
        """API エンジンの作成"""
        engine = create_judgment_engine('api', model='gemini')
        self.assertIsInstance(engine, APIJudgmentEngine)
        self.assertEqual(engine.get_model_name(), 'API-gemini')

    def test_create_tool_engine(self):
        """ツールエンジンの作成"""
        engine = create_judgment_engine('tool')
        self.assertIsInstance(engine, ToolJudgmentEngine)
        self.assertEqual(engine.get_model_name(), 'Tool-RuleBased')

    def test_create_invalid_engine(self):
        """無効なエンジンタイプの処理"""
        with self.assertRaises(ValueError):
            create_judgment_engine('invalid')


if __name__ == '__main__':
    unittest.main()
