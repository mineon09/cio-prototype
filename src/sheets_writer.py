"""
sheets_writer.py - Google Sheets 出力モジュール
================================================
分析結果を Google Sheets に書き込む。
"""

import os, re, json
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID              = os.environ.get('SPREADSHEET_ID')
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')

try:
    with open("config.json", encoding="utf-8") as f:
        CONFIG = json.load(f)
except Exception:
    CONFIG = {"sheets": {"output": "分析結果"}}


def get_sheets_client():
    """Google Sheets クライアントを認証・取得する。失敗時は None。"""
    if not GOOGLE_SERVICE_ACCOUNT_JSON or not SPREADSHEET_ID:
        return None
    try:
        creds = Credentials.from_service_account_info(
            json.loads(GOOGLE_SERVICE_ACCOUNT_JSON),
            scopes=['https://www.googleapis.com/auth/spreadsheets',
                    'https://www.googleapis.com/auth/drive'])
        gc = gspread.authorize(creds)
        print("✅ Google Sheets 認証成功")
        return gc
    except Exception as e:
        print(f"⚠️ Sheets認証失敗（出力なしで続行）: {e}")
        return None


def write_to_sheets(gc, target_ticker: str, target_data: dict,
                    competitors: dict, report: str, table_str: str,
                    yuho_data: dict = None, scorecard: dict = None):
    """分析結果を Google Sheets に1行追記する。"""
    try:
        sp = gc.open_by_key(SPREADSHEET_ID)
        sname = CONFIG['sheets']['output']
        try:
            sheet = sp.worksheet(sname)
        except:
            sheet = sp.add_worksheet(sname, rows=1000, cols=13)
            sheet.append_row([
                "日付", "銘柄", "価格", "シグナル", "総合スコア",
                "地力", "割安度", "タイミング", "定性",
                "比較対象", "有報リスク", "レポート", "対戦表",
            ])

        sig_m   = re.search(r'シグナル.*?(BUY|WATCH|SELL)', report) or re.search(r'\b(BUY|WATCH|SELL)\b', report)
        score_m = re.search(r'総合スコア.*?(\d+)/10', report)
        tech    = target_data.get('technical', {})

        # スコアカード値の取得
        sc = scorecard or {}
        fund_score = sc.get('fundamental', {}).get('score', 'N/A')
        valu_score = sc.get('valuation', {}).get('score', 'N/A')
        tech_score = sc.get('technical', {}).get('score', 'N/A')
        qual_score = sc.get('qualitative', {}).get('score', 'N/A')

        # 有報リスク要約
        yuho_risk_text = ""
        if yuho_data and yuho_data.get('available'):
            risks = yuho_data.get('risk_top3', [])
            yuho_risk_text = " / ".join(
                f"[{r.get('severity','?')}]{r.get('risk','不明')}" for r in risks[:3]
            )

        row = [
            datetime.now().strftime('%Y/%m/%d %H:%M'),
            target_ticker,
            f"{tech.get('current_price','N/A')} {target_data.get('currency','')}",
            sig_m.group(1)   if sig_m   else "N/A",
            score_m.group(1) if score_m else "N/A",
            str(fund_score), str(valu_score), str(tech_score), str(qual_score),
            str(competitors.get('direct',[]) + competitors.get('substitute',[])),
            yuho_risk_text or "対象外",
            report,
            table_str,
        ]
        sheet.append_row(row)
        last = len(sheet.get_all_values())
        sheet.format(f"L{last}:M{last}", {"wrapStrategy": "WRAP"})

        # シグナルに応じた行の色分け
        signal = sig_m.group(1) if sig_m else ""
        if signal == "BUY":
            bg_color = {"red": 0.85, "green": 0.95, "blue": 0.85}
        elif signal == "SELL":
            bg_color = {"red": 0.95, "green": 0.85, "blue": 0.85}
        else:
            bg_color = None

        if bg_color:
            sheet.format(f"A{last}:K{last}", {
                "backgroundColor": bg_color,
            })

        print(f"✅ スプレッドシート書き込み完了（行 {last}）")
    except Exception as e:
        print(f"❌ Sheetsエラー: {e}")
