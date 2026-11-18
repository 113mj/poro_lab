"""Patch collection windows (UTC).

Windows are used only to narrow match-ID queries; they are deliberately a little wide.
gameVersion is authoritative: every match is stored with its real patch, and only matches
whose gameVersion matches the target patch count toward the collection target.

16.22 patch notes (26.22) were posted 2026-11-03 19:00 UTC; patches ship every 2 weeks.
Tighten these from data later (min/max game_start per patch in the matches table).
"""
from datetime import datetime, timezone


def _utc(s):
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


PATCHES = {
    "16.20": (_utc("2026-10-06 15:00"), _utc("2026-10-21 06:00")),
    "16.21": (_utc("2026-10-20 15:00"), _utc("2026-11-04 03:00")),
    "16.22": (_utc("2026-11-03 15:00"), _utc("2026-11-18 03:00")),
}


def window(patch):
    if patch not in PATCHES:
        raise SystemExit(f"unknown patch {patch}; add it to src/patches.py")
    start, end = PATCHES[patch]
    now = datetime.now(timezone.utc)
    return int(start.timestamp()), int(min(end, now).timestamp())
