import os
import time
from datetime import datetime
from notion_client import Client

def get_notion_client():
    from dotenv import load_dotenv
    import os
    load_dotenv()
    api_key = os.environ.get("NOTION_API_KEY")
    if not api_key:
        return None
    try:
        return Client(auth=api_key)
    except Exception as e:
        print(f"⚠️ Notionクライアント初期化エラー: {e}")
        return None

def ensure_database_properties(notion, db_id):
    """
    データベースに必要なプロパティを追加する（書き込みエラーが発生した場合のリカバリ用）。
    """
    try:
        needed = {
            "Ticker": {"rich_text": {}},
            "Date": {"date": {}},
            "Signal": {
                "select": {
                    "options": [
                        {"name": "BUY", "color": "green"},
                        {"name": "WATCH", "color": "yellow"},
                        {"name": "SELL", "color": "red"}
                    ]
                }
            },
            "Score": {"number": {}},
            "Price": {"rich_text": {}}
        }
        
        print(f"📦 書き込みエラー発生。不足しているプロパティの補完を試みます...")
        notion.databases.update(database_id=db_id, properties=needed)
        time.sleep(2) # 同期を待つ
        return True
    except Exception as e:
        print(f"⚠️ プロパティ追加エラー: {e}")
        return False

def write_to_notion(ticker: str, target_data: dict, report: str, scorecard: dict = None, md_path: str = None) -> bool:
    from dotenv import load_dotenv
    import os
    load_dotenv()
    db_id_env = os.environ.get("NOTION_DATABASE_ID")
    
    notion = get_notion_client()
    if not notion or not db_id_env:
        print("⚠️ Notion設定が不完全です。")
        return False
        
    db_id = db_id_env
    
    try:
        # 1. データベースの存在確認。もしページだったら中のDBを探す
        try:
            obj = notion.search().get("results", [])
            found_db = None
            for o in obj:
                if o["id"].replace("-", "") == db_id.replace("-", ""):
                    if o["object"] == "database":
                        found_db = o["id"]
                    elif o["object"] == "page":
                        # ページ内にあるDBを探す
                        children = notion.blocks.children.list(block_id=o["id"]).get("results", [])
                        for child in children:
                            if child["type"] == "child_database":
                                found_db = child["id"]
                                break
            if found_db:
                db_id = found_db
        except:
            pass

        # 2. データの構成
        signal = scorecard.get("signal", "WATCH") if scorecard else "WATCH"
        total_score = scorecard.get("total_score", 0) if scorecard else 0
        
        target_data = target_data or {}
        name = target_data.get("name") or ticker
        price = target_data.get("technical", {}).get("current_price", 0) if target_data.get("technical") else 0
        currency = target_data.get("currency", "USD")
        
        report = report or ""
        blocks = []
        limit = 1500
        for i in range(0, len(report), limit):
            chunk = report[i:i+limit]
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": chunk}}]}
            })

        title_text = f"{ticker} - {name}"[:150]
        ticker_text = str(ticker)[:50]
        price_text = f"{price} {currency}"[:50]

        properties = {
            "Name": {"title": [{"text": {"content": title_text}}]},
            "Ticker": {"rich_text": [{"text": {"content": ticker_text}}]},
            "Date": {"date": {"start": datetime.now().isoformat()}},
            "Signal": {"select": {"name": signal}},
            "Score": {"number": float(total_score)},
            "Price": {"rich_text": [{"text": {"content": price_text}}]}
        }
        
        # MD Link は Notion API が file:// URL を拒否するため送信しない
        # if md_path:
        #     properties["MD Link"] = {"url": f"file://{os.path.abspath(md_path)}"}

        has_ensured_props = False
        
        for attempt in range(4):
            try:
                response = notion.pages.create(
                    parent={"type": "database_id", "database_id": db_id},
                    properties=properties,
                    children=blocks[:100] # Notion制限: 100 blocks
                )
                print(f"✅ Notionに保存完了: {response.get('url')}")
                return True
            except Exception as e:
                err_msg = str(e).lower()
                if "not a property that exists" in err_msg or "property failed validation" in err_msg or "could not find property" in err_msg:
                    if not has_ensured_props:
                        print(f"⚠️ {e}")
                        ensure_database_properties(notion, db_id)
                        has_ensured_props = True
                        continue
                    elif "md link" in err_msg:
                         print("⚠️ MD Link プロパティが拒否されました。除外してリトライします。")
                         properties.pop("MD Link", None)
                         continue
                         
                    print(f"⏳ プロパティ同期待ち... ({attempt}/3)")
                    time.sleep(5)
                    continue
                print(f"❌ NotionAPI エラー: {e}")
                raise e
        return False
    
    except Exception as e:
        print(f"❌ Notion致命的エラー: {e}")
        return False
