# 🤖 外部AI向けレビュー依頼プロンプト (CIO Prototype v2.0.0)

このファイルの内容をすべてコピーし、外部AI（Claude 3.5 Sonnet, GPT-4o など）のチャット欄に貼り付けてレビューを依頼してください。

---

## 📋 プロンプト（ここから下をコピー）

あなたはシニア・ソフトウェアエンジニアおよびクオンツ・デベロッパーとして、以下の「AI投資分析システム（CIO Prototype v2.0.0）」のコードレビューを行ってください。

### 📌 1. プロジェクトの背景と目的
このシステムは、マクロ環境（金利、VIXなど）、証券会社の財務データ、バリュエーション（DCFモデル）、テクニカル指標、および有価証券報告書のLLM解析（定性評価）を統合し、0〜10点でスコアリングして投資判断（Buy/Sellシグナル）を下す自律型エージェントです。

今回の v2.0.0 アップデートでは、プロトタイプの実運用化に向けて以下の「堅牢化」を行いました。
- **Point-in-Time フィルタ**: 決算発表の45日ラグを考慮し、バックテスト時のルックアヘッドバイアスを排除。
- **動的 WACC**: 固定の割引率ではなく、最新の米国10年債利回りをリアルタイムで取得してDCFに反映。
- **ポートフォリオ制限**: 同一セクターへの集中投資を制限（上限30%）。
- **リトライ処理/例外ハンドリング**: 外部API呼び出しの安定化。

### 🎯 2. レビューの焦点を当ててほしいポイント
以下の観点から、アーキテクチャやコードベースに対する**「辛口で実践的なフィードバック」**および**「設計上の死角（Edge Cases / Race Conditions / Logical Flaws）」**を指摘してください。

1. **バックテストの妥当性 (Backtest Integrity)**: `backtester.py` や `data_fetcher.py` における Point-in-Time 処理に、まだ先読みバイアスの抜け穴はないか。
2. **システム堅牢性 (Resilience)**: APIエラー、ネットワーク切断、データ欠損時のフォールバック処理は適切か。
3. **アーキテクチャ設計 (Architecture)**: 将来的なマルチスレッド処理や、SQLite / DB 移行を見据えた際、現在の状態管理（`results.json` など）の潜在的リスクは何か。
4. **金融ロジックの正確性 (Quant Logic)**: DCFモデルやATR（Average True Range）計算、ポジションサイジングのロジックに致命的な誤りはないか。

### 📂 3. システムの実装状況（全体構造）
```text
CIO Prototype/
├── main.py                 # オーケストレーター。全体のフロー制御。
├── src/
│   ├── data_fetcher.py     # yfinance/EDINETからのデータ取得とPitフィルタ
│   ├── macro_regime.py     # マクロ指標(VIX, 金利差)によるRegime判定
│   ├── analyzers.py        # 4軸スコアリングエンジン (ルールベース)
│   ├── strategies.py       # 取引戦略 (Strategy Pattern: Long/Bounce/Breakout)
│   ├── dcf_model.py        # 企業価値算出 (動的WACC)
│   ├── portfolio.py        # ポジション・セクター集中度管理
│   ├── backtester.py       # メイン検証系 (Rolling, Monte Carlo Bootstrap)
│   └── sheets_writer.py    # Google Sheetsへの結果・ログ出力 (最大5000文字)
└── config.json             # 閾値やスコアリングの重み定義
```

### 💻 4. レビュー対象のコアロジック概要
外部AIであるあなたがコードのニュアンスを掴めるよう、コアとなる仕様を説明します。

- **`src.portfolio`**: JSONファイルから既存の `holding = true` なポジションを読み込み、これから買おうとしている銘柄のセクターウェイトが上限（`max_sector_exposure_pct`）を超えないかをチェックします。
- **`src.dcf_model`**: `macro_regime.get_macro_regime()` から米国10年債利回り（Risk Free Rate）を取得し、それにBetaとMarket Premiumを足してWACCを動的計算します。
- **`src.data_fetcher (Pit Filter)`**: `as_of_date` 引数が渡された場合、`quarterly_financials` のカラム日付に対して45日以上のラグがあるデータのみを `valid_cols` として抽出します。
- **`src.backtester (Bootstrap)`**: トレード結果のリストに対し、再帰的な抽出（`random.choices`）を行うことで、配列の順序入れ替えに留まらないモンテカルロ・ブートストラップ・シミュレーションを実行します。

---
**[指示]**
上記の背景とアーキテクチャを踏まえ、**「シニアエンジニアの視点で、このシステムが抱える最大のリスク（技術的負債、ロジックの穴）をトップ3つ」**挙げ、その改善案を具体的なコードレベルのアイデアと共に提示してください。
必要であれば、「このモジュールのコードを見せてほしい」と要求してください。
