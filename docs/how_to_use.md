# 操作ガイド

このガイドは、現行コードに存在する入口スクリプトとStreamlit UIを中心に、日常利用の導線をまとめたものです。

## 事前準備

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
cp .env.example .env
```

用途ごとの前提:

| 用途 | 前提 |
| --- | --- |
| `main.py` の標準運用 | `GEMINI_API_KEY` |
| 米国株のSEC取得 | `SEC_USER_AGENT` |
| GitHub Models系 (`analyze.py` など) | `gh auth login` |
| Claude最適化 | `ANTHROPIC_API_KEY` |
| Notion連携 | `NOTION_API_KEY`, `NOTION_DATABASE_ID` |
| LINE Notify | `LINE_NOTIFY_TOKEN` |

## 1. 総合分析をCLIで回す

`main.py` が最上位のオーケストレーターです。ティッカーは位置引数でも `--ticker` でも渡せます。

```bash
./venv/bin/python3 main.py 7203.T
./venv/bin/python3 main.py 7203.T 8306.T AAPL
./venv/bin/python3 main.py --ticker AAPL --strategy breakout
./venv/bin/python3 main.py 8035.T --strategy bounce
./venv/bin/python3 main.py AAPL --engine copilot
```

確認できたオプション:

| オプション | 内容 |
| --- | --- |
| `--ticker <code>` | 追加の分析対象を指定 |
| `--strategy <long|bounce|breakout>` | 戦略切替 |
| `--engine <gemini|copilot>` | 最終レポート生成エンジンを切替 |

主な出力:

- Markdownレポート
- `data/results.json`
- Notion（設定されている場合）

## 2. ダッシュボードを使う

```bash
streamlit run app.py
```

`app.py` でできること:

- ティッカー入力からの分析実行
- 戦略切替（`long / bounce / breakout`）
- バックテスト実行
- 履歴の閲覧
- LINE Messaging API の送信テスト
- Prompt Studio への遷移

## 3. Prompt Studio を使う

Streamlit のサイドバー、または直接 `pages/01_prompt_studio.py` を通じて使います。

主な役割:

1. `generate_prompt.py` を裏側で呼び出してプロンプト生成
2. 生成結果のコピー補助
3. Claude等の回答を `save_claude_result.py` 経由で保存
4. 生成ログと診断ログの確認

## 4. 外部LLM向けプロンプトを生成する

```bash
./venv/bin/python3 generate_prompt.py 7203.T
./venv/bin/python3 generate_prompt.py 7203.T --copy
./venv/bin/python3 generate_prompt.py AAPL --simple
./venv/bin/python3 generate_prompt.py 8306.T --no-qualitative
./venv/bin/python3 generate_prompt.py 7203.T --no-cache
./venv/bin/python3 generate_prompt.py --check-env
```

確認できたオプション:

| オプション | 内容 |
| --- | --- |
| `-o, --output` | 出力先を指定 |
| `--copy` | クリップボードへコピー |
| `--simple` | データ取得なしの簡易プロンプト |
| `--no-qualitative` | ニュース/アナリスト/業界動向を省略 |
| `--no-cache` | キャッシュを使わず再取得 |
| `--check-env` | APIキー状態を診断して終了 |
| `--model <gemini|qwen|chatgpt|claude|groq>` | 対象モデルラベル |

保存物:

- `prompts/*.txt`
- `prompts/*_context.json`（`--simple` 以外）

## 5. Claude等の回答を履歴へ保存する

```bash
./venv/bin/python3 save_claude_result.py 7203.T --from-clipboard
./venv/bin/python3 save_claude_result.py AAPL --from-file response.txt
cat response.txt | ./venv/bin/python3 save_claude_result.py AMAT
```

ポイント:

- 先に `generate_prompt.py` で `*_context.json` を作っておくと、スコアカードやテクニカル情報も一緒に保存されます。
- 応答中の JSON ブロックから `signal / score / entry_price` などを抽出します。
- `HOLD` は内部で `WATCH` に正規化されます。
- `NOTION_API_KEY` と `NOTION_DATABASE_ID` があれば Notion 保存も試行します。

## 6. GitHub Models API で一気通貫分析する

```bash
./venv/bin/python3 analyze.py AMAT
./venv/bin/python3 analyze.py 7203.T --model gpt-4o-mini
./venv/bin/python3 analyze.py XOM --no-cache
./venv/bin/python3 analyze.py NVDA -o my_report.md
./venv/bin/python3 analyze.py --list-models
```

確認できたモデル別名:

- `gpt-4o`
- `gpt-4o-mini`
- `llama405b`
- `llama70b`
- `mistral`

`analyze.py` は `generate_prompt.py` のロジックを再利用し、分析結果を Markdown に保存します。

## 7. バックテストを実行する

```bash
./venv/bin/python3 -m src.backtester --ticker 7203.T --strategy long --start 2024-01-01 --months 12
./venv/bin/python3 -m src.backtester --ticker 7203.T --strategy bounce --rolling --window-months 12 --step-months 3
```

確認できた主要オプション:

| オプション | 内容 |
| --- | --- |
| `--ticker` | 対象ティッカー |
| `--strategy` | `long / bounce / breakout` |
| `--days`, `--start`, `--months` | 期間指定 |
| `--rolling` | ローリングバックテスト |
| `--window-months`, `--step-months` | ローリング設定 |
| `--rsi-threshold`, `--volume-multiplier`, `--entry-price-ma` | 戦略パラメータ上書き |

## 8. 戦略最適化を回す

```bash
./venv/bin/python3 scripts/optimize_strategy.py --ticker 8035.T --strategy bounce --dry-run
./venv/bin/python3 scripts/optimize_strategy.py --ticker AAPL --strategy breakout --model gpt-4o
./venv/bin/python3 scripts/optimize_strategy.py --group JP_financial --level P2
./venv/bin/python3 scripts/optimize_strategy.py --ticker 8035.T --strategy bounce --compare-models
```

関連コマンド:

```bash
./venv/bin/python3 scripts/apply_optimization_results.py --dry-run
./venv/bin/python3 scripts/apply_optimization_results.py --ticker 8035.T AMAT
```

`scripts/optimize_strategy.py` は結果JSONを保存し、`scripts/apply_optimization_results.py` が `config.json` に反映します。

## 9. 予測精度と重み調整を回す

```bash
./venv/bin/python3 verify_predictions.py
./venv/bin/python3 verify_predictions.py --ticker 8306.T --window 30
./venv/bin/python3 verify_predictions.py --stats
./venv/bin/python3 verify_predictions.py --dry-run
./venv/bin/python3 verify_predictions.py --update-weights --model claude
./venv/bin/python3 src/weight_optimizer.py --dry-run
```

`verify_predictions.py` は `data/results.json` を更新し、必要に応じて `data/accuracy_history.json` を蓄積します。

## 10. アラートを送る

```bash
./venv/bin/python3 alert_check.py --dry-run
./venv/bin/python3 alert_check.py
./venv/bin/python3 alert_check.py --ticker 8306.T
./venv/bin/python3 alert_check.py --all
```

トリガーは以下の3種類です。

1. `stop_loss` への接近
2. 直近2回のシグナル変化
3. 直近2回のスコア急落

## 11. 補助スクリプト

| スクリプト | 役割 |
| --- | --- |
| `list_latest_models.py` | Gemini SDK で利用可能モデルを列挙 |
| `get_prompt.py` | AIへ貼り付けるための素材を標準出力に整形 |
| `prompt_builder.py` | プロンプト生成ライブラリ兼CLI |
| `scripts/validate_catalyst_dates.py` | 業界カタリスト日付の検証 |
| `analyze_trades.py` | 既定ティッカーのトレード一覧を書き出す簡易スクリプト |

## 12. 主な保存先

| パス | 内容 |
| --- | --- |
| `data/results.json` | 分析履歴と予測検証 |
| `data/reports/YYYYMM/` | Markdownレポート |
| `prompts/` | 生成プロンプトとコンテキスト |
| `data/optimization/` | 最適化結果JSON |

## 13. 現在の注意点

- `portfolio_manager.py` は台帳CLIの実装を含みますが、現スナップショットでは構文エラーがあり、そのままでは実行できません。
- 除外設定は `.gignore` ではなく `.gitignore` です。
