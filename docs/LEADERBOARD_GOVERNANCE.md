# 리더보드 거버넌스

리더보드에 무엇이 나타나는지, 어떻게 순위가 매겨지는지, 얼마나 신뢰할 수
있는지.

**두 개의** 리더보드가 있다. 둘은 한 가지 결정적 속성에서 다르다:
항목이 **검증**되었는지 여부.

| | 검증됨(호스티드) | 자가 보고(로컬) |
| --- | --- | --- |
| 코드 | `verified_leaderboard`, `bench/ceb/hosted/db.py` | `compute_leaderboard`, `bench/ceb/scoring/track_a.py` |
| 항목 출처 | 호스티드 SQLite DB의 `results` 행 | `<results>/*/state.json` 스캔 (기본 `runs/`) |
| `verified` 플래그 | `True` (워커가 발행한 것만) | 항상 `False` |
| CLI | `ceb hosted leaderboard --db --track` | `ceb leaderboard compute --track --results` |
| API | `GET /api/hosted/leaderboard?track=A` | `GET /api/leaderboard?track=A` |

## 검증됨 대 미검증

**호스티드 공식 워커만 `verified:true`를 발행한다.** 결과는
`ceb hosted worker run-once`를 통해 `run_official_eval`
(`bench/ceb/hosted/official_eval.py`)이 **verifiable 프로파일**(`official` /
`final-production`)로 산출하고 모든 게이트가 통과한 경우에만 검증된다. 그 경로는:

1. 비공개 eval 팩 필수(없으면 거부),
2. **엔진 감옥 가드**: verifiable 프로파일은 `engine_jail == docker`가 아니면
   평가 전에 검증을 거부한다(P0.1),
3. 스냅샷의 정적 부정 방지(anti-cheating) 스캔,
4. **비공개** eval 팩에 대한 엄격 게이트,
5. 비공개 팩 + Docker 엔진 감옥으로 `official_round` /
   `final_production`(또는 레거시 `final_eval`),
6. 공개/비공개 아티팩트 분리,
7. **공개 아티팩트 누출 스캔**(누출 시 검증 거부),
8. 재현성 메타데이터 + 서명(Ed25519 권장),
9. DB에 `verified=1`로 기록된 결과(`profile`, `verification_grade` 포함).

비공개 eval 팩이 없거나, 감옥이 docker가 아니거나(개발 플래그 없이), 스캔이
실패하거나, 엄격 게이트가 실패하거나, 누출이 탐지되면 워커는 **검증을 거부한다**
— 검증된 결과가 기록되지 않는다.

**`smoke` 프로파일(=`--quick-test-mode`)은 결코 verified가 아니다.** 프로파일이
verifiable이 아니므로 어떤 플래그를 줘도 verified 결과를 만들 수 없다("마법 같은
verified"는 없다). 개발 전용 `--dev-allow-unjailed`도 결과를 강제로
`verified: false`(diagnostic-unjailed)로 만든다.

**로컬 순위는 결코 검증되지 않는다.** `compute_leaderboard`는 로컬
`ceb round run` 호출이 작성한 `state.json` 파일을 스캔하고 모든 항목에
`verified: false`를 찍는다. 이것들은 명령을 실행한 누군가에 의해 자가
보고된 것이며, 하니스는 그것을 증명하지 않는다. 로컬 보드의 페이로드는 이를
명시하기 위해 `verified_only: false`로 설정한다.

## 선택 규칙

두 보드 모두 **실행당 하나의 항목**을, 최고 점수 순으로 순위 매기며, 동일한
우선순위를 사용한다(검증된 보드는 공유 선택자 `select_best_verified_result`를
사용해 리더보드 / `result show` / `official-result` API가 항상 같은 결과를
고르게 한다 — P0.4):

1. 존재한다면 **최고 final-tier** 결과(`final_production` / `final_eval`,
   Track B는 `track_b_official`), 없으면
2. **최고 official-tier** 결과(`official_round` / 레거시 `official`), 없으면
3. **없음** — 그 실행은 순위에 오르지 않는다.

**quick / smoke는 순위에 절대 집계되지 않는다.** 호스티드 워커는 smoke 결과를
검증으로 표시하지 않으므로 검증된 보드에 도달할 수 없다. 로컬 보드에서 quick은
`--include-quick`이 설정되지 않는 한 제외되며, 이 옵션은 **진단** 뷰이고 결코
공식 순위가 아니다 — 그 페이로드도 여전히 `verified_only: false`를 보고한다.

**레거시 "official"이 집계된다.** v0.3 이전 모드 이름 `official`은 공식
라운드로 취급된다: `OFFICIAL_MODES = {"official", "official_round"}`
(`track_a.py`), 그리고 호스티드 쿼리는 `mode in ("official_round",
"official")`과 일치시킨다. `mode` 필드 없이 기록된 로컬 라운드는 기본적으로
`official`이 된다.

eval 모드는 `bench/ceb/rounds/round_runner.py`와
`tracks/a_from_scratch/scoring.yaml`에 정의된다:

| 모드 | 예산 | 게이트 | 상대당 게임 | 오프닝 |
| --- | --- | --- | --- | --- |
| `quick` | free | non-strict | 2 | 2 |
| `official_round` | 1 of 3 units | strict | 4 | 6 |
| `final_eval` | none | strict | 8 | 8 |
| `final_production` | none | strict | 336 (2016 총) | 24 |

프로파일↔모드 매핑은 `bench/ceb/hosted/profiles.py`와
`tracks/a_from_scratch/eval_profiles.yaml`에 있다: `smoke`→`official_round`(tiny,
미검증), `official`→`official_round`, `final-production`→`final_production`. Track B
verified 결과는 `track_b_official` 모드로 final-tier에 들어간다.

## 결과를 등재 가능하게 만드는 것

**검증된 보드**의 경우 항목은 `verified=1`, null이 아닌 `score`, 모드
`final_eval`, `official_round`, 또는 레거시 `official`을 가진 DB `results`
행이어야 한다. 워커만 그런 행을 작성한다.

**로컬 보드**의 경우 항목은 `track`이 일치하는 읽을 수 있는 `state.json`에서
와야 하며, 등재 가능한 모드에서 null이 아닌 `score`를 가진 라운드를 적어도
하나 포함해야 한다. 읽을 수 없거나 비JSON인 상태 파일은 조용히 건너뛴다. 각
항목은 또한 맥락을 위해 `gate_passed`, `rounds_played`,
`official_rounds_played`를 보고한다.

## 무결성 주의 사항

- **자가 보고된 실행은 권위가 없다.** `compute_leaderboard` 출력
  (CLI `ceb leaderboard compute`, API `/api/leaderboard`)은 편의/진단
  뷰다. 항목은 러너가 통제하는 로컬 상태에서 계산되며, 스캔도, 비공개 팩
  강제도, 서명도 없다. 이것들을 공식 순위로 취급하지 않는다.
- **검증된 결과는 공개키로 검증 가능하다.** 검증된 보드는 워커가 산출한
  결과를 반영하며, 운영자의 **Ed25519 비공개 키**로 서명된다(권장; 레거시 HMAC도
  지원). 누구나 게시된 운영자 공개 키로 `ceb hosted verify-result --public-key`로
  진정성을 독립 확인할 수 있다(`docs/RESULT_SIGNING.md` 참조). 서명되지 않은
  결과는 결코 진정한 것으로 취급되지 않는다.
- **검증된 결과 전용이 공개용 기본값이다.** `ceb hosted leaderboard`와
  `GET /api/hosted/leaderboard`는 검증된 항목만 반환한다. 미검증 로컬
  보드는 순위 발행이 아니라 자가 점검을 위해 존재한다.
