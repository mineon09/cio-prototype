from src.data_fetcher import fetch_stock_data, select_competitors
import json
print("Testing Dividend Yield/ROE ...")
data = fetch_stock_data("7203.T")
print("Dividend Yield:", data["metrics"].get("dividend_yield"))
print("ROE:", data["metrics"].get("roe"))

print("\nTesting TOPX fallback ...")
res = select_competitors({"ticker": "4502.T", "name": "Takeda", "sector": "Health"})
print("competitors fallback:", res)
