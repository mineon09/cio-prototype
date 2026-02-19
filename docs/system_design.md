# 🤖 AI投資司令塔 - CIO Prototype システム設計書 v1.5.1

---

## 変更履歴

| バージョン | 変更日 | 変更内容 | ステータス |
| :--- | :--- | :--- | :--- |
| **v1.0** | 2024-01 | 初版：4軸スコアリング、DCFモデル、バックテスト基本機能 | ✅ 完了 |
| **v1.1-1.3** | 2024-02 | 取引コスト反映、短期戦略の日次ループ化、データキャッシュ実装、S評価達成 | ✅ 完了 |
| **v1.4** | 2024-02 | スイング戦略（Bounce/Breakout）、Regime連動閾値、MomentumBonus | ✅ 完了 |
| **v1.5.0** | 2025-02 | **Strategy Pattern導入**、バックテスト精度向上（データスライシング修正）、Alpha計算適正化 | ✅ 完了 |
| **v1.5.1** | 2025-02 | **致命的バグ修正 (v2.0 Review対応)**：モンテカルロのブートストラップ化、オーケストレーション修正、型安全性の強化、安全側デフォルトの徹底 | ✅ 完了 |

---

## 1. システム概要

**CIO Prototype** は、プロフェッショナルな投資判断（Chief Investment Officer レベル）を自動化するAIエージェントシステムです。
銘柄コードを入力するだけで、財務データ、テクニカル指標、マクロ環境、および定性情報（有報/10-K）を統合的に解析し、以下の出力を行います。

1.  **4軸スコアカード**: 企業の「基礎体力」「割安度」「タイミング」「定性評価」を数値化 (0-10点)。
2.  **投資レポート**: Gemini/Groqを活用した、CIO視点の詳細な日本語レポート。
3.  **売買シグナル**: 市場環境（Regime）と戦略（Long/Bounce/Breakout）に基づいた具体的なアクションプラン。

---

## 2. システムアーキテクチャ

システムはモジュール結合度を下げ、拡張性を高めるために**レイヤー構造**と**Strategy Pattern**を採用しています。v1.5.1では、特にオーケストレーションの堅牢性を高めました。

### 構成図

```mermaid
graph TD
    User[ユーザー (CLI/Web)] --> Main[main.py (Orchestrator)]
    
    subgraph "Core Logic"
        Main --> Macro[src/macro_regime.py<br>(マクロ環境判定)]
        Main --> Fetcher[src/data_fetcher.py<br>(データ取得)]
        Main --> Analyzers[src/analyzers.py<br>(4軸スコアリング)]
        Main --> Strategies[src/strategies.py<br>(戦略判定)]
    end
    
    subgraph "External Services"
        Fetcher --> YF[yfinance API]
        Fetcher --> EDINET[EDINET API (有報)]
        Fetcher --> SEC[SEC EDGAR (10-K)]
        Main --> LLM[Gemini / Groq API]
    end
    
    subgraph "Validation"
        Backtester[src/backtester.py<br>(歴史的検証)] --> Analyzers
        Backtester --> Strategies
    end
    
    Strategies -- 使用 --> Analyzers
    Main -- 設定読込 --> Config[config.json]
```

---

## 3. コンポーネント詳細

### 3.1 オーケストレーター (`main.py`)
システムのエントリーポイント。v1.5.1では `run()` 関数が全フローを確実に完結させます。
1.  **マクロ判定**: `detect_regime()` で現在の市場環境（RISK_ON, RATE_HIKE等）を特定。
2.  **データ取得**: 株価、財務指標、競合他社データを取得。
3.  **スコアリング**: `generate_scorecard()` でベーススコアを算出。
4.  **戦略適用**: `run_strategy_analysis()` で戦略固有のエントリー/エグジットを判定。
5.  **レポート生成**: `analyze_all()` でLLMにプロンプトを送り、自然言語レポートを作成。
6.  **保存処理**: スプレッドシート書込とダッシュボード用JSON保存を確実に実行。

### 3.2 マクロ環境判定 (`src/macro_regime.py`)
市場の「天気」を判定し、スコアリングの重みや戦略の閾値を動的に調整します。

| 指標 | 判定ロジック | 判定結果 (Regime) |
| :--- | :--- | :--- |
| **10Y-2Y金利差** | -0.1%以下 (逆イールド) | `YIELD_INVERSION` (景気後退警戒) |
| **HYG (信用)** | 20日MA比 -3.0% 急落 | `RISK_OFF` (信用収縮) |
| **VIX指数** | 25以上 | `RISK_OFF` (恐怖相場) |
| **10年債利回り** | 1ヶ月で+5%以上上昇 | `RATE_HIKE` (金利上昇局面) |
| **10年債利回り** | 1ヶ月で-5%以上低下 | `RATE_CUT` (金利低下局面) |
| **その他** | 上記以外かつVIX < 18 | `RISK_ON` (安定上昇) |

### 3.3 4軸スコアリングエンジン (`src/analyzers.py`)
AI（LLM）を使わず、**ルールベース**で客観的な数値評価を行います。

| Layer | 項目 | 評価内容 |
| :--- | :--- | :--- |
| **1. Fundamental** | ROE, 営業利益率, 自己資本比率, CF品質, R&D | 企業の「稼ぐ力」と「財務安全性」。セクター別に基準値を調整。 |
| **2. Valuation** | PER, PBR, 配当利回り, DCF乖離 | 株価の割安度。マクロ環境により適正水準を補正。 |
| **3. Technical** | RSI, MA乖離, ボリンジャーバンド, 出来高 | 売買タイミング。逆張り/順張り双方の視点を持つ。 |
| **4. Qualitative** | 堀(Moat), リスク情報, 経営陣トーン | 有報/10-Kのテキスト解析結果（LLM前処理済み）をスコア化。 |

### 3.4 戦略モジュール (`src/strategies.py`)
**GoF Strategy Pattern** を適用。v1.5.1では型安全性を強化。

#### 共通インターフェース `BaseStrategy`
- `analyze_entry()`: エントリー条件を判定。
- `should_sell()`: 損切り、利確、期限切れ等のエグジットを判定。
- **v1.5.1向上**: `pd.Timestamp` への型統一により、経過バー数計算のクラッシュリスクを解消。

---

## 4. 戦略ロジック（v1.5.1 詳細）

### 4.1 Long 戦略
- **エントリー**: 合算スコア ≥ 閾値（Regime連動、通常6.5以上）。
    - *Premium Quality Override*: Fundamental ≥ 8.0 ならスコア5.5でも可。

### 4.2 Bounce 戦略
- **エントリー条件 (AND)**:
    1.  **RSI(9) < 30**
    2.  **株価 ≤ BB下限 (2σ)**
    3.  **出来高 ≥ 20日平均 × 1.3**
    4.  **株価 > MA75** (上昇トレンド中の押し目)

### 4.3 Breakout 戦略 (v1.5.1 強化版)
- **エントリー条件 (AND)**:
    1.  **Golden Cross**: 直近5日以内にMA5がMA25を上抜け。
    2.  **High Breakout**: 終値が過去20日間の最高値を更新。
    3.  **出来高 ≥ 20日平均 × 1.2**
    4.  **MA75フィルター**: **MA75データ欠損時は NG (安全側)** とし、トレンド不明時の高値掴みを防止。

---

## 5. 検証システム (`src/backtester.py`)

v1.5.1にて統計的妥当性を大幅に向上させました。

- **Bootstrap Monte Carlo**: 単なる順序入れ替え（shuffle）から、**復元抽出（random.choices）**によるブートストラップ法へ変更。未知のシナリオに対する耐性をより正確に評価可能。
- **ATRロジックの適正化**: 戦略コンテキスト（Bounce/Breakout）をATR計算に正しく引き継ぐよう修正。
- **ローリングバックテスト**: 戦略引数のハードコードを排除し、任意の戦略での検証を可能に。

---

## 6. 次世代アーキテクチャ案 (v2.0)

現行の「動くプロトタイプ」から「運用に耐えうるシステム」への進化。

1.  **堅牢なエラーハンドリング**: `src/exceptions.py` を新設し、API障害や設定エラーをサイレントに握りつぶさず、明示的にハンドル。
2.  **SQLiteストレージへの移行**: `results.json` を SQLite に移行し、並列実行時のデータ競合を根本的に解消。
3.  **LLM出力の構造化 (JSON)**: 文字列パースへの依存を止め、Geminiの `response_mime_type: application/json` を活用。
4.  **Point-in-Time バックテスト**: 過去のバックテスト時に「その時点で入手可能だった財務データ」のみを反映させる設計への昇華。

---
*End of Document*
