#!/usr/bin/env python3
"""
yfinance 完全ブロック シミュレーション テスト

Layer 4 (info) も含めて yfinance が完全にブロックされた場合、
Layer 5 (J-Quants) → Layer 6 (Google Finance) で正しくフォールバックするか確認する。
"""
import os
import sys
import unittest.mock as mock

from dotenv import load_dotenv
load_dotenv()

def test_full_block_simulation():
    """yfinance が完全にブロックされた状況をシミュレート"""
    
    print("=" * 60)
    print("🧪 yfinance 完全ブロック シミュレーション開始")
    print("=" * 60)
    
    import tempfile
    fake_cache = tempfile.mkdtemp(prefix="test_cache_")
    print(f"\n📂 テスト用キャッシュ: {fake_cache} （空）")
    
    rate_limit_error = Exception("Too Many Requests. Rate limited. Try after a while.")
    
    from src import data_fetcher
    import yfinance as yf
    
    # _get_cache_dir をモック
    original_get_cache_dir = data_fetcher._get_cache_dir
    data_fetcher._get_cache_dir = lambda: fake_cache
    
    # _fetch_yf_with_retry をモック
    original_fetch = data_fetcher._fetch_yf_with_retry
    data_fetcher._fetch_yf_with_retry = lambda *a, **k: (_ for _ in ()).throw(rate_limit_error)
    
    # yf.Ticker().info もモック（Layer 4 をブロック）
    original_ticker = yf.Ticker
    class MockTicker:
        def __init__(self, *args, **kwargs):
            raise Exception("Too Many Requests. Rate limited. Try after a while.")
        @property
        def info(self):
            raise Exception("Too Many Requests. Rate limited. Try after a while.")
    yf.Ticker = MockTicker
    
    try:
        print("\n--- fetch_stock_data('8306.T') 実行 [yfinance 完全ブロック] ---\n")
        result = data_fetcher.fetch_stock_data('8306.T')
        
        print("\n--- 結果 ---")
        print(f"  ticker: {result.get('ticker')}")
        print(f"  name: {result.get('name')}")
        print(f"  metrics: {result.get('metrics')}")
        print(f"  technical: {result.get('technical')}")
        print(f"  _data_source: {result.get('_data_source', '(なし)')}")
        
        metrics = result.get('metrics', {})
        technical = result.get('technical', {})
        
        print("\n--- フォールバック判定 ---")
        if len(metrics) < 1 and not technical:
            print(f"  ❌ 簡易プロンプトにフォールバック (metrics={len(metrics)}件, technical={len(technical)}件)")
        else:
            print(f"  ✅ 詳細プロンプト生成可能 (metrics={len(metrics)}件, technical={len(technical)}件)")
        
    finally:
        data_fetcher._fetch_yf_with_retry = original_fetch
        data_fetcher._get_cache_dir = original_get_cache_dir
        yf.Ticker = original_ticker
        
        import shutil
        shutil.rmtree(fake_cache, ignore_errors=True)
    
    print("\n" + "=" * 60)
    print("🧪 テスト完了")
    print("=" * 60)


if __name__ == "__main__":
    test_full_block_simulation()
