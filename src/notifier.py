"""
notifier.py - LINE Messaging API 通知モジュール
===============================================
直近1週間に分析した銘柄のうち、BUYシグナルに変化した銘柄を
LINE Messaging API (Push Message) で通知する。

使い方:
  python notifier.py              # 通知チェック＆送信
  python notifier.py --test       # テスト送信

LINEクレデンシャル:
  line_secret.txt に以下の形式で保存（.gitignoreで除外済み）
  ---------------------------
  YOUR_CHANNEL_ACCESS_TOKEN
  YOUR_USER_ID
  ---------------------------
"""

import os
import sys
import json
from datetime import datetime, timedelta

try:
    from linebot.v3 import WebhookHandler
    from linebot.v3.messaging import (
        Configuration,
        ApiClient,
        MessagingApi,
        PushMessageRequest,
        TextMessage
    )
except ImportError:
    print("❌ line-bot-sdk がインストールされていません。")
    print("pip install line-bot-sdk を実行してください。")
    sys.exit(1)


def _load_credentials() -> tuple[str | None, str | None]:
    """
    line_secret.txt からアクセストークンとユーザーIDを読み込む
    1行目: Channel Access Token
    2行目: User ID
    """
    token_file = os.path.join(os.path.dirname(__file__), "..", "extra", "line_secret.txt")
    if os.path.exists(token_file):
        with open(token_file, "r") as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]
            if len(lines) >= 2:
                return lines[0], lines[1]
            elif len(lines) == 1:
                return lines[0], None
    
    # 環境変数フォールバック
    return os.environ.get("LINE_CHANNEL_ACCESS_TOKEN"), os.environ.get("LINE_USER_ID")


def send_line_push(message: str) -> bool:
    """LINE Messaging API でプッシュ通知を送信する"""
    access_token, user_id = _load_credentials()
    
    if not access_token:
        print("⚠️ Channel Access Token が line_secret.txt の1行目にありません")
        return False
    if not user_id:
        print("⚠️ User ID が line_secret.txt の2行目にありません")
        print("   (LINE Developersコンソール -> Basic settings -> Your user ID)")
        return False

    configuration = Configuration(access_token=access_token)
    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            push_request = PushMessageRequest(
                to=user_id,
                messages=[TextMessage(text=message)]
            )
            line_bot_api.push_message(push_request)
            print(f"✅ LINE通知送信成功 (to: {user_id[:4]}...)")
            return True
    except Exception as e:
        print(f"❌ LINE通知エラー: {e}")
        return False


def check_and_notify():
    """
    data/results.json を読み込み、直近1週間に分析した銘柄で
    BUYシグナルの銘柄を LINE 通知する。
    """
    results_file = os.path.join(os.path.dirname(__file__), "..", "data", "results.json")
    if not os.path.exists(results_file):
        print("ℹ️ 分析データがありません")
        return

    with open(results_file, "r", encoding="utf-8") as f:
        all_data = json.load(f)

    one_week_ago = datetime.now() - timedelta(days=7)
    buy_alerts = []
    score_up_alerts = []

    for ticker, data in all_data.items():
        history = data.get("history", [])
        if not history:
            continue

        latest = history[-1]
        latest_date_str = latest.get("date", "")

        try:
            latest_date = datetime.strptime(latest_date_str.split(" ")[0], "%Y-%m-%d")
        except (ValueError, IndexError):
            continue

        if latest_date < one_week_ago:
            continue

        # BUYシグナル
        if latest.get("signal") == "BUY":
            total_score = latest.get("total_score", 0)
            buy_alerts.append(f"🟢 {ticker} ({data.get('name', '')}) — BUY (Score: {total_score:.1f})")

        # スコア上昇
        if len(history) >= 2:
            prev = history[-2]
            prev_score = prev.get("total_score", 0)
            curr_score = latest.get("total_score", 0)
            if curr_score - prev_score >= 2:
                score_up_alerts.append(
                    f"📈 {ticker} — スコア上昇 +{curr_score - prev_score:.1f} ({prev_score:.1f}→{curr_score:.1f})"
                )

    if not buy_alerts and not score_up_alerts:
        print("ℹ️ 通知対象なし（直近1週間のBUYシグナルなし）")
        return

    lines = ["🤖 CIO Intelligence Alert"]
    lines.append(f"📅 {datetime.now().strftime('%m/%d %H:%M')}")

    if buy_alerts:
        lines.append("\n【BUYシグナル】")
        lines.extend(buy_alerts)

    if score_up_alerts:
        lines.append("\n【スコア急上昇】")
        lines.extend(score_up_alerts)

    message = "\n".join(lines)
    print(f"\n--- 通知内容 ---\n{message}\n---")
    send_line_push(message)


def main():
    if "--test" in sys.argv:
        print("🧪 LINE Messaging API テスト送信...")
        send_line_push("🧪 CIO Intelligence — Messaging API テスト通知成功！")
        return

    check_and_notify()


if __name__ == "__main__":
    main()
