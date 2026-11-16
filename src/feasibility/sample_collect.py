"""Stage 1: small sample collection to inspect ARAM: Mayhem match structure.

Seeds : KR solo-queue ladder, a few players from each tier (recorded to data/raw/sample/seeds.json)
Flow  : seeds -> recent queue-2400 match IDs -> dedupe -> match detail JSON (+ a few timelines)
Resume: matches already saved on disk are skipped.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gzip
import json
import random
from datetime import datetime, timezone
from pathlib import Path

from riot import RiotClient

QUEUE_ID = 2400            # ARAM: Mayhem (Riot queues.json)
PLATFORM = "kr"           # league-v4
REGION = "asia"           # match-v5 routing for KR
SEEDS_PER_TIER = 5
IDS_PER_SEED = 20
TARGET_MATCHES = 300
TIMELINES = 10
RANDOM_SEED = 42

APEX = ["challengerleagues", "grandmasterleagues", "masterleagues"]
DIVISION_TIERS = [("DIAMOND", "I"), ("EMERALD", "II"), ("PLATINUM", "II"),
                  ("GOLD", "II"), ("SILVER", "II"), ("BRONZE", "II")]

OUT = Path(__file__).resolve().parents[2] / "data" / "raw" / "sample"
MATCH_DIR = OUT / "matches"
TL_DIR = OUT / "timelines"


def save_gz(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


def pick_seeds(api, rng):
    seeds = []
    for league in APEX:
        data = api.get(PLATFORM, f"/lol/league/v4/{league}/by-queue/RANKED_SOLO_5x5")
        entries = [e for e in data["entries"] if e.get("puuid")]
        for e in rng.sample(entries, min(SEEDS_PER_TIER, len(entries))):
            seeds.append({"tier": data["tier"], "rank": e.get("rank"), "puuid": e["puuid"]})
    for tier, div in DIVISION_TIERS:
        entries = api.get(PLATFORM, f"/lol/league/v4/entries/RANKED_SOLO_5x5/{tier}/{div}",
                          params={"page": rng.randint(1, 5)})
        entries = [e for e in entries if e.get("puuid")]
        for e in rng.sample(entries, min(SEEDS_PER_TIER, len(entries))):
            seeds.append({"tier": tier, "rank": div, "puuid": e["puuid"]})
    return seeds


def main():
    rng = random.Random(RANDOM_SEED)
    api = RiotClient()

    print("[1/3] picking seeds from KR ladder")
    seeds = pick_seeds(api, rng)
    print(f"  {len(seeds)} seeds")

    print(f"[2/3] collecting queue {QUEUE_ID} match IDs")
    ids = set()
    for i, s in enumerate(seeds, 1):
        got = api.get(REGION, f"/lol/match/v5/matches/by-puuid/{s['puuid']}/ids",
                      params={"queue": QUEUE_ID, "count": IDS_PER_SEED}) or []
        s["n_ids"] = len(got)
        ids.update(got)
        if i % 10 == 0:
            print(f"  {i}/{len(seeds)} seeds, {len(ids)} unique IDs")
    print(f"  {len(ids)} unique match IDs")

    save_gz(OUT / "seeds.json.gz", {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "method": f"KR solo ladder, {SEEDS_PER_TIER}/tier, random.Random({RANDOM_SEED})",
        "seeds": seeds,
    })

    targets = sorted(ids)
    rng.shuffle(targets)
    targets = targets[:TARGET_MATCHES]

    print(f"[3/3] downloading {len(targets)} matches (+{TIMELINES} timelines)")
    done = skipped = 0
    for i, mid in enumerate(targets, 1):
        path = MATCH_DIR / f"{mid}.json.gz"
        if path.exists():
            skipped += 1
        else:
            m = api.get(REGION, f"/lol/match/v5/matches/{mid}")
            if m:
                save_gz(path, m)
                done += 1
        if i <= TIMELINES:
            tpath = TL_DIR / f"{mid}.json.gz"
            if not tpath.exists():
                t = api.get(REGION, f"/lol/match/v5/matches/{mid}/timeline")
                if t:
                    save_gz(tpath, t)
        if i % 50 == 0:
            print(f"  {i}/{len(targets)}")
    print(f"done: {done} new, {skipped} already on disk -> {MATCH_DIR}")


if __name__ == "__main__":
    main()
