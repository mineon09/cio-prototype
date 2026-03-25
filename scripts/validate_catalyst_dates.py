#!/usr/bin/env python3
"""
カタリスト日付バリデーション - dogfooding テスト
修正後の動作確認用スクリプト

Usage:
    python scripts/validate_catalyst_dates.py XOM AMD 8306.T
"""
import sys
import re
from datetime import datetime

sys.path.append(".")
from src.data_fetcher import fetch_stock_data
from src.industry_trends import fetch_all_industry_data


def validate_ticker(ticker: str) -> dict:
    today = datetime.now()
    current_year = today.year
    current_quarter_num = (today.month - 1) // 3 + 1

    # fetch base data to get sector/name
    data = fetch_stock_data(ticker)
    sector = data.get("sector", "Technology")
    company_name = data.get("name", ticker)

    # fetch industry data which contains catalysts
    industry_data = fetch_all_industry_data(ticker, sector=sector, company_name=company_name)
    catalysts = industry_data.get("catalysts", {}).get("catalysts", [])

    results = {
        "ticker": ticker,
        "total": len(catalysts),
        "passed": 0,
        "failed": [],
    }

    for cat in catalysts:
        timing = str(
            cat.get("expected_date", "")
            or cat.get("expected_timing", "")
            or cat.get("timing", "")
            or cat.get("date", "")
        )
        year_match = re.search(r"(20\d{2})", timing)

        if year_match:
            year = int(year_match.group(1))
            if year < current_year:
                results["failed"].append({
                    "event": str(cat.get("event", ""))[:40],
                    "timing": timing,
                    "issue": "past_year",
                })
                continue
            if year == current_year:
                q_match = re.search(r"Q(\d)", timing, re.IGNORECASE)
                if q_match and int(q_match.group(1)) < current_quarter_num:
                    results["failed"].append({
                        "event": str(cat.get("event", ""))[:40],
                        "timing": timing,
                        "issue": "past_quarter",
                    })
                    continue
        results["passed"] += 1

    return results


if __name__ == "__main__":
    tickers = sys.argv[1:] or ["XOM", "AMD"]
    all_passed = True

    print(f"\n{'='*50}")
    print(f"カタリスト日付バリデーション ({datetime.now().strftime('%Y-%m-%d')})")
    print(f"{'='*50}")

    for ticker in tickers:
        result = validate_ticker(ticker)
        status = "✅ PASS" if not result["failed"] else "❌ FAIL"
        print(f"\n{status} {ticker}: {result['passed']}/{result['total']} 件合格")

        for f in result["failed"]:
            print(f"  → {f['issue']}: [{f['timing']}] {f['event']}")
            all_passed = False

    print(f"\n{'='*50}")
    print(f"総合結果: {'✅ 全銘柄合格' if all_passed else '❌ 要修正あり'}")
    sys.exit(0 if all_passed else 1)
