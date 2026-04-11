# ドキュメント索引

現行コードと照合して、存在する文書だけを整理した索引です。

## 最初に読むもの

| ファイル | 用途 |
| --- | --- |
| `../README.md` | プロジェクト全体の入口 |
| `how_to_use.md` | 実行手順の詳細 |
| `architecture.md` | モジュールとデータの流れ |

## 全体理解

| ファイル | 内容 |
| --- | --- |
| `system_design.md` | 主要ユースケースごとの設計観点 |
| `spec.md` | AI/開発者向けの実装リファレンス |
| `CHANGELOG.md` | 変更履歴 |

## 機能別の詳細資料

| ファイル | 内容 |
| --- | --- |
| `investment_judgment_guide.md` | BUY/WATCH/SELL やスコアの読み方 |
| `YUHO_SYSTEM_DESIGN.md` | EDINET/SEC 周辺の詳細設計 |
| `feedback-loop.md` | 予測精度フィードバックと重み最適化 |

## QA・テスト

| ファイル | 内容 |
| --- | --- |
| `qa_report.md` | 8カテゴリ56件のQAテスト項目（実行前レビュー） |

## 読み分けの目安

| 目的 | 推奨ドキュメント |
| --- | --- |
| まず動かしたい | `../README.md` → `how_to_use.md` |
| 入口スクリプトを把握したい | `architecture.md` |
| 主要フローを理解したい | `system_design.md` |
| AIエージェント向けに構造を確認したい | `spec.md` |
| 投資判断の見方を知りたい | `investment_judgment_guide.md` |
| テスト項目・リスク確認 | `qa_report.md` |
