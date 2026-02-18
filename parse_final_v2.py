
import re

try:
    with open("final_report_v2.md", "r", encoding="utf-8") as f:
        lines = f.readlines()
except:
    with open("final_report_v2.md", "r", encoding="utf-16le") as f:
        lines = f.readlines()

print("Parsed Rows:")
for line in lines:
    if "|" in line and "Strategy" not in line and ":---" not in line:
        print(line.strip())
