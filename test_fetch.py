"""Test: fetch_stock_data with as_of_date via module import"""
import sys, os, io
sys.path.insert(0, os.path.dirname(__file__))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from datetime import datetime
from src.data_fetcher import fetch_stock_data

date = datetime(2024, 6, 1)
print(f"Testing fetch_stock_data('7203.T', as_of_date={date})")
data = fetch_stock_data('7203.T', as_of_date=date)

print(f"Keys: {list(data.keys())}")
print(f"technical keys: {list(data.get('technical', {}).keys())}")
print(f"current_price: {data.get('technical', {}).get('current_price')}")
print(f"metrics keys: {list(data.get('metrics', {}).keys())}")
print(f"metrics: {data.get('metrics', {})}")
print("SUCCESS!" if data.get('technical', {}).get('current_price') else "FAILED: no current_price")
