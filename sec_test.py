import subprocess
import requests
import json

SEC_HEADERS = {"User-Agent": "CIO-Prototype/1.0 (cio-analysis-safety@example.com)"}
url = "https://data.sec.gov/submissions/CIK0001824920.json"
resp = requests.get(url, headers=SEC_HEADERS)
data = resp.json()
recent = data.get('filings', {}).get('recent', {})
forms = recent.get('form', [])
for i, f in enumerate(forms):
    if f == "10-K":
        acc = recent["accessionNumber"][i].replace("-", "")
        doc = recent["primaryDocument"][i]
        print(f"File: {doc}")
        full_url = f"https://www.sec.gov/Archives/edgar/data/0001824920/{acc}/{doc}"
        print(full_url)
        content = requests.get(full_url, headers=SEC_HEADERS).text
        print(f"Len: {len(content)}")
        print(content[:500])
        break
