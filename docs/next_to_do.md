# Botter 構築計画 完全まとめ

> 作成日: 2026-03-23  
> ベースリポジトリ: <https://github.com/mineon09/cio-prototype>  
> 参照ポスト: @aiba_algorithm「botterになりたいけど何から始めればいいですか？」2026年版

---

## 0. 出発点：元ポストの方針

```
①Claude Codeで取引所APIを叩くコードを生成
②ヒストリカルデータでバックテスト
③取り敢えず小額（1万円）で実弾テスト

昔との違いは①。
昔は「Pythonの基礎を学ぶ」が最初だったけど、
今はAIに書かせて動かしながら理解する方が速い。
```

---

## 1. cio-prototype の現状

### リポジトリ概要

| 項目 | 内容 |
|------|------|
| URL | <https://github.com/mineon09/cio-prototype> |
| 主要言語 | Python 89.8% / JavaScript 4.0% / CSS 2.6% |
| 概要 | AI投資司令塔。銘柄コードを入力するだけでBUY/SELL判断を自動出力 |

### 既存の処理フロー

```
入力: "7203.T"（トヨタ）
        ↓
① yfinanceで財務・テクニカル・ニュースを取得
        ↓
② GeminiAPIが比較対象を自動選定
   直接競合: TSLA, BYD, F
   機能代替: UBER, LYFT
   資本効率ベンチマーク: AAPL, MSFT
        ↓
③ (日本株) EDINET有価証券報告書をGeminiで解析
        ↓
④ 4軸スコアカードを算出
   Fundamental / Valuation / Technical / Qualitative
        ↓
⑤ 最終判断: BUY / WATCH / SELL
   → Google Sheets + Webダッシュボードに出力
```

### 既存ファイル構成（主要なもの）

```
cio-prototype/
├── main.py                  # オーケストレーション＆分析ロジック
├── app.py                   # Streamlit アプリ
├── config.json              # 設定（閾値・セクタープロファイル）
├── requirements.txt
├── .env.example
├── .github/workflows/
│   └── main.yml             # GitHub Actions（手動実行）
├── src/                     # コアロジック
├── scripts/
└── data/reports/
```

---

## 2. Q&A ログ

### Q: 取引対象は？

**A: 米国株・日本株**

### Q: コーディングのスタンスは？

**A: Antigravity上でGitHub Copilot**

---

## 3. ブローカー選定

### 米国株 → Alpaca（最優先）

| 項目 | 内容 |
|------|------|
| API | alpaca-py（公式Pythonライブラリ） |
| コスト | 無料 |
| フラクショナルシェア | 対応（1万円から実弾可能） |
| Paper trading | あり（本番前の動作確認に使う） |
| URL | <https://alpaca.markets> |

### 日本株 → kabu.com API

| 項目 | 内容 |
|------|------|
| 証券会社 | auカブコム証券 |
| API | REST API 無料 |
| 注意点 | 最低単元が数万円〜のため**1万円テストは米国株で実施**、日本株はシグナル確認のみで開始を推奨 |

---

## 4. 追加するファイル構成

```
cio-prototype/
├── execution/
│   ├── __init__.py
│   ├── alpaca_client.py      # 米国株 注文実行（本ドキュメントに全コード記載）
│   ├── kabu_client.py        # 日本株 注文実行（Phase 2以降）
│   ├── execution_engine.py   # シグナル→注文変換 + リスク管理
│   └── risk_guard.py         # ロスカット / 上限チェック
├── backtest/
│   ├── __init__.py
│   ├── backtest_engine.py    # vectorbt でシグナル検証
│   └── performance.py        # Sharpe / DD / PF 計算
├── .github/workflows/
│   └── trade.yml             # 既存 main.yml を拡張
└── .env.example              # ALPACA_API_KEY 等追記
```

---

## 5. リスク管理ルール

| パラメータ | 値 |
|---|---|
| 初期資本 | 10,000円 |
| 1回の最大注文額 | 2,000円（≒ MAX_ORDER_USD=15.0） |
| 最大累計損失（停止ライン） | 3,000円（≒ MAX_DAILY_LOSS_USD=20.0） |
| 最大ポジション数 | 2銘柄 |
| バックテスト合格基準 | PF > 1.3 かつ 最大DD < 25% |

---

## 6. 実装手順（Copilotで進める順番）

### Step 1（今週）：Alpaca 接続テスト

1. Alpaca に無料登録 → Paper trading 用 API キー取得
2. `.env` に追記（後述）
3. `execution/alpaca_client.py` を作成し Copilot で補完（後述）
4. `python execution/alpaca_client.py` でスモークテスト

### Step 2（来週）：バックテスト

```python
# Copilot へのコメント指示例（backtest_engine.py 冒頭に書く）
# vectorbt で過去2年のシグナルをリプレイして
# 勝率・PF・最大ドローダウンを出力するスクリプト
# データソース: yfinance（米国株）/ J-Quants（日本株）
# シグナルは main.py の出力 results.json を読み込む
```

### Step 3（バックテスト合格後）：GitHub Actions で自動化

```yaml
# .github/workflows/trade.yml に追記するイメージ
# 東京時間 22:30（NY市場オープン）に実行
# main.py → execution_engine.py の順に起動
# 結果を Notion に POST
```

---

## 7. .env 追記内容

```bash
# ── 既存 ──
GEMINI_API_KEY=your_gemini_api_key
EDINET_API_KEY=your_edinet_subscription_key
SPREADSHEET_ID=your_spreadsheet_id
GOOGLE_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}'

# ── 新規追加 ──

# Alpaca（最初は Paper trading）
ALPACA_API_KEY=PKxxxxxxxxxxxx
ALPACA_SECRET_KEY=xxxxxxxxxxxxxxxx
ALPACA_BASE_URL=https://paper-api.alpaca.markets
# Live に切り替えるとき:
# ALPACA_BASE_URL=https://api.alpaca.markets

# リスク管理
MAX_ORDER_USD=15.0        # 約2,200円
MAX_DAILY_LOSS_USD=20.0   # 約3,000円
```

---

## 8. execution/alpaca_client.py（全コード）

> Copilot の `# TODO:` コメントにカーソルを合わせて Tab → 補完の繰り返しで完成させる。

```python
"""
execution/alpaca_client.py
--------------------------
Alpaca Markets API クライアント（米国株 自動売買）

【依存ライブラリ】
    pip install alpaca-py python-dotenv

【環境変数（.env に追記）】
    ALPACA_API_KEY=your_key
    ALPACA_SECRET_KEY=your_secret
    ALPACA_BASE_URL=https://paper-api.alpaca.markets   # Paper trading
    # Live に切り替える時: https://api.alpaca.markets

【使い方（呼び出し元 execution_engine.py から）】
    from execution.alpaca_client import AlpacaClient
    client = AlpacaClient()
    client.submit_order(symbol="AAPL", side="buy", notional_usd=20.0)
"""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from dotenv import load_dotenv

# alpaca-py の公式クライアントをインポート
# TradingClient: 注文・ポジション管理
# StockDataClient: 価格データ取得
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, GetAssetsRequest
from alpaca.trading.enums import OrderSide, TimeInForce, AssetClass
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest

load_dotenv()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# リスクパラメータ（変更はここだけ）
# ---------------------------------------------------------------------------

# 1回の注文の最大金額（円建て）。execution_engine がドルに変換して渡す。
MAX_ORDER_USD: float = float(os.getenv("MAX_ORDER_USD", "15.0"))   # 約2,200円

# 1日の最大損失（USD）。超えたら AlpacaClient が注文を拒否する。
MAX_DAILY_LOSS_USD: float = float(os.getenv("MAX_DAILY_LOSS_USD", "20.0"))  # 約3,000円


# ---------------------------------------------------------------------------
# データクラス：注文結果
# ---------------------------------------------------------------------------

# TODO: GitHub Copilot に補完させる
# OrderResult は注文送信後に返す軽量な結果オブジェクト。
# フィールド: order_id(str), symbol(str), side(str), qty(float),
#             notional(float), status(str), submitted_at(datetime)
@dataclass
class OrderResult:
    order_id: str
    symbol: str
    side: str
    qty: Optional[float]
    notional: Optional[float]
    status: str
    submitted_at: datetime


# ---------------------------------------------------------------------------
# AlpacaClient クラス
# ---------------------------------------------------------------------------

class AlpacaClient:
    """
    Alpaca Markets との通信を担当するクライアント。
    - Paper / Live 両対応（環境変数で切り替え）
    - 注文送信・残高確認・ポジション照会・最新価格取得
    - MAX_ORDER_USD と MAX_DAILY_LOSS_USD によるガード
    """

    def __init__(self) -> None:
        # TODO: GitHub Copilot に補完させる
        # 環境変数から api_key / secret_key / base_url を読み込み、
        # self.trading_client = TradingClient(api_key, secret_key, paper=True/False)
        # self.data_client = StockHistoricalDataClient(api_key, secret_key)
        # を初期化する。base_url に "paper" が含まれれば paper=True とする。
        # 初期化時に self._validate_connection() を呼んでアカウント情報をログ出力する。
        pass

    # ------------------------------------------------------------------
    # 接続確認
    # ------------------------------------------------------------------

    def _validate_connection(self) -> None:
        # TODO: GitHub Copilot に補完させる
        # self.trading_client.get_account() でアカウント情報を取得し、
        # account.status が "ACTIVE" でなければ RuntimeError を投げる。
        # 成功時は logger.info でアカウントID・残高・モード（paper/live）をログ出力する。
        pass

    # ------------------------------------------------------------------
    # 残高・エクイティ取得
    # ------------------------------------------------------------------

    def get_equity_usd(self) -> float:
        """現在の総資産（USD）を返す。"""
        # TODO: GitHub Copilot に補完させる
        # trading_client.get_account().equity を float に変換して返す
        pass

    def get_cash_usd(self) -> float:
        """現金残高（USD）を返す。"""
        # TODO: GitHub Copilot に補完させる
        pass

    # ------------------------------------------------------------------
    # ポジション
    # ------------------------------------------------------------------

    def get_open_positions(self) -> list[dict]:
        """
        保有ポジションの一覧を返す。
        各要素: {"symbol": str, "qty": float, "market_value_usd": float,
                 "unrealized_pl_usd": float, "side": str}
        """
        # TODO: GitHub Copilot に補完させる
        # trading_client.get_all_positions() でリスト取得後、
        # 上記 dict 形式に変換して返す。ポジションがなければ空リストを返す。
        pass

    def get_position(self, symbol: str) -> Optional[dict]:
        """指定銘柄のポジションを返す。なければ None。"""
        # TODO: GitHub Copilot に補完させる
        # trading_client.get_open_position(symbol) を try/except で呼ぶ。
        # 404 相当の例外（alpaca.common.exceptions.APIError）は None を返す。
        pass

    # ------------------------------------------------------------------
    # 価格取得
    # ------------------------------------------------------------------

    def get_latest_price_usd(self, symbol: str) -> float:
        """
        指定銘柄の最新 ask 価格（USD）を返す。
        例: get_latest_price_usd("AAPL") -> 178.52
        """
        # TODO: GitHub Copilot に補完させる
        # StockLatestQuoteRequest(symbol_or_symbols=symbol) を使い、
        # data_client.get_stock_latest_quote() で取得する。
        # .ask_price が 0 または None の場合は .bid_price を使う。
        pass

    # ------------------------------------------------------------------
    # 注文送信（メインメソッド）
    # ------------------------------------------------------------------

    def submit_order(
        self,
        symbol: str,
        side: str,           # "buy" または "sell"
        notional_usd: float, # 注文金額（USD建て）。fractional shares を使う。
    ) -> OrderResult:
        """
        成行注文を送信する。

        Args:
            symbol: ティッカー例 "AAPL", "TSLA"
            side: "buy" または "sell"
            notional_usd: 注文金額（USD）。MAX_ORDER_USD を超えるとガードされる。

        Returns:
            OrderResult

        Raises:
            ValueError: リスクガード違反（金額超過・損失超過）
            RuntimeError: API エラー
        """
        # TODO: GitHub Copilot に補完させる（以下の手順でコード生成させる）
        #
        # 手順1: リスクガード
        #   - notional_usd > MAX_ORDER_USD なら ValueError を投げる
        #   - _check_daily_loss() が False なら ValueError を投げる
        #
        # 手順2: 注文リクエスト作成
        #   - MarketOrderRequest を notional 指定（fractional shares）で作る
        #   - side = OrderSide.BUY / OrderSide.SELL
        #   - time_in_force = TimeInForce.DAY
        #
        # 手順3: 注文送信
        #   - trading_client.submit_order(order_request) で送信
        #   - 結果を OrderResult に変換して返す
        #   - 成功/失敗を logger.info / logger.error で記録する
        pass

    def close_position(self, symbol: str) -> Optional[OrderResult]:
        """指定銘柄のポジションを全決済する。ポジションがなければ None を返す。"""
        # TODO: GitHub Copilot に補完させる
        # trading_client.close_position(symbol) を呼ぶ。
        # 決済結果を OrderResult に変換して返す。
        pass

    def close_all_positions(self) -> list[OrderResult]:
        """全ポジションを成行で全決済する。緊急停止用。"""
        # TODO: GitHub Copilot に補完させる
        # trading_client.close_all_positions(cancel_orders=True) を呼ぶ。
        # 各決済結果をリストで返す。
        pass

    # ------------------------------------------------------------------
    # 内部ユーティリティ
    # ------------------------------------------------------------------

    def _check_daily_loss(self) -> bool:
        """
        今日の累計損失が MAX_DAILY_LOSS_USD 未満であれば True を返す。
        超えていれば False を返し、logger.warning を出力する。
        """
        # TODO: GitHub Copilot に補完させる
        # get_account().equity と get_account().last_equity の差分で
        # 当日損益を計算する（Alpaca は前日終値を last_equity に持つ）。
        # daily_pl = float(equity) - float(last_equity)
        # daily_pl < -MAX_DAILY_LOSS_USD なら False
        pass

    def _is_market_open(self) -> bool:
        """現在 NYSE が開いているか確認する。"""
        # TODO: GitHub Copilot に補完させる
        # trading_client.get_clock() で market clock を取得し、
        # clock.is_open を返す。
        pass


# ---------------------------------------------------------------------------
# 動作確認用スクリプト（直接実行時のみ）
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # TODO: GitHub Copilot に補完させる
    # logging を basicConfig(level=INFO) で設定し、
    # AlpacaClient() を初期化して以下をプリントする:
    #   - get_equity_usd()
    #   - get_cash_usd()
    #   - get_open_positions()
    #   - _is_market_open()
    # ペーパー注文テスト: submit_order("AAPL", "buy", 10.0) を呼んで結果を表示
    logging.basicConfig(level=logging.INFO)
    print("AlpacaClient smoke test...")

    # --- ここから Copilot に書かせる ---
```

---

## 9. Copilot 補完の進め方

### 補完させる順番

1. `__init__` → `_validate_connection`（接続確認から慣らす）
2. `get_equity_usd` → `get_cash_usd`（シンプルな getter）
3. `get_open_positions` → `get_position`（ポジション管理）
4. `get_latest_price_usd`（価格取得）
5. `submit_order`（核心：3ステップに分けて1ステップずつ確認する）
6. `close_position` → `close_all_positions`（決済）
7. `_check_daily_loss` → `_is_market_open`（ユーティリティ）
8. `__main__`（スモークテスト）

### Copilot を使うコツ

- `# TODO:` コメントの行末で **Tab** を押すと提案が出る
- 一気に全部補完させず **10行ずつ確認** する（submit_order は特に重要）
- 意図と違う補完が出たら **Alt+]** で次の候補を見る
- スモークテストは Paper trading で必ず通してから Live へ

---

## 10. 次のステップ

| 優先度 | タスク | 備考 |
|--------|--------|------|
| 🔴 今すぐ | Alpaca アカウント作成・API キー取得 | <https://alpaca.markets> |
| 🔴 今すぐ | `.env` に `ALPACA_API_KEY` 等を追記 | Paper trading から始める |
| 🟡 今週 | `alpaca_client.py` を Copilot で補完・スモークテスト | `python execution/alpaca_client.py` |
| 🟡 今週 | `execution_engine.py` の設計（シグナル→注文の橋渡し） | 次回 Claude と設計 |
| 🟠 来週 | `backtest_engine.py` で過去2年のシグナル検証 | PF>1.3 / 最大DD<25% が合格基準 |
| 🟠 来週 | GitHub Actions `trade.yml` で自動実行設定 | 東京時間 22:30 |
| 🟢 合格後 | 実弾テスト開始（1万円） | 最大損失 3,000円でハード停止 |

---

## 11. 免責

本計画は投資判断の参考情報提供を目的としたシステム構築の記録です。  
投資は自己責任で行ってください。
