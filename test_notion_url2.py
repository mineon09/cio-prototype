import os
from dotenv import load_dotenv
load_dotenv()
from notion_client import Client
import time

api_key = os.environ.get("NOTION_API_KEY")
notion = Client(auth=api_key)
db_id = "d3c6a059-8dd1-4ec3-8b28-82dd23f01896"

print(f"Adding URL property to: {db_id}")
notion.databases.update(
    database_id=db_id,
    properties={"MD Link": {"url": {}}}
)
print("✅ URL property added!")

time.sleep(2)

print("Trying to add a row with file:// url...")
try:
    notion.pages.create(
        parent={"type": "database_id", "database_id": db_id},
        properties={
            "Name": {"title": [{"text": {"content": "Test URL"}}]},
            "MD Link": {"url": "file:///home/liver/test.md"}
        }
    )
    print("✅ Row added with URL!")
except Exception as e:
    print(f"❌ Error: {e}")
