import os
from dotenv import load_dotenv
from src.notion_writer import write_to_notion

# Ensure environment variables are loaded for the test
load_dotenv()

target_data = {
    "name": "Super Long Test Company " * 20,  # Ensure name is long enough to trigger limit if bug #4 is not completely fixed
    "technical": {"current_price": 999.99},
    "currency": "USD"
}
scorecard = {
    "signal": "BUY",
    "total_score": 99
}

# Create a dummy report with exactly 5000 characters
report_content = "あ" * 5000

print(f"Testing Notion with report length: {len(report_content)}")
print(f"Testing Notion with target_data name length: {len(target_data['name'])}")

result = write_to_notion(
    ticker="LONG.TEST",
    target_data=target_data,
    report=report_content,
    scorecard=scorecard,
    md_path="/home/liver/dummy_long_test.md"
)

if result:
    print("✅ Successfully wrote >2000 chars to Notion!")
else:
    print("❌ Failed to write to Notion")
