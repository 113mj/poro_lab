"""Minimal Riot API client: per-host rate limiting + 429/5xx retry.

The API key is read from .env (RIOT_API_KEY) and is never logged.
"""
import os
import time
from collections import deque
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Dev/personal key limits: 20 req / 1s, 100 req / 120s, applied per routing host.
# Stay slightly under to leave headroom.
LIMITS = [(18, 1.0), (95, 120.0)]


class RiotClient:
    def __init__(self):
        key = os.getenv("RIOT_API_KEY")
        if not key:
            raise RuntimeError("RIOT_API_KEY missing in .env")
        self.session = requests.Session()
        self.session.headers["X-Riot-Token"] = key
        self.calls = {}  # host -> deque of timestamps

    def _wait_for_slot(self, host):
        q = self.calls.setdefault(host, deque())
        while True:
            now = time.monotonic()
            longest = max(w for _, w in LIMITS)
            while q and now - q[0] > longest:
                q.popleft()
            wait = 0.0
            for limit, window in LIMITS:
                recent = [t for t in q if now - t < window]
                if len(recent) >= limit:
                    wait = max(wait, window - (now - recent[0]) + 0.05)
            if wait <= 0:
                q.append(now)
                return
            time.sleep(wait)

    def get(self, host, path, params=None, max_retries=5, forbidden_ok=False):
        """forbidden_ok: return None on 403 (restricted matches, e.g. queue 2400)
        instead of treating it as an invalid key."""
        url = f"https://{host}.api.riotgames.com{path}"
        for attempt in range(max_retries):
            self._wait_for_slot(host)
            r = self.session.get(url, params=params, timeout=15)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                return None
            if r.status_code == 429:
                retry = float(r.headers.get("Retry-After", 5))
                print(f"  429 on {host}{path[:40]}... sleeping {retry:.0f}s")
                time.sleep(retry)
                continue
            if r.status_code in (500, 502, 503, 504):
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 403 and forbidden_ok:
                return None
            if r.status_code in (401, 403):
                raise RuntimeError(f"{r.status_code}: API key invalid or expired")
            raise RuntimeError(f"{r.status_code} on {path}: {r.text[:200]}")
        raise RuntimeError(f"gave up after {max_retries} retries: {path}")
