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
│   ├── strategies.py          # BounceStrategy / BreakoutStrategy（スコアリングモード対応）
│   ├── macro_regime.py        # マクロ環境レジーム判定（TTLキャッシュ）
│   ├── dcf_model.py           # DCF理論株価（正式WACC・PITフィルタ）
│   ├── edinet_client.py       # EDINET 有報取得（日本株）
│   ├── edinetdb_client.py     # EDINET DB API（財務健全性・AI分析、日本株）
│   ├── jquants_client.py      # J-Quants V2 東証公式OHLC株価（日本株）
│   ├── sec_client.py          # SEC 10-K/10-Q 取得（米国株）
│   ├── news_fetcher.py        # ニュース取得（yfinance + Exa/Perplexity/Tavily）
│   ├── investment_judgment.py # API / ツールベース投資判断エンジン
│   ├── backtester.py          # バックテスト（PIT・モンテカルロ・ローリング）
│   ├── backtest_reporter.py   # バックテスト結果→LLMフィードバックプロンプト生成 (P1/P2/P3)
│   ├── llm_strategy_optimizer.py # LLMによる戦略パラメータ反復最適化
│   ├── portfolio.py           # ポジションサイジング・セクター集中度チェック
│   ├── notion_writer.py       # Notion API 書き込み
│   ├── copilot_client.py      # GitHub Models API クライアント（GPT-4o）
│   └── parallel_utils.py      # 複数銘柄並列データ取得
├── scripts/                   # 検証・デバッグ・最適化スクリプト
│   ├── optimize_strategy.py           # LLM戦略最適化 CLI（論文フレームワーク実装）
│   └── apply_optimization_results.py  # 最適化結果を config.json に自動反映
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

### ☁️ Streamlit Cloud にデプロイした場合

`.env` ファイルはリポジトリに含まれません。Streamlit Cloud では **Settings → Secrets** に以下の TOML を設定してください。

```toml
# 必須
GEMINI_API_KEY = "AIza..."

# 日本株の完全版プロンプト生成に必要
EDINET_API_KEY     = "..."       # 有報 PDF（未設定→有報セクションなし）
EXA_API_KEY        = "..."       # Webニュース（未設定→ニュースセクションなし）

# 任意
ANTHROPIC_API_KEY  = "..."       # Claude API
JQUANTS_API_KEY    = "..."       # 東証公式OHLC
EDINETDB_API_KEY   = "..."       # 有報DB + AI分析
FINNHUB_API_KEY    = "..."       # 米国株ニュース
PERPLEXITY_API_KEY = "..."       # Webニュース fallback
TAVILY_API_KEY     = "..."       # Webニュース fallback
NOTION_API_KEY     = "..."
NOTION_DATABASE_ID = "..."
SPREADSHEET_ID     = "..."
GOOGLE_SERVICE_ACCOUNT_JSON = '{"type":"service_account",...}'
LINE_CHANNEL_ACCESS_TOKEN = "..."
LINE_USER_ID = "..."
```

> **診断ヒント**: Prompt Studio ページの「🩺 環境診断」ボタンを押すと、
> 現在の Cloud 環境でどの API キーが設定済みかを確認できます。
>
> CLI でも確認可能：
> ```bash
> ./venv/bin/python3 generate_prompt.py --check-env
> ```

#### ⚠️ 簡易プロンプトにフォールバックした場合

Streamlit Cloud で `--check-env` を実行しても API キーに問題がないのに「データ取得に失敗したため簡易プロンプトが生成されました」と表示される場合、 **「📊 データ取得ログ」が自動展開** され、原因が以下のプレフィックスで表示されます。

| ログプレフィックス | 意味 |
|---|---|
| `[FALLBACK_REASON]` | フォールバック理由（metrics 件数不足・例外） |
| `[DATA_ERROR]` | `fetch_stock_data` の例外メッセージ |
| `[DATA_ERROR_DETAIL]` | トレースバック末尾（詳細） |
| `[FETCH_TRACEBACK]` | fetch_stock_data 呼び出し時の完全トレースバック |

典型的な原因と対処：

| 原因 | 対処 |
|---|---|
| yfinance レート制限 / 403 | 数分待って再試行、またはキャッシュ利用 |
| yfinance ネットワーク不通 | Streamlit Cloud の外部通信制限を確認 |
| `metrics=0件, technical=0件` | ティッカーシンボルが正しいか確認（日本株は `.T` 付き） |

---

### 🔄 バックテスト

```bash
# 例: トヨタ (7203.T) を 2024年1月から12ヶ月シミュレーション
python3 -m src.backtester --ticker 7203.T --start 2024-01-01 --months 12

# ローリングバックテスト（Walk-Forward）
python3 -m src.backtester --ticker 7203.T --start 2023-01-01 --months 24 --rolling --window-months 12
```

---

### 🤖 LLM戦略最適化（論文ベース）

バックテスト結果を LLM に渡し、エントリー/エグジット条件のパラメータを反復改善します。
論文「大規模言語モデルを用いた株式投資戦略の自動生成におけるフィードバック設計」の
フレームワークを実装しています。

**モデル性能（論文実験結果）:**
| モデル | 平均P&L改善 | 特性 |
|--------|------------|------|
| Claude Sonnet | **+14.1%** | 漸進的・安定改善（推奨） |
| Gemini | +7.3% | 探索的・高分散 |
| GPT-4o | -0.3% | 保守的・変更少 |

```bash
# 事前確認（DRY RUN: 設定は変更されない）
./venv/bin/python3 scripts/optimize_strategy.py \
  --ticker 8035.T --strategy bounce --dry-run

# 最適化を実行（デフォルト: Claude, P1フィードバック, 5回反復）
./venv/bin/python3 scripts/optimize_strategy.py \
  --ticker 8035.T --strategy bounce \
  --start 2023-01-01 --months 12

# 30 iter 設計（ConvergenceMonitor で自動早期打ち切りあり）
./venv/bin/python3 scripts/optimize_strategy.py \
  --ticker AMAT --strategy bounce --max-iter 30 --level P2

# Gemini で実行（Claude APIキーなしの場合）
./venv/bin/python3 scripts/optimize_strategy.py \
  --ticker 7203.T --strategy breakout --model gemini

# プロット付きフィードバック（P3: レジーム適応性改善に有効）
./venv/bin/python3 scripts/optimize_strategy.py \
  --ticker AAPL --strategy bounce --level P3 --max-iter 5

# モデル比較実験（Claude vs Gemini vs GPT-4o を同条件で比較）
./venv/bin/python3 scripts/optimize_strategy.py \
  --ticker 8035.T --strategy bounce --compare-models --dry-run

# グループ一括最適化（TICKER_GROUPS 定義の全銘柄を順番に処理）
./venv/bin/python3 scripts/optimize_strategy.py \
  --group JP_semiconductor --level P2  # 30iter × 2銘柄
./venv/bin/python3 scripts/optimize_strategy.py \
  --group US_semiconductor --level P2  # 30iter × 2銘柄（FED/DXY/VIXレジーム使用）
```

**利用可能なグループ (`--group`):**
| グループ名 | 銘柄 | 戦略 | iter | 備考 |
|-----------|------|------|------|------|
| `JP_semiconductor` | 8035.T, 6857.T | bounce | 30 | YEN_STRONG 逆風対策 |
| `JP_trading` | 8053.T, 8058.T | breakout | 15 | ベースラインが強い |
| `JP_financial` | 8306.T, 8316.T | bounce | 30 | BOJ_HIKE 除外済み |
| `US_semiconductor` | AMAT, LRCX | bounce | 30 | USレジーム v2 (FED/DXY/VIX) |
| `US_energy` | XOM, CVX | breakout | 20 | USレジーム v2 必須 |

**フィードバックレベル:**
| レベル | 内容 | 推奨場面 |
|--------|------|--------|
| `P1` | 基本指標（Sharpe/MDD/勝率/レジーム別損益） | 初回・通常運用 |
| `P2` | P1 + エグジット理由別内訳 | トレード品質改善時 |
| `P3` | P2 + 損益曲線プロット | レジーム適応性改善時 |

最適化結果は `data/optimization/{ticker}_{strategy}_{date}.json` に自動保存されます。

**最適化結果の config.json への自動反映:**

```bash
# 差分確認（config.json は変更されない）
./venv/bin/python3 scripts/apply_optimization_results.py --dry-run

# 全銘柄の最良結果を反映
./venv/bin/python3 scripts/apply_optimization_results.py

# 特定銘柄のみ反映
./venv/bin/python3 scripts/apply_optimization_results.py --ticker 8035.T AMAT
```

> **注意:** Claude を使う場合は `ANTHROPIC_API_KEY` を `.env` に設定してください。
> 未設定の場合は Gemini → GitHub Models (GPT-4o) の順でフォールバックします。

---

### 💼 保有銘柄台帳（ポートフォリオ管理）

`data/portfolio.json` に保有銘柄を登録すると、プロンプトに「保有中: 100株 @¥2,450」が自動挿入されます。

```bash
# 銘柄を追加
./venv/bin/python3 portfolio_manager.py add 8306.T --qty 100 --price 2450 --notes "長期保有"
./venv/bin/python3 portfolio_manager.py add AAPL   --qty 50  --price 185.5 --currency USD

# 一覧表示（現在価格・含損益付き）
./venv/bin/python3 portfolio_manager.py list

# 詳細表示 / 削除
./venv/bin/python3 portfolio_manager.py show 8306.T
./venv/bin/python3 portfolio_manager.py remove 8306.T
```

`data/portfolio.json` は `.gitignore` 対象です（個人情報保護）。

---

### 🎯 予測 vs 実績 トラッキング

分析から 30/90/180 日後に実際の株価と照合して精度を測定します。

```bash
# 全銘柄・全ウィンドウを確認（書き込みあり）
./venv/bin/python3 verify_predictions.py

# 特定銘柄のみ
./venv/bin/python3 verify_predictions.py --ticker 8306.T --window 30

# 現在の精度統計を表示
./venv/bin/python3 verify_predictions.py --stats

# 書き込みなしで確認のみ
./venv/bin/python3 verify_predictions.py --dry-run
```

ダッシュボードの銘柄詳細画面に「予測精度」セクション（勝率・平均リターン）が表示されます。

---

### 🔔 LINE Notify アラート

損切りライン接近・シグナル変化・スコア急落を LINE Notify で通知します。

**事前準備:**
1. [LINE Notify](https://notify-bot.line.me/my/) でトークンを発行
2. `.env` に `LINE_NOTIFY_TOKEN=<your_token>` を追記

```bash
# 手動実行（確認のみ）
./venv/bin/python3 alert_check.py --dry-run

# 実行（通知あり）
./venv/bin/python3 alert_check.py

# 特定銘柄のみ
./venv/bin/python3 alert_check.py --ticker 8306.T
```

**cron で毎朝8時に自動実行:**
```bash
# crontab -e で以下を追記
0 8 * * * cd ~/projects/stock_analyze && ./venv/bin/python3 alert_check.py >> data/alert.log 2>&1
```

**トリガー条件:**
| トリガー | 条件 |
|----------|------|
| 損切りライン接近 | 現在価格が `stop_loss` の +3% 以内 |
| シグナル変化 | 前回分析から BUY/WATCH/SELL が変化 |
| スコア急落 | 前回比 -1.5 以上のスコア低下 |

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
