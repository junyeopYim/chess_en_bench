# 리더보드 정책

실행의 순위가 매겨지는 방식. 구현: `bench/ceb/scoring/track_a.py`의
`compute_leaderboard`. `ceb leaderboard compute` CLI와
`/api/leaderboard` 엔드포인트(`bench/ceb/api/main.py`)로 노출된다.

## 순위 규칙: 실행당 최고의 검증 등재 가능 결과

로컬 리더보드는 `<results>/*/state.json`(기본 `runs/`)을 스캔한다. `track`
필드가 요청한 트랙과 일치하는 각 실행에 대해:

1. 실행에 기록된 라운드들을 순회한다.
2. 실행당 최고(`score`가 null이 아닌) `final_eval` 결과가 있으면 그것을,
   없으면 최고 `official_round`를 선택한다. `official`로 기록된 라운드(모드
   이름이 바뀌기 전에 작성된 레거시 실행)는 공식 라운드로 집계된다. quick
   라운드는 절대 집계되지 않는다.
3. 실행의 리더보드 점수는 그 선택된 점수이며, 항목은 그것을 산출한 라운드를
   기록한다(`best_round`: 라운드 번호, 점수, 모드).
4. 실행은 최고 점수 순으로 정렬된다. 읽을 수 없거나 비JSON인 `state.json`
   파일은 조용히 건너뛴다.

각 항목은 다음을 포함한다: `run_id`, `workspace`, `gate_passed`,
`rounds_played`(모든 라운드), `official_rounds_played`(공식 + final, quick
제외), `best_round`, `score`, `verified`. 이 스캐너는 자가 보고된 로컬
실행을 읽으므로 `verified`는 항상 `false`이고 보드 JSON은 `verified_only:
false`로 설정한다. 암호학적으로 **검증된** 공식 결과는 호스티드 워커에서만
나온다. `docs/LEADERBOARD_GOVERNANCE.md`를 참조한다. 출력 스키마는
`ceb.leaderboard/v1`이며 어떤 뷰가 보드를 산출했는지 기록하는 `include_quick`
필드를 갖는다.

## quick 라운드가 제외되는 이유

quick 라운드는 빠른 반복을 위해 존재한다: 무료이고 무제한이며, 비엄격
게이트를 실행하고, 50 ms movetime에서 상대 2명만 대국하며, 더 작은 오프닝
부분집합을 사용한다. 그 사다리(ladder) 점수는 공식 라운드와 비교할 수 없고
(상대 풀이 다르면 성능 평균이 다름), 무료 무제한 라운드를 집계하면 실행이
비용 없이 점수를 다시 굴릴(reroll) 수 있게 된다. 공식 라운드는 예산을
소비하고(실행당 3회), 엄격 게이트(`go perft` 필수)를 요구하며, 전체 6명 상대
풀을 대국한다 — 이것들만 집계된다.

## 진단 뷰: --include-quick

`ceb leaderboard compute --include-quick`(API:
`/api/leaderboard?include_quick=true`)은 quick 라운드도 고려한다. CLI 출력은
"diagnostic view: quick rounds INCLUDED — not an official ranking"으로
라벨링되며 JSON은 `include_quick: true`로 설정한다. 예산을 쓰기 전에
워크스페이스를 정상성 점검하는 데 사용하며, 절대 순위로 발행하지 않는다.
`best_round.mode`는 진단 항목의 최고가 quick 라운드에서 왔는지를 보여준다.

## 라운드를 유효하게 만드는 것

라운드는 실제로 실행된 경우에만 `state.json`에 나타나며, 다음이 필요하다
(`bench/ceb/rounds/round_runner.py`와 `rounds/state.py`가 강제):

- 게이트 통과 — 모든 라운드 시작 시 재실행되며, 게이트 실패는 어떤 매치보다
  먼저 라운드를 중단시킨다. 공식 라운드는 항상 엄격 게이트를 사용하고,
  quick 라운드는 공개(비엄격) 게이트를 사용한다.
- 공식 라운드의 경우 예산이 남아 있을 것(실행당 공식 라운드 3회. quick
  라운드는 무료이며 예산을 소비하지 않음).

기록된 `score`는 라운드의 `ceb.score.track_a/v1` 보고서의
`final_score`(사다리 점수에서 페널티를 뺀 값)다. 어떤 상대 페어링도 등급
경기(rated games)를 만들지 못하면 null이며, null 점수 라운드는 절대 실행의
최고 라운드가 되지 않는다.

## 동점과 null

정렬 키는 `(score is None, -score)`다:

- 자격을 갖춘 채점 라운드가 없는(`score`가 null) 실행은 모든 채점된 실행
  뒤로 정렬되며, 그들 사이에서는 스캔 순서를 유지한다.
- 정확한 점수 동점도 스캔 순서를 유지하고(Python의 정렬은 안정적임), 스캔은
  `sorted(glob("*/state.json"))`을 순회한다 — 따라서 동점은 실행 디렉터리
  이름의 알파벳 순으로 깨진다. 헤드 투 헤드(head-to-head)나 최소 라운드 수
  타이브레이커는 없다.

## 사용법

```bash
# CLI: rank all runs under runs/ for Track A, optionally write JSON
ceb leaderboard compute --track A --results runs --json-out leaderboard.json

# API + dashboard
ceb server start --host 127.0.0.1 --port 8000
curl http://127.0.0.1:8000/api/leaderboard            # official rounds only
curl "http://127.0.0.1:8000/api/leaderboard?include_quick=true"
```

API는 서버에 구성된 runs 디렉터리에 대해 동일한 `compute_leaderboard` 출력을
서빙한다. Track B의 경우 다음 메모와 함께 빈 `entries` 리스트를 반환한다:
Track B 라운드는 개별적으로 채점되며(`ceb track-b round run`, 고정 baseline
대비 델타 Elo) 아직 집계된 리더보드가 없다 — 그 집계는 계획되어 있으나
구현되지 않았다.

## 무결성 주의 사항 (수치를 신뢰하기 전에 읽을 것)

모든 리더보드 입력은 로컬 디스크의 자가 보고 파일이다:

- `state.json`과 라운드 보고서는 서명이나 변조 탐지 없이 하니스가 작성한
  평범한 JSON이다 — 파일 접근 권한이 있는 누구나 점수를 편집할 수 있다.
- 이 저장소에는 숨겨진 테스트 데이터가 들어 있지 않다. 운영자는 비공개
  eval 팩을 마운트할 수 있지만(`--eval-pack`, 또는 공식 라운드의 경우
  `CEB_PRIVATE_EVAL_DIR`), 리더보드는 라운드 보고서의 `eval_pack` 필드를
  넘어 어떤 팩이 점수를 산출했는지 알 수 없다.
- 항목의 `gate_passed`는 참고용이다. 라운드 러너 자체는 통과한 게이트 없이
  라운드 시작을 거부하지만, 리더보드는 게이트 실패 플래그가 있는 실행을
  제외하지 않는다.
- Docker 평가기 샌드박스(`--sandbox docker`)는 신뢰할 수 없는 제출물에
  권장되지만 선택적이다. 리더보드는 그것이 사용되었는지 기록하거나 검증하지
  않는다.

중요한 비교에는, 복사된 `runs/` 디렉터리를 신뢰하는 대신 제출된
워크스페이스에서 직접 공식 라운드를 다시 실행한다(`ceb round run --sandbox
docker`).
