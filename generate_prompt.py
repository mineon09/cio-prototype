#!/usr/bin/env python3
"""
generate_prompt.py - 投資判断用プロンプト生成ツール（強化版）
=====================================================
銘柄コードを指定するだけで、LLM 用の投資判断プロンプトを生成します。

定性情報（ニュース、アナリスト評価、業界動向）を自動取得して
プロンプトに埋め込むことで、より精度の高い分析が可能になります。

使い方:
    ./venv/bin/python3 generate_prompt.py 7203.T
    ./venv/bin/python3 generate_prompt.py AAPL --output prompt.txt
    ./venv/bin/python3 generate_prompt.py 7203.T --copy  # クリップボードにコピー
    ./venv/bin/python3 generate_prompt.py AMAT --enhanced  # 定性情報あり
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict


def build_simple_prompt(ticker: str, name: str = None):
    """
    簡易プロンプトを生成（データ取得なし）
    """
    if name is None:
        name = ticker

    prompt = f"""あなたは優秀な金融アナリストです。
以下の銘柄のデータを収集・分析し、投資判断を JSON 形式で出力してください。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【対象銘柄】{name} ({ticker})
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【タスク】
1. 上記銘柄の最新財務データを収集（ROE, PER, PBR, 営業利益率など）
2. テクニカル指標を確認（RSI, 移動平均乖離率など）
3. 競合他社と比較分析
4. 投資判断（BUY/WATCH/SELL）を導出

【出力形式】
以下の JSON 形式で**必ず**出力してください。

```json
{{
    "signal": "BUY",
    "score": 7.5,
    "confidence": 0.8,
    "reasoning": "判断理由を 200 文字以内で記載",
    "entry_price": 2850,
    "stop_loss": 2700,
    "take_profit": 3100,
    "position_size": 0.12,
    "holding_period": "medium",
    "risks": ["リスク要因 1", "リスク要因 2"],
    "catalysts": ["カタリスト 1", "カタリスト 2"]
}}
```

【各フィールドの説明】
- signal: "BUY", "WATCH", "SELL" のいずれか
- score: 0-10 のスコア（10 が最強）
- confidence: 0-1 の信頼度（1 が最高）
- reasoning: 判断理由（200 文字以内）
- entry_price: 推奨エントリー価格
- stop_loss: 損切り価格
- take_profit: 利確価格
- position_size: ポジションサイズ（0.0-1.0）
- holding_period: "short" (数日), "medium" (数週間), "long" (数ヶ月〜)
- risks: リスク要因リスト（最大 5 件）
- catalysts: 株価上昇のカタリスト（最大 5 件）
"""
    return prompt


def build_enhanced_prompt_with_data(
    ticker: str,
    company_name: str = None,
    sector: str = None,
    financial_data: Dict = None,
    technical_data: Dict = None,
    news_data: Dict = None,
    analyst_data: Dict = None,
    industry_data: Dict = None,
) -> str:
    """
    全ての定性情報を含む完全版プロンプトを生成
    """
    name = company_name or ticker
    current_date = datetime.now().strftime("%Y年%m月%d日")

    # セクション構築
    sections = []

    # 1. 基本情報
    sections.append(f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【基本情報】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
銘柄名          : {name} ({ticker})
セクター        : {sector or 'Unknown'}
分析基準日      : {current_date}
""")

    # 2. 財務指標
    if financial_data and financial_data.get('metrics'):
        m = financial_data['metrics']
        sections.append(f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【財務指標】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ROE            : {m.get('roe', 'N/A')}%
  PER            : {m.get('per', 'N/A')}倍
  PBR            : {m.get('pbr', 'N/A')}倍
  営業利益率     : {m.get('op_margin', 'N/A')}%
  自己資本比率   : {m.get('equity_ratio', 'N/A')}%
  配当利回り     : {m.get('dividend_yield', 'N/A')}%
  営業 CF/純利益 : {m.get('cf_quality', 'N/A')}
  R&D 比率       : {m.get('rd_ratio', 'N/A')}%
""")

    # 3. テクニカル指標
    if technical_data:
        t = technical_data
        sections.append(f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【テクニカル指標】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  現在価格       : {t.get('current_price', 'N/A')}
  RSI(14)        : {t.get('rsi', 'N/A')}
  MA25 乖離率    : {t.get('ma25_deviation', 'N/A')}%
  BB 位置        : {t.get('bb_position', 'N/A')}%
  出来高比率     : {t.get('volume_ratio', 'N/A')}
  Perfect Order  : {t.get('perfect_order', 'N/A')}
""")

    # 4. ニュース・センチメント
    if news_data and news_data.get('available'):
        from src.news_fetcher import format_news_for_prompt
        sections.append(f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【ニュース・市場センチメント】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{format_news_for_prompt(news_data)}

""")

    # 5. アナリスト評価
    if analyst_data and analyst_data.get('available'):
        from src.analyst_ratings import format_analyst_for_prompt
        sections.append(f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【アナリスト評価・コンセンサス】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{format_analyst_for_prompt(analyst_data)}

""")

    # 6. 業界動向
    if industry_data and industry_data.get('available'):
        from src.industry_trends import format_industry_for_prompt
        sections.append(f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【業界動向・競合比較】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{format_industry_for_prompt(industry_data)}

""")

    # 7. 分析タスク
    sections.append(f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【分析タスク】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
以下の 3 点について詳細に分析し、投資判断を導出してください：

1. 総合評価
   - 定量データ（財務・テクニカル）と定性データ（ニュース・アナリスト評価）の整合性
   - 業界動向に対する会社のポジショニング
   - 現在のバリュエーション水準の妥当性

2. 投資判断の根拠
   - BUY/WATCH/SELL の推奨と、その確信度
   - 向こう 12 ヶ月の主要カタリストとリスク
   - エントリー・利確・損切りの具体的な価格水準

3. シナリオ分析
   - ベースケース（確率 50-60%）
   - ブルケース（確率 20-30%）
   - ベアケース（確率 20-30%）
   - 各シナリオでの目標株価と期間

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【出力形式】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
以下の JSON 形式で**必ず**出力してください。

```json
{{
    "signal": "BUY",
    "score": 7.5,
    "confidence": 0.85,
    "reasoning": "現在の市場環境、業界展望、企業業績を踏まえた判断理由を 300 文字以内で記載",
    "industry_outlook": "業界の将来性についての見解を 100 文字以内",
    "competitive_position": "競争地位の評価を 100 文字以内",
    "entry_price": 340.0,
    "stop_loss": 300.0,
    "take_profit": 400.0,
    "position_size": 0.12,
    "holding_period": "medium",
    "time_horizon": "12-18 months",
    "key_catalysts": [
        {{
            "event": "次四半期決算発表",
            "expected_timing": "2026Q2",
            "impact": "high",
            "probability": 0.8
        }},
        {{
            "event": "新製品発表",
            "expected_timing": "2026Q3",
            "impact": "medium",
            "probability": 0.6
        }}
    ],
    "key_risks": [
        {{
            "risk": "半導体サイクルの下落局面入り",
            "impact": "high",
            "mitigation": "ポートフォリオの分散とヘッジ"
        }},
        {{
            "risk": "中国規制強化",
            "impact": "medium",
            "mitigation": "地域別売上のモニタリング"
        }}
    ],
    "scenario_analysis": {{
        "bull_case": {{
            "target": 450.0,
            "probability": 0.25,
            "scenario": "AI 需要の継続とシェア拡大で EPS がコンセンサス 15% 上振れ"
        }},
        "base_case": {{
            "target": 380.0,
            "probability": 0.50,
            "scenario": "コンセンサス通りの成長、バリュエーションは現状維持"
        }},
        "bear_case": {{
            "target": 280.0,
            "probability": 0.25,
            "scenario": "景気後退で半導体投資が減少、マージン圧迫"
        }}
    }},
    "esg_factors": {{
        "environmental": "環境面の評価と課題",
        "social": "社会面の評価と課題",
        "governance": "ガバナンス面の評価と課題"
    }}
}}
```

【各フィールドの説明】
- signal: "BUY"（推奨）, "WATCH"（様子見）, "SELL"（売却）のいずれか
- score: 0-10 の総合スコア（10 が最強）
- confidence: 0-1 の信頼度（1 が最高）
- reasoning: 判断理由（300 文字以内）
- industry_outlook: 業界展望（100 文字以内）
- competitive_position: 競争地位（100 文字以内）
- entry_price: 推奨エントリー価格
- stop_loss: 損切り価格
- take_profit: 利確価格
- position_size: ポジションサイズ（0.0-1.0）
- holding_period: "short" (数日), "medium" (数週間), "long" (数ヶ月〜)
- time_horizon: 投資期間の見通し
- key_catalysts: 株価上昇のカタリスト（最大 5 件）
- key_risks: リスク要因と緩和策（最大 5 件）
- scenario_analysis: シナリオ別目標株価と確率
- esg_factors: ESG 評価
""")

    return "\n".join(sections)


def build_full_prompt(ticker: str, include_qualitative: bool = True):
    """
    完全版プロンプトを生成（データ取得あり）
    
    Parameters
    ----------
    ticker             : 銘柄コード
    include_qualitative: ニュース・アナリスト・業界データを含むか
    """
    print(f"📈 株価データ取得中...")
    try:
        from src.data_fetcher import fetch_stock_data
        data = fetch_stock_data(ticker)
    except Exception as e:
        print(f"⚠️ データ取得失敗：{e}")
        return build_simple_prompt(ticker)

    if not data or not data.get('metrics'):
        return build_simple_prompt(ticker)

    # スコアカード生成
    print(f"📊 スコアカード生成中...")
    try:
        from src.analyzers import generate_scorecard
        scorecard = generate_scorecard(
            data.get('metrics', {}),
            data.get('technical', {}),
            sector=data.get('sector', ''),
        )
    except:
        scorecard = {'total_score': 5.0, 'scores': {}}

    # 定性情報の取得
    news_data = None
    analyst_data = None
    industry_data = None

    if include_qualitative:
        try:
            # ニュース取得
            from src.news_fetcher import fetch_all_news
            news_data = fetch_all_news(ticker, company_name=data.get('name'), include_google=True)
        except Exception as e:
            print(f"  ⚠️ ニュース取得エラー：{e}")

        try:
            # アナリスト評価取得
            from src.analyst_ratings import fetch_all_analyst_data
            analyst_data = fetch_all_analyst_data(ticker)
        except Exception as e:
            print(f"  ⚠️ アナリスト評価取得エラー：{e}")

        try:
            # 業界動向取得
            from src.industry_trends import fetch_all_industry_data
            industry_data = fetch_all_industry_data(
                ticker,
                sector=data.get('sector', 'Technology'),
                company_name=data.get('name'),
            )
        except Exception as e:
            print(f"  ⚠️ 業界動向取得エラー：{e}")

    # 強化版プロンプト生成
    prompt = build_enhanced_prompt_with_data(
        ticker=ticker,
        company_name=data.get('name'),
        sector=data.get('sector'),
        financial_data=data,
        technical_data=data.get('technical', {}),
        news_data=news_data,
        analyst_data=analyst_data,
        industry_data=industry_data,
    )

    return prompt


def copy_to_clipboard(text: str) -> bool:
    """テキストをクリップボードにコピー"""
    try:
        import pyperclip
        pyperclip.copy(text)
        return True
    except:
        return False


def main():
    parser = argparse.ArgumentParser(description='LLM 用投資判断プロンプトを生成')
    parser.add_argument('ticker', help='銘柄コード（例：7203.T, AAPL）')
    parser.add_argument('-o', '--output', help='出力ファイルパス')
    parser.add_argument('--copy', action='store_true', help='クリップボードにコピー')
    parser.add_argument('--simple', action='store_true', help='簡易モード（データ取得なし）')
    parser.add_argument('--enhanced', action='store_true',
                       help='強化モード（ニュース・アナリスト・業界動向を含む）')
    parser.add_argument('--no-qualitative', action='store_true',
                       help='定性情報（ニュース等）をスキップ')
    parser.add_argument('--model', choices=['gemini', 'qwen', 'chatgpt', 'claude'],
                       default='gemini', help='対象モデル')

    args = parser.parse_args()

    print(f"🔍 プロンプト生成中：{args.ticker}")

    # プロンプト生成
    if args.simple:
        prompt = build_simple_prompt(args.ticker)
    elif args.enhanced or not args.no_qualitative:
        prompt = build_full_prompt(args.ticker, include_qualitative=not args.no_qualitative)
    else:
        prompt = build_full_prompt(args.ticker, include_qualitative=False)

    # 出力
    if args.copy:
        if copy_to_clipboard(prompt):
            print(f"✅ クリップボードにコピーしました")
        else:
            print(f"⚠️ クリップボードコピー失敗（pyperclip をインストール：pip install pyperclip）")

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(prompt)
        print(f"✅ ファイルに保存：{args.output}")

    if not args.output and not args.copy:
        print(f"\n{'='*60}")
        print(prompt)
        print(f"{'='*60}")

    print(f"\n💡 使用方法:")
    print(f"   1. 上記プロンプトをコピー")
    print(f"   2. {args.model.upper()} のチャットに貼り付け")
    print(f"   3. 実行して投資判断を取得")


if __name__ == '__main__':
    main()
