import sys
import os
import io
from datetime import datetime

# Windowsの文字化け対策
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(__file__))
from src.data_fetcher import fetch_stock_data

ticker = "7203.T"
# 過去の特定の日付（2024年6月1日）でテスト
test_date = datetime(2024, 6, 1)

print(f"--- Testing {ticker} as of {test_date.date()} ---")

try:
    data = fetch_stock_data(ticker, as_of_date=test_date)
    
    metrics = data.get('metrics', {})
    print("\n[Extracted Metrics]")
    for k, v in metrics.items():
        print(f"  {k}: {v}")
    
    technical = data.get('technical', {})
    print("\n[Technical Data]")
    print(f"  Current Price: {technical.get('current_price')}")
    print(f"  RSI: {technical.get('rsi')}")
    
    # 判定に必要な主要指標が取れているか
    required = ['roe', 'op_margin', 'equity_ratio']
    missing = [m for m in required if metrics.get(m) is None]
    
    if not missing:
        print("\n✅ SUCCESS: All major metrics extracted!")
    else:
        print(f"\n❌ FAILED: Missing metrics: {missing}")
        
except Exception as e:
    print(f"\n💥 CRASH: {e}")
    import traceback
    traceback.print_exc()
