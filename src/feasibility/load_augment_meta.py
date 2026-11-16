"""Load augment metadata from CommunityDragon into MySQL for browsing.

Tables (rebuilt on every run):
  augment_meta       one row per augment (id, names ko/en, rarity, icon folder, base name)
  augment_mode_list  which mode's augment list contains which augment (CHERRY / KIWI / KIWI_JADE)
  cdragon_meta       which CommunityDragon version this was loaded from
View:
  v_augment_modes    augment_meta + in_kiwi / in_kiwi_jade / in_cherry_list flags
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
from pathlib import Path

import pandas as pd
import requests
from sqlalchemy import text

from db import get_engine

BASE = "https://raw.communitydragon.org/latest"
GD = f"{BASE}/plugins/rcp-be-lol-game-data/global"
RAW = Path(__file__).resolve().parents[2] / "data" / "raw" / "cdragon"


def fetch(url, name):
    RAW.mkdir(parents=True, exist_ok=True)
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    (RAW / name).write_text(r.text, encoding="utf-8")
    return r.json()


def main():
    version = fetch(f"{BASE}/content-metadata.json", "content-metadata.json").get("version")
    en = fetch(f"{GD}/default/v1/cherry-augments.json", "cherry-augments.en.json")
    ko = fetch(f"{GD}/ko_kr/v1/cherry-augments.json", "cherry-augments.ko.json")
    lists = fetch(f"{GD}/default/v1/augment-lists.json", "augment-lists.json")

    ko_name = {a["id"]: a["nameTRA"] for a in ko}
    meta = pd.DataFrame([{
        "augment_id": a["id"],
        "name_id": a["augmentNameId"],
        "name_ko": ko_name.get(a["id"]),
        "name_en": a["nameTRA"],
        "rarity": a["rarity"].removeprefix("k"),
        "icon_folder": a["augmentSmallIconPath"].split("/Augments/")[0].split("/")[-1] or None,
        "base_name_id": a["augmentNameId"].removeprefix("ARAM_"),
        "icon_path": a["augmentSmallIconPath"],
    } for a in en])

    modes = pd.DataFrame([
        {"mode_name": l["modeName"], "name_id": p.split("/")[-1]}
        for l in lists for p in l["augmentList"]
    ]).drop_duplicates()

    eng = get_engine()
    with eng.begin() as c:
        c.execute(text("DROP VIEW IF EXISTS v_augment_modes"))
        for t in ("augment_mode_list", "augment_meta", "cdragon_meta"):
            c.execute(text(f"DROP TABLE IF EXISTS {t}"))
        c.execute(text("""
            CREATE TABLE augment_meta (
                augment_id   INT PRIMARY KEY,
                name_id      VARCHAR(100) NOT NULL,
                name_ko      VARCHAR(100),
                name_en      VARCHAR(100),
                rarity       VARCHAR(20),
                icon_folder  VARCHAR(30),
                base_name_id VARCHAR(100),
                icon_path    VARCHAR(255),
                INDEX (name_id), INDEX (base_name_id)
            )"""))
        c.execute(text("""
            CREATE TABLE augment_mode_list (
                mode_name VARCHAR(30)  NOT NULL,
                name_id   VARCHAR(100) NOT NULL,
                PRIMARY KEY (mode_name, name_id)
            )"""))
        c.execute(text("""
            CREATE TABLE cdragon_meta (
                loaded_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
                cdragon_version  VARCHAR(255)
            )"""))
    meta.to_sql("augment_meta", eng, if_exists="append", index=False)
    modes.to_sql("augment_mode_list", eng, if_exists="append", index=False)
    with eng.begin() as c:
        c.execute(text("INSERT INTO cdragon_meta (cdragon_version) VALUES (:v)"), {"v": version})
        c.execute(text("""
            CREATE VIEW v_augment_modes AS
            SELECT m.*,
                   COALESCE(MAX(l.mode_name = 'KIWI'), 0)      AS in_kiwi,
                   COALESCE(MAX(l.mode_name = 'KIWI_JADE'), 0) AS in_kiwi_jade,
                   COALESCE(MAX(l.mode_name = 'CHERRY'), 0)    AS in_cherry_list
            FROM augment_meta m
            LEFT JOIN augment_mode_list l ON l.name_id = m.name_id
            GROUP BY m.augment_id"""))
    print(f"cdragon {version}: {len(meta)} augments, {len(modes)} mode-list rows loaded")


if __name__ == "__main__":
    main()
