# システム設計メモ

この文書は、現行コードで確認できた主要ユースケースを設計観点で簡潔にまとめたものです。

## 1. 総合分析フロー

対象: `main.py`

1. ティッカー入力を正規化
2. 市場データ取得 (`src/data_fetcher.py`)
3. 競合銘柄の選定
4. 日本株なら EDINET、米国株なら SEC を補助情報として取得
5. 4軸スコアカードとマクロレジームを生成
6. LLM 向けレポート本文を組み立て
7. Markdown / `data/results.json` / 任意のNotionへ保存

設計上の要点:

- `config.json` がシグナル閾値、戦略パラメータ、ティッカー別上書きの中心
- 総合スコアは `src/analyzers.py` と `config.json` に強く依存
- `data/results.json` は履歴の中心で、検証・通知・UI の共通入力でもある

## 2. 外部LLM連携フロー

対象: `generate_prompt.py`, `save_claude_result.py`, `pages/01_prompt_studio.py`

1. `generate_prompt.py` がプロンプトと context JSON を生成
2. ユーザーが Claude 等へ貼り付け
3. `save_claude_result.py` が回答から JSON を抽出
4. `signal` や `score` を `data/results.json` に反映
5. Notion 設定済みなら追加保存

設計上の要点:

- Prompt Studio は上記フローのUIラッパー
- `*_context.json` があると、回答保存時にローカルのスコアや価格情報を補完できる

## 3. GitHub Models 分析フロー

対象: `analyze.py`, `src/copilot_client.py`

1. 最小限のデータ収集とプロンプト生成
2. `gh auth token` で GitHub Models API を呼び出し
3. 返却テキストから JSON シグナルを抽出
4. Markdown レポートを保存

設計上の要点:

- 利用モデルは `src/copilot_client.py` の別名定義に依存
- 追加APIキーではなく GitHub CLI 認証を前提にしている

## 4. バックテストと改善フロー

対象: `src/backtester.py`, `scripts/optimize_strategy.py`, `verify_predictions.py`, `src/weight_optimizer.py`

1. `src/backtester.py` で戦略ごとのシミュレーション
2. `scripts/optimize_strategy.py` で LLM に改善提案を依頼
3. `scripts/apply_optimization_results.py` で `config.json` へ反映
4. `verify_predictions.py` で実運用結果を検証
5. `src/weight_optimizer.py` で重み再調整

設計上の要点:

- 検証フローは `data/results.json` と `data/accuracy_history.json` を共有ストアとして使う
- 設定変更の最終反映先は `config.json`

## 5. 通知フロー

対象: `alert_check.py`, `src/notifier.py`

- `alert_check.py` は `data/results.json` と `data/portfolio.json` を参照して LINE Notify を送信
- `app.py` には LINE Messaging API のテスト送信導線がある

## 6. 現在の注意点

- `portfolio_manager.py` は設計上は保有銘柄台帳CLIだが、現スナップショットでは構文エラーがある
- 一部の詳細設計書は履歴重視で古い記述を含むため、最新導線は `README.md` と `docs/how_to_use.md` を優先する
