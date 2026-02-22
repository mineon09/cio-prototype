# 🤖 AI投資司令塔 - CIO Prototype システムアーキテクチャ設計書 (v2.0.0)

本ドキュメントは、CIO Prototype（AI投資分析システム）の全体構成、データフロー、および主要ロジックを正確に定義する。

---

## 1. システム構成・コンポーネント

システムはレイヤー構造とStrategy Patternを用いて、堅牢性と拡張性を担保している。

### システム構成図 (Mermaid)

```mermaid
graph TD
    User[ユーザー または GitHub Actions] --> Main[main.py (Orchestrator)]
    
    subgraph "Core Logic"
        Main --> Macro[src/macro_regime.py<br>(マクロ判定 & リアルタイム金利)]
        Main --> Fetcher[src/data_fetcher.py<br>(データ取得 / Pitフィルタ)]
        Main --> Analyzers[src/analyzers.py<br>(4軸スコアリング)]
        Main --> Strategies[src/strategies.py<br>(戦略判定 / Strategy Pattern)]
        Main --> DCF[src/dcf_model.py<br>(DCF / 動的WACC)]
        Main --> Portfolio[src/portfolio.py<br>(ポジション / セクター管理)]
    end
    
    subgraph "Verification"
        Backtester[src/backtester.py<br>(Pitバックテスト / Rolling)] --> Fetcher
        Backtester --> Strategies
        Backtester --> Portfolio
    end
    
    subgraph "External API & Data"
        Fetcher --> YF[yfinance API]
        Fetcher --> EDINET[EDINET API (有報)]
        Fetcher --> SEC[SEC EDGAR (10-K)]
        Main --> LLM[Gemini / Groq API]
    end
    
    subgraph "Output & Persistence"
        Main --> SheetsWriter[src/sheets_writer.py<br>(Google Sheets書込)]
        SheetsWriter --> DB_Log[(System_Log シート / 5000文字)]
        Main --> DB_JSON[(data/results.json<br>保有フラグ込)]
    end
    
    Strategies -- 使用 --> Analyzers
    Main -- 設定読込 --> Config[config.json]
```

### 主要コンポーネント
1. **Orchestrator (`main.py`)**: 全体の制御フロー。モジュールレベルでのインポートにより初期化オーバーヘッドを抑制。
2. **Data Fetcher (`src/data_fetcher.py`)**: 株価、財務状況を取得。バックテスト時は **Point-in-Time フィルタリング（45日ラグ）** によりルックアヘッドバイアスを排除。
3. **DCF Model (`src/dcf_model.py`)**: マクロ判定から得た **リアルタイム米10年債利回り** を取り入れた動的WACC算出。
4. **Portfolio (`src/portfolio.py`)**: `results.json` 内の `holding` フラグを参照し、セクター集中度（`max_sector_exposure_pct`）を考慮したサイズ決定。
5. **Backtester (`src/backtester.py`)**: ローリング・ウィンドウ検証および復元抽出によるモンテカルロ・シミュレーションに対応。JSON互換の統計出力。

---

## 2. 独自ロジックと信頼性向上

### 2.1 Point-in-Time (Pit) データ処理
バックテスト実行時、財務データが決算発表の翌日に既知であったと仮定せず、実務上の公表ラグ（45日）を考慮してデータをフィルタリングする。

### 2.2 リアルタイム WACC 算出
DCFモデルにおいて、リスクフリーレートを固定値（旧4.3%等）とせず、`src/macro_regime.py` が取得した最新の米国10年債利回りをシームレスに結合して計算する。

### 2.3 セクター集中度ガード
`results.json` を共有DBとして扱い、新規 BUY シグナル発生時に同一セクターの既存ポジション合計が上限（デフォルト30%）を超えないよう自動制限する。

---

## 3. 堅牢化の原則 (v2.0 準拠)

1. **例外安全とリトライ**:
   - `tenacity` ライブラリによる指数バックオフ・リトライを API 通信（yfinance, EDINET, LLM）に適用。
2. **ログの可視化**:
   - Google Sheets の `System_Log` への出力文字数を 5000 文字に拡大。詳細なスタックトレースを保持。
3. **循環インポートの完全排除**:
   - `edinet_client.py` と `data_fetcher.py` の間の依存関係を関数内インポート等により最適化。
4. **型安全性の強化**:
   - `analyze_all` や `BaseStrategy` インターフェースにおける型ヒントの厳密な適用。

---

## 4. プロトタイプ運用 Roadmap (Next Steps)

1. **DB移行**: JSON ファイルから SQLite への移行による並列実行耐性の向上。
2. **非日本株対応の拡充**: SEC EDGAR クライアントの安定化と Qualitative 評価の精度向上。
3. **ダッシュボード強化**: トレード履歴と月次リターンのグラフ化。

---
*Last Updated: 2026-02-22 (v2.0.0)*
