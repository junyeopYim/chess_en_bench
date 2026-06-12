# Track A — 밑바닥부터 만드는 체스 엔진

Track A는 에이전트가 외부 체스 라이브러리 없이 동작하는 UCI 체스 엔진을
만들 수 있는지, 그리고 그 엔진을 고정된 상대 사다리(ladder)를 상대로 개선할
수 있는지를 측정한다. 여기 설명된 모든 것은 구현되어 있으며 로컬에서 실행된다.
숨겨진 데이터가 함께 배포되지는 않지만, 운영자는 공식 라운드를 위해 비공개 평가
팩을 마운트할 수 있다("Eval packs" 참고). 트랙 설정: `tracks/a_from_scratch/track.yaml`
(실행당 공식 라운드 3회, 게이트 시도 횟수 무제한, 최종 점수 = 최고 유효 라운드).
공식 리더보드는 공식 라운드만 집계한다.

## 밑바닥부터 구현 요구사항

제출물은 자체 체스 로직을 구현해야 한다: 보드 표현, 수 생성(move generation),
합법성 판정, 탐색(search). 제출물에서 외부 체스 라이브러리와 엔진은 금지된다 —
python-chess 금지, Stockfish 바인딩 금지, 다운로드한 엔진 바이너리, 오프닝 북,
테이블베이스 금지. 워크스페이스가 실행 가능한 `./engine`을 산출하기만 하면 어떤
언어든 허용된다.

이는 동작 기반으로 강제된다(모든 수는 벤치마크 자체 오라클 `bench/ceb/chess/`로
검증되며, perft 카운트는 교차 검증된다) 및 워크스페이스 검사로도 강제된다. 아직
자동 라이브러리 스캐너는 없다.

## 제출물 레이아웃

워크스페이스에는 다음 중 하나가 필요하다:

- `engine` — `specs/uci_minimal.md`의 UCI 서브셋을 구사하는 실행 파일, 또는
- `build.sh` — `./engine`을 생성하는 스크립트(제한 시간 120초); 게이트가 이를 실행한다.

```bash
ceb workspace prepare --track A --run-id myrun    # creates runs/myrun/workspace
```

동작하는 레퍼런스: `examples/submissions/minimal_uci_engine_python/`. 준비된
워크스페이스(`state.json` 옆의 `runs/<run_id>/workspace`)의 경우 라운드 러너가
상위 디렉터리에서 실행 id를 추론한다. `--run-id`로 덮어쓸 수 있다.

## 공개 게이트(public gate, 시도 횟수 무제한)

```bash
ceb gate run --track A --workspace runs/myrun/workspace [--strict] [--json-out F] [--no-match]
```

게이트는 라운드 예산을 절대 소비하지 않는다. 검사는 순서대로 실행되며, 치명적
실패(hard failure)가 발생하면 남은 무거운 검사는 건너뛴다. 통과 시 종료 코드 0,
실패 시 2. JSON 리포트(스키마 `ceb.gate.report/v1`, `strict` 필드 포함)는
`--json-out`이 주어지지 않는 한 `runs/_gate/` 아래에 저장된다. Bestmove/perft
실패 상세는 row id만 인용하며 FEN은 절대 인용하지 않는다.

| # | 검사 | 검증 내용 | 심각도 |
| --- | --- | --- | --- |
| 1 | format | 워크스페이스에 `engine` 또는 `build.sh` 존재 | hard |
| 2 | build | `build.sh`가 120초 내에 0으로 종료(사전 빌드 시 건너뜀) | hard |
| 3 | engine | `./engine`이 존재하고 실행 가능 | hard |
| 4 | handshake | `uci`/`uciok`, `isready`/`readyok` | hard |
| 5 | position | `position startpos` / `fen ...` / `moves ...` 수용 | hard |
| 6 | bestmove | 팩 FEN에 대한 합법 bestmove, 오라클 검증 | hard |
| 7 | perft | `go perft` 카운트가 오라클과 일치(깊이 ≤ 3) | soft / strict에서는 hard |
| 8 | time | `go movetime 100`에 대한 bestmove가 100 + 2500 ms 내 | hard |
| 9 | mini_match | BenchRandom 상대 50 ms/move로 2판, 후보 결함 0 | hard |

기본(비-strict) 모드에서 `go perft` 확장(`specs/uci_extension_perft.md`)은
권장 사항이다 — 지원이 없으면 경고만 하지만, 노드 카운트가 틀리면 게이트가
실패한다. **strict** 모드(`--strict`, 공식 라운드는 항상 사용)에서는 perft가
hard 검사다: 지원이 없거나 카운트가 틀리면 게이트가 실패하고 남은 검사를
건너뛴다. 올바른 perft가 없는 엔진은 공식 점수를 받을 수 없다. 모든 조정값
(타임아웃, movetime, 미니매치 크기)은 `tracks/a_from_scratch/public/gate_config.yaml`에
공개되어 있다: handshake 타임아웃 8초, bestmove movetime 200 ms + 3000 ms 유예,
보고되는 bestmove 실패는 최대 2건. 신뢰할 수 없는 제출물은 `--sandbox docker`로
실행한다(`docs/security.md`).

## 라운드 모드

```bash
ceb round run --track A --workspace runs/myrun/workspace --round 1 --quick   # free
ceb round run --track A --workspace runs/myrun/workspace --round 2           # spends budget
```

모든 라운드는 먼저 게이트를 다시 실행한다. 게이트가 실패하면 예산을 소비하지
않고 라운드를 중단한다. 공식 라운드는 strict 게이트를 실행하고(perft 필수),
quick 라운드는 비-strict 게이트를 실행한다. `tracks/a_from_scratch/scoring.yaml`
기준:

| 모드 | 게이트 | 상대 | 각 게임 수 | movetime | 최대 ply | 오프닝 | 앵커 | 예산 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| quick | non-strict | BenchRandom, BenchMaterial1 | 2 | 50 ms | 120 | first 2 | [] | free |
| official | strict | 전체 6종(아래 사다리 순서) | 4 | 200 ms | 200 | first 6 | [] | 1 of 3 per run |

내부 러너(`bench/ceb/match/internal_runner.py`)는 색을 번갈아 두고, 각 게임에
시드를 부여하며, 모든 수를 오라클과 대조 검증하고, ply 상한과 50수 규칙으로
무승부를 판정한다. 산출물은 `runs/<run_id>/round_N/`에 생성된다: 상대별
`match_vs_*.json`(게임별 `opening_id`와 `openings` 목록 포함), UCI-movetext
게임 파일, `report.json`(`ceb.round.report/v1`, `openings_used`, `strict_gate`,
`eval_pack` 포함), 그리고 `feedback.json`(`ceb.round.feedback/v1`) — 집계 전용:
상대별 W/D/L과 점수율, 결함 수, 점수, 일반적 조언. 수 로그, FEN, 오프닝 id는
피드백되지 않는다.

## 오프닝 스위트(opening suite)

게임은 항상 `startpos`에서 시작하는 것이 아니라 검증된 오프닝 스위트에서
시작한다. 표준 형식(`bench/ceb/match/openings.py`)은 JSONL이며, 한 줄에 오프닝
하나다: `{"id", "fen": "startpos"|FEN, "moves": [UCI...], "tags": [...]}`. 모든
수는 로드 시점에 오라클 검증된다(불법인 것이 있으면 `OpeningError`). 공개
스위트는 `tracks/a_from_scratch/public/openings_public.jsonl`(오프닝 8개)이며,
`.pgn` 파일은 사람 독자용으로만 남아 있다. 각 라운드 모드는 해소된 스위트의 첫
`openings_limit`개 오프닝을 사용한다(quick 2, official 6). 오프닝은 쌍으로 진행
된다 — 같은 오프닝을 색을 바꿔 두므로 후보는 각 오프닝을 백과 흑 양쪽으로 둔다.
`pairs = ceil(games_per_opponent / 2)`. 라운드 전체에서 스위트는 상대별로 회전
되므로(상대 `j`는 오프셋 `j·pairs`에서 시작하며 순환), 한 라운드가 단일 매치보다
더 많은 오프닝을 다룬다.

## 평가 팩(Eval packs)

평가가 소비하는 데이터는 팩으로 묶인다(`bench/ceb/eval_pack.py`). 공개 팩 =
`fen_examples.jsonl` + `perft_examples.jsonl` + `openings_public.jsonl`. 비공개
팩은 `fen_hidden.jsonl` / `perft_hidden.jsonl` / `openings_hidden.jsonl` 중 임의의
것과 선택적 `manifest.json`(`{"name", "openings_mode": "extend"|"replace"}`,
기본 extend)을 담은 디렉터리다. 비공개 row는 항상 id를 받으므로 리포트가 숨겨진
FEN을 인용하지 않는다. 해소 규칙: 명시적 `--eval-pack <dir>` 플래그는 어디서나
적용되고, `CEB_PRIVATE_EVAL_DIR` 환경 변수는 공식 라운드와 strict 게이트에만
적용된다. 이 저장소에는 숨겨진 데이터가 배포되지 않는다. `examples/eval_packs/tiny_private/`는
테스트에 쓰이는 가짜 데모 팩이다. `--eval-pack`은 `--sandbox docker`와 함께
지원되지 않는다.

## 앵커(Anchors, 선택)

`tracks/a_from_scratch/scoring.yaml`은 강도 제한 앵커 엔진을 정의한다
(`anchor_opponents`: SF18_UCI_Elo_1320/1600/1900/2200 — 엔진 바이너리 이름,
`uci_elo`, `rating`). 라운드는 모드의 `anchors` 목록에 이름이 있을 때만 앵커를
둔다(기본은 비어 있음). 엔진 바이너리가 PATH에 없으면 라운드 러너는 실패하는
대신 진행 메모와 함께 앵커를 건너뛴다. 존재할 경우
`UCI_LimitStrength`/`UCI_Elo`를 보낸다. 앵커는 CI에서 절대 필수가 아니다.

## 상대 풀(Opponent pool)

벤치마크 소유이고, 시드가 주어지면 결정적이며(러너가 게임별로 설정), 단독 실행
가능하다: `python -m ceb.match.opponents BenchRandom`.

| 이름 | 명목 레이팅 | 수 선택 방식 |
| --- | --- | --- |
| BenchRandom | 400 | 균등 랜덤 합법수 |
| BenchGreedyCapture | 600 | 가능하면 가장 높은 가치의 캡처(앙파상 포함), 없으면 랜덤 |
| BenchMaterial1 | 800 | 깊이 1 negamax, 기물 가치만으로 평가 |
| BenchPST1 | 1000 | 깊이 1 negamax, 기물 가치 + 중앙/폰 전진 칸 보너스 |
| BenchMiniMax2 | 1200 | 깊이 2 negamax, 기물 가치만으로 평가 |
| BenchAlphaBeta3 | 1400 | 깊이 3 alpha-beta, 기물 가치 + 칸 보너스 |

깊이 기반 상대는 `go movetime` 내에서 반복적으로 깊이를 늘리고, 완료된 가장 깊은
깊이로 폴백한다. 동등한 수 사이의 동점은 시드된 RNG로 해소한다.

## 채점 요약

상대별(`bench/ceb/scoring/elo.py`, `bench/ceb/scoring/track_a.py`):

- `score_rate = (W + 0.5·D) / games`, `eps = 1 / (2·(games+1))`로 (0, 1)에 클램프
- `delta_elo = −400 · log10(1/rate − 1)`
- `performance = opponent_rating + delta_elo`

`ladder_score` = 상대 전체에 대한 평균 performance. 후보 결함당 페널티:
illegal_move 30, timeout 15, crash 25점. 라운드 `final_score = ladder_score − penalties`
(스키마 `ceb.score.track_a/v1`). 실행의 점수는 그 **최고 유효 공식 라운드**다.
다음으로 실행 순위를 매긴다:

```bash
ceb leaderboard compute --track A --results runs [--json-out F]
```

공식 라운드만 집계된다. `--include-quick`은 진단용 뷰이며(출력에 그렇게
표시됨), 절대 공식 순위가 아니다.

## 공개 데이터 파일(`tracks/a_from_scratch/public/`)

| 파일 | 내용 |
| --- | --- |
| `fen_examples.jsonl` | 게이트 bestmove 검사에 쓰이는 태그된 FEN 10개(캐슬링, 앙파상, 승급, 엔드게임) |
| `perft_examples.jsonl` | perft 검사에 쓰이는 position/depth/node row 10개(startpos, Kiwipete, CPW 포지션) |
| `gate_config.yaml` | 공개 게이트 조정값(게이트 러너가 읽음) |
| `openings_public.jsonl` | 게임 시작 위치로 쓰이는 표준 공개 오프닝 스위트(오프닝 8개) |
| `openings_public.pgn` | 같은 라인을 PGN으로 담은 것, 사람 독자용 — 러너가 파싱하지 않음 |

에이전트는 이들을 모두 읽을 수 있다. 공식 라운드는 추가로 운영자가 마운트한
비공개 팩을 사용할 수 있으며, 그 내용은 에이전트 피드백에 절대 나타나지 않는다.
