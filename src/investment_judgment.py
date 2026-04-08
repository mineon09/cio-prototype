"""
investment_judgment.py - 投資判断エンジン
==========================================
API ベースと外部ツールベースの 2 つの投資判断システムを提供する。

使用例:
    from src.investment_judgment import create_judgment_engine
    
    # API ベース
    api_engine = create_judgment_engine("api", model="gemini")
    result = api_engine.judge(ticker_data, competitors, yuho_data)
    
    # 外部ツールベース
    tool_engine = create_judgment_engine("tool")
    result = tool_engine.judge(ticker_data, competitors, yuho_data)
    
    # 両方使用（比較）
    from src.investment_judgment import DualJudgmentEngine
    dual_engine = DualJudgmentEngine(api_engine, tool_engine)
    results = dual_engine.judge(ticker_data, competitors, yuho_data)
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime
import json

from src.logging_utils import get_logger

logger = get_logger(__name__)


@dataclass
class InvestmentJudgment:
    """投資判断結果"""
    signal: str  # BUY, WATCH, SELL
    score: float  # 0-10
    confidence: float  # 0-1 (信頼度)
    reasoning: str  # 判断理由
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    position_size: float = 0.1  # ポジションサイズ (%)
    holding_period: str = "medium"  # short, medium, long
    risks: List[str] = None
    catalysts: List[str] = None
    model_name: str = "unknown"
    judgment_time: str = ""
    
    def __post_init__(self):
        if self.risks is None:
            self.risks = []
        if self.catalysts is None:
            self.catalysts = []
        if not self.judgment_time:
            self.judgment_time = datetime.now().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


class BaseJudgmentEngine(ABC):
    """投資判断エンジンの基底クラス"""
    
    @abstractmethod
    def judge(
        self,
        ticker_data: Dict[str, Any],
        competitors: Dict[str, Any],
        yuho_data: Optional[Dict[str, Any]] = None,
        macro_data: Optional[Dict[str, Any]] = None,
        dcf_data: Optional[Dict[str, Any]] = None,
    ) -> InvestmentJudgment:
        """
        投資判断を実行する。
        
        Args:
            ticker_data: 対象銘柄のデータ
            competitors: 競合他社データ
            yuho_data: 有価証券報告書データ
            macro_data: マクロ環境データ
            dcf_data: DCF 理論株価データ
            
        Returns:
            InvestmentJudgment: 投資判断結果
        """
        pass
    
    @abstractmethod
    def get_model_name(self) -> str:
        """モデル名を取得する"""
        pass


class APIJudgmentEngine(BaseJudgmentEngine):
    """
    API ベース投資判断エンジン
    =========================
    LLM API (Gemini/Qwen) を使用して投資判断を行う。
    """
    
    def __init__(self, model: str = "gemini", api_key: Optional[str] = None):
        """
        Args:
            model: 使用するモデル ("gemini", "qwen")
            api_key: API キー（省略時は環境変数から取得）
        """
        self.model = model
        self.api_key = api_key
        self._client = None
        logger.info(f"API Judgment Engine initialized with model: {model}")
    
    def _get_client(self):
        """API クライアントを取得/初期化する"""
        if self._client is None:
            if self.model == "gemini":
                from google import genai
                from src.data_fetcher import _get_gemini_key
                self._client = genai.Client(api_key=self.api_key or _get_gemini_key())
            elif self.model == "qwen":
                # Qwen API クライアント（DashScope または OpenAI 互換）
                from openai import OpenAI
                self._client = OpenAI(
                    api_key=self.api_key or "",
                    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
                )
        return self._client
    
    def _build_prompt(
        self,
        ticker_data: Dict[str, Any],
        competitors: Dict[str, Any],
        yuho_data: Optional[Dict[str, Any]],
        macro_data: Optional[Dict[str, Any]],
        dcf_data: Optional[Dict[str, Any]],
    ) -> str:
        """プロンプトを構築する"""
        ticker = ticker_data.get('ticker', 'Unknown')
        name = ticker_data.get('name', 'Unknown')
        sector = ticker_data.get('sector', 'Unknown')
        metrics = ticker_data.get('metrics', {})
        technical = ticker_data.get('technical', {})
        scores = ticker_data.get('scores', {})
        
        def _m(v): return v if v is not None else 'N/A'
        
        prompt = f"""あなたは優秀な金融アナリストです。
以下のデータに基づいて、投資判断（BUY/WATCH/SELL）を出力してください。

【対象銘柄】{name} ({ticker})
【セクター】{sector}

【財務指標】
- ROE: {_m(metrics.get('roe'))}%
- PER: {_m(metrics.get('per'))}倍
- PBR: {_m(metrics.get('pbr'))}倍
- 営業利益率：{_m(metrics.get('op_margin'))}%
- 自己資本比率：{_m(metrics.get('equity_ratio'))}%
- 配当利回り：{_m(metrics.get('dividend_yield'))}%

【テクニカル】
- 現在価格：{technical.get('current_price', 'N/A')}
- RSI: {technical.get('rsi', 'N/A')}
- MA25 乖離：{technical.get('ma25_deviation', 'N/A')}%
- BB 位置：{technical.get('bb_position', 'N/A')}%

【4 軸スコア】
- Fundamental: {scores.get('fundamental', {}).get('score', 'N/A')}/10
- Valuation: {scores.get('valuation', {}).get('score', 'N/A')}/10
- Technical: {scores.get('technical', {}).get('score', 'N/A')}/10
- Qualitative: {scores.get('qualitative', {}).get('score', 'N/A')}/10
- 総合：{scores.get('total_score', 'N/A')}/10

【出力形式】
以下の JSON 形式で出力してください：
{{
    "signal": "BUY" or "WATCH" or "SELL",
    "score": 0-10,
    "confidence": 0-1,
    "reasoning": "判断理由（200 文字以内）",
    "entry_price": 数値,
    "stop_loss": 数値,
    "take_profit": 数値,
    "position_size": 0.0-1.0,
    "holding_period": "short" or "medium" or "long",
    "risks": ["リスク 1", "リスク 2"],
    "catalysts": ["カタリスト 1", "カタリスト 2"]
}}
"""
        return prompt
    
    def _parse_response(self, response_text: str) -> InvestmentJudgment:
        """API レスポンスをパースする"""
        try:
            # JSON 抽出
            import re
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
            else:
                data = json.loads(response_text)
            
            return InvestmentJudgment(
                signal=data.get('signal', 'WATCH'),
                score=float(data.get('score', 5.0)),
                confidence=float(data.get('confidence', 0.5)),
                reasoning=data.get('reasoning', ''),
                entry_price=data.get('entry_price'),
                stop_loss=data.get('stop_loss'),
                take_profit=data.get('take_profit'),
                position_size=float(data.get('position_size', 0.1)),
                holding_period=data.get('holding_period', 'medium'),
                risks=data.get('risks', []),
                catalysts=data.get('catalysts', []),
                model_name=f"API-{self.model}",
            )
        except Exception as e:
            logger.error(f"API レスポンスのパース失敗：{e}")
            # フォールバック
            return InvestmentJudgment(
                signal='WATCH',
                score=5.0,
                confidence=0.3,
                reasoning=f"API レスポンスのパースに失敗しました：{e}",
                model_name=f"API-{self.model}-fallback",
            )
    
    def judge(
        self,
        ticker_data: Dict[str, Any],
        competitors: Dict[str, Any] = None,
        yuho_data: Optional[Dict[str, Any]] = None,
        macro_data: Optional[Dict[str, Any]] = None,
        dcf_data: Optional[Dict[str, Any]] = None,
    ) -> InvestmentJudgment:
        """API を使用して投資判断を行う"""
        logger.info(f"API Judgment ({self.model}) started for {ticker_data.get('ticker')}")
        
        try:
            prompt = self._build_prompt(ticker_data, competitors or {}, yuho_data, macro_data, dcf_data)
            
            if self.model == "gemini":
                client = self._get_client()
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                )
                response_text = response.text
            elif self.model == "qwen":
                client = self._get_client()
                response = client.chat.completions.create(
                    model="qwen-max",
                    messages=[
                        {"role": "system", "content": "あなたは優秀な金融アナリストです。JSON 形式で出力してください。"},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},
                )
                response_text = response.choices[0].message.content
            else:
                raise ValueError(f"Unknown model: {self.model}")
            
            judgment = self._parse_response(response_text)
            logger.info(f"API Judgment completed: {judgment.signal}")
            return judgment
            
        except Exception as e:
            logger.error(f"API Judgment failed: {e}")
            return InvestmentJudgment(
                signal='WATCH',
                score=5.0,
                confidence=0.0,
                reasoning=f"API 判断に失敗しました：{e}",
                model_name=f"API-{self.model}-error",
            )
    
    def get_model_name(self) -> str:
        return f"API-{self.model}"


class ToolJudgmentEngine(BaseJudgmentEngine):
    """
    外部ツールベース投資判断エンジン
    ===============================
    ルールベース・数値分析・外部 API などを組み合わせて投資判断を行う。
    """
    
    def __init__(self, use_external_apis: bool = True):
        """
        Args:
            use_external_apis: 外部 API（株価・財務）を使用するか
        """
        self.use_external_apis = use_external_apis
        logger.info("Tool Judgment Engine initialized")
    
    def _calculate_signal_from_scores(self, scores: Dict[str, Any]) -> Tuple[str, float]:
        """スコアからシグナルを計算する"""
        total_score = scores.get('total_score', 5.0)
        
        # 設定ベースの閾値
        buy_threshold = 6.5
        sell_threshold = 3.5
        
        if total_score >= buy_threshold:
            signal = 'BUY'
        elif total_score <= sell_threshold:
            signal = 'SELL'
        else:
            signal = 'WATCH'
        
        # 信頼度計算（スコアの分散から）
        fund = scores.get('fundamental', {}).get('score', 5.0)
        val = scores.get('valuation', {}).get('score', 5.0)
        tech = scores.get('technical', {}).get('score', 5.0)
        qual = scores.get('qualitative', {}).get('score', 5.0)
        
        # 4 軸の一致度が高いほど信頼度高
        avg = (fund + val + tech + qual) / 4
        variance = ((fund-avg)**2 + (val-avg)**2 + (tech-avg)**2 + (qual-avg)**2) / 4
        confidence = max(0.3, min(1.0, 1.0 - (variance / 25)))  # 正規化
        
        return signal, confidence, total_score
    
    def _calculate_entry_price(self, technical: Dict[str, Any], signal: str) -> Optional[float]:
        """エントリー価格を計算する"""
        current_price = technical.get('current_price')
        if not current_price:
            return None
        
        if signal == 'BUY':
            # 現在価格または少し下をエントリー
            ma25_dev = technical.get('ma25_deviation', 0)
            if ma25_dev < -5:  # 5% 以上下落
                return current_price * 1.01  # 1% 上値
            else:
                return current_price
        elif signal == 'SELL':
            return current_price * 0.99
        else:
            return current_price
    
    def _calculate_stop_loss(self, technical: Dict[str, Any], entry_price: float) -> Optional[float]:
        """損切り価格を計算する"""
        if not entry_price:
            return None
        
        # ATR または固定％で計算
        volatility = technical.get('volatility', 0.25)
        stop_distance = max(0.05, volatility * 2)  # 最低 5%、ボラティリティの 2 倍
        
        return entry_price * (1 - stop_distance)
    
    def _calculate_take_profit(self, technical: Dict[str, Any], entry_price: float, signal: str) -> Optional[float]:
        """利確価格を計算する"""
        if not entry_price:
            return None
        
        if signal == 'BUY':
            # リスクリワード比 1:2
            stop_loss = self._calculate_stop_loss(technical, entry_price)
            if stop_loss:
                risk = entry_price - stop_loss
                return entry_price + (risk * 2)
            else:
                return entry_price * 1.10
        else:
            return entry_price * 0.90
    
    def _extract_risks(self, yuho_data: Optional[Dict[str, Any]], metrics: Dict[str, Any]) -> List[str]:
        """リスク要因を抽出する"""
        risks = []
        
        # 有報データから
        if yuho_data and yuho_data.get('risk_top3'):
            for risk in yuho_data['risk_top3'][:3]:
                if isinstance(risk, dict):
                    risks.append(risk.get('risk', '不明なリスク'))
                else:
                    risks.append(str(risk))
        
        # 財務指標から
        if metrics.get('roe', 0) < 5:
            risks.append("ROE が低い（資本効率に課題）")
        if metrics.get('equity_ratio', 100) < 20:
            risks.append("自己資本比率が低い（財務リスク）")
        if metrics.get('op_margin', 0) < 5:
            risks.append("営業利益率が低い（収益性に課題）")
        
        return risks[:5]  # 最大 5 件
    
    def _extract_catalysts(self, macro_data: Optional[Dict[str, Any]], technical: Dict[str, Any]) -> List[str]:
        """カタリスト（株価上昇要因）を抽出する"""
        catalysts = []
        
        # マクロ環境から
        if macro_data:
            regime = macro_data.get('regime', '')
            if regime == 'RISK_ON':
                catalysts.append("リスクオン環境")
            elif regime == 'RATE_CUT':
                catalysts.append("利下げ環境（グロース株に追い風）")
            elif regime == 'YEN_WEAK':
                catalysts.append("円安進行（輸出企業に有利）")
        
        # テクニカルから
        rsi = technical.get('rsi', 50)
        if rsi < 30:
            catalysts.append("RSI 売られすぎ（反発期待）")
        
        bb_pos = technical.get('bb_position', 50)
        if bb_pos < 20:
            catalysts.append("ボリンジャーバンド下限付近（押し目買い機会）")
        
        return catalysts[:5]  # 最大 5 件
    
    def _determine_position_size(self, scores: Dict[str, Any], signal: str) -> float:
        """ポジションサイズを決定する"""
        if signal != 'BUY':
            return 0.0
        
        total_score = scores.get('total_score', 5.0)
        confidence = self._calculate_signal_from_scores(scores)[1]
        
        # スコアと信頼度に基づくポジションサイズ
        base_size = 0.10  # 基準 10%
        score_factor = min(1.5, max(0.5, (total_score - 5) / 5 + 1))
        confidence_factor = confidence
        
        position_size = base_size * score_factor * confidence_factor
        return min(0.20, max(0.02, position_size))  # 2-20% の範囲
    
    def _determine_holding_period(self, scores: Dict[str, Any]) -> str:
        """保有期間を決定する"""
        fund_score = scores.get('fundamental', {}).get('score', 5.0)
        tech_score = scores.get('technical', {}).get('score', 5.0)
        
        if fund_score >= 7 and tech_score >= 6:
            return 'long'  # 長期保有
        elif fund_score >= 5 and tech_score >= 5:
            return 'medium'  # 中期保有
        else:
            return 'short'  # 短期保有
    
    def judge(
        self,
        ticker_data: Dict[str, Any],
        competitors: Dict[str, Any] = None,
        yuho_data: Optional[Dict[str, Any]] = None,
        macro_data: Optional[Dict[str, Any]] = None,
        dcf_data: Optional[Dict[str, Any]] = None,
    ) -> InvestmentJudgment:
        """ルールベースで投資判断を行う"""
        logger.info(f"Tool Judgment started for {ticker_data.get('ticker')}")
        
        try:
            metrics = ticker_data.get('metrics', {})
            technical = ticker_data.get('technical', {})
            scores = ticker_data.get('scores', {})
            
            # シグナル計算
            signal, confidence, score = self._calculate_signal_from_scores(scores)
            
            # エントリー価格計算
            entry_price = self._calculate_entry_price(technical, signal)
            
            # 損切り・利確計算
            stop_loss = self._calculate_stop_loss(technical, entry_price) if entry_price else None
            take_profit = self._calculate_take_profit(technical, entry_price, signal) if entry_price else None
            
            # ポジションサイズ
            position_size = self._determine_position_size(scores, signal)
            
            # 保有期間
            holding_period = self._determine_holding_period(scores)
            
            # リスク・カタリスト抽出
            risks = self._extract_risks(yuho_data, metrics)
            catalysts = self._extract_catalysts(macro_data, technical)
            
            # 判断理由生成
            reasoning = self._generate_reasoning(signal, scores, metrics, technical)
            
            judgment = InvestmentJudgment(
                signal=signal,
                score=score,
                confidence=confidence,
                reasoning=reasoning,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                position_size=position_size,
                holding_period=holding_period,
                risks=risks,
                catalysts=catalysts,
                model_name="Tool-RuleBased",
            )
            
            logger.info(f"Tool Judgment completed: {judgment.signal}")
            return judgment
            
        except Exception as e:
            logger.error(f"Tool Judgment failed: {e}")
            return InvestmentJudgment(
                signal='WATCH',
                score=5.0,
                confidence=0.0,
                reasoning=f"ツール判断に失敗しました：{e}",
                model_name="Tool-RuleBased-error",
            )
    
    def _generate_reasoning(
        self,
        signal: str,
        scores: Dict[str, Any],
        metrics: Dict[str, Any],
        technical: Dict[str, Any],
    ) -> str:
        """判断理由を生成する"""
        reasons = []
        
        if signal == 'BUY':
            reasons.append("総合スコアが BUY 閾値を上回っています")
            if scores.get('fundamental', {}).get('score', 0) >= 7:
                reasons.append("ファンダメンタルズが良好")
            if scores.get('valuation', {}).get('score', 0) >= 7:
                reasons.append("割安度が高い")
            if technical.get('rsi', 50) < 30:
                reasons.append("テクニカル的に売られすぎ")
        elif signal == 'SELL':
            reasons.append("総合スコアが SELL 閾値を下回っています")
            if scores.get('fundamental', {}).get('score', 0) < 4:
                reasons.append("ファンダメンタルズに懸念")
            if technical.get('rsi', 50) > 70:
                reasons.append("テクニカル的に買われすぎ")
        else:
            reasons.append("総合スコアは WATCH 範囲です")
            reasons.append("追加の材料待ちが適切")
        
        return "。".join(reasons[:4]) + "。"
    
    def get_model_name(self) -> str:
        return "Tool-RuleBased"


class DualJudgmentEngine:
    """
    二重投資判断エンジン
    ===================
    API と外部ツールの両方で判断し、結果を比較・統合する。
    """
    
    def __init__(self, api_engine: BaseJudgmentEngine, tool_engine: BaseJudgmentEngine):
        """
        Args:
            api_engine: API ベース判断エンジン
            tool_engine: ツールベース判断エンジン
        """
        self.api_engine = api_engine
        self.tool_engine = tool_engine
        logger.info("Dual Judgment Engine initialized")
    
    def judge(
        self,
        ticker_data: Dict[str, Any],
        competitors: Dict[str, Any] = None,
        yuho_data: Optional[Dict[str, Any]] = None,
        macro_data: Optional[Dict[str, Any]] = None,
        dcf_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        両方のエンジンで判断し、結果を比較する。
        
        Returns:
            {
                "api_judgment": InvestmentJudgment,
                "tool_judgment": InvestmentJudgment,
                "consensus": str,  # 合意シグナル
                "confidence": float,  # 統合信頼度
                "disagreement": bool,  # 不一致フラグ
                "final_recommendation": InvestmentJudgment
            }
        """
        # 両方で判断
        api_judgment = self.api_engine.judge(
            ticker_data, competitors, yuho_data, macro_data, dcf_data
        )
        tool_judgment = self.tool_engine.judge(
            ticker_data, competitors, yuho_data, macro_data, dcf_data
        )
        
        # 合意判定
        api_signal = api_judgment.signal
        tool_signal = tool_judgment.signal
        
        if api_signal == tool_signal:
            consensus = api_signal
            disagreement = False
        else:
            # 不一致の場合、より保守的なシグナルを採用
            if 'SELL' in [api_signal, tool_signal]:
                consensus = 'SELL'
            elif 'BUY' in [api_signal, tool_signal]:
                consensus = 'WATCH'  # 不一致時は WATCH に
            else:
                consensus = 'WATCH'
            disagreement = True
        
        # 統合信頼度
        avg_confidence = (api_judgment.confidence + tool_judgment.confidence) / 2
        if disagreement:
            avg_confidence *= 0.7  # 不一致時は信頼度低下
        
        # 最終推奨
        if consensus == api_signal:
            final = api_judgment
        else:
            final = tool_judgment
        
        # 信頼度を更新
        final.confidence = avg_confidence
        
        return {
            "api_judgment": api_judgment,
            "tool_judgment": tool_judgment,
            "consensus": consensus,
            "confidence": avg_confidence,
            "disagreement": disagreement,
            "final_recommendation": final,
        }
    
    def compare_and_report(
        self,
        ticker_data: Dict[str, Any],
        competitors: Dict[str, Any] = None,
        yuho_data: Optional[Dict[str, Any]] = None,
        macro_data: Optional[Dict[str, Any]] = None,
        dcf_data: Optional[Dict[str, Any]] = None,
    ) -> str:
        """比較レポートを生成する"""
        results = self.judge(ticker_data, competitors, yuho_data, macro_data, dcf_data)
        
        api = results["api_judgment"]
        tool = results["tool_judgment"]
        
        report = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 投資判断比較レポート
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【対象】{ticker_data.get('name', 'Unknown')} ({ticker_data.get('ticker', 'Unknown')})

┌─────────────────────────────────────────┐
│ API 判断 ({api.model_name})                  │
├─────────────────────────────────────────┤
│ シグナル：{api.signal:<20} │
│ スコア：{api.score:.1f}/10              │
│ 信頼度：{api.confidence:.0%}                  │
│ 理由：{api.reasoning[:50]}...    │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│ ツール判断 ({tool.model_name})                │
├─────────────────────────────────────────┤
│ シグナル：{tool.signal:<20} │
│ スコア：{tool.score:.1f}/10              │
│ 信頼度：{tool.confidence:.0%}                  │
│ 理由：{tool.reasoning[:50]}...   │
└─────────────────────────────────────────┘

【合意判定】
- 合意シグナル：{results['consensus']}
- 統合信頼度：{results['confidence']:.0%}
- 不一致フラグ：{'⚠️ あり' if results['disagreement'] else '✅ なし'}

【最終推奨】
- シグナル：{results['final_recommendation'].signal}
- スコア：{results['final_recommendation'].score:.1f}/10
- 信頼度：{results['final_recommendation'].confidence:.0%}
- エントリー：{results['final_recommendation'].entry_price}
- 損切り：{results['final_recommendation'].stop_loss}
- 利確：{results['final_recommendation'].take_profit}
- ポジション：{results['final_recommendation'].position_size:.1%}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
        return report


def create_judgment_engine(
    engine_type: str = "api",
    model: str = "gemini",
    **kwargs
) -> BaseJudgmentEngine:
    """
    投資判断エンジンを作成するファクトリ関数。
    
    Args:
        engine_type: "api" または "tool"
        model: API モデル（"gemini", "qwen"）
        **kwargs: 各エンジンへの追加引数
        
    Returns:
        BaseJudgmentEngine: 投資判断エンジン
    """
    if engine_type == "api":
        return APIJudgmentEngine(model=model, **kwargs)
    elif engine_type == "tool":
        return ToolJudgmentEngine(**kwargs)
    else:
        raise ValueError(f"Unknown engine type: {engine_type}")
