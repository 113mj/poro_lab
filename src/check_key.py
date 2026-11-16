"""Verify RIOT_API_KEY in .env works. Never prints the key itself."""
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()
key = os.getenv("RIOT_API_KEY")
if not key:
    sys.exit("RIOT_API_KEY is empty. Put it in .env")

url = "https://kr.api.riotgames.com/lol/status/v4/platform-data"
r = requests.get(url, headers={"X-Riot-Token": key}, timeout=10)

if r.status_code == 200:
    print("OK: key works (KR platform status reachable)")
elif r.status_code in (401, 403):
    print(f"FAIL {r.status_code}: key invalid or expired -> regenerate on developer portal")
else:
    print(f"FAIL {r.status_code}: {r.text[:200]}")
