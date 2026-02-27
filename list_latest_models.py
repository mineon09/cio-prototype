import os
from google import genai
from dotenv import load_dotenv

# .envファイルから環境変数を読み込む
load_dotenv()

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

if not GEMINI_API_KEY:
    print("❌ エラー: GEMINI_API_KEY が .env ファイルに設定されていません。")
    exit(1)

# 最新の google-genai クライアントを初期化
client = genai.Client(api_key=GEMINI_API_KEY)

print("--- 利用可能なGeminiモデル一覧 (google-genai SDK) ---")
print(f"{'Model Name':<40} {'Display Name':<40}")
print("-" * 80)

try:
    # モデル一覧を取得
    # 注意: APIキーの権限やプランによっては一部のモデルが表示されない場合があります
    models = list(client.models.list())
    
    if not models:
        # クォータ制限などでリストが空の場合のヒント
        print("⚠ モデルが見つかりませんでした。")
        print("APIキーが有効であること、およびレート制限（429）に達していないか確認してください。")
        print("\n基本的な推論に使用可能な最新モデル識別子:")
        print("- gemini-3.1-flash")
        print("- gemini-3.1-pro")
        print("- gemini-2.5-flash")
    else:
        for m in models:
            # コンテンツ生成が可能なモデルをフィルタリング（必要に応じて）
            if 'generateContent' in m.supported_generation_methods:
                print(f"{m.name:<40} {m.display_name:<40}")

except Exception as e:
    print(f"❌ エラーが発生しました: {e}")
    if "429" in str(e):
        print("💡 ヒント: レート制限（Quota Exceeded）に達しているようです。数分待ってから再試行してください。")
