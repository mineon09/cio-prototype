import requests
SEC_HEADERS = {"User-Agent": "CIO-Prototype/1.0 (cio-analysis-safety@example.com)"}
index_url = "https://www.sec.gov/Archives/edgar/data/0001824920/000119312526071562/index.json"
resp = requests.get(index_url, headers=SEC_HEADERS)
print("status:", resp.status_code)
data = resp.json()
for f in data.get('directory', {}).get('item', []):
    print(f["name"], f["size"])
