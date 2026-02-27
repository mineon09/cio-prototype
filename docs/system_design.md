# 🤖 AI投資司令塔 - CIO Prototype システム設計書 v2.2.0

## 変更履歴

| バージョン | 変更日 | 変更内容 | ステータス |
| :--- | :--- | :--- | :--- |
| **v1.5.1** | 2025-02 | 初期プロトタイプ。モンテカルロのブートストラップ化。 | ✅ 完了 |
| **v2.0.0** | 2026-02 | **プロダクション堅牢化**：Pitフィルタ（45日ラグ）、保有フラグによるポートフォリオ管理、動的WACC、循環インポート解消、ログ文字数拡大、依存関係固定。 | ✅ 完了 |
| **v2.1.0** | 2026-02 | **外部AIレビュー対応（16項目）**：TTM EPS、正式WACC（負債コスト込み）、FCF PITフィルタ、MCポジションサイズ、マクロキャッシュTTL化、filelock排他制御、numpy JSON安全化。 | ✅ 完了 |
| **v2.2.0** | 2026-02 | **API最適化・安定化**：競合選定のルールベース化によるGemini API節約、Notion APIのAdd-On-Demandプロパティ追加および2000文字チャンク保護（Bug #4対応）。 | ✅ 完了 |

---

## 1. システム概要

**CIO Prototype** は、プロフェッショナルな投資判断を自動化するAIエージェントシステムです。
マクロ（天気）、ファンダメンタル（体力）、バリュエーション（割安度）、テクニカル（タイミング）、定性評価（堀）の多角的なデータを統合。

## 2. 主要ロジックの詳細

### 2.1 4軸スコアリング (Analyzers)

- **Fundamental**: セクター別にROE/利益率の重みを調整。
- **Valuation**: DCFモデルと市場平均との比較。
- **Technical**: 逆張り(Bounce)と順張り(Breakout)のシグナル。
- **Qualitative**: Geminiによる有報/10-K解析結果の構造化。

### 2.2 バックテスト環境 (Backtester)

Point-in-Time フィルタにより、**歴史的な決算発表タイミング**を意識したシミュレーションが可能。

- `as_of_date` 以前かつ発表から45日経過済みのデータのみを「既知」として扱う。
- **TTM (Trailing Twelve Months)**: EPS算出では過去4四半期の合計を使用し、季節性歪みを排除。
- **FCF PITフィルタ**: DCF用のFCF取得時も `as_of_date` を考慮し、ルックアヘッドを防止。
- **モンテカルロ**: ブートストラップ法（1000回）に `position_pct` を反映。Rolling BTでは Sharpe Ratio を集計。

### 2.3 ポートフォリオ管理 (Portfolio)

買いシグナル発生時に以下のチェックを自動実行。

1. **既存保有確認**: `results.json` の `holding` フラグの状態を確認。
2. **セクター集中度**: 同一セクターへの投資比率が `max_sector_exposure_pct` を超える場合は購入見送り。

## 3. インフラ・外部サービス

- **LLM**: Gemini-2.0-Flash (Primary), Groq (Fallback)
- **Data**: yfinance, EDINET API v2, SEC EDGAR
- **Storage**: Google Sheets (Log/Report), JSON (Local State, filelock排他制御)
- **キャッシュ**: マクロ指標は `MacroHistoryCache`(TTL=12h) で管理

---
*Last Updated: 2026-02-22 (v2.1.0)*
