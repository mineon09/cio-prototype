# 📖 CIO Prototype ユーザー操作マニュアル

このドキュメントでは、AI 投資司令塔「CIO Prototype」の使用方法について詳しく説明します。

---

## 1. 銘柄の通常分析（最新データ）

最新の株価、財務データ、有価証券報告書に基づいた総合レポートを生成します。

### CLI での実行

最も詳細な分析を行う場合は、`main.py` を使用します。

```bash
# 仮想環境を使用する場合（推奨）
./venv/bin/python3 main.py --ticker 7203.T

# 通常分析（長期戦略）
python3 main.py --ticker 7203.T

# 複数銘柄を一括分析
python3 main.py --ticker 7203.T 8306.T 9984.T

# スイング戦略（Bounce: 逆張り / Breakout: 順張り）で分析
python3 main.py --ticker 7203.T --strategy bounce
python3 main.py --ticker 7011.T --strategy breakout
```

- **実行内容**: データの取得、DCF 算出（有利子負債を反映した正式な WACC 計算対応）、マクロ環境判定（自動・TTL 付きキャッシュ）、ルールベース＆AI ハイブリッドによる競合比較（API 節約対応）、AI レポート生成、Notion への自動記録、ローカル Markdown 形式およびダッシュボード用 JSON（排他制御対応）への保存。

### Streamlit ダッシュボード

視覚的に分析結果を閲覧したい場合に使用します。

```powershell
# サーバー起動
streamlit run app.py
```

- ブラウザが起動し、銘柄コード入力欄が表示されます。
- 左側のサイドバーから過去の分析履歴を素早く確認できます。
- マクロ指標データは自動的にキャッシュ（TTL 対応）されるため、リロード不要で高速動作します。

---

## 2. 投資判断の実行（v2.4.0 新機能）

API ベースとルールベースの 2 つの投資判断システムを使用できます。

### クイックスタート（Python スクリプト）

```python
from src.investment_judgment import create_judgment_engine, DualJudgmentEngine

# 銘柄データ（既存の分析結果を使用）
ticker_data = {
    'ticker': '7203.T',
    'name': 'Toyota Motor',
    'sector': 'Consumer Cyclical',
    'metrics': {
        'roe': 10.5, 'per': 10.0, 'pbr': 1.2,
        'op_margin': 8.5, 'equity_ratio': 40.0,
    },
    'technical': {
        'current_price': 2850, 'rsi': 45,
        'ma25_deviation': -2.5, 'bb_position': 35,
    },
    'scores': {
        'fundamental': {'score': 7.5},
        'valuation': {'score': 6.0},
        'technical': {'score': 5.5},
        'qualitative': {'score': 7.0},
        'total_score': 6.5,
    },
}

# 方法 1: API ベース判断（Gemini/Qwen）
api_engine = create_judgment_engine('api', model='gemini')
api_result = api_engine.judge(ticker_data)
print(f"API 判断：{api_result.signal}")
print(f"理由：{api_result.reasoning}")

# 方法 2: ツールベース判断（ルールベース）
tool_engine = create_judgment_engine('tool')
tool_result = tool_engine.judge(ticker_data)
print(f"ツール判断：{tool_result.signal}")

# 方法 3: 両方比較（推奨）
dual_engine = DualJudgmentEngine(api_engine, tool_engine)
results = dual_engine.judge(ticker_data)
print(f"合意シグナル：{results['consensus']}")
print(f"最終推奨：{results['final_recommendation'].signal}")
```

### 比較レポートの生成

```python
from src.investment_judgment import DualJudgmentEngine, create_judgment_engine

api_engine = create_judgment_engine('api', model='gemini')
tool_engine = create_judgment_engine('tool')
dual_engine = DualJudgmentEngine(api_engine, tool_engine)

# 比較レポートを出力
report = dual_engine.compare_and_report(ticker_data)
print(report)
```

**出力例**:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 投資判断比較レポート
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【対象】Toyota Motor (7203.T)

┌─────────────────────────────────────┐
│ API 判断 (API-gemini)                │
├─────────────────────────────────────┤
│ シグナル：BUY                  │
│ スコア：7.5/10              │
│ 信頼度：80%                  │
└─────────────────────────────────────┘

┌─────────────────────────────────────┐
│ ツール判断 (Tool-RuleBased)          │
├─────────────────────────────────────┤
│ シグナル：BUY                  │
│ スコア：6.5/10              │
│ 信頼度：75%                  │
└─────────────────────────────────────┘

【合意判定】
- 合意シグナル：BUY
- 統合信頼度：78%
- 不一致フラグ：✅ なし

【最終推奨】
- エントリー：2850 円
- 損切り：2700 円
- 利確：3100 円
- ポジション：12.5%
```

---

## 3. 外部ツール用プロンプト生成

LLM API（Gemini/Qwen/ChatGPT/Claude）に投資判断を依頼するためのプロンプトを生成します。

### 方法 0: 簡易コマンド（推奨・最速）

```bash
# 簡易プロンプト（データ取得なし、最速）
./venv/bin/python3 generate_prompt.py 7203.T --simple

# 完全プロンプト（データ取得あり）
./venv/bin/python3 generate_prompt.py 7203.T

# ファイルに保存
./venv/bin/python3 generate_prompt.py 7203.T -o prompt.txt

# クリップボードにコピー（pyperclip が必要）
./venv/bin/python3 generate_prompt.py 7203.T --copy

# モデル指定（gemini, qwen, chatgpt, claude）
./venv/bin/python3 generate_prompt.py 7203.T --model qwen
```

**出力例**:

```
🔍 プロンプト生成中：7203.T
============================================================
あなたは優秀な金融アナリストです。
以下のデータに基づいて、投資判断（BUY/WATCH/SELL）を出力してください。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【対象銘柄】Toyota Motor (7203.T)
【セクター】Consumer Cyclical
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【財務指標】
  ROE: 10.5%
  PER: 10.0 倍
  PBR: 1.2 倍
...

💡 使用方法:
   1. 上記プロンプトをコピー
   2. GEMINI のチャットに貼り付け
   3. 実行して投資判断を取得
```

### 方法 1: 投資判断エンジンの API ベースを使用（推奨）

```python
from src.investment_judgment import APIJudgmentEngine

# エンジン作成
engine = APIJudgmentEngine(model='gemini')

# 内部でプロンプトが自動生成され、API に送信される
result = engine.judge(ticker_data)

# 結果を取得
print(f"シグナル：{result.signal}")
print(f"スコア：{result.score}/10")
print(f"理由：{result.reasoning}")
```

**メリット**:

- プロンプト生成・送信・パースを自動で実行
- エラーハンドリング付き
- 一貫した出力形式

### 方法 2: プロンプトを手動生成して外部 API に送信

```python
from src.investment_judgment import APIJudgmentEngine

# エンジン作成
engine = APIJudgmentEngine(model='gemini')

# プロンプトを生成（API 送信はしない）
prompt = engine._build_prompt(
    ticker_data=ticker_data,
    competitors={},
    yuho_data=yuho_data,
    macro_data=macro_data,
    dcf_data=dcf_data,
)

# 生成されたプロンプトを表示
print(prompt)

# またはファイルに保存
with open('investment_prompt.txt', 'w', encoding='utf-8') as f:
    f.write(prompt)
```

**生成されるプロンプト例**:

```
あなたは優秀な金融アナリストです。
以下のデータに基づいて、投資判断（BUY/WATCH/SELL）を出力してください。

【対象銘柄】Toyota Motor (7203.T)
【セクター】Consumer Cyclical

【財務指標】
- ROE: 10.5%
- PER: 10.0 倍
- PBR: 1.2 倍
- 営業利益率：8.5%
- 自己資本比率：40.0%
- 配当利回り：2.8%

【テクニカル】
- 現在価格：2850
- RSI: 45
- MA25 乖離：-2.5%
- BB 位置：35%

【4 軸スコア】
- Fundamental: 7.5/10
- Valuation: 6.0/10
- Technical: 5.5/10
- Qualitative: 7.0/10
- 総合：6.5/10

【出力形式】
以下の JSON 形式で出力してください：
{
    "signal": "BUY" or "WATCH" or "SELL",
    "score": 0-10,
    "confidence": 0-1,
    "reasoning": "判断理由（200 文字以内）",
    "entry_price": 数値，
    "stop_loss": 数値，
    "take_profit": 数値，
    "position_size": 0.0-1.0,
    "holding_period": "short" or "medium" or "long",
    "risks": ["リスク 1", "リスク 2"],
    "catalysts": ["カタリスト 1", "カタリスト 2"]
}
```

### 方法 3: 既存のプロンプトビルダーを使用

```bash
# プロンプトを生成して.txt ファイルに保存
python3 prompt_builder.py 7203.T

# 画面にプロンプト用データを表示
python3 get_prompt.py 7203.T
```

### 方法 4: 手動でカスタムプロンプトを作成

```python
def create_custom_prompt(ticker_data):
    """カスタムプロンプトの作成"""
    metrics = ticker_data.get('metrics', {})
    scores = ticker_data.get('scores', {})
    
    prompt = f"""
あなたはプロの投資アナリストです。
以下の銘柄を分析し、投資判断を教えてください。

## 銘柄情報
- ティッカー：{ticker_data.get('ticker')}
- 企業名：{ticker_data.get('name')}
- セクター：{ticker_data.get('sector')}

## 財務指標
- ROE: {metrics.get('roe')}%
- PER: {metrics.get('per')}倍
- PBR: {metrics.get('pbr')}倍
- 営業利益率：{metrics.get('op_margin')}%

## 評価スコア
- 総合スコア：{scores.get('total_score')}/10
- ファンダメンタル：{scores.get('fundamental', {}).get('score')}/10
- 割安度：{scores.get('valuation', {}).get('score')}/10

## 質問
1. この銘柄への投資判断（BUY/WATCH/SELL）とその理由
2. 適切なエントリー価格
3. 損切りラインと利確ライン
4. 注意すべきリスク要因
"""
    return prompt

# 使用例
prompt = create_custom_prompt(ticker_data)
print(prompt)
```

### 外部 API への送信例

#### Gemini API

```python
from google import genai
import os

client = genai.Client(api_key=os.environ.get('GEMINI_API_KEY'))

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=prompt,
)

# 結果をパース
import json
result = json.loads(response.text)
print(f"判断：{result['signal']}")
```

#### Qwen API (DashScope)

```python
from openai import OpenAI
import os

client = OpenAI(
    api_key=os.environ.get('DASHSCOPE_API_KEY'),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)

response = client.chat.completions.create(
    model="qwen-max",
    messages=[
        {"role": "system", "content": "あなたは優秀な金融アナリストです。JSON 形式で出力してください。"},
        {"role": "user", "content": prompt}
    ],
    response_format={"type": "json_object"},
)

import json
result = json.loads(response.choices[0].message.content)
print(f"判断：{result['signal']}")
```

#### ChatGPT API

```python
from openai import OpenAI
import os

client = OpenAI(api_key=os.environ.get('OPENAI_API_KEY'))

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[
        {"role": "system", "content": "あなたはプロの投資アナリストです。JSON 形式で出力してください。"},
        {"role": "user", "content": prompt}
    ],
    response_format={"type": "json_object"},
)

import json
result = json.loads(response.choices[0].message.content)
print(f"判断：{result['signal']}")
```

#### Claude API

```python
import anthropic
import os

client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))

response = client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=1024,
    messages=[
        {"role": "user", "content": prompt}
    ]
)

import json
result = json.loads(response.content[0].text)
print(f"判断：{result['signal']}")
```

---

## 4. バックテストの実行

過去のデータを用いて、戦略の有効性をシミュレーションします。
**Point-in-Time フィルタリング (v2.1.0 強化版)**: 財務データは決算発表のラグ（基本 45 日）を考慮して「当時利用可能だったデータ」のみを使用します。EPS 計算等の指標では季節性の歪みを防ぐため**TTM（過去 4 四半期合計）**ベースで算出され、ルックアヘッドバイアスを排除しています。

### 基本コマンド

`src.backtester` モジュールを使用します。

```bash
# 例：トヨタ (7203.T) を 2024 年 1 月 1 日から 12 ヶ月間シミュレーション
python3 -m src.backtester --ticker 7203.T --start 2024-01-01 --months 12

# 戦略指定
python3 -m src.backtester --ticker 7203.T --start 2024-01-01 --months 12 --strategy bounce
```

### 高度なシミュレーション機能 (v2.1.0 強化版)

#### 🎲 モンテカルロシミュレーション (リスク評価)

バックテスト実行時、トレード結果に基づくブートストラップ法を用いたモンテカルロシミュレーション（1000 回）が実行され、リスクや最悪のドローダウンを推定します。各トレードは設定された資金サイズ（`position_pct`）を考慮して計算されます。

#### 🔄 ローリングバックテスト (Walk-Forward)

一定期間（ウィンドウ）ごとに期間をずらしながらテストを繰り返し、戦略の堅牢性を検証します。各ウィンドウにおけるシャープレシオ（Sharpe Ratio）も集計され、安定性を評価できます。

```bash
# 24 ヶ月の総期間を、12 ヶ月のウィンドウ、3 ヶ月ステップでスライド検証
python3 -m src.backtester --ticker 7203.T --start 2023-01-01 --months 24 --rolling --window-months 12 --step-months 3
```

#### ⚙️ CLI パラメータ・オーバーライド

`config.json` を書き換えることなく、一時的に戦略パラメータを変更してテストできます。

```bash
# RSI 閾値を 25 に変更して Bounce 戦略を検証
python3 -m src.backtester --ticker 7203.T --strategy bounce --rsi-threshold 25

# 出来高急増判定を 1.5 倍に変更
python3 -m src.backtester --ticker 7203.T --strategy breakout --volume-multiplier 1.5
```

---

## 5. 設定のカスタマイズ

`config.json` を編集することで、システムの恒久的な挙動をコントロールできます。

- **`ai_engine`**: 自動分析で使用する LLM の指定（`primary`, `fallback`）。
- **`signals`**: BUY/SELL 判定の閾値（Regime ごとの上書き設定も可能）。
- **`strategies`**: 各戦略のデフォルトパラメータ（RSI, 移動平均、出来高倍率など）。
- **`exit_strategy`**: 戦略ごとの損切り（Stop Loss）および利確（Take Profit）の ATR 倍率。
- **`sector_profiles`**: セクターごとのスコア配分（Tech 銘柄ならテクニカル重視など）。
- **`position_sizing`**: 推奨ロットサイズ（`pct_per_trade`）およびセクター集中度の最大許容範囲。この値はモンテカルロリスク評価にも適用されます。
- **`scoring_thresholds`**: スコアリングの閾値（CF 品質、R&D 比率、配当利回りなど）。

---

## 6. トラブルシューティング

- **yfinance の株価仕様注意点**: バックテストにて過去の株価を参照する際、yfinance の仕様により、その後に発生した**株式分割などで調整済みの価格（現在の基準）**が過去にも遡って適用されます（当時の実際の価格ではない点に留意してください）。
- **財務データの欠損**: yfinance 等でデータが取得できない項目は、安全側のデフォルト値（NG 判定）や通期データによる補完が自動で行われます。
- **文字化け・環境不整合**: Windows 環境では、実行時に `chcp 65001 > nul &&` (CMD) や `$OutputEncoding = [System.Text.Encoding]::UTF8; [Console]::OutputEncoding = [System.Text.Encoding]::UTF8; $env:PYTHONUTF8=1;` (PowerShell) を設定することを強く推奨します。
- **複数システムからの並列実行**: `results.json` へのアクセスは `filelock` により排他制御されています。GitHub Actions 等で並列実行した場合も安全に書き込みが行われます。
- **Notion 連携時の挙動**: Notion 書き込み時にデータベースのプロパティが不足している場合、エラーを検知して動的にプロパティを追加・リトライします（Add-On-Demand 機能）。またブロックの文字数制限（2000 文字）を回避するため、長文レポートは自動で安全なサイズにチャンク分割されて保存されます。
- **実行ログ**: ターミナルの標準出力およびローカルディレクトリ (`data/reports/`) 内の Markdown ファイルで詳細を確認できます。Notion 連携を設定している場合は、指定したデータベースにも内容が自動書き込みされます。
- **API キーのエラー**: `.env` ファイルに API キーが正しく設定されているか確認してください。`python3 -c "import os; print(os.environ.get('GEMINI_API_KEY'))` で環境変数を確認できます。
- **投資判断エンジンのエラー**: `src/investment_judgment.py` のログ出力を確認してください。`logging` モジュールで INFO レベル以上のログが出力されます。

---

## 付録：投資判断エンジンの詳細

### API ベースエンジン vs ツールベースエンジン

| 項目 | API ベース | ツールベース |
|------|-----------|-------------|
| 使用技術 | LLM (Gemini/Qwen) | ルールベース |
| 処理時間 | 2-5 秒 | <0.1 秒 |
| コスト | API 料金が必要 | 無料 |
| 文脈理解 | ✅ 可能 | ❌ 限定的 |
| 再現性 | ❌ 変動あり | ✅ 高い |
| 定性分析 | ✅ 可能 | ❌ 数値のみ |

### 推奨使い分け

- **API ベース**: 重要な投資判断、定性分析も含めて深く分析したい場合
- **ツールベース**: 快速なスクリーニング、バックテスト、コスト削減したい場合
- **デュアルエンジン**: 両方の結果を比較して、より信頼性の高い判断を得たい場合

---
*Last Updated: 2026-03-15 (v2.4.0 投資判断エンジンとプロンプト生成機能追加)*
