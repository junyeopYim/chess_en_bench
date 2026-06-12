# 채점(Scoring)

chess_en_bench가 게임 결과를 점수로 바꾸는 방식. 구현:
`bench/ceb/scoring/elo.py`, `track_a.py`, `track_b.py`. Track A 상수는
`tracks/a_from_scratch/scoring.yaml`에서 설정한다.

## 핵심 Elo 수식 (`ceb.scoring.elo`)

모든 채점은 한 페어링의 W/D/L 카운트에서 시작한다.

```
score_rate = (wins + 0.5 * draws) / games
eps        = 1 / (2 * (games + 1))
clamped    = min(max(score_rate, eps), 1 - eps)
delta_elo  = -400 * log10(1 / clamped - 1)
```

`delta_elo`는 표준 로지스틱 모델에서 (클램프된) 점수율이 함의하는 Elo 차이다.
양수면 후보가 기준보다 우수했음을 뜻한다(Track A에서는 상대, Track B에서는 고정된
baseline). 결과는 정확히 동점일 때 `0.0`을 내도록 정규화되며, 절대 `-0.0`이 되지
않는다.

### 왜 클램프하는가?

완벽한 4-0 점수는 `score_rate = 1.0`을 주는데, `log10(1/1 - 1)`은 정의되지
않는다(무한 Elo). 클램프는 증거가 늘어날수록 줄어드는 여유를 두고 점수율을 (0, 1)
내부로 엄격히 유지한다. 4게임이면 `eps = 1/10 = 0.1`이므로 완승은 1.0 대신 0.9로
사상된다. 100게임이면 `eps = 1/202 ≈ 0.005`이므로 큰 표본은 거의 영향받지 않는다.
이는 작은 표본이 주장할 수 있는 Elo의 상한을 둔다.

### 계산 예시

| W-D-L | games | raw rate | clamped | delta Elo |
|-------|-------|----------|---------|-----------|
| 3-0-1 | 4 | 0.75 | 0.75 | **+190.8** |
| 4-0-0 | 4 | 1.00 | 0.90 | +381.7 |
| 3-1-0 | 4 | 0.875 | 0.875 | +338.0 |
| 2-0-2 | 4 | 0.50 | 0.50 | 0.0 |
| 0-0-4 | 4 | 0.00 | 0.10 | -381.7 |

`0.75 -> +190.8`을 손으로 확인: `-400 * log10(1/0.75 - 1)
= -400 * log10(1/3) = 400 * log10(3) ≈ 190.85`.

### 95% 신뢰구간

`delta_elo_ci(wins, draws, losses, z=1.96)`는 게임당 평균 점수(무승부는 0.5로
계산)에 대한 정규 근사를 사용한다.

```
p   = score_rate
var = (W*(1-p)^2 + D*(0.5-p)^2 + L*(0-p)^2) / games
se  = sqrt(var / games)
(lo, mid, hi) = delta_elo(clamp(p - z*se)), delta_elo(clamp(p)), delta_elo(clamp(p + z*se))
```

예시: 20게임에서 10W 6D 4L이면 `p = 0.65`, `se ≈ 0.0873`이므로 점수율 구간은
[0.479, 0.821]이고 Elo로는 **+107.5, CI95 [-14.7, +264.8]**이다. 20게임은 정보가
거의 없으므로 구간이 넓다. 작은 표본의 델타는 그에 맞게 취급하라.

## 페널티 (두 트랙 공통)

후보의 결함(fault)마다 최종 점수 / 최종 델타 Elo에서 차감된다.

| Fault | Points |
|-------|--------|
| illegal_move | 30 |
| timeout | 15 |
| crash | 25 |

결함 카운트는 내부 매치 러너의 `candidate_faults`(키는 `illegal`, `timeout`,
`crash`)에서 오며 라운드의 모든 게임에 걸쳐 합산된다.

## Track A: 사다리 점수 (`ceb.score.track_a/v1`)

`compute_round_score(match_reports, ...)`는 상대마다 하나씩의 내부 러너 보고서를
집계한다.

- 상대별: `performance = opponent_rating + delta_elo(clamped rate)`. 레이팅은
  `scoring.yaml`의 `opponent_ratings`에서 온다(공칭값: BenchRandom 400,
  BenchGreedyCapture 600, BenchMaterial1 800, BenchPST1 1000, BenchMiniMax2 1200,
  BenchAlphaBeta3 1400). 라운드 러너는 `anchor_opponents` 항목
  (SF18_UCI_Elo_1320/1600/1900/2200)의 `rating` 값이 표에 아직 없으면 병합하므로,
  선택적 앵커 매치도 같은 방식으로 채점된다. 알려지지 않은 상대는 기본 800이다.
- `ladder_score` = 널이 아닌 모든 상대별 performance의 평균.
- `final_score = ladder_score - penalty_points`, 0.1 단위로 반올림.
- 0게임인 상대는 null rate/delta/performance를 가지며 평균에서 제외된다. 게임을
  가진 상대가 하나도 없으면 `final_score`는 null이다.

예시 보고서(공식 라운드, 상대당 4게임, 타임아웃 1회):

```json
{
  "schema": "ceb.score.track_a/v1",
  "per_opponent": [
    {"opponent": "BenchRandom", "opponent_rating": 400, "wins": 4, "draws": 0,
     "losses": 0, "games": 4, "score_rate": 0.9, "delta_elo": 381.7,
     "performance": 781.7},
    {"opponent": "BenchPST1", "opponent_rating": 1000, "wins": 2, "draws": 1,
     "losses": 1, "games": 4, "score_rate": 0.625, "delta_elo": 88.7,
     "performance": 1088.7}
  ],
  "faults": {"illegal": 0, "timeout": 1, "crash": 0},
  "penalty_points": 15,
  "ladder_score": 995.4,
  "final_score": 980.4
}
```

(`per_opponent`는 축약함. 실제 공식 라운드에는 여섯 상대 전부가 들어간다.)

### 리더보드 (`ceb.leaderboard/v1`)

`compute_leaderboard(results_dir, track, include_quick=False)`는
`runs/*/state.json`을 스캔하여 실행에 순위를 매긴다. 공식 정책은 실행마다 존재하면
가장 좋은 `final_eval` 결과를, 없으면 가장 좋은 `official_round`를 선택한다.
`official`(레거시)로 기록된 라운드는 공식 라운드로 계산되며, quick 라운드는 결코
계산되지 않는다. `include_quick=True`(CLI `ceb leaderboard compute
--include-quick`, API `/api/leaderboard?include_quick=true`)는 모든 모드에 걸친
최고 점수로 순위를 매기는 진단용 보기다 — CLI는 이를 비공식으로 표시하며 결코
공식 순위로 제시되어서는 안 된다. 보드 JSON은 이 플래그를 `include_quick` 필드에
반영하고, 각 항목은 `rounds_played`, `verified`(이 자가 보고 스캐너에서는 항상
`false` — 검증된 결과는 호스트 워커에서만 나온다)와 더불어
`official_rounds_played`를 담는다. `docs/leaderboard_policy.md`와
`docs/LEADERBOARD_GOVERNANCE.md`를 참조하라.

## Track B: baseline 대비 델타 Elo (`ceb.score.track_b/v1`)

`compute_delta_elo_report(wins, draws, losses, faults=None)`는 후보 Stockfish
빌드를 고정된 baseline(sf_18, cb3d4ee)에 대해 채점한다.

```json
{
  "schema": "ceb.score.track_b/v1",
  "wins": 10, "draws": 6, "losses": 4, "games": 20,
  "faults": {"illegal": 0, "timeout": 0, "crash": 0},
  "score_rate": 0.65,
  "delta_elo": 107.5,
  "delta_elo_ci95": [-14.7, 264.8],
  "penalty_points": 0,
  "final_delta_elo": 107.5
}
```

0게임이면 `score_rate`, `delta_elo`, `delta_elo_ci95`, `final_delta_elo`는 null
이다. `ceb track-b round run`은 이 점수를 자동으로 생성하여 라운드 보고서
(`ceb.track_b.round.report/v1`, 운영자용, 전체 상세)에 임베드하며, 정제된
`feedback.json`(`ceb.track_b.feedback/v1`, 집계값만) 옆에 둔다. 매치는 기본적으로
내부 러너로 실행되며, 대량 Track B 매치를 위한 선택적 `fastchess`
어댑터(`--runner fastchess`)가 존재하되 내부 러너가 신뢰 기준으로 남는다.

## 수치 재현하기

```bash
python -c "import sys; sys.path.insert(0,'bench'); \
from ceb.scoring import elo; print(elo.delta_elo(0.75))"        # 190.848...
python -c "import sys; sys.path.insert(0,'bench'); \
from ceb.scoring import elo; print(elo.delta_elo_ci(10, 6, 4))"  # (-14.7, 107.5, 264.8)
```
