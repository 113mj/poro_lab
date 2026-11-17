-- ARAM (queue 450) collection schema. Idempotent: safe to run repeatedly.

-- Snowball frontier, kept separately per patch. status: pending -> done
CREATE TABLE IF NOT EXISTS players (
    patch        VARCHAR(8)  NOT NULL,
    puuid        CHAR(78)    NOT NULL,
    source       VARCHAR(20) NOT NULL,          -- 'seed:q<queue>' or 'snowball'
    depth        INT         NOT NULL,          -- 0 = seed, n = found n hops away
    found_in     VARCHAR(20) NULL,              -- match where this player was found
    status       VARCHAR(10) NOT NULL DEFAULT 'pending',
    n_ids        INT         NULL,              -- ARAM match IDs returned in the window
    updated_at   TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (patch, puuid),
    KEY idx_patch_status (patch, status)
);

CREATE TABLE IF NOT EXISTS matches (
    match_id         VARCHAR(20) NOT NULL PRIMARY KEY,
    game_version     VARCHAR(32) NOT NULL,
    patch            VARCHAR(8)  NOT NULL,       -- e.g. '16.22'
    queue_id         INT         NOT NULL,
    game_start       DATETIME    NOT NULL,       -- UTC
    duration_s       INT         NOT NULL,
    winning_team     INT         NULL,           -- 100 / 200
    early_surrender  TINYINT(1)  NOT NULL,       -- remake, exclude from win-rate analysis
    collected_at     TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_patch (patch)
);

CREATE TABLE IF NOT EXISTS participants (
    match_id        VARCHAR(20) NOT NULL,
    participant_id  TINYINT     NOT NULL,
    puuid           CHAR(78)    NOT NULL,
    team_id         INT         NOT NULL,
    win             TINYINT(1)  NOT NULL,
    champion_id     INT         NOT NULL,
    champion_name   VARCHAR(32) NOT NULL,
    champ_level     INT,
    kills           INT,
    deaths          INT,
    assists         INT,
    dmg_to_champs   INT,
    dmg_taken       INT,
    gold_earned     INT,
    item0 INT, item1 INT, item2 INT, item3 INT, item4 INT, item5 INT, item6 INT,
    spell1          INT,
    spell2          INT,
    primary_style   INT,
    sub_style       INT,
    keystone        INT,
    PRIMARY KEY (match_id, participant_id),
    KEY idx_champ (champion_id),
    KEY idx_puuid (puuid)
);
