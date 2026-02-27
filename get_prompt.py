import sys
import os
from datetime import datetime

# モジュールインポートのパスを通す
sys.path.append(os.getcwd())

try:
    from src.data_fetcher import fetch_stock_data
    from src.edinet_client import extract_yuho_data
    from src.macro_regime import detect_regime
    from src.analyzers import generate_scorecard, format_yuho_for_prompt
except ImportError as e:
    print(f"❌ モジュールのインポートに失敗しました: {e}")
    sys.exit(1)

def get_data(ticker):
    print(f"🔍 {ticker} の分析データを取得中...")
    
    # 1. 基礎データ取得
    try:
        data = fetch_stock_data(ticker)
    except Exception as e:
        print(f"❌ データ取得失敗: {e}")
        return
    
    # 2. マクロ環境判定
    try:
        regime = detect_regime(ticker)
    except Exception:
        regime = {"regime": "NEUTRAL"}
        
    # 3. 有報取得（日本株のみ）
    yuho = {}
    if ticker.endswith('.T'):
        try:
            yuho = extract_yuho_data(ticker)
        except Exception:
            yuho = {}

    # 4. スコアカード生成
    scorecard = generate_scorecard(
        data.get('metrics', {}), 
        data.get('technical', {}), 
        yuho, 
        sector=data.get('sector', ''), 
        macro_data=regime
    )

    print("\n" + "="*40)
    print("📋 AIプロンプト用 貼り付けデータ")
    print("="*40)
    
    print(f"\n【基本情報】")
    print(f"銘柄: {data.get('name', '不明')} ({ticker})")
    print(f"市場レジーム: {regime.get('regime', 'NEUTRAL')} ({regime.get('detail', 'N/A')})")
    
    print(f"\n【1. スコアカード概要】")
    print(scorecard.get('summary_text', '生成失敗'))
    
    print(f"\n【2. 定性データ・有報要約】")
    yuho_text = format_yuho_for_prompt(yuho)
    print(yuho_text if yuho_text else "（定性データなし）")
    
    print("\n" + "="*40)
    print("💡 この内容を AI_ANALYSIS_PROMPT.md の [ ] 部分に貼り付けてください。")
    print("="*40)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        ticker = input("分析したい銘柄コードを入力してください（例: 7203.T）: ").strip()
    else:
        ticker = sys.argv[1]
    
    if ticker:
        get_data(ticker.upper())
    else:
        print("❌ 銘柄コードを入力してください。")
