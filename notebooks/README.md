# 노트북 안내

순서대로 읽으면 데이터 확인 → 패치 효과 추정 → 조정 패치노트로 이어집니다.
GitHub에서 노트북이 안 열리거나 느리면 **nbviewer** 링크로 보세요. 그래프까지 안정적으로 보입니다.

| 노트북 | 내용 | 보기 |
|---|---|---|
| [01_eda.ipynb](01_eda.ipynb) | 수집 현황, 표본 편향 점검(플레이어당 경기 수), 챔피언별 승률과 신뢰구간, 아이템 노출군, 첫 DiD | [nbviewer](https://nbviewer.org/github/113mj/poro_lab/blob/main/notebooks/01_eda.ipynb) |
| [02_patch_effects.ipynb](02_patch_effects.ipynb) | 3개 패치 구간 DiD, 위약 검정, 그룹별 평균 효과, 칼바람 보정치 환산값, 경험적 베이즈 축소, 승률 수준 | [nbviewer](https://nbviewer.org/github/113mj/poro_lab/blob/main/notebooks/02_patch_effects.ipynb) |

결과를 정리한 문서는 [`reports/aram_patch_notes.md`](../reports/aram_patch_notes.md)입니다.

## 02에서 볼 것

| 절 | 질문 | 답 (16.19 ~ 16.22, 약 7만 경기) |
|---|---|---|
| 3 | 챔피언별 패치 효과가 있었나? | 대부분 신뢰구간이 0을 포함한다. 예외는 **스웨인 (26.20 협곡 상향, +12.1%p)** |
| 4 | 이 방법은 믿을 만한가? | 바뀌지 않은 챔피언으로 위약 검정을 하면 오탐률 6.3% (기대 5%) |
| 5 | 버프·너프는 평균 몇 %p인가? | 상향 +1.0%p, 하향 -0.2%p. 협곡 변경은 칼바람에서 대부분 희석된다 |
| 5-1 | 칼바람 전용 보정치는 얼마나 강한가? | 보정치 1%p당 승률 약 0.6%p (벨베스·로크 사례) |
| 6 | 개별 추정치 중 믿을 만한 건? | 축소 후에도 남는 것은 스웨인 (+6.3%p) |
| 7 | 칼바람 조정이 필요한 챔피언은? | 4개 패치 내내 강세 12종, 약세 19종. 승률 수준은 패치 간 상관 0.65~0.80 |

## 다시 실행하기

```bash
docker compose up -d          # MySQL
jupyter lab notebooks/        # Kernel → Restart & Run All
```

노트북은 DB에서 읽기만 하므로, 수집 중에 실행해도 됩니다.
출력에는 챔피언·패치 단위 집계만 있고 개별 플레이어 정보는 없습니다.
