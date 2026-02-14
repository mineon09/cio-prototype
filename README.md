# 🤖 AI投資司令塔 - CIO Prototype (Professional Edition)

外資との「対戦表」を自動生成し、**市場が気づいていない本質的価値のバグ**を発見するAI投資分析システム。

[![Python](https://img.shields.io/badge/Python-3.11-blue)](https://python.org)
[![Gemini](https://img.shields.io/badge/Gemini-3--flash-orange)](https://ai.google.dev)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

---

## 🎯 何をするシステムか

銘柄コードを1つ入力するだけで、以下を自動実行：

```
入力: "7203.T"（トヨタ）
        ↓
① yfinanceで財務・テクニカル・ニュースを取得
        ↓
② GeminiAPIが最適な比較対象を自動選定
   直接競合: TSLA, BYD, F
   機能代替: UBER, LYFT
   資本効率ベンチマーク: AAPL, MSFT
        ↓
③ (日本株) EDINET有価証券報告書をGeminiで解析
   リスクTOP3 / 堀(Moat) / R&D / 経営陣トーン
        ↓
④ 4軸スコアカードを算出（セクター別閾値）
   Fundamental / Valuation / Technical / Qualitative
        ↓
⑤ 最終判断: BUY / WATCH / SELL
   → Google Sheets + Webダッシュボードに出力
```

---

## 📦 ファイル構成

```
.
├── main.py                    # オーケストレーション＆分析ロジック
├── edinet_client.py           # EDINET API v2 有報取得モジュール
├── analyzers.py               # 4軸ルールベーススコアリング
├── config.json                # 設定（閾値・セクタープロファイル）
├── serve.py                   # ダッシュボード用ローカルサーバー
├── index.html                 # CIO Intelligence Dashboard
├── dashboard.css              # ダッシュボードスタイル
├── dashboard.js               # ダッシュボードロジック
├── data/
│   └── results.json           # 分析結果（自動生成）
├── requirements.txt
├── .env.example
├── .gitignore
└── .github/workflows/
    └── main.yml               # GitHub Actions（手動実行）
```

---

## 🚀 セットアップ

### 1. 依存パッケージをインストール

```bash
pip install -r requirements.txt
```

### 2. 環境変数を設定

```bash
cp .env.example .env
```

`.env` を編集：

```bash
GEMINI_API_KEY=your_gemini_api_key
EDINET_API_KEY=your_edinet_subscription_key
SPREADSHEET_ID=your_spreadsheet_id
GOOGLE_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}'
```

| キー | 取得先 |
|------|--------|
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/) |
| `EDINET_API_KEY` | [EDINET API](https://disclosure2dl.edinet-fsa.go.jp/) |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | [Google Cloud Console](https://console.cloud.google.com/) |

---

## 💻 使い方

### 分析を実行

```bash
# 1銘柄
python main.py 7203.T

# 複数銘柄
python main.py 7203.T 8306.T AAPL

# 対話モード
python main.py
```

### ダッシュボードを表示

```bash
python serve.py
```

ブラウザが自動で `http://localhost:8080` を開きます。

---

## 📊 4軸スコアカード

| 軸 | 内容 | 主要指標 |
|----|------|----------|
| **Fundamental** | 企業の地力 | ROE, 営業利益率, 自己資本比率 |
| **Valuation** | 割安度 | PER, PBR, 配当利回り, 目標株価乖離 |
| **Technical** | タイミング | RSI, MA乖離率, BB位置, ボラティリティ |
| **Qualitative** | 定性分析 | 有報リスク, 堀(Moat), R&D, 経営陣トーン |

スコアはセクター別に閾値が自動調整されます（High-Growth / Value / Financial）。

---

## ⚙️ カスタマイズ

`config.json` で挙動を変更できます：

```json
{
  "signals": {
    "BUY":   {"min_score": 7},
    "SELL":  {"max_score": 3}
  },
  "sector_profiles": {
    "high_growth": {
      "sectors": ["Technology", "Healthcare"],
      "fundamental": {"roe_good": 15},
      "valuation": {"per_cheap": 25}
    }
  }
}
```

---

## 🔒 GitHub Secretsの設定

| Secret名 | 内容 |
|----------|------|
| `GEMINI_API_KEY` | Gemini APIキー |
| `EDINET_API_KEY` | EDINET APIキー |
| `SPREADSHEET_ID` | Google SheetsのID |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | サービスアカウントJSON |

---

## ⚠️ 免責事項

このシステムは投資判断の参考情報を提供するものです。投資は自己責任で行ってください。

---

## 📝 License

MIT
