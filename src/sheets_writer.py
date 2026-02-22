"""
sheets_writer.py - Google Sheets 出力モジュール
================================================
分析結果を Google Sheets に書き込む。
"""

import os, re, json, math
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID              = os.environ.get('SPREADSHEET_ID')
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')
GOOGLE_SHEETS_KEY_PATH      = os.environ.get('GOOGLE_SHEETS_KEY_PATH')

try:
    with open("config.json", encoding="utf-8") as f:
        CONFIG = json.load(f)
except Exception:
    CONFIG = {"sheets": {"output": "分析結果"}}


def get_sheets_client():
    """Google Sheets クライアントを認証・取得する。失敗時は None。"""
    if not SPREADSHEET_ID:
        return None
    
    creds = None
    try:
        # 1. raw JSON string からロード
        if GOOGLE_SERVICE_ACCOUNT_JSON:
            creds = Credentials.from_service_account_info(
                json.loads(GOOGLE_SERVICE_ACCOUNT_JSON),
                scopes=['https://www.googleapis.com/auth/spreadsheets',
                        'https://www.googleapis.com/auth/drive'])
        # 2. JSON ファイルパスからロード
        elif GOOGLE_SHEETS_KEY_PATH and os.path.exists(GOOGLE_SHEETS_KEY_PATH):
            creds = Credentials.from_service_account_file(
                GOOGLE_SHEETS_KEY_PATH,
                scopes=['https://www.googleapis.com/auth/spreadsheets',
                        'https://www.googleapis.com/auth/drive'])
        
        if not creds:
            return None

        gc = gspread.authorize(creds)
        print("✅ Google Sheets 認証成功")
        return gc
    except Exception as e:
        print(f"⚠️ Sheets認証失敗（出力なしで続行）: {e}")
        return None

def _sanitize_for_sheets(value):
    """
    Google Sheets API が受け付けない値 (NaN, Inf) を空文字列に置換する。
    """
    if value is None:
        return ""
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return ""
    return value

def write_system_log(gc, status: str, message: str, ticker: str = "System"):
    """実行ステータスとエラーログを System_Log シートに書き込む。"""
    if not gc:
        return
    try:
        sp = gc.open_by_key(SPREADSHEET_ID)
        sname = "System_Log"
        try:
            sheet = sp.worksheet(sname)
        except gspread.exceptions.WorksheetNotFound:
            sheet = sp.add_worksheet(title=sname, rows=10000, cols=4)  # C-5: 1000→10000
            sheet.append_row(["Timestamp", "Ticker", "Status", "Message"])

        row = [
            datetime.now().strftime('%Y/%m/%d %H:%M:%S'),
            ticker,
            status,
            message[:5000] # HIGH-007: Sheets 1セル上限50,000文字のうち5,000まで許容
        ]
        sheet.append_row(row)
        
        # エラー時は背景を赤っぽく
        if status.upper() in ["FAIL", "ERROR"]:
            last = len(sheet.get_all_values())
            sheet.format(f"A{last}:D{last}", {
                "backgroundColor": {"red": 0.95, "green": 0.85, "blue": 0.85},
            })

    except Exception as e:
        print(f"❌ System_Log Sheetsエラー: {e}")


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

        # C-2: scorecard のシグナルを最優先で使用（LLMレポートとの乖離防止）
        sc = scorecard or {}
        signal_from_scorecard = sc.get('signal', '')
        if signal_from_scorecard in ('BUY', 'WATCH', 'SELL'):
            signal_value = signal_from_scorecard
        else:
            sig_m = re.search(r'シグナル.*?(BUY|WATCH|SELL)', report) or re.search(r'\b(BUY|WATCH|SELL)\b', report)
            signal_value = sig_m.group(1) if sig_m else 'N/A'

        score_m = re.search(r'総合スコア.*?(\d+)/10', report)
        tech    = target_data.get('technical', {})

        # スコアカード値の取得
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
            signal_value,  # C-2: scorecard ベースのシグナル
            score_m.group(1) if score_m else 'N/A',
            str(fund_score), str(valu_score), str(tech_score), str(qual_score),
            str(competitors.get('direct',[]) + competitors.get('substitute',[])),
            yuho_risk_text or "対象外",
            report,
            table_str,
        ]
        
        # Sheets API エラーを防ぐためのサニタイズ
        safe_row = [_sanitize_for_sheets(val) for val in row]
        
        sheet.append_row(safe_row)
        last = len(sheet.get_all_values())
        sheet.format(f"L{last}:M{last}", {"wrapStrategy": "WRAP"})

        # シグナルに応じた行の色分け（C-2: scorecard ベース）
        if signal_value == "BUY":
            bg_color = {"red": 0.85, "green": 0.95, "blue": 0.85}
        elif signal_value == "SELL":
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
