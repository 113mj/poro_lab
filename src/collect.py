"""ARAM (queue 450) snowball collector with random seeding.

Seeds : random KR match IDs inside the time window (any queue). From each LoL match hit,
        up to 2 participants who have a recent ARAM game become seeds. This avoids
        depending on the ranked ladder, whose players rarely play ARAM.
Loop  : take a random pending player (any depth) -> their latest few ARAM match IDs in
        the window -> fetch unseen matches -> save raw JSON + insert rows -> push the
        other participants into the frontier.
Resume: all state (players / matches / seed probes) lives in MySQL, so re-running continues.

Bias notes (see docs/DECISIONS.md):
- Few IDs per player and random frontier order limit heavy-user / friend-group clustering.
- Seeds are weighted toward people active in any queue during the window.

Usage : python src/collect.py --target 200 --days 14
"""
import argparse
import gzip
import json
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import bindparam, text

from db import get_engine
from riot import RiotClient

QUEUE = 450
PLATFORM, REGION = "kr", "asia"
ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "aram" / "matches"
SEEDS_PER_MATCH = 2   # cap per probed match: participants of one game are often a premade group


def init_schema(engine):
    sql = (ROOT / "src" / "schema.sql").read_text()
    with engine.begin() as c:
        for stmt in [s for s in sql.split(";") if s.strip()]:
            c.execute(text(stmt))


def id_num(match_id):
    return int(match_id.split("_")[1])


def window_id_range(api, start_ts):
    """Approximate the KR match ID range of the window from very active (challenger) players."""
    data = api.get(PLATFORM, "/lol/league/v4/challengerleagues/by-queue/RANKED_SOLO_5x5")
    nums = []
    for e in [e for e in data["entries"] if e.get("puuid")][:5]:
        ids = api.get(REGION, f"/lol/match/v5/matches/by-puuid/{e['puuid']}/ids",
                      params={"startTime": start_ts, "count": 100}) or []
        nums += [id_num(i) for i in ids]
    if not nums:
        raise RuntimeError("could not determine match ID range")
    return min(nums), max(nums)


def has_aram(api, puuid, start_ts):
    return bool(api.get(REGION, f"/lol/match/v5/matches/by-puuid/{puuid}/ids",
                        params={"queue": QUEUE, "count": 1, "startTime": start_ts}))


def pick_seeds(api, engine, rng, start_ts, n_seeds, max_probes):
    lo, hi = window_id_range(api, start_ts)
    print(f"  ID range KR_{lo} .. KR_{hi}")
    found, probes, stats = 0, 0, {}
    while found < n_seeds and probes < max_probes:
        probes += 1
        m = api.get(REGION, f"/lol/match/v5/matches/KR_{rng.randint(lo, hi)}", forbidden_ok=True)
        if m is None:
            stats["miss"] = stats.get("miss", 0) + 1
            continue
        q = m["info"]["queueId"]
        stats[q] = stats.get(q, 0) + 1
        if q == QUEUE:
            save_match(engine, m)
        puuids = list(m["metadata"]["participants"])
        rng.shuffle(puuids)
        taken = 0
        for p in puuids:
            if taken >= SEEDS_PER_MATCH or found >= n_seeds:
                break
            if has_aram(api, p, start_ts):
                add_player(engine, p, f"seed:q{q}", 0, m["metadata"]["matchId"])
                taken += 1
                found += 1
        if taken:
            print(f"  seeds {found}/{n_seeds}  (probes {probes})")
    print(f"  probe outcomes: {stats}")
    return found


def add_player(engine, puuid, source, depth, found_in):
    with engine.begin() as c:
        c.execute(text("INSERT IGNORE INTO players (puuid, source, depth, found_in) "
                       "VALUES (:p, :s, :d, :f)"),
                  {"p": puuid, "s": source, "d": depth, "f": found_in})


def next_player(engine):
    with engine.connect() as c:
        return c.execute(text("SELECT puuid, depth FROM players WHERE status='pending' "
                              "ORDER BY RAND() LIMIT 1")).first()


def known_matches(engine, ids):
    if not ids:
        return set()
    with engine.connect() as c:
        rows = c.execute(text("SELECT match_id FROM matches WHERE match_id IN :ids")
                         .bindparams(bindparam("ids", expanding=True)),
                         {"ids": list(ids)}).all()
    return {r[0] for r in rows}


def save_match(engine, m):
    info, mid = m["info"], m["metadata"]["matchId"]
    path = RAW / f"{mid}.json.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False)

    parts = info["participants"]
    win_team = next((t["teamId"] for t in info.get("teams", []) if t.get("win")), None)
    ver = info["gameVersion"]
    match_row = {
        "match_id": mid, "game_version": ver, "patch": ".".join(ver.split(".")[:2]),
        "queue_id": info["queueId"],
        "game_start": datetime.fromtimestamp(info["gameStartTimestamp"] / 1000, timezone.utc)
                              .replace(tzinfo=None),
        "duration_s": info["gameDuration"], "winning_team": win_team,
        "early_surrender": int(any(p.get("gameEndedInEarlySurrender") for p in parts)),
    }
    part_rows = []
    for p in parts:
        styles = p.get("perks", {}).get("styles", [])
        prim = next((s for s in styles if s.get("description") == "primaryStyle"), {})
        sub = next((s for s in styles if s.get("description") == "subStyle"), {})
        part_rows.append({
            "match_id": mid, "participant_id": p["participantId"], "puuid": p["puuid"],
            "team_id": p["teamId"], "win": int(p["win"]),
            "champion_id": p["championId"], "champion_name": p["championName"],
            "champ_level": p.get("champLevel"), "kills": p.get("kills"),
            "deaths": p.get("deaths"), "assists": p.get("assists"),
            "dmg_to_champs": p.get("totalDamageDealtToChampions"),
            "dmg_taken": p.get("totalDamageTaken"), "gold_earned": p.get("goldEarned"),
            **{f"item{i}": p.get(f"item{i}") for i in range(7)},
            "spell1": p.get("summoner1Id"), "spell2": p.get("summoner2Id"),
            "primary_style": prim.get("style"), "sub_style": sub.get("style"),
            "keystone": (prim.get("selections") or [{}])[0].get("perk"),
        })
    with engine.begin() as c:
        c.execute(text(f"INSERT IGNORE INTO matches ({', '.join(match_row)}) "
                       f"VALUES ({', '.join(':' + k for k in match_row)})"), match_row)
        cols = list(part_rows[0])
        c.execute(text(f"INSERT IGNORE INTO participants ({', '.join(cols)}) "
                       f"VALUES ({', '.join(':' + k for k in cols)})"), part_rows)
    return mid, [p["puuid"] for p in parts]


def count_matches(engine):
    with engine.connect() as c:
        return c.execute(text("SELECT COUNT(*) FROM matches")).scalar()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=200, help="stop when matches table reaches this")
    ap.add_argument("--days", type=int, default=14, help="collect games from the last N days")
    ap.add_argument("--ids-per-player", type=int, default=3)
    ap.add_argument("--seeds", type=int, default=15)
    ap.add_argument("--max-probes", type=int, default=300, help="random match IDs tried for seeding")
    ap.add_argument("--rng", type=int, default=42)
    args = ap.parse_args()

    rng = random.Random(args.rng)
    api, engine = RiotClient(), get_engine()
    init_schema(engine)
    start_ts = int((datetime.now(timezone.utc) - timedelta(days=args.days)).timestamp())

    with engine.connect() as c:
        has_players = c.execute(text("SELECT COUNT(*) FROM players")).scalar()
    t0 = time.time()
    if not has_players:
        print("[seeds] random match IDs -> participants with recent ARAM games")
        pick_seeds(api, engine, rng, start_ts, args.seeds, args.max_probes)
        print(f"  seeding took {(time.time() - t0) / 60:.1f} min")
    else:
        print(f"[resume] {has_players} players already in frontier")

    n = count_matches(engine)
    while n < args.target:
        pick = next_player(engine)
        if pick is None:
            print("frontier exhausted")
            break
        puuid, depth = pick
        ids = api.get(REGION, f"/lol/match/v5/matches/by-puuid/{puuid}/ids",
                      params={"queue": QUEUE, "count": args.ids_per_player,
                              "startTime": start_ts}) or []
        seen = known_matches(engine, ids)
        for mid in [i for i in ids if i not in seen]:
            if n >= args.target:
                break
            m = api.get(REGION, f"/lol/match/v5/matches/{mid}")
            if m is None or m["info"].get("queueId") != QUEUE:
                continue
            mid, puuids = save_match(engine, m)
            for p in puuids:
                if p != puuid:
                    add_player(engine, p, "snowball", depth + 1, mid)
            n += 1
            if n % 25 == 0:
                print(f"  {n}/{args.target} matches  ({(time.time() - t0) / 60:.1f} min)")
        with engine.begin() as c:
            c.execute(text("UPDATE players SET status='done', n_ids=:n WHERE puuid=:p"),
                      {"n": len(ids), "p": puuid})
    print(f"done: {count_matches(engine)} matches in DB, {(time.time() - t0) / 60:.1f} min total")


if __name__ == "__main__":
    main()
