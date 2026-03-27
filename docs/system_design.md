# 🤖 AI投資司令塔 - CIO Prototype システム設計書 v2.4+

## 変更履歴

| バージョン | 変更日 | 変更内容 | ステータス |
| :--- | :--- | :--- | :--- |
| **v1.5.1** | 2025-02 | 初期プロトタイプ。モンテカルロのブートストラップ化。 | ✅ 完了 |
| **v2.0.0** | 2026-02 | **プロダクション堅牢化**：PITフィルタ（45日ラグ）、保有フラグ、動的WACC、循環インポート解消、filelock排他制御。 | ✅ 完了 |
| **v2.1.0** | 2026-02 | **外部AIレビュー対応（16項目）**：TTM EPS、正式WACC（負債コスト込み）、FCF PITフィルタ、MCポジションサイズ、MacroHistoryCache TTL化。 | ✅ 完了 |
| **v2.2.0** | 2026-03 | **API最適化**：競合選定ルールベース化（Gemini API節約）、Notion Add-On-Demand、2000文字チャンク保護。 | ✅ 完了 |
| **v2.3.0** | 2026-03-15 | **コード品質強化**：単体テスト66件導入、logging_utils、parallel_utils、scoring_thresholds外部化。 | ✅ 完了 |
| **v2.4.0** | 2026-03-15 | **投資判断エンジン**：APIベース(Gemini/Qwen)・ツールベース・デュアルエンジンを `src/investment_judgment.py` に実装。 | ✅ 完了 |
| **v2.4.1** | 2026-03-27 | **カタリスト日付ガード**：`analyze_all()` にTEMPORAL CONSTRAINTSブロック注入。`news_fetcher.py` による14日ニュース取得。 | ✅ 完了 |

---

## 1. システム概要

**CIO Prototype** は、プロフェッショナルな投資判断を自動化するAIエージェントシステムです。
マクロ（レジーム）、ファンダメンタル（体力）、バリュエーション（割安度）、テクニカル（タイミング）、定性評価（堀）の多角的なデータを統合し、`BUY / WATCH / SELL` シグナルと具体的なアクションプランを生成します。

## 2. 主要ロジックの詳細

### 2.1 4軸スコアリング (Analyzers)

- **Fundamental**: セクター別にROE/利益率の重みを `config.json` の `sector_profiles` で調整。
- **Valuation**: DCFモデル（正式WACC）と市場平均との比較。PBR・PER・配当利回りを加味。
- **Technical**: RSI・MA乖離・BB位置・出来高比率で算出。逆張り(Bounce)と順張り(Breakout)で解釈が異なる。
- **Qualitative**: Geminiによる有報/10-K解析結果の構造化スコア。データ未取得時はウェイトを 0% に再配分（設計意図通り）。

### 2.2 スコア制約（プロンプト厳守条件）

LLMに渡すプロンプトには以下の制約を明記し、スコアの恣意的な上書きを防止する。

- 4軸スコアの数値変更禁止（±1.0 以内）
- 総合スコアは加重平均と大きく乖離させない
- ROE低＋PER高 → 「過小評価」断定を禁止

### 2.3 カタリスト日付ガード (TEMPORAL CONSTRAINTS)

`analyze_all()` 冒頭で `_today / _current_year / _current_quarter / _next_quarter` を計算し、
プロンプトに `TEMPORAL CONSTRAINTS` ブロックを注入する。

- 現在年以前のカタリスト日付を出力禁止
- 日付が不明な場合は `{year}H2` や `{Q}` などの範囲表記を強制

LLMの訓練データカットオフ（2024年）依存を排除するための対策。

### 2.4 バックテスト環境 (Backtester)

Point-in-Time フィルタにより、**歴史的な決算発表タイミング**を意識したシミュレーションが可能。

- `as_of_date` 以前かつ発表から45日経過済みのデータのみを「既知」として扱う。
- **TTM (Trailing Twelve Months)**: EPS算出では過去4四半期の合計を使用し、季節性歪みを排除。
- **FCF PITフィルタ**: DCF用のFCF取得時も `as_of_date` を考慮し、ルックアヘッドを防止。
- **モンテカルロ**: ブートストラップ法（1000回）に `position_pct` を反映。Rolling BTでは Sharpe Ratio を集計。

### 2.5 ポートフォリオ管理 (Portfolio)

買いシグナル発生時に以下のチェックを自動実行。

1. **既存保有確認**: `results.json` の `holding` フラグの状態を確認。
2. **セクター集中度**: 同一セクターへの投資比率が `max_sector_exposure_pct` を超える場合は推奨ポジションサイズを縮小。

### 2.6 投資判断エンジン (Investment Judgment)

`src/investment_judgment.py` に3種のエンジンを実装。

| エンジン | 技術 | 速度 | コスト |
|---|---|---|---|
| `APIJudgmentEngine` | LLM (Gemini/Qwen) | 2-5秒 | API料金 |
| `ToolJudgmentEngine` | ルールベース | <0.1秒 | 無料 |
| `DualJudgmentEngine` | 両者比較・統合 | 2-5秒 | API料金 |

## 3. インフラ・外部サービス

- **LLM**: Gemini 2.5 Flash (Primary), Groq Llama 3 (Fallback), GitHub Models GPT-4o (`--engine=copilot`)
- **Data**: yfinance, EDINET API v2, SEC EDGAR, Gemini google_search（ニュース・日本株）
- **Storage**: Google Sheets (ログ/シグナル), Notion (レポート), JSON (ローカル状態, filelock排他制御)
- **キャッシュ**: マクロ指標は `MacroHistoryCache`(TTL=12h), SEC/EDINET は TTL=30/90日のファイルキャッシュ

---
*Last Updated: 2026-03-27 (v2.4.1)*
