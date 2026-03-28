import sys
from src.sec_client import extract_sec_data
from src.analyzers import format_yuho_for_prompt

print("1. SECデータ取得開始...")
sec_data = extract_sec_data('xom')
print("SEC Data keys:", list(sec_data.keys()))

print("2. format_yuho_for_prompt実行...")
summary = format_yuho_for_prompt(sec_data)
print("Summary length:", len(summary))
print("Summary start:", repr(summary[:100]))

if not sec_data or not sec_data.get('available'):
    summary = "（SEC 10-K/10-Q データなし）"

print("3. 結果...")
print("Final summary length:", len(summary))
