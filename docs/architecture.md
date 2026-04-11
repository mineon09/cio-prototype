# アーキテクチャ概要

この文書は、現行リポジトリにある入口スクリプトと `src/` モジュールの関係を実装ベースで要約したものです。

## 全体像

```text
CLI / UI
├── main.py
├── analyze.py
├── generate_prompt.py
├── save_claude_result.py
├── verify_predictions.py
├── alert_check.py
├── app.py
└── pages/01_prompt_studio.py

Core modules
├── src/data_fetcher.py       # 市場データ取得・競合選定・Gemini/Groq呼び出し
├── src/analyzers.py          # 4軸スコアカード
├── src/strategies.py         # long / bounce / breakout の判定
├── src/macro_regime.py       # レジーム判定
├── src/dcf_model.py          # DCF理論株価
├── src/news_fetcher.py       # ニュース収集と要約用整形
├── src/edinet_client.py      # 日本株のEDINET取得
├── src/sec_client.py         # 米国株のSEC取得
├── src/investment_judgment.py# API/ルール/デュアル判断エンジン
├── src/backtester.py         # バックテスト
├── src/weight_optimizer.py   # 精度フィードバックによる重み最適化
├── src/copilot_client.py     # GitHub Models API
├── src/notion_writer.py      # Notion保存
└── src/md_writer.py          # Markdown保存

Outputs
├── data/results.json
├── data/reports/YYYYMM/*.md
├── prompts/*.txt
├── prompts/*_context.json
└── data/optimization/*.json
```

## 主な処理フロー

### 1. `main.py` の総合分析

```text
ticker
  ↓
src/data_fetcher.fetch_stock_data()
  ↓
src/data_fetcher.select_competitors()
  ↓
src/edinet_client または src/sec_client
  ↓
src/analyzers.generate_scorecard()
  ↓
src/macro_regime.detect_regime()
  ↓
main.analyze_all()
  ↓
src/md_writer / data/results.json / src/notion_writer
```

### 2. `generate_prompt.py` → `save_claude_result.py`

```text
generate_prompt.py
  ├── prompts/<timestamp>.txt
  └── prompts/<ticker>_context.json
          ↓
Claude 等へ貼り付け
          ↓
save_claude_result.py
  ├── JSON 抽出
  ├── signal 正規化
  ├── data/results.json 更新
  └── 任意で Notion 保存
```

### 3. `analyze.py` のGitHub Models分析

```text
collect_data_minimal() / build_high_quality_prompt()
  ↓
src/copilot_client.call_github_models()
  ↓
JSON シグナル抽出
  ↓
src/md_writer.write_to_md()
```

### 4. 検証と改善ループ

```text
data/results.json
  ↓
verify_predictions.py
  ├── verified_30d / 90d / 180d を付与
  └── data/accuracy_history.json を更新
          ↓
src/weight_optimizer.py
          ↓
scripts/optimize_strategy.py
          ↓
scripts/apply_optimization_results.py -> config.json
```

## モジュール責務

| レイヤ | 代表ファイル | 役割 |
| --- | --- | --- |
| Entry points | `main.py`, `app.py`, `analyze.py` | 実行導線 |
| Data collection | `src/data_fetcher.py`, `src/news_fetcher.py`, `src/edinet_client.py`, `src/sec_client.py` | 市場データ・定性情報の取得 |
| Analysis | `src/analyzers.py`, `src/dcf_model.py`, `src/macro_regime.py`, `src/investment_judgment.py` | スコアリングと判断 |
| Strategy / validation | `src/strategies.py`, `src/backtester.py`, `verify_predictions.py`, `src/weight_optimizer.py` | 売買ルール、検証、改善 |
| Output / integration | `src/md_writer.py`, `src/notion_writer.py`, `src/copilot_client.py`, `alert_check.py` | 保存・外部連携・通知 |

## 外部サービス

| 種別 | 実装で確認できた利用先 |
| --- | --- |
| 相場データ | yfinance, J-Quants |
| 日本株開示 | EDINET, EDINET DB |
| 米国株開示 | SEC EDGAR |
| LLM | Gemini, Groq, Anthropic, GitHub Models |
| ニュース/検索 | Google News RSS, Finnhub, Exa, Perplexity, Tavily |
| 通知/保存 | Notion, LINE Notify, LINE Messaging API |

## ストレージ

| パス | 役割 |
| --- | --- |
| `config.json` | 閾値、戦略パラメータ、ティッカー別上書き |
| `data/results.json` | 分析履歴の中心 |
| `data/reports/` | Markdownレポート |
| `data/optimization/` | 最適化結果 |
| `prompts/` | 外部LLM向け生成物 |
| `cache/`, `.edinet_cache/` | 各種キャッシュ |

## 補足

- `main.py` と `app.py` は `run_strategy_analysis()` など一部ロジックを共有します。
- GitHub Models 経路は `gh auth token` を利用するため、事前に `gh auth login` が必要です。
- `portfolio_manager.py` は台帳CLIの意図を持つものの、現スナップショットでは構文エラーがあり実行不能です。
