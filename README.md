# Poro Lab

**협곡 기준 밸런스 패치가 칼바람 나락(ARAM)에서는 실제로 어떤 효과를 냈을까?**

리그 오브 레전드의 챔피언 버프·너프는 주로 소환사의 협곡을 기준으로 조정됩니다.
같은 변경이 칼바람 나락(일반 칼바람, 큐 450)에서는 지나치게 세게 작동하기도 하고, 거의 효과가 없기도 합니다.
이 프로젝트는 KR 서버의 칼바람 경기 데이터로 **패치별 챔피언 변경이 칼바람 승률에 준 효과를 추정**하고,
그 근거를 붙여 "내가 쓴 칼바람 조정 패치노트"를 만드는 데이터 분석 프로젝트입니다.

> 🚧 **진행 중**: 4개 패치(16.19~16.22, 약 7만 경기) 분석과 조정 패치노트 초안까지 완료했습니다.

## 주요 결과 (초안)

- **협곡 변경은 칼바람에서 대부분 희석된다.** 버프·너프가 칼바람 승률에 남기는 평균 효과는 1%p 안팎이다.
- **하지만 가끔 크게 증폭된다.** 스웨인은 26.20 협곡 상향 한 번으로 칼바람 승률이 50% → 63%가 됐다 (DiD +12.1%p, 95% CI 8.1~16.0).
- **칼바람 전용 보정치는 강한 손잡이다.** 실제 보정 변경 사례로 재면 보정치 1%p당 승률 약 0.6%p다.
- **방법 검증:** 4개 패치 내내 강세로 잡힌 칼리스타는 26.23에서 Riot이 실제로 칼바람 보정을 하향했다.

👉 [칼바람 조정 패치노트](reports/aram_patch_notes.md) · [노트북 안내](notebooks/README.md) · [분석 노트북 (nbviewer)](https://nbviewer.org/github/113mj/poro_lab/blob/main/notebooks/02_patch_effects.ipynb)

## 접근 방법

- **데이터**: Riot API(Match-v5)로 KR 칼바람 경기를 패치 단위로 수집합니다. 목표는 패치당 2~3만 경기입니다.
- **패치 효과 추정**: 단순 전후 비교 대신 **이중차분(DiD)**을 씁니다. 해당 패치에서 변경되지 않은 챔피언을 대조군으로 삼아, 메타 변화나 시기 효과를 걷어냅니다.
- **소표본 보정**: 픽이 적은 챔피언의 극단적인 승률을 베이지안 축소(경험적 베이즈·계층 모델)로 보정합니다.
- **표기 원칙**: 승률에는 항상 표본 수(n)와 신뢰구간을 함께 표시합니다.

## 진행 상황

| 단계 | 상태 |
|---|---|
| 주제 검증 및 전환 (아수라장 → 일반 칼바람) | ✅ [근거](docs/DECISIONS.md) |
| 과거 패치 소급 가능 범위 확인 (패치 14.23까지 가능) | ✅ |
| 수집 방식 설계 및 편향 점검 (무작위 시드 + 스노볼) | ✅ |
| 패치별 챔피언 변경 목록 구조화 (26.20~26.22) | ✅ [표](data/patch_changes/) |
| 패치 단위 본 수집 (16.19~16.22) | ✅ |
| EDA · DiD 분석 | ✅ [01](notebooks/01_eda.ipynb) · [02](notebooks/02_patch_effects.ipynb) |
| 칼바람 조정 패치노트 | 🟡 [초안](reports/aram_patch_notes.md) |
| 보정치 환산값 검증 (16.23 칼리스타, 과거 보정 사례) | ⏳ |

주요 결정과 그 근거는 [`docs/DECISIONS.md`](docs/DECISIONS.md)에 기록합니다.

## 데이터 수집

Riot API에는 경기를 무작위로 뽑는 기능이 없고, 랭크 유저는 칼바람을 거의 하지 않습니다.
그래서 다음과 같이 수집합니다.

1. **시드**: 기간 안의 경기 ID를 무작위로 조회해, 그 경기 참가자 중 최근 칼바람 기록이 있는 플레이어를 시드로 씁니다.
2. **스노볼 확장**: 플레이어마다 칼바람 경기를 3개씩 받고, 그 경기의 다른 참가자를 대기열에 추가합니다. 다음 플레이어는 대기열에서 무작위로 고릅니다.
3. **정제**: 경기 ID로 중복을 제거하고, `gameVersion`으로 패치를 구분합니다. 리메이크 경기는 승률 분석에서 제외합니다.

이 방식은 특정 플레이어나 친구 무리에 경기가 몰리는 현상을 줄이지만, 칼바람을 자주 하는 사람이 더 많이 뽑히는 편향은 남아 있습니다.
자세한 실험 결과는 [`docs/DECISIONS.md`](docs/DECISIONS.md)에 있습니다.

## 폴더 구조

```
src/              수집·저장 스크립트 (collect.py, riot.py, db.py, schema.sql)
src/feasibility/  아수라장 가능성 검증 스크립트 (전환 근거로 보존)
notebooks/        EDA·분석 노트북
reports/          최종 패치노트, 그래프
docs/             의사결정 기록
data/             원본·가공 데이터 (원본은 저장소에 포함하지 않음)
```

## 실행 방법

```bash
pip install -r requirements.txt
cp .env.example .env          # RIOT_API_KEY, MYSQL_* 값 입력
docker compose up -d          # MySQL 8.4 (포트 3307)
python src/check_key.py       # API 키 확인
python src/collect.py --target 200 --days 14
```

## 데이터 처리 원칙

- 원본 경기 데이터는 로컬에만 보관하며 저장소에 포함하거나 재배포하지 않습니다.
- 공개하는 결과는 챔피언·패치 단위 집계뿐이며, 개별 플레이어를 식별하거나 평가하는 정보는 공개하지 않습니다.
- API 키와 DB 접속 정보는 `.env`로만 관리합니다.

## Legal

Poro Lab isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot Games or anyone officially involved in producing or managing Riot Games properties. Riot Games, and all associated properties are trademarks or registered trademarks of Riot Games, Inc.

Poro Lab은 Riot Games와 무관한 개인 비상업 프로젝트입니다.
