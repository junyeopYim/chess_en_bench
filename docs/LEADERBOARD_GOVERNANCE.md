# 리더보드 거버넌스

리더보드에 무엇이 나타나는지, 어떻게 순위가 매겨지는지, 얼마나 신뢰할 수
있는지.

v0.3에는 **두 개의** 리더보드가 있다. 둘은 한 가지 결정적 속성에서 다르다:
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
(`bench/ceb/hosted/official_eval.py`)이 산출한 경우에만 검증된다. 그 경로는:

1. 스냅샷의 정적 부정 방지(anti-cheating) 스캔,
2. **비공개** eval 팩에 대한 엄격 게이트,
3. 비공개 팩으로 `official_round` 또는 `final_eval`(선택적 엔진 감옥),
4. 공개/비공개 아티팩트 분리,
5. 재현성 메타데이터 + 서명,
6. DB에 `verified=1`로 기록된 결과.

비공개 eval 팩이 없거나, 스캔이 실패하거나, 엄격 게이트가 실패하면 워커는
**검증을 거부한다** — 검증된 결과가 기록되지 않는다.

**로컬 순위는 결코 검증되지 않는다.** `compute_leaderboard`는 로컬
`ceb round run` 호출이 작성한 `state.json` 파일을 스캔하고 모든 항목에
`verified: false`를 찍는다. 이것들은 명령을 실행한 누군가에 의해 자가
보고된 것이며, 하니스는 그것을 증명하지 않는다. 로컬 보드의 페이로드는 이를
명시하기 위해 `verified_only: false`로 설정한다.

## 선택 규칙

두 보드 모두 **실행당 하나의 항목**을, 최고 점수 순으로 순위 매기며, 동일한
우선순위를 사용한다:

1. 존재한다면 **최고 `final_eval`** 결과, 없으면
2. **최고 `official_round`** 결과, 없으면
3. **없음** — 그 실행은 순위에 오르지 않는다.

**quick 라운드는 순위에 절대 집계되지 않는다.** 호스티드 워커는 quick 결과를
검증으로 표시하지 않으므로 quick은 검증된 보드에 도달할 수 없다. 로컬
보드에서 quick은 `--include-quick`이 설정되지 않는 한 제외되며, 이 옵션은
**진단** 뷰(quick을 포함한 *모든* 모드에 걸친 최고 점수)이고 결코 공식
순위가 아니다 — 그 페이로드도 여전히 `verified_only: false`를 보고한다.

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
- **검증된 결과는 대칭 서명만 지닌다.** 검증된 보드는 워커가 산출한 결과를
  반영하며, 이는 **대칭** HMAC-SHA256으로 서명된다(`docs/RESULT_SIGNING.md`
  참조). 진정성(authenticity)은 `CEB_SIGNING_KEY` 보유자만 확인할 수 있다
  — v0.3에는 **공개 키 증명이 없다.** 키가 없는 소비자는 운영자의 말을
  믿어야 한다.
- **검증된 결과 전용이 공개용 기본값이다.** `ceb hosted leaderboard`와
  `GET /api/hosted/leaderboard`는 검증된 항목만 반환한다. 미검증 로컬
  보드는 순위 발행이 아니라 자가 점검을 위해 존재한다.
