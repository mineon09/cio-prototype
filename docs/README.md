# 株式分析システム ドキュメント索引

**最終更新**: 2026-03-18

---

## 📚 ドキュメント一覧

### 設計書類

| ドキュメント | ファイル | 概要 |
|-------------|----------|------|
| **システム設計書** | `system_design.md` | 全体アーキテクチャとコンポーネント設計 |
| **有報システム設計書** | `docs/YUHO_SYSTEM_DESIGN.md` | 有価証券報告書取得システムの詳細設計（v1.1） |
| **アーキテクチャ** | `architecture.md` | システムアーキテクチャ概要 |

### 改善記録

| ドキュメント | ファイル | 概要 |
|-------------|----------|------|
| **改善サマリー** | `docs/IMPROVEMENT_SUMMARY.md` | 有報データ取得改善の概要 |
| **改善詳細** | `YUHO_IMPROVEMENTS.md` | 有報データ取得改善の詳細説明 |
| **変更履歴** | `CHANGELOG.md` | バージョン別の変更履歴 |

### 利用ガイド

| ドキュメント | ファイル | 概要 |
|-------------|----------|------|
| **使い方** | `how_to_use.md` | インストール・起動・操作方法 |
| **README** | `README.md` | プロジェクト概要とクイックスタート |

### 投資判断ガイド

| ドキュメント | ファイル | 概要 |
|-------------|----------|------|
| **投資判断ガイド** | `investment_judgment_guide.md` | スコア・シグナル・アクションの解釈方法 |

### レビュー・検証

| ドキュメント | ファイル | 概要 |
|-------------|----------|------|
| **バックテストレポート** | `backtest_report_v1.4.2.md` | バージョン 1.4.2 のバックテスト結果 |
| **パッケージレビュー** | `REVIEW_PACKAGE_v2.md` | 外部レビュー用パッケージ資料 |
| **レビュー用プロンプト** | `prompt_for_external_review.md` | 外部レビュー向けプロンプト |
| **レビューチェックリスト** | `review_response_checklist.md` | レビュー対応チェックリスト |

---

## 🎯 目的別ドキュメントガイド

### 新規ユーザー

1. **README.md** - プロジェクト概要とクイックスタート
2. **how_to_use.md** - 詳細なインストール・操作方法
3. **investment_judgment_guide.md** - 分析結果の解釈方法

### 開発者

1. **system_design.md** - 全体アーキテクチャ理解
2. **docs/YUHO_SYSTEM_DESIGN.md** - 有報モジュールの詳細設計
3. **architecture.md** - システムアーキテクチャ

### 運用担当者

1. **docs/YUHO_SYSTEM_DESIGN.md** - 10. 運用設計
2. **CHANGELOG.md** - 変更履歴とバージョンアップ内容
3. **how_to_use.md** - 日常運用マニュアル

### 改善・機能追加担当者

1. **docs/IMPROVEMENT_SUMMARY.md** - 最新の改善概要
2. **YUHO_IMPROVEMENTS.md** - 改善の詳細と背景
3. **docs/YUHO_SYSTEM_DESIGN.md** - 11. 変更履歴

---

## 📋 有報システム関連ドキュメント

### 構成

```
有報システム関連ドキュメント
├── docs/YUHO_SYSTEM_DESIGN.md    # 詳細設計書（919 行）
├── docs/IMPROVEMENT_SUMMARY.md   # 改善サマリー
└── YUHO_IMPROVEMENTS.md          # 改善詳細説明
```

### 関連ソースコード

```
src/
├── edinet_client.py              # EDINET（日本株）クライアント
├── sec_client.py                 # SEC（米国株）クライアント
└── analyzers.py                  # 定性分析スコアリング
```

### 改善の要点

1. **API キーチェックの遅延** - キャッシュ優先で API キーなしでも利用可能
2. **AI 解析の条件付き実行** - 失敗時も生テキストで続行
3. **生テキストの活用** - Gemini が直接解析可能な形式で提供

---

## 🔗 外部リンク

- **EDINET API**: https://api.edinet-fsa.go.jp/
- **SEC EDGAR**: https://www.sec.gov/edgar
- **Gemini API**: https://ai.google.dev/

---

## 📝 ドキュメント作成ガイドライン

### 表記規則

- **日付**: ISO 8601 形式（YYYY-MM-DD）
- **バージョン**: セマンティックバージョニング（major.minor.patch）
- **コード**: Python 3.10+ の構文
- **図表**: Mermaid または ASCII アート

### レビュープロセス

1. ドキュメント作成
2. 内容確認（`review_response_checklist.md`）
3. 更新（`CHANGELOG.md` に記録）
4. コミット

---

**文書索引 終了**
