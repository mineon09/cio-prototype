# 🤖 AI投資司令塔 - CIO Prototype (Professional Edition)

外資との「対戦表」を自動生成し、**市場が気づいていない本質的価値のバグ**を発見するAI投資分析システム。

[![Python](https://img.shields.io/badge/Python-3.11-blue)](https://python.org)
[![Gemini](https://img.shields.io/badge/Gemini-3--flash-orange)](https://ai.google.dev)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

---

## 🎯 何をするシステムか

銘柄コードを1つ入力するだけで、以下を自動実行：

```
入力: "7203.T"（トヨタ）
        ↓
① yfinanceで財務・テクニカル・ニュースを取得
        ↓
② GeminiAPIが最適な比較対象を自動選定
   直接競合: TSLA, BYD, F
   機能代替: UBER, LYFT
   資本効率ベンチマーク: AAPL, MSFT
        ↓
③ (日本株) EDINET有価証券報告書をGeminiで解析
   リスクTOP3 / 堀(Moat) / R&D / 経営陣トーン
        ↓
④ 4軸スコアカードを算出（セクター別閾値）
   Fundamental / Valuation / Technical / Qualitative
        ↓
⑤ 最終判断: BUY / WATCH / SELL
   → Google Sheets + Webダッシュボードに出力
```

---

## 📦 ファイル構成

```
.
├── main.py                    # オーケストレーション＆分析ロジック（Gemini 自動分析）
├── analyze.py                 # GitHub Models API 版（追加 API キー不要）
├── generate_prompt.py         # プロンプト生成 → Claude 等に手動貼り付け用
├── save_claude_result.py      # Claude 回答をダッシュボードに取り込む
├── config.json                # 設定（閾値・セクタープロファイル）
├── data/
│   └── results.json           # 分析結果（自動生成）
├── prompts/                   # 生成されたプロンプト・コンテキスト保存先
│   ├── 7203_T_YYYYMMDD.txt    # 生成プロンプト
│   └── 7203_T_context.json    # スコアカード等コンテキスト（save_claude_result.py が参照）
├── src/                       # コアモジュール群
│   ├── data_fetcher.py        # 株価・財務データ取得 + Gemini/Groq API 呼び出し
│   ├── analyzers.py           # 4軸スコアカード生成
│   ├── edinet_client.py       # EDINET 有報取得（日本株）
│   ├── sec_client.py          # SEC 10-K/10-Q 取得（米国株）
│   ├── macro_regime.py        # マクロ環境レジーム判定
│   └── copilot_client.py      # GitHub Models API クライアント
├── web/                       # ダッシュボード UI
├── requirements.txt
├── .env.example
└── AGENTS.md                  # エージェント作業ルール
```

---

## 🚀 セットアップ

### 1. 依存パッケージをインストール

```bash
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
SPREADSHEET_ID=your_spreadsheet_id
GOOGLE_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}'
```

| キー | 取得先 |
|------|--------|
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/) |
| `EDINET_API_KEY` | [EDINET API](https://disclosure2dl.edinet-fsa.go.jp/) |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | [Google Cloud Console](https://console.cloud.google.com/) |

---

## 💻 使い方

### 🥇 推奨: Claude Sonnet で分析（高精度・半自動）

データ収集・プロンプト生成・結果保存は自動。Claude への貼り付けのみ手動。

```bash
# Step 1: プロンプト生成（スコアカード・財務・テクニカルを自動収集）
./venv/bin/python3 generate_prompt.py 7203.T --copy
# → プロンプトがクリップボードにコピー、prompts/7203_T_context.json も自動保存

# Step 2: 【手動】Claude Sonnet (copilot.github.com 等) に貼り付け → 回答全体をコピー

# Step 3: 回答をダッシュボードに自動保存
./venv/bin/python3 save_claude_result.py 7203.T --from-clipboard
# → data/results.json に追記（signal / entry / stop / take_profit / risks 等）
```

**オプション:**

```bash
# 最新データで再取得（キャッシュ無効）
./venv/bin/python3 generate_prompt.py 7203.T --copy --no-cache

# 回答をファイルから読み込む
./venv/bin/python3 save_claude_result.py 7203.T --from-file response.txt

# モデル名を記録（デフォルト: claude-sonnet）
./venv/bin/python3 save_claude_result.py 7203.T --from-clipboard --model claude-sonnet-4-5
```

---

### 🤖 完全自動: Gemini / Groq で分析

```bash
# Gemini 使用（デフォルト）
./venv/bin/python3 main.py 7203.T

# 複数銘柄
./venv/bin/python3 main.py 7203.T 8306.T AAPL
```

---

### 🆕 analyze.py（GitHub Models API 版 — 追加 API キー不要）

`gh auth login` で GitHub にログイン済みであれば、追加の API キーなしで実行できます。

```bash
# 基本（gpt-4o で分析）
./venv/bin/python3 analyze.py AMAT

# 日本株
./venv/bin/python3 analyze.py 7203.T

# 高速モード（gpt-4o-mini）
./venv/bin/python3 analyze.py XOM --model gpt-4o-mini

# キャッシュなし（最新データ）
./venv/bin/python3 analyze.py NVDA --no-cache

# レポートのコピー先を指定
./venv/bin/python3 analyze.py AMAT -o ~/Desktop/amat_report.md
```

レポートは `data/reports/YYYYMM/TICKER_date.md` に自動保存されます。

**利用可能モデル（`--model`）:**

| 略称 | 正式名称 | 特徴 |
|------|---------|------|
| `gpt-4o` | GPT-4o | 高品質・推奨（デフォルト） |
| `gpt-4o-mini` | GPT-4o-mini | 高速・低コスト |
| `llama405b` | Meta-Llama-3.1-405B-Instruct | オープンソース高性能 |
| `llama70b` | Meta-Llama-3.1-70B-Instruct | バランス型 |
| `mistral` | Mistral-large-2407 | Mistral 系 |

> **注意**: GitHub Models API では現時点で Claude Sonnet は利用不可。
> プロンプトのみ生成して手動でコピペする場合は `generate_prompt.py` を使用。

### プロンプト生成のみ（手動貼り付け用・旧フロー）

```bash
# プロンプト生成 → ファイル保存
./venv/bin/python3 generate_prompt.py AMAT -o prompt.txt
```

> **推奨**: `--copy` フラグ + `save_claude_result.py` を使う新フローの方がシステマチック（上記参照）。

### main.py（Gemini / GitHub Models 切り替え版）

```bash
# Gemini 使用（デフォルト）
./venv/bin/python3 main.py 7203.T

# GitHub Models (gpt-4o) に切り替え
./venv/bin/python3 main.py AMAT --engine copilot

# 複数銘柄
./venv/bin/python3 main.py 7203.T 8306.T AAPL
```

### ダッシュボードを表示

```bash
python serve.py
```

ブラウザが自動で `http://localhost:8080` を開きます。

---

## 📊 4軸スコアカード

| 軸 | 内容 | 主要指標 |
|----|------|----------|
| **Fundamental** | 企業の地力 | ROE, 営業利益率, 自己資本比率 |
| **Valuation** | 割安度 | PER, PBR, 配当利回り, 目標株価乖離 |
| **Technical** | タイミング | RSI, MA乖離率, BB位置, ボラティリティ |
| **Qualitative** | 定性分析 | 有報リスク, 堀(Moat), R&D, 経営陣トーン |

スコアはセクター別に閾値が自動調整されます（High-Growth / Value / Financial）。

---

## ⚙️ カスタマイズ

`config.json` で挙動を変更できます：

```json
{
  "signals": {
    "BUY":   {"min_score": 7},
    "SELL":  {"max_score": 3}
  },
  "sector_profiles": {
    "high_growth": {
      "sectors": ["Technology", "Healthcare"],
      "fundamental": {"roe_good": 15},
      "valuation": {"per_cheap": 25}
    }
  }
}
```

---

## 🔒 GitHub Secretsの設定

| Secret名 | 内容 |
|----------|------|
| `GEMINI_API_KEY` | Gemini APIキー |
| `EDINET_API_KEY` | EDINET APIキー |
| `SPREADSHEET_ID` | Google SheetsのID |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | サービスアカウントJSON |

---

## ⚠️ 免責事項

このシステムは投資判断の参考情報を提供するものです。投資は自己責任で行ってください。

---

## 📝 License

MIT
