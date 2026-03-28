import requests
import json
SEC_HEADERS = {"User-Agent": "CIO-Prototype/1.0 (cio-analysis-safety@example.com)"}
index_url = "https://www.sec.gov/Archives/edgar/data/0001824920/000119312526071562/index.json"
idx_resp = requests.get(index_url, headers=SEC_HEADERS, timeout=15)
idx_data = idx_resp.json()
files = idx_data.get('directory', {}).get('item', [])
target_file = None
for f in files:
    name = f.get('name', '').lower()
    if name.endswith('.htm') or name.endswith('.txt'):
        size = int(f.get('size', 0))
        if size > 500000 and '-ex' not in name:
            target_file = f.get('name')
            print("Found!", target_file, size)
            break
