"""Inspect sample match JSON: where do augments / map info live?"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gzip
import json
from collections import Counter
from pathlib import Path

RAW = Path(__file__).resolve().parents[2] / "data" / "raw" / "sample"
HINTS = ("aug", "map", "mode", "mayhem", "arena", "quest", "anvil", "perk", "role", "subteam")


def load(p):
    with gzip.open(p, "rt", encoding="utf-8") as f:
        return json.load(f)


def walk_keys(obj, prefix=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield f"{prefix}{k}", v
            yield from walk_keys(v, f"{prefix}{k}.")
    elif isinstance(obj, list) and obj and isinstance(obj[0], dict):
        yield from walk_keys(obj[0], f"{prefix}[].")


matches = [load(p) for p in sorted((RAW / "matches").glob("*.json.gz"))]
print(f"matches: {len(matches)}")
if not matches:
    raise SystemExit

info = [m["info"] for m in matches]
for field in ("queueId", "mapId", "gameMode", "gameType"):
    print(f"{field:10s}", Counter(i.get(field) for i in info).most_common())
print("gameVersion", Counter(".".join(i["gameVersion"].split(".")[:2]) for i in info).most_common())
print("duration(min) median:", sorted(i["gameDuration"] for i in info)[len(info) // 2] / 60)

print("\n-- info-level keys --")
print(sorted(k for k in info[0] if k != "participants"))

p0 = info[0]["participants"][0]
print(f"\n-- participant keys ({len(p0)}) --")
print(sorted(p0))

print("\n-- keys matching hints (anywhere, with sample values) --")
seen = set()
for k, v in walk_keys(info[0]):
    leaf = k.split(".")[-1].lower()
    if any(h in leaf for h in HINTS) and k not in seen and not isinstance(v, (dict, list)):
        seen.add(k)
        print(f"  {k} = {v!r}")

aug_cols = sorted(k for k in p0 if "aug" in k.lower())
if aug_cols:
    print("\n-- augment value distribution across all participants --")
    for c in aug_cols:
        vals = Counter(p[c] for i in info for p in i["participants"])
        print(f"  {c}: {len(vals)} distinct, top: {vals.most_common(5)}")

tls = sorted((RAW / "timelines").glob("*.json.gz"))
if tls:
    t = load(tls[0])
    ev = Counter(e["type"] for f in t["info"]["frames"] for e in f["events"])
    print(f"\n-- timeline event types ({tls[0].name}) --")
    print(ev.most_common())
