import requests
SEC_HEADERS = {"User-Agent": "CIO-Prototype/1.0 (cio-analysis-safety@example.com)"}
url1 = "https://www.sec.gov/Archives/edgar/data/0001824920/000119312526071562/index.json"
url2 = "https://www.sec.gov/Archives/edgar/data/0001824920/0001193125-26-071562/index.json"
r1 = requests.get(url1, headers=SEC_HEADERS)
r2 = requests.get(url2, headers=SEC_HEADERS)
print("No hyphen status:", r1.status_code)
print("Hyphen status:", r2.status_code)
