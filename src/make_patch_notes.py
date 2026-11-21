"""Build the inputs for reports/aram_patch_notes.md: candidate table + figures.

Usage: python src/make_patch_notes.py
Writes reports/patch_notes_candidates.csv and reports/figures/*.png (champion-level aggregates only).
"""
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
from scipy import stats

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from db import get_engine  # noqa: E402

PATCHES = ["16.19", "16.20", "16.21", "16.22"]
DIAG_PATCHES = ["16.21", "16.22"]       # diagnosis uses the latest two patches
ELASTIC, ELASTIC_LO, ELASTIC_HI = 0.633, 0.123, 1.144   # %p win rate per 1%p ARAM modifier (02_patch_effects)
SHORT_MIN = 18
OUT = ROOT / "reports"
FIG = OUT / "figures"
COL = {"buff": "#2a78d6", "nerf": "#eb6834", "other": "#8a8985", "ink": "#3d3d3a"}
plt.rcParams.update({
    "font.family": "Apple SD Gothic Neo", "axes.unicode_minus": False,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": "#e6e5e1", "grid.linewidth": 0.8,
    "axes.edgecolor": "#8a8985", "axes.axisbelow": True, "figure.dpi": 130,
})

# Proposed ARAM modifier changes (units: %p, + = stronger for the champion).
# dealt = 입히는 피해량, taken = 받는 피해량 (taken +5 means the champion takes 5%p MORE damage = nerf)
PROPOSALS = {
    "Swain":       dict(dealt=-5,  taken=+10, why="받는 피해가 같은 마법사의 2.2배인데 사망은 14% 적다. 피해를 흡수하고 회복으로 버티는 구조가 핵심이라 받는 피해를 주로 올린다"),
    "Viktor":      dict(dealt=-5,  taken=0,   why="가하는 피해가 마법사 평균보다 10% 높다. 26.22 협곡 상향 뒤 55%까지 올라갔다"),
    "Velkoz":      dict(dealt=-5,  taken=0,   why="가하는 피해가 마법사 평균보다 10% 높고, 짧은 게임 승률이 58%로 높다"),
    "MissFortune": dict(dealt=-5,  taken=0,   why="픽률 1위권(경기의 14%)이라 승률 3%p 차이도 체감이 크다. 가하는 피해가 원딜 평균보다 높다"),
    "Varus":       dict(dealt=-5,  taken=0,   why="짧은 게임 승률 59%로 초반 견제 압박이 강하다. 가하는 피해가 원딜 평균보다 7% 높다"),
    "Lux":         dict(dealt=0,   taken=+5,  why="가하는 피해는 평균보다 낮지만 받는 피해 -26%, 사망 -22%로 안전하게 싸운다. 생존 쪽을 조정한다"),
    "Akali":       dict(dealt=+5,  taken=-5,  why="받는 피해가 암살자 평균보다 25% 많고 짧은 게임·긴 게임 모두 40% 안팎이다. 진입 비용이 큰 구조라 생존과 피해를 함께 올린다"),
    "Locke":       dict(dealt=+5,  taken=-5,  why="26.20에 입히는 피해 +10%p를 받았는데도 43%다. 받는 피해·사망이 평균보다 많아 이번에는 생존을 올린다"),
    "LeeSin":      dict(dealt=+5,  taken=0,   why="짧은 게임과 긴 게임 모두 44%로 고르게 약하다. 진입형이라 진입 후 마무리 피해를 올린다"),
    "Smolder":     dict(dealt=+5,  taken=0,   why="26.20·26.22 협곡 상향에도 44%다. 가하는 피해가 원딜 평균보다 7% 낮고 성장 전 구간이 특히 약하다"),
    "Cassiopeia":  dict(dealt=+5,  taken=0,   why="가하는 피해가 마법사 평균보다 13% 낮고 받는 피해는 27% 많다. 4개 패치 내내 44~45%로 꾸준히 약하다"),
    "Leblanc":     dict(dealt=+5,  taken=0,   why="픽률이 높은 약세 챔피언(경기의 7%). 피해·생존 지표는 오히려 평균 이상이라 원인이 지표로 뚜렷하지 않다 → 최소 폭만 조정하고 관찰"),
}
WATCH = {
    "Kalista": "4개 패치 내내 강세(56%). Riot이 26.23에서 이미 칼바람 보정 하향(입히는 피해 110→105%, 받는 피해 90→100%) → 16.23 데이터로 효과 확인",
    "Ziggs": "53%로 강세지만 벨코즈·바루스와 같은 원거리 견제형. 이번 하향들의 파급 효과를 본 뒤 결정",
    "Kennen": "45%로 약세. 26.20 협곡 상향(E 공속)이 칼바람에 효과가 없었다",
}


def load():
    e = get_engine()
    q = f"""SELECT p.champion_id, p.champion_name AS c, p.win, p.deaths, p.dmg_to_champs, p.dmg_taken,
                   m.duration_s, m.patch
            FROM participants p JOIN matches m USING (match_id)
            WHERE m.queue_id = 450 AND m.early_surrender = 0
              AND m.patch IN ({",".join(f"'{x}'" for x in PATCHES)})"""
    return pd.read_sql(q, e)


def eb_levels(p):
    """Beta-binomial empirical Bayes win rate per patch x champion."""
    out = []
    for pt, g in p.groupby("patch"):
        t = g.groupby("c").win.agg(n="size", w="sum")
        r = t.w / t.n
        m = t.w.sum() / t.n.sum()
        k = m * (1 - m) / max(r.var() - (r * (1 - r) / t.n).mean(), 1e-6) - 1
        a, b = m * k, (1 - m) * k
        out.append(t.assign(patch=pt, eb=(t.w + a) / (t.n + a + b) * 100,
                            lo=stats.beta.ppf(0.025, t.w + a, t.n - t.w + b) * 100,
                            hi=stats.beta.ppf(0.975, t.w + a, t.n - t.w + b) * 100))
    return pd.concat(out).reset_index()


def diagnose(p, tags):
    d = p[p.patch.isin(DIAG_PATCHES)].copy()
    d["cls"] = d.champion_id.map(tags)
    mins = d.duration_s / 60
    d["dpm"], d["tpm"], d["dth"] = d.dmg_to_champs / mins, d.dmg_taken / mins, d.deaths / mins
    d["short"] = d.duration_s < SHORT_MIN * 60
    g = d.groupby("c").agg(n=("win", "size"), w=("win", "sum"), cls=("cls", "first"),
                           dpm=("dpm", "mean"), tpm=("tpm", "mean"), dth=("dth", "mean"))
    g["wr_short"] = d[d.short].groupby("c").win.mean() * 100
    g["wr_long"] = d[~d.short].groupby("c").win.mean() * 100
    for col in ["dpm", "tpm", "dth"]:
        g[col + "_rel"] = (g[col] / g.groupby("cls")[col].transform("median") - 1) * 100
    g["pick_pct"] = g.n / (len(d) / 10) * 100
    r = g.w / g.n
    m = g.w.sum() / g.n.sum()
    k = m * (1 - m) / (r.var() - (r * (1 - r) / g.n).mean()) - 1
    g["eb"] = (g.w + m * k) / (g.n + k) * 100
    g["lo"] = stats.beta.ppf(0.025, g.w + m * k, g.n - g.w + (1 - m) * k) * 100
    g["hi"] = stats.beta.ppf(0.975, g.w + m * k, g.n - g.w + (1 - m) * k) * 100
    return g


def fig_swain(lv):
    s = lv[lv.c == "Swain"].set_index("patch").loc[PATCHES]
    fig, ax = plt.subplots(figsize=(6.4, 3.4))
    x = np.arange(len(PATCHES))
    ax.fill_between(x, s.lo, s.hi, color=COL["nerf"], alpha=0.15, linewidth=0)
    ax.plot(x, s.eb, color=COL["nerf"], lw=2, marker="o", ms=7, mec="white", mew=1.2)
    for xi, (pt, r) in zip(x, s.iterrows()):
        ax.annotate(f"{r.eb:.1f}%\n(n={int(r.n):,})", (xi, r.hi), xytext=(0, 6), textcoords="offset points",
                    ha="center", fontsize=8.5, color=COL["ink"])
    ax.axhline(50, color=COL["ink"], lw=1)
    ax.axvline(0.5, color=COL["other"], lw=1, ls="--")
    ax.text(0.53, 47, "26.20 협곡 상향\n(W 피해량·재사용 대기시간)", fontsize=8.5, color=COL["other"], va="top")
    ax.set_xticks(x, PATCHES)
    ax.set_ylim(40, 72)
    ax.set_ylabel("칼바람 승률 (%)")
    ax.set_title("스웨인: 협곡 상향 한 번에 칼바람 승률 50% → 60%대", loc="left", fontsize=10)
    ax.grid(axis="x", visible=False)
    fig.tight_layout()
    fig.savefig(FIG / "swain_trend.png")


def fig_candidates(tab):
    t = tab.sort_values("eb")
    fig, ax = plt.subplots(figsize=(7.6, 0.42 * len(t) + 1.2))
    y = np.arange(len(t))
    for yi, r in zip(y, t.itertuples()):
        c = COL["nerf"] if r.eb > 50 else COL["buff"]
        ax.plot([r.lo, r.hi], [yi, yi], color=c, lw=2, solid_capstyle="round", alpha=0.5)
        ax.plot(r.eb, yi, "o", ms=7, color=c, mec="white", mew=1.2)
        ax.annotate("", xy=(r.expected, yi), xytext=(r.eb, yi),
                    arrowprops=dict(arrowstyle="->", color=COL["ink"], lw=1.2))
    ax.axvline(50, color=COL["ink"], lw=1)
    ax.set_yticks(y, [f"{r.name}  (n={int(r.n):,})" for r in t.itertuples()], fontsize=9)
    ax.set_xlabel("칼바람 승률 (%): 현재(점, 95% 구간) → 조정 후 기대값(화살표)")
    ax.set_title("조정 대상 12종: 현재 승률과 조정 후 기대 승률", loc="left", fontsize=10)
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    fig.savefig(FIG / "candidates.png")


def fig_class(diag):
    t = diag[diag.n >= 300].groupby("cls").apply(lambda g: pd.Series(dict(
        wr=g.w.sum() / g.n.sum() * 100, n=g.n.sum(), k=len(g))), include_groups=False).sort_values("wr")
    ko = {"Assassin": "암살자", "Fighter": "전사", "Tank": "탱커", "Mage": "마법사", "Marksman": "원거리 딜러",
          "Support": "서포터"}
    fig, ax = plt.subplots(figsize=(6.4, 3.0))
    y = np.arange(len(t))
    for yi, (cls, r) in zip(y, t.iterrows()):
        se = np.sqrt(r.wr * (100 - r.wr) / r.n)
        c = COL["buff"] if r.wr < 50 else COL["nerf"]
        ax.barh(yi, r.wr - 50, left=50, height=0.6, color=c)
        ax.text(r.wr + (0.15 if r.wr >= 50 else -0.15), yi, f"{r.wr:.1f}%", va="center",
                ha="left" if r.wr >= 50 else "right", fontsize=8.5, color=COL["ink"])
    ax.axvline(50, color=COL["ink"], lw=1)
    ax.set_yticks(y, [f"{ko.get(c, c)} ({int(r.k)}종)" for c, r in t.iterrows()], fontsize=9)
    ax.set_xlim(45.5, 52)
    ax.set_xlabel(f"칼바람 승률 (%), {' + '.join(DIAG_PATCHES)}")
    ax.set_title("역할군별 승률: 암살자는 칼바람에서 구조적으로 약하다", loc="left", fontsize=10)
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    fig.savefig(FIG / "class_winrate.png")
    return t


def main():
    FIG.mkdir(parents=True, exist_ok=True)
    ver = requests.get("https://ddragon.leagueoflegends.com/api/versions.json", timeout=10).json()[0]
    champs = requests.get(f"https://ddragon.leagueoflegends.com/cdn/{ver}/data/ko_KR/champion.json",
                          timeout=10).json()["data"]
    tags = {int(v["key"]): v["tags"][0] for v in champs.values()}
    names = pd.read_csv(ROOT / "data/processed/champion_names.csv")
    ko = dict(zip(names.champion_name, names.champion_ko))

    p = load()
    lv = eb_levels(p)
    diag = diagnose(p, tags)
    trend = lv.pivot(index="c", columns="patch", values="eb")[PATCHES].add_prefix("wr_")

    rows = []
    for c, pr in PROPOSALS.items():
        r = diag.loc[c]
        units = pr["dealt"] - pr["taken"]          # + = stronger
        rows.append(dict(champ=c, name=ko[c], cls=r.cls, n=int(r.n), pick_pct=r.pick_pct,
                         eb=r.eb, lo=r.lo, hi=r.hi, wr_short=r.wr_short, wr_long=r.wr_long,
                         dpm_rel=r.dpm_rel, tpm_rel=r.tpm_rel, dth_rel=r.dth_rel,
                         dealt=pr["dealt"], taken=pr["taken"], units=units,
                         expected=r.eb + units * ELASTIC,
                         exp_lo=r.eb + units * (ELASTIC_LO if units > 0 else ELASTIC_HI),
                         exp_hi=r.eb + units * (ELASTIC_HI if units > 0 else ELASTIC_LO),
                         why=pr["why"]))
    tab = pd.DataFrame(rows).set_index("champ").join(trend)
    tab.round(2).to_csv(OUT / "patch_notes_candidates.csv")

    fig_swain(lv)
    fig_candidates(tab)
    cls = fig_class(diag)
    print(cls.round(2))
    pd.set_option("display.width", 250)
    print(tab.drop(columns="why").round(1).to_string())
    for c, note in WATCH.items():
        r = diag.loc[c]
        print(f"watch {c}: eb {r.eb:.1f} n {int(r.n)}")


if __name__ == "__main__":
    main()
