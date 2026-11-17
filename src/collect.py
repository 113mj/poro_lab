"""ARAM (queue 450) snowball collector, one patch at a time, with random seeding.

Seeds : random KR match IDs inside the patch window (any queue). From each LoL match hit,
        up to 2 participants who have an ARAM game in the window become seeds. This avoids
        depending on the ranked ladder, whose players rarely play ARAM.
Loop  : take a random pending player of this patch -> their latest few ARAM match IDs in
        the window -> fetch unseen matches -> save raw JSON + insert rows -> push the
        other participants into this patch's frontier.
Patch : the window (src/patches.py) only narrows queries. Every match is stored with its
        real gameVersion; only matches of the target patch count toward --target.
Resume: all state (players per patch / matches) lives in MySQL, so re-running continues.

Bias notes (see docs/DECISIONS.md):
- Few IDs per player and random frontier order limit heavy-user / friend-group clustering.
- Seeds are weighted toward people active in any queue during the window.

Usage : python -u src/collect.py --patch 16.22 --target 20000
"""
import argparse
import gzip
import json
import random
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import bindparam, text

from db import get_engine
from patches import window
from riot import RiotClient

QUEUE = 450
PLATFORM, REGION = "kr", "asia"
ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "aram" / "matches"
SEEDS_PER_MATCH = 2   # cap per probed match: participants of one game are often a premade group


def log(msg):
    print(f"[{datetime.now():%m-%d %H:%M:%S}] {msg}", flush=True)


def init_schema(engine):
    sql = (ROOT / "src" / "schema.sql").read_text()
    with engine.begin() as c:
        for stmt in [s for s in sql.split(";") if s.strip()]:
            c.execute(text(stmt))


def id_num(match_id):
    return int(match_id.split("_")[1])


def window_id_range(api, start_ts, end_ts):
    """Approximate the KR match ID range of the window from very active (challenger) players."""
    data = api.get(PLATFORM, "/lol/league/v4/challengerleagues/by-queue/RANKED_SOLO_5x5")
    nums = []
    for e in [e for e in data["entries"] if e.get("puuid")][:8]:
        ids = api.get(REGION, f"/lol/match/v5/matches/by-puuid/{e['puuid']}/ids",
                      params={"startTime": start_ts, "endTime": end_ts, "count": 100}) or []
        nums += [id_num(i) for i in ids]
    if not nums:
        raise RuntimeError("could not determine match ID range")
    return min(nums), max(nums)


def aram_ids(api, puuid, start_ts, end_ts, count):
    return api.get(REGION, f"/lol/match/v5/matches/by-puuid/{puuid}/ids",
                   params={"queue": QUEUE, "count": count,
                           "startTime": start_ts, "endTime": end_ts}) or []


def pick_seeds(api, engine, rng, patch, start_ts, end_ts, n_seeds, max_probes):
    lo, hi = window_id_range(api, start_ts, end_ts)
    log(f"ID range KR_{lo} .. KR_{hi}")
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
            if aram_ids(api, p, start_ts, end_ts, 1):
                add_player(engine, patch, p, f"seed:q{q}", 0, m["metadata"]["matchId"])
                taken += 1
                found += 1
        if taken:
            log(f"seeds {found}/{n_seeds}  (probes {probes})")
    log(f"probe outcomes: {stats}")
    return found


def add_player(engine, patch, puuid, source, depth, found_in):
    with engine.begin() as c:
        c.execute(text("INSERT IGNORE INTO players (patch, puuid, source, depth, found_in) "
                       "VALUES (:pt, :p, :s, :d, :f)"),
                  {"pt": patch, "p": puuid, "s": source, "d": depth, "f": found_in})


def add_players(engine, patch, puuids, depth, found_in):
    if not puuids:
        return
    with engine.begin() as c:
        c.execute(text("INSERT IGNORE INTO players (patch, puuid, source, depth, found_in) "
                       "VALUES (:pt, :p, 'snowball', :d, :f)"),
                  [{"pt": patch, "p": p, "d": depth, "f": found_in} for p in puuids])


def next_player(engine, patch):
    with engine.connect() as c:
        return c.execute(text("SELECT puuid, depth FROM players "
                              "WHERE patch=:pt AND status='pending' ORDER BY RAND() LIMIT 1"),
                         {"pt": patch}).first()


def known_matches(engine, ids):
    if not ids:
        return set()
    with engine.connect() as c:
        rows = c.execute(text("SELECT match_id FROM matches WHERE match_id IN :ids")
                         .bindparams(bindparam("ids", expanding=True)),
                         {"ids": list(ids)}).all()
    return {r[0] for r in rows}


def save_match(engine, m):
    """Store raw JSON + rows. Returns the match's patch string."""
    info, mid = m["info"], m["metadata"]["matchId"]
    path = RAW / f"{mid}.json.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False)

    parts = info["participants"]
    win_team = next((t["teamId"] for t in info.get("teams", []) if t.get("win")), None)
    ver = info["gameVersion"]
    patch = ".".join(ver.split(".")[:2])
    match_row = {
        "match_id": mid, "game_version": ver, "patch": patch,
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
    return patch


def count_patch(engine, patch):
    with engine.connect() as c:
        return c.execute(text("SELECT COUNT(*) FROM matches WHERE patch=:pt"), {"pt": patch}).scalar()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--patch", required=True, help="e.g. 16.22 (window defined in src/patches.py)")
    ap.add_argument("--target", type=int, default=20000, help="stop when this patch has N matches")
    ap.add_argument("--ids-per-player", type=int, default=3)
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--max-probes", type=int, default=400, help="random match IDs tried for seeding")
    ap.add_argument("--rng", type=int, default=42)
    args = ap.parse_args()

    rng = random.Random(args.rng)
    api, engine = RiotClient(), get_engine()
    init_schema(engine)
    start_ts, end_ts = window(args.patch)
    log(f"patch {args.patch}  window {datetime.fromtimestamp(start_ts, timezone.utc):%Y-%m-%d %H:%M} "
        f"~ {datetime.fromtimestamp(end_ts, timezone.utc):%Y-%m-%d %H:%M} UTC  target {args.target}")

    with engine.connect() as c:
        has_players = c.execute(text("SELECT COUNT(*) FROM players WHERE patch=:pt"),
                                {"pt": args.patch}).scalar()
    if not has_players:
        log("seeding: random match IDs -> participants with ARAM games in the window")
        pick_seeds(api, engine, rng, args.patch, start_ts, end_ts, args.seeds, args.max_probes)
    else:
        log(f"resume: {has_players} players already in the {args.patch} frontier")

    n = count_patch(engine, args.patch)
    other, t0, last_log = 0, time.time(), n
    log(f"start: {n} matches of {args.patch} in DB")
    while n < args.target:
        pick = next_player(engine, args.patch)
        if pick is None:
            log("frontier exhausted")
            break
        puuid, depth = pick
        try:
            ids = aram_ids(api, puuid, start_ts, end_ts, args.ids_per_player)
            seen = known_matches(engine, ids)
            for mid in [i for i in ids if i not in seen]:
                m = api.get(REGION, f"/lol/match/v5/matches/{mid}")
                if m is None or m["info"].get("queueId") != QUEUE:
                    continue
                if save_match(engine, m) == args.patch:
                    n += 1
                else:
                    other += 1
                add_players(engine, args.patch,
                            [p for p in m["metadata"]["participants"] if p != puuid], depth + 1, mid)
            status = "done"
        except RuntimeError as e:
            if "invalid or expired" in str(e):
                log(f"STOP: {e}")
                raise
            log(f"skip player after error: {e}")
            ids, status = [], "error"
        with engine.begin() as c:
            c.execute(text("UPDATE players SET status=:s, n_ids=:n WHERE patch=:pt AND puuid=:p"),
                      {"s": status, "n": len(ids), "pt": args.patch, "p": puuid})
        if n - last_log >= 250:
            last_log = n
            el = (time.time() - t0) / 3600
            log(f"{n}/{args.target} matches of {args.patch}  (+{other} other patch)  {el:.1f}h elapsed")
    log(f"done: {count_patch(engine, args.patch)} matches of {args.patch}, "
        f"{other} other-patch matches stored, {(time.time() - t0) / 3600:.1f}h")


if __name__ == "__main__":
    main()
