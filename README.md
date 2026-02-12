# 🤖 AI投資司令塔 - CIO Prototype

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
③ 外資との「対戦表」を自動生成
   営業利益率 | トヨタ8.2% | Tesla5.1% | BYD3.8%
   CF品質     | 1.3        | 0.8       | 1.0
   ...
        ↓
④ Layer1: 地力分析（外資比較 → バグ発見）
   Layer2: タイミング分析（ニュース × テクニカル）
        ↓
⑤ 最終判断: BUY / WATCH / SELL
   エントリー価格 / 損切り / 利確 → Google Sheetsに出力
```

---

## 📦 ファイル構成

```
.
├── main.py                          # 全ロジック（エントリーポイント）
├── config.json                      # 設定（比較対象数・閾値・シグナル基準）
├── requirements.txt                 # 依存パッケージ
├── .env.example                     # 環境変数サンプル
├── .gitignore
├── README.md
└── .github/
    └── workflows/
        └── cio_analysis.yml         # GitHub Actions（手動実行）
```

---

## 🚀 セットアップ

### 1. リポジトリをクローン

```bash
git clone https://github.com/YOUR_USERNAME/cio-prototype.git
cd cio-prototype
```

### 2. 依存パッケージをインストール

```bash
pip install -r requirements.txt
```

### 3. 環境変数を設定

```bash
cp .env.example .env
```

`.env` を編集：

```bash
GEMINI_API_KEY=your_gemini_api_key
SPREADSHEET_ID=11q5zORCYlP9ZeNjZLopoeiQhuM5_hXeSE4Evp0NNChA
GOOGLE_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}'
```

#### API Keyの取得方法

| キー | 取得先 |
|------|--------|
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/) |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | [Google Cloud Console](https://console.cloud.google.com/) でサービスアカウント作成 |

---

## 💻 使い方

### ローカル実行

```bash
# 1銘柄
python main.py 7203.T

# 複数銘柄
python main.py 7203.T 8306.T AAPL

# 対話モード
python main.py
> 分析したい銘柄コードを入力: 7203.T
```

### GitHub Actionsで実行

1. GitHubリポジトリの `Actions` タブを開く
2. `CIO Analysis` → `Run workflow`
3. 銘柄コードを入力して実行

---

## 📊 出力例

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🏆 最終判断: 7203.T
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎯 シグナル: BUY
📊 地力スコア: 8/10
⏱️ タイミングスコア: 7/10
🔢 総合スコア: 8/10

【根拠】
CF品質1.3はTesla(0.8)を圧倒。「本物の利益」を生んでいる。
PER8倍はApple(25倍)比で3倍過小評価されており市場のバグが存在。
EV投資加速ニュースで短期カタリストも揃い始めた。

【アクション】
- エントリー価格: ¥2,850以下
- 損切りライン:   ¥2,650（MA75近辺）
- 利確ライン:     ¥3,400（PER10倍到達）
- ポジションサイズ: ポートフォリオの 5%
```

Google Sheetsには対戦表・地力分析・タイミング分析・最終判断が折り返し表示で保存されます。

---

## ⚙️ カスタマイズ

`config.json` を編集するだけで挙動を変更できます：

```json
{
  "competitor_selection": {
    "direct_count": 3,      // 直接競合の数
    "substitute_count": 2,  // 機能代替の数
    "benchmark_count": 2    // 資本効率ベンチマークの数
  },
  "signals": {
    "BUY":   {"min_score": 7},  // 7点以上でBUY
    "WATCH": {"min_score": 4},
    "SELL":  {"max_score": 3}
  }
}
```

---

## 🔒 GitHub Secretsの設定

1. リポジトリの `Settings` → `Secrets and variables` → `Actions`
2. 以下を追加：

| Secret名 | 内容 |
|----------|------|
| `GEMINI_API_KEY` | Gemini APIキー |
| `SPREADSHEET_ID` | Google SheetsのID |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | サービスアカウントのJSONファイル全体 |

---

## ⚠️ 免責事項

このシステムは投資判断の参考情報を提供するものです。投資は自己責任で行ってください。

---

## 📝 License

MIT
