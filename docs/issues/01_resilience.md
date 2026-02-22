# Issue: 運用堅牢化（リトライ・例外処理・文字化け対策）

## 概要 (Overview)
システムを継続的かつ安定的に運用するため、各種外部API（yfinance, EDINET, LLM）との通信におけるエラーハンドリングを強化し、実行環境における文字化け（エンコーディング起因）の問題を解消する。

## 背景・課題 (Background / Problem)
- 現状、APIの一時的なエラー（HTTP 429 Too Many Requests や 500 Internal Server Error など）でプロセス全体がダウンするリスクがある。
- Windows環境（PowerShell/CMD）やGitHub Actions上での実行時、標準出力やログファイルに文字化けが発生し、原因究明やデータ処理に支障をきたすことがある。
- エラーが発生した際、コンソール出力に留まり、後からスプレッドシート等で状態を確認できない。

## 修正方針 (Proposed Solution)

### 1. 例外ハンドリングと指数のバックオフ (Retry with Exponential Backoff)
- `src/data_fetcher.py`, `src/edinet_client.py` などの通信を行うモジュールにおいて、`try-except`ブロックを導入する。
- 失敗時には `tenacity` などのライブラリ、またはカスタムのデコレータを用いて、指数バックオフによるリトライ処理を実装する。

### 2. 環境のUTF-8強制 (Enforce UTF-8 Encoding)
- PowerShell実行時の指定: `$OutputEncoding = [System.Text.Encoding]::UTF8; [Console]::OutputEncoding = [System.Text.Encoding]::UTF8;`
- CMD実行時の指定: `chcp 65001 > nul`
- Python実行時の指定: 環境変数 `$env:PYTHONUTF8=1` を付与。
- ファイル入出力時: `open(..., encoding='utf-8')` を明示する。
- GitHub Actions の Workflow定義 (`.github/workflows/*.yml`) にも上記コマンドを付与する。

### 3. System_Log シートへの実行ステータス記録
- `src/sheets_writer.py` を改修し、分析ごとの Success/Fail ステータスと、エラー発生時のスタックトレース概要を `System_Log` シートに書き込む機能を実装する。

## タスクリスト (Tasks)
- [ ] `data_fetcher.py` の API 呼び出しにリトライロジックを追加
- [ ] `edinet_client.py` へのリトライロジック追加
- [ ] LLM API 呼び出し部 (`run_and_report.py` 等) へのリトライ追加
- [ ] `sheets_writer.py` に `write_system_log` 関数を実装
- [ ] GitHub Actions ワークフロー (`main.yml`) のエンコーディング設定の修正
- [ ] 既存のファイル入出力 `open()` に `encoding='utf-8'` が指定されているかの全体チェックと修正

## 影響範囲 (Impact)
外部通信を行うすべてのモジュールおよびGitHub Actionsのワークフロー設定。

## 備考 (Notes)
「エラーを握りつぶさない（サイレントフェイルさせない）」ことを念頭に置き、原因究明が容易になるログ設計を行うこと。
