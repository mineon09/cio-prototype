# 実装リファレンス

このファイルは、現行リポジトリに存在する主要ファイルとその役割を、AI/開発者向けに簡潔に整理した参照資料です。

## 1. プロジェクトの目的

単一ティッカーを起点に、株価・財務・ニュース・開示資料・戦略ロジックを組み合わせて投資分析を行う。主な成果物は `BUY / WATCH / SELL`、補助価格帯、説明テキスト、履歴データ。

## 2. 主要エントリーポイント

| ファイル | 役割 | 確認できた主な引数 |
| --- | --- | --- |
| `main.py` | 総合分析オーケストレーター | `--ticker`, `--strategy`, `--engine` |
| `app.py` | Streamlit ダッシュボード | 引数なし |
| `generate_prompt.py` | 外部LLM用プロンプト生成 | `--copy`, `--simple`, `--no-qualitative`, `--no-cache`, `--check-env`, `--model` |
| `save_claude_result.py` | Claude等の回答保存 | `--from-clipboard`, `--from-file`, `--model` |
| `analyze.py` | GitHub Models 分析 | `--model`, `--no-cache`, `--output`, `--list-models` |
| `verify_predictions.py` | 予測検証 | `--ticker`, `--window`, `--dry-run`, `--stats`, `--update-weights`, `--model` |
| `alert_check.py` | LINE Notify アラート | `--ticker`, `--dry-run`, `--all` |
| `scripts/optimize_strategy.py` | 戦略最適化 | `--ticker`, `--strategy`, `--group`, `--model`, `--level`, `--max-iter`, `--compare-models` |
| `scripts/apply_optimization_results.py` | 最適化結果の反映 | `--result-dir`, `--config`, `--ticker`, `--dry-run` |
| `src/backtester.py` | バックテストCLI | `--ticker`, `--strategy`, `--days`, `--start`, `--months`, `--rolling` |
| `src/weight_optimizer.py` | 重み最適化CLI | `--sector`, `--window`, `--model`, `--dry-run` |

## 3. ディレクトリマップ

```text
src/      コアロジック
scripts/  運用・最適化補助
pages/    Streamlit マルチページ
tests/    単体テスト群
docs/     ドキュメント
data/     結果・検証・最適化出力
prompts/  生成プロンプトと context JSON
cache/    SEC 解析などのキャッシュ
```

## 4. `src/` の主要モジュール

| ファイル | 役割 |
| --- | --- |
| `src/data_fetcher.py` | 株価/財務データ取得、Gemini/Groq呼び出し、競合選定 |
| `src/analyzers.py` | 4軸スコアカード生成、セクタープロファイル解決 |
| `src/strategies.py` | `long / bounce / breakout` 戦略ロジック |
| `src/macro_regime.py` | 市場レジーム判定 |
| `src/dcf_model.py` | DCF理論株価 |
| `src/news_fetcher.py` | RSS/API/検索系ニュース収集 |
| `src/edinet_client.py` | EDINET 取得 |
| `src/edinetdb_client.py` | EDINET DB API 補助 |
| `src/jquants_client.py` | J-Quants 取得 |
| `src/sec_client.py` | SEC 取得 |
| `src/sec_parser.py` | SEC本文のセクション抽出 |
| `src/investment_judgment.py` | API / Tool / Dual の投資判断エンジン |
| `src/backtester.py` | バックテスト実行 |
| `src/backtest_reporter.py` | バックテスト結果の要約 |
| `src/llm_strategy_optimizer.py` | LLM による戦略改善ロジック |
| `src/weight_optimizer.py` | 検証結果に基づく重み改善 |
| `src/copilot_client.py` | GitHub Models API クライアント |
| `src/notion_writer.py` | Notion DB 保存 |
| `src/notifier.py` | LINE Messaging API 補助 |
| `src/parallel_utils.py` | 並列処理ユーティリティ |

## 5. データと保存先

| パス | 内容 |
| --- | --- |
| `config.json` | 閾値・戦略・ティッカー別 override |
| `data/results.json` | 分析履歴の中心 |
| `data/reports/YYYYMM/` | Markdown レポート |
| `data/optimization/` | 戦略最適化結果 |
| `data/accuracy_history.json` | 精度履歴 |
| `prompts/*.txt` | 外部LLM用プロンプト |
| `prompts/*_context.json` | 回答保存用コンテキスト |

## 6. 外部サービス

| 種別 | 実装で確認した利用先 |
| --- | --- |
| 相場データ | yfinance, J-Quants |
| 開示資料 | EDINET, EDINET DB, SEC EDGAR |
| LLM | Gemini, Groq, Anthropic, GitHub Models |
| ニュース/検索 | Google News RSS, Finnhub, Exa, Perplexity, Tavily |
| 保存/通知 | Notion, LINE Notify, LINE Messaging API |

## 7. 代表的な環境変数

| キー | 用途 |
| --- | --- |
| `GEMINI_API_KEY` | 総合分析やプロンプト生成の主経路 |
| `ANTHROPIC_API_KEY` | Claude 系最適化 |
| `SEC_USER_AGENT` | SEC 取得 |
| `EDINET_API_KEY` | 日本株開示取得 |
| `FINNHUB_KEY` | 米国株ニュース/フォールバック |
| `NOTION_API_KEY`, `NOTION_DATABASE_ID` | Notion 保存 |
| `LINE_NOTIFY_TOKEN` | LINE Notify |
| `LINE_CHANNEL_ACCESS_TOKEN`, `LINE_USER_ID` | LINE Messaging API |

## 8. テスト

`tests/` には、以下のような単体テストがあることを確認済みです。

- `test_analyzers.py`
- `test_data_fetcher.py`
- `test_dcf_model.py`
- `test_investment_judgment.py`
- `test_strategies.py`
- `test_weight_optimizer.py`
- `test_save_claude_result.py`
- `test_select_competitors.py`

## 9. 現時点の注意点

- `portfolio_manager.py` は保有銘柄台帳CLIの実装を含むが、現スナップショットでは構文エラーがあり実行できない。
- `.gignore` は存在せず、除外設定は `.gitignore`。
