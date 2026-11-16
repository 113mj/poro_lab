"""Probe: how far back can we collect ARAM (queue 450) matches on KR?

1. Find a few ARAM players (ladder seed -> ARAM match -> participants).
2. For each, query match IDs in monthly startTime/endTime windows going back 24 months.
3. For the oldest ID found per window, fetch the match detail and record gameVersion.

Output: printed table + data/raw/backfill_probe.json.gz
"""
import gzip
import json
import random
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from riot import RiotClient

QUEUE = 450
PLATFORM, REGION = "kr", "asia"
N_PLAYERS = 6
MONTHS_BACK = 24
OUT = Path(__file__).resolve().parent.parent / "data" / "raw" / "backfill_probe.json.gz"


def find_aram_players(api, rng):
    entries = api.get(PLATFORM, "/lol/league/v4/entries/RANKED_SOLO_5x5/GOLD/II", params={"page": 1})
    rng.shuffle(entries)
    for e in entries:
        ids = api.get(REGION, f"/lol/match/v5/matches/by-puuid/{e['puuid']}/ids",
                      params={"queue": QUEUE, "count": 1}) or []
        if ids:
            m = api.get(REGION, f"/lol/match/v5/matches/{ids[0]}")
            puuids = m["metadata"]["participants"]
            rng.shuffle(puuids)
            return puuids[:N_PLAYERS]
    raise RuntimeError("no ARAM player found in seed page")


def main():
    rng = random.Random(7)
    api = RiotClient()
    players = find_aram_players(api, rng)
    print(f"{len(players)} ARAM players found")

    now = datetime.now(timezone.utc)
    rows = []
    for m in range(MONTHS_BACK):
        end = now - timedelta(days=30 * m)
        start = end - timedelta(days=30)
        n_ids, sample_id = 0, None
        for p in players:
            ids = api.get(REGION, f"/lol/match/v5/matches/by-puuid/{p}/ids",
                          params={"queue": QUEUE, "count": 100,
                                  "startTime": int(start.timestamp()),
                                  "endTime": int(end.timestamp())}) or []
            n_ids += len(ids)
            if ids and sample_id is None:
                sample_id = ids[-1]
        version, detail_ok = None, None
        if sample_id:
            d = api.get(REGION, f"/lol/match/v5/matches/{sample_id}")
            detail_ok = d is not None
            version = d["info"]["gameVersion"] if d else None
        row = {"months_ago": m, "window_start": start.date().isoformat(),
               "ids": n_ids, "sample_id": sample_id, "detail_ok": detail_ok,
               "gameVersion": version}
        rows.append(row)
        print(f"{m:2d}m  {start.date()}  ids={n_ids:4d}  detail={detail_ok}  ver={version}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT, "wt", encoding="utf-8") as f:
        json.dump({"probed_at": now.isoformat(), "players": len(players), "rows": rows}, f)


if __name__ == "__main__":
    main()
