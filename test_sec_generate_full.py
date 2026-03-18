import sys
from datetime import datetime
from src.sec_client import extract_sec_data
from src.analyzers import format_yuho_for_prompt
from generate_prompt import collect_data_minimal, build_high_quality_prompt

print("1. collect_data_minimal実行...")
data, calls, yuho_summary = collect_data_minimal('xom', use_cache=True)
print("yuho_summary length:", len(yuho_summary))
print("yuho_summary content start:", repr(yuho_summary[:100]))

print("2. build_high_quality_prompt実行...")
prompt = build_high_quality_prompt(
    ticker='xom',
    company_name=data.get('name', 'xom'),
    sector=data.get('sector', 'Unknown'),
    as_of_date=datetime.now().strftime("%Y-%m-%d"),
    regime=data.get('regime', 'NEUTRAL'),
    regime_weights=data.get('regime_weights', {}),
    scorecard=data.get('scorecard', {}),
    financial_metrics=data.get('metrics', {}),
    technical_data=data.get('technical', {}),
    yuho_summary=yuho_summary,
)

print("Prompt section 5 length:", len(prompt.split('5. 定性データ・有価証券報告書要約')[1].split('6. 分析タスク')[0]))
print("Prompt section 5 content:", repr(prompt.split('5. 定性データ・有価証券報告書要約')[1].split('6. 分析タスク')[0]))
