import os
from datetime import datetime

MD_DIR_BASE = "data/reports"

def write_to_md(ticker: str, target_data: dict, report: str, scorecard: dict = None) -> str:
    """
    分析レポートをローカルのMarkdownファイルとして保存する
    
    保存先ディレクトリ構成: /data/reports/[YYYYMM]/[TICKER]_[YYYYMMDD_HHMM].md
    """
    now = datetime.now()
    month_dir = now.strftime("%Y%m")
    date_str = now.strftime("%Y%m%d_%H%M")
    
    # ターゲットディレクトリの作成
    target_dir = os.path.join(MD_DIR_BASE, month_dir)
    os.makedirs(target_dir, exist_ok=True)
    
    file_name = f"{ticker.replace('.', '_')}_{date_str}.md"
    file_path = os.path.join(target_dir, file_name)
    
    # スコア情報や基本データをフロントマター的に用意
    signal = scorecard.get("signal", "WATCH") if scorecard else "WATCH"
    total_score = scorecard.get("total_score", 0) if scorecard else 0
    name = target_data.get("name", ticker)
    price = target_data.get("technical", {}).get("current_price", "-")
    currency = target_data.get("currency", "")
    
    # Markdownコンテンツの構築
    content = f"""# {ticker} - {name} 分析レポート
    
**日付:** {now.strftime("%Y-%m-%d %H:%M")}
**現在価格:** {price} {currency}
**シグナル:** {signal}
**総合スコア:** {total_score}/10

---

## 📝 最終レポート
{report}
"""

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"📝 Markdown保存完了: {file_path}")
        return file_path
    except Exception as e:
        print(f"❌ Markdown保存失敗: {e}")
        return ""
