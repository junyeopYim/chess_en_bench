# 라운드 피드백 계약 (Round Feedback Contract)

피드백 문서는 제출하는 에이전트를 위해 의도된 유일한 라운드 결과다.
스키마는 두 가지다: `ceb.round.feedback/v1` (Track A)와
`ceb.track_b.feedback/v1` (Track B). 둘 다 집계 전용(aggregate-only)이며, 전체
세부 정보는 운영자 아티팩트에 남는다.

## Track A — `ceb.round.feedback/v1`

`bench/ceb/rounds/feedback.py`의 `make_feedback()`가 생성하고,
`bench/ceb/rounds/round_runner.py`의 `run_round()`가 모든 라운드 끝에서 호출하며,
`runs/<run_id>/round_<N>/feedback.json`에 기록한다. 동일한 내용이
`feedback_to_text()`로 텍스트로 렌더링되어 `ceb round run`에 의해 출력된다.

하나 생성하기:

```bash
ceb round run --track A --workspace <dir> --round 1 --quick
cat runs/<run_id>/round_1/feedback.json
```

### 필드

| 필드 | 타입 | 의미 |
|---|---|---|
| `schema` | string | 상수 `"ceb.round.feedback/v1"`. |
| `round` | integer | 라운드 번호, `ceb round run --round N`에 전달된 값. |
| `mode` | string | `"quick"`(무료 스모크 라운드), `"official_round"`(라운드 예산 소비, strict 게이트), 또는 `"final_eval"`(리더보드 품질, strict 게이트, 예산 비용 없음). 구(legacy) 리포트는 `"official"`을 표시할 수 있다. |
| `per_opponent` | 객체 배열 | 상대당 하나의 엔트리, 매치가 진행된 순서대로. 아래 참고. |
| `faults` | object | 라운드 내 모든 매치에 걸친 후보 결함 합계: `{"illegal": int, "timeout": int, "crash": int}`. |
| `penalty_points` | number | `illegal*30 + timeout*15 + crash*25` (가중치는 `tracks/a_from_scratch/scoring.yaml`에서). |
| `ladder_score` | number 또는 null | 상대당 성능 레이팅의 평균, 소수점 1자리로 반올림. 채점된 게임이 없으면 null. |
| `final_score` | number 또는 null | `ladder_score - penalty_points`, 소수점 1자리로 반올림. 이것이 라운드의 점수이며, 실행의 최종 점수는 그 실행에서 가장 좋은 유효 라운드다. |
| `advice` | string 배열 | 결함 카운터만을 기준으로 하는 일반적인 고정 템플릿 힌트(존재하는 결함 종류당 하나의 힌트, 결함이 없을 때는 하나의 일반 힌트). |

각 `per_opponent` 엔트리:

| 필드 | 타입 | 의미 |
|---|---|---|
| `opponent` | string | 공개 상대 이름 (`tracks/a_from_scratch/opponents/README.md` 참고). |
| `games` | integer | 집계된 게임 수 (`wins + draws + losses`). |
| `wins`, `draws`, `losses` | integer | 후보 관점에서의 결과. |
| `score_rate` | number 또는 null | `(W + 0.5*D) / games`, `eps = 1/(2*(games+1))`로 `[eps, 1-eps]`에 클램프, 소수점 4자리로 반올림. `games == 0`이면 null. |

이 피드백은 전체 라운드 리포트의 `score` 블록
(`ceb.score.track_a/v1`, `bench/ceb/scoring/track_a.py`에서 계산)의 엄격한
부분집합(strict subset)이다. 상대당 `opponent_rating`, `delta_elo`, `performance`
필드를 제거하지만, 이 모두는 `score_rate`와 `bench/ceb/scoring/elo.py`의 공개
공식으로부터 재계산할 수 있다 — 피드백의 어떤 것도 비밀(secret)에 의존하지 않는다.
문서의 모든 것은 `round_report["score"]`와 라운드 번호 및 모드에서 파생된다 —
다른 입력은 없다.

## Track B — `ceb.track_b.feedback/v1`

`bench/ceb/track_b/round_runner.py`의 `make_track_b_feedback()`가 생성하고,
`ceb track-b round run`에 의해 `runs/<run_id>/track_b_round_<N>/feedback.json`에
기록된다. 모든 카운트는 후보 관점에서 계산된다.

| 필드 | 타입 | 의미 |
|---|---|---|
| `schema` | string | 상수 `"ceb.track_b.feedback/v1"`. |
| `round` | integer | 라운드 번호. |
| `games` | integer | 채점된 게임 수 (`wins + draws + losses`). |
| `wins`, `draws`, `losses` | integer | 베이스라인 엔진 대비 합계. |
| `faults` | object | `{"illegal": int, "timeout": int, "crash": int}` 후보 결함 합계. |
| `delta_elo` | number 또는 null | 클램프된 점수 비율(`bench/ceb/scoring/elo.py`)이 함의하는 Elo 차이, 소수점 1자리로 반올림. `games == 0`이면 null. |
| `delta_elo_ci95` | `[lo, hi]` 또는 null | `delta_elo`에 대한 95% 신뢰 구간(게임당 평균 점수에 대한 정규 근사를 Elo로 매핑). |
| `penalty_points` | number | `illegal*30 + timeout*15 + crash*25`. |
| `final_delta_elo` | number 또는 null | `delta_elo - penalty_points`, 소수점 1자리로 반올림. 라운드의 Track B 점수. |
| `openings_used` | integer | 진행된 서로 다른 오프닝의 개수(COUNT) — 숫자이며, 결코 오프닝 id가 아니다. |

`openings_used`(리스트가 아니라 길이)를 제외하면, 모든 것은 리포트의 `score`
블록(`ceb.score.track_b/v1`, `bench/ceb/scoring/track_b.py`에서 계산)과 라운드
번호의 부분집합이다.

## 정화(sanitization) 보장 (양쪽 트랙)

피드백은 설계상 집계 전용이므로, 에이전트는 평가 채널이 자신이 이미 가지고
있지 않은 어떤 것도 유출하지 않는 채로 라운드 사이에 반복 작업을 할 수 있다:

- 수 로그 없음: PGN 없음, UCI movetext 없음, 개별 게임 기록 없음,
  게임당 결과 없음 — 오직 W/D/L 합계만.
- 포지션 없음: FEN 없음, 오프닝 라인 없음, 어떤 종류의 테스트 포지션도 없음.
- 숨겨진 평가 데이터 없음: 비공개 평가 팩이 로드될 때(`--eval-pack` /
  `CEB_PRIVATE_EVAL_DIR`, `bench/ceb/eval_pack.py` 참고), 에이전트가 보는
  어떤 피드백에도 숨겨진 FEN, 수, 또는 오프닝 id가 나타나지 않는다. 전체 라운드
  리포트는 `openings_used` id와 `eval_pack` 설명을 기록하지만, 그것들은
  운영자 아티팩트다. 피드백은 기껏해야 오프닝 개수(COUNT)(Track B)를 담거나
  오프닝에 관해 전혀 아무것도 담지 않는다(Track A). 게이트 실패 세부
  정보도 마찬가지로 row id만 인용하며, 결코 raw FEN을 인용하지 않는다.
- `advice` 문자열(Track A)은 오직 `illegal`, `timeout`, `crash` 카운터에
  의해 트리거되는 고정 템플릿이다. 그것들은 결코 게임이나 포지션 내용을
  되울리지(echo) 않는다.

정직한 단서(caveat): 이것은 로컬 하네스이므로, 운영자 아티팩트 — 전체
라운드 리포트(`report.json`), 매치당 리포트(`match_vs_<Opponent>.json`
또는 `match.json`), 게임 movetext 파일(`games_vs_<Opponent>.txt` 또는
`games.txt`) — 는 로컬 디스크의 동일한 `runs/<run_id>/` 하위 트리에
기록된다. 이 계약은 에이전트를 마주하는 하네스가 에이전트에게 무엇을
반환하는지를 정의한다. 호스티드 배포에서는 오직 `feedback.json`만이 그
경계를 넘어간다.

## 예시 페이로드 (Track A)

그럴듯한 official 라운드(상대당 4게임, 따라서 `eps = 0.1`. 두 번의 4-0
완승은 1.0에서 0.9로 클램프됨):

```json
{
  "schema": "ceb.round.feedback/v1",
  "round": 1,
  "mode": "official",
  "per_opponent": [
    {"opponent": "BenchRandom",        "games": 4, "wins": 4, "draws": 0, "losses": 0, "score_rate": 0.9},
    {"opponent": "BenchGreedyCapture", "games": 4, "wins": 4, "draws": 0, "losses": 0, "score_rate": 0.9},
    {"opponent": "BenchMaterial1",     "games": 4, "wins": 3, "draws": 1, "losses": 0, "score_rate": 0.875},
    {"opponent": "BenchPST1",          "games": 4, "wins": 2, "draws": 1, "losses": 1, "score_rate": 0.625},
    {"opponent": "BenchMiniMax2",      "games": 4, "wins": 1, "draws": 1, "losses": 2, "score_rate": 0.375},
    {"opponent": "BenchAlphaBeta3",    "games": 4, "wins": 0, "draws": 1, "losses": 3, "score_rate": 0.125}
  ],
  "faults": {"illegal": 0, "timeout": 1, "crash": 0},
  "penalty_points": 15,
  "ladder_score": 1027.2,
  "final_score": 1012.2,
  "advice": [
    "Timeouts detected: respect 'go movetime' and always answer with a bestmove line."
  ]
}
```

결함이 없을 때, `advice`는 탐색 깊이와 평가가 더 높은 ladder 점수를 위한 주된
지렛대라는 하나의 일반 힌트를 담는다.
