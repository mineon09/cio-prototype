#!/usr/bin/env python3
"""
yfinance レート制限シミュレーション テスト

ローカル環境で Streamlit Cloud の状況を再現し、
フォールバックチェーンが正しく動作するか確認する。
"""
import os
import sys
import unittest.mock as mock

# dotenvを読み込み
from dotenv import load_dotenv
load_dotenv()

def test_rate_limit_simulation():
    """yfinance が 429 を返す状況をシミュレート"""
    
    print("=" * 60)
    print("🧪 yfinance レート制限シミュレーション開始")
    print("=" * 60)
    
    # 1. キャッシュを無効化（Streamlit Cloud の初回起動を再現）
    import tempfile
    fake_cache = tempfile.mkdtemp(prefix="test_cache_")
    print(f"\n📂 テスト用キャッシュ: {fake_cache} （空）")
    
    # 2. yfinance をモックして常に 429 エラーを投げる
    rate_limit_error = Exception("Too Many Requests. Rate limited. Try after a while.")
    
    # _fetch_yf_with_retry をモックで上書き
    from src import data_fetcher
    
    # _get_cache_dir をモックして空ディレクトリを返す
    original_get_cache_dir = data_fetcher._get_cache_dir
    data_fetcher._get_cache_dir = lambda: fake_cache
    
    # _fetch_yf_with_retry をモックして常にエラー
    original_fetch = data_fetcher._fetch_yf_with_retry
    
    call_count = 0
    def mock_fetch(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        print(f"  🔴 [MOCK] _fetch_yf_with_retry 呼び出し #{call_count} → 429 エラーを発生")
        raise rate_limit_error
    
    # tenacity のリトライもスキップするため、リトライなしの関数でパッチ
    data_fetcher._fetch_yf_with_retry = mock_fetch
    
    try:
        print("\n--- fetch_stock_data('8306.T') 実行 ---\n")
        result = data_fetcher.fetch_stock_data('8306.T')
        
        print("\n--- 結果 ---")
        print(f"  ticker: {result.get('ticker')}")
        print(f"  name: {result.get('name')}")
        print(f"  currency: {result.get('currency')}")
        print(f"  metrics: {result.get('metrics')}")
        print(f"  technical: {result.get('technical')}")
        print(f"  _data_source: {result.get('_data_source', '(なし)')}")
        
        metrics = result.get('metrics', {})
        technical = result.get('technical', {})
        
        print("\n--- フォールバック判定 ---")
        if len(metrics) < 1 and not technical:
            print(f"  ❌ 簡易プロンプトにフォールバック (metrics={len(metrics)}件, technical={len(technical)}件)")
            print(f"  → Streamlit Cloud でも同じ結果になります")
        else:
            print(f"  ✅ 詳細プロンプト生成可能 (metrics={len(metrics)}件, technical={len(technical)}件)")
            print(f"  → Streamlit Cloud でも正常に動作するはずです")
        
    finally:
        # モックを元に戻す
        data_fetcher._fetch_yf_with_retry = original_fetch
        data_fetcher._get_cache_dir = original_get_cache_dir
        
        # テスト用キャッシュを削除
        import shutil
        shutil.rmtree(fake_cache, ignore_errors=True)
    
    print("\n" + "=" * 60)
    print("🧪 テスト完了")
    print("=" * 60)


if __name__ == "__main__":
    test_rate_limit_simulation()
