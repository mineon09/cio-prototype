# 🤖 AI投資司令塔 - CIO Prototype (Professional Edition)

外資との「対戦表」を自動生成し、**市場が気づいていない本質的価値のバグ**を発見するAI投資分析システム。

[![Python](https://img.shields.io/badge/Python-3.11-blue)](https://python.org)
[![Gemini](https://img.shields.io/badge/Gemini-2.5--flash-orange)](https://ai.google.dev)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

---

## 🎯 何をするシステムか

銘柄コードを1つ入力するだけで、以下を自動実行：

```plaintext
入力: "7203.T"（トヨタ）
        ↓
① yfinanceで財務・テクニカル・ニュースを取得
        ↓
② GeminiAPIが最適な比較対象を自動選定（API節約のためルールベース補完）
   直接競合: TSLA, BYD, F
   機能代替: UBER, LYFT
   資本効率ベンチマーク: AAPL, MSFT
        ↓
③ (日本株) EDINET有価証券報告書 / (米国株) SEC 10-K をGeminiで解析
   リスクTOP3 / 堀(Moat) / R&D / 経営陣トーン
        ↓
④ 4軸スコアカードを算出（セクター別閾値 + DCF + マクロ補正）
   Fundamental / Valuation / Technical / Qualitative
        ↓
⑤ 最終判断: BUY / WATCH / SELL
   → Notion + Streamlit ダッシュボードに出力
```

---

## 📦 ファイル構成

```plaintext
.
├── main.py                    # オーケストレーター（CLIエントリポイント）
├── app.py                     # Streamlit ダッシュボード
├── generate_prompt.py         # プロンプト生成 → Claude 等に手動貼り付け用
├── save_claude_result.py      # Claude 回答をダッシュボードに取り込む
├── config.json                # 設定（閾値・セクタープロファイル・戦略パラメータ）
├── data/
│   ├── results.json           # 分析結果（自動生成・履歴蓄積・filelock排他制御）
│   └── reports/               # Markdown レポート保存先
├── prompts/                   # 生成プロンプト・コンテキスト JSON 保存先
├── src/                       # コアモジュール群
│   ├── data_fetcher.py        # 株価・財務データ取得 + Gemini/Groq API 呼び出し
│   ├── analyzers.py           # 4軸スコアカード生成（セクター別閾値）
│   ├── strategies.py          # BounceStrategy / BreakoutStrategy
│   ├── macro_regime.py        # マクロ環境レジーム判定（TTLキャッシュ）
│   ├── dcf_model.py           # DCF理論株価（正式WACC・PITフィルタ）
│   ├── edinet_client.py       # EDINET 有報取得（日本株）
│   ├── edinetdb_client.py     # EDINET DB API（財務健全性・AI分析、日本株）
│   ├── jquants_client.py      # J-Quants V2 東証公式OHLC株価（日本株）
│   ├── sec_client.py          # SEC 10-K/10-Q 取得（米国株）
│   ├── news_fetcher.py        # ニュース取得（yfinance + Exa/Perplexity/Tavily）
│   ├── investment_judgment.py # API / ツールベース投資判断エンジン
│   ├── backtester.py          # バックテスト（PIT・モンテカルロ・ローリング）
│   ├── portfolio.py           # ポジションサイジング・セクター集中度チェック
│   ├── notion_writer.py       # Notion API 書き込み
│   ├── copilot_client.py      # GitHub Models API クライアント（GPT-4o）
│   └── parallel_utils.py      # 複数銘柄並列データ取得
├── scripts/                   # 検証・デバッグスクリプト
├── tests/                     # 単体テスト（pytest）
├── requirements.txt
├── .env.example
└── AGENTS.md                  # エージェント作業ルール
```

---

## 🚀 セットアップ

### 1. 依存パッケージをインストール

```bash
python3 -m venv venv
pip install -r requirements.txt
```

### 2. 環境変数を設定

```bash
cp .env.example .env
```

`.env` を編集：

```bash
GEMINI_API_KEY=your_gemini_api_key
EDINET_API_KEY=your_edinet_subscription_key
# 日本株の追加データソース（任意）
EDINETDB_API_KEY=your_edinetdb_api_key      # edinetdb.jp 財務DB + AI分析
JQUANTS_API_KEY=your_jquants_api_key        # 東証公式株価 OHLC
EXA_API_KEY=your_exa_api_key               # Exa ウェブ検索ニュース
PERPLEXITY_API_KEY=your_perplexity_key     # Perplexity（Exaフォールバック）
TAVILY_API_KEY=your_tavily_api_key         # Tavily（最終フォールバック）
NOTION_TOKEN=your_notion_integration_token
NOTION_DATABASE_ID=your_notion_database_id
# Google Sheets（任意）
SPREADSHEET_ID=your_spreadsheet_id
GOOGLE_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}'
```

| キー | 取得先 | 用途 |
|------|--------|------|
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/) | AI分析（必須） |
| `EDINET_API_KEY` | [EDINET API](https://disclosure2dl.edinet-fsa.go.jp/) | 有価証券報告書 |
| `EDINETDB_API_KEY` | [edinetdb.jp](https://edinetdb.jp/) | 財務健全性スコア・AI分析（任意） |
| `JQUANTS_API_KEY` | [J-Quants](https://jpx-jquants.com/) | 東証公式OHLC株価（任意） |
| `EXA_API_KEY` | [Exa](https://exa.ai/) | ウェブ検索ニュース（任意） |
| `PERPLEXITY_API_KEY` | [Perplexity](https://www.perplexity.ai/settings/api) | ニュースフォールバック（任意） |
| `TAVILY_API_KEY` | [Tavily](https://tavily.com/) | ニュースフォールバック（任意） |
| `NOTION_TOKEN` | [Notion Integrations](https://www.notion.so/my-integrations) | Notion書き込み |

---

## 💻 使い方

### 🤖 完全自動: Gemini で分析（推奨）

```bash
# 基本（デフォルト: Gemini 2.5 Flash）
./venv/bin/python3 main.py 7203.T

# 複数銘柄
./venv/bin/python3 main.py 7203.T 8306.T AAPL

# スイング戦略で分析（bounce: 逆張り / breakout: 順張り）
./venv/bin/python3 main.py 7203.T --strategy bounce
./venv/bin/python3 main.py AAPL --strategy breakout

# エンジン指定（GitHub Models GPT-4o を使用）
./venv/bin/python3 main.py AAPL --engine copilot
```

---

### 🥇 高精度: Claude Sonnet で分析（半自動）

データ収集・プロンプト生成・結果保存は自動。Claude への貼り付けのみ手動。

```bash
# Step 1: プロンプト生成（スコアカード・財務・テクニカルを自動収集）
./venv/bin/python3 generate_prompt.py 7203.T --copy
# → プロンプトがクリップボードにコピー、prompts/7203_T_context.json も自動保存

# Step 2: 【手動】Claude Sonnet に貼り付け → 回答全体をコピー

# Step 3: 回答をダッシュボードに自動保存
./venv/bin/python3 save_claude_result.py 7203.T --from-clipboard
# → data/results.json に追記（signal / entry / stop / take_profit / risks 等）
```

---

### 📊 Streamlit ダッシュボードを表示

```bash
streamlit run app.py
```

ブラウザが自動で `http://localhost:8501` を開きます。

---

### 🔄 バックテスト

```bash
# 例: トヨタ (7203.T) を 2024年1月から12ヶ月シミュレーション
python3 -m src.backtester --ticker 7203.T --start 2024-01-01 --months 12

# ローリングバックテスト（Walk-Forward）
python3 -m src.backtester --ticker 7203.T --start 2023-01-01 --months 24 --rolling --window-months 12
```

---

## 📊 4軸スコアカード

| 軸 | 内容 | 主要指標 |
|----|------|----------|
| **Fundamental** | 企業の地力 | ROE, 営業利益率, 自己資本比率 |
| **Valuation** | 割安度 | PER, PBR, 配当利回り, DCF乖離率 |
| **Technical** | タイミング | RSI, MA乖離率, BB位置, ボラティリティ |
| **Qualitative** | 定性分析 | 有報リスク, 堀(Moat), R&D, 経営陣トーン |

スコアはセクター別・マクロレジーム別に閾値が自動調整されます（High-Growth / Value / Financial 等）。

---

## ⚙️ カスタマイズ

`config.json` で挙動を変更できます：

```json
{
  "signals": {
    "BUY":  {"min_score": 6.5},
    "SELL": {"max_score": 3}
  },
  "sector_profiles": {
    "high_growth": {
      "sectors": ["Technology", "Healthcare"],
      "fundamental": {"roe_good": 15},
      "valuation": {"per_cheap": 25}
    }
  },
  "strategies": {
    "bounce": {"rsi_threshold": 30},
    "breakout": {"volume_multiplier": 1.5}
  }
}
```

---

## 🔒 GitHub Secrets の設定

| Secret名 | 内容 |
|----------|------|
| `GEMINI_API_KEY` | Gemini API キー |
| `EDINET_API_KEY` | EDINET API キー |
| `NOTION_TOKEN` | Notion インテグレーショントークン |
| `NOTION_DATABASE_ID` | Notion データベース ID |
| `SPREADSHEET_ID` | Google Sheets の ID（任意） |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | サービスアカウント JSON（任意） |

---

## 📖 ドキュメント

| ドキュメント | 内容 |
|---|---|
| [`docs/how_to_use.md`](docs/how_to_use.md) | 詳細な操作マニュアル（CLI・バックテスト・投資判断エンジン） |
| [`docs/architecture.md`](docs/architecture.md) | システムアーキテクチャ・モジュール一覧 |
| [`docs/system_design.md`](docs/system_design.md) | 主要ロジックの設計詳細 |
| [`docs/CHANGELOG.md`](docs/CHANGELOG.md) | バージョン別変更履歴 |

---

## ⚠️ 免責事項

このシステムは投資判断の参考情報を提供するものです。投資は自己責任で行ってください。

---

## 📝 License

MIT
