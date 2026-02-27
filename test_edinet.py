import os
import requests
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("EDINET_API_KEY")
print("API Key:", api_key[:4] if api_key else "None")

url = "https://api.edinet-fsa.go.jp/api/v2/EdinetcodeDlInfo.json"
params = {"type": 2, "Subscription-Key": api_key}

resp = requests.get(url, params=params, allow_redirects=False)
print("Status:", resp.status_code)
print("Headers:", resp.headers)
print("Content[:200]:", resp.content[:200])
