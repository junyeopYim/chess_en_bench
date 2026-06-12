# 제출 계약 (Track A 워크스페이스)

이것은 제출 워크스페이스와 벤치마크 하네스 사이의 구속력 있는 계약이다.
게이트(`ceb gate run`)가 이를 기계적으로 강제한다. 라운드는 어떤 매치 전에든
게이트를 재실행하며, official 라운드는 항상 **strict 모드**에서 게이트를
실행한다(아래 perft 섹션 참고). 행위에 대한 금지 사항은
`specs/forbidden_behaviors.md`에 있다. 이 계약을 만족하는 참조 제출물은
`examples/submissions/minimal_uci_engine_python/`에 있다.

## 워크스페이스 레이아웃

워크스페이스 디렉터리는 다음 중 적어도 하나를 포함해야 한다(MUST):

- `./engine` — UCI를 말하는 실행 가능한 파일(아래 참고), 또는
- `./build.sh` — `./engine`을 생성하는 스크립트.

워크스페이스 내의 그 밖의 모든 것(소스, 데이터 파일)은 여러분의 것이다. 하네스는
오직 `build.sh`와 `engine`만 실행한다.

## build.sh

- `cwd` = 워크스페이스 디렉터리로 `bash build.sh`로 실행되며, 출력이
  캡처되고, **120초 타임아웃**이 적용된다. 이를 초과하거나 0이 아닌 값으로
  종료하면 `build` 검사가 실패한다(stderr/stdout의 마지막 300자가 보고됨).
- `build.sh`가 없으면 검사는 "prebuilt engine"으로 통과한다.
- 빌드 후, `./engine`은 일반 파일로 존재해야 한다. 실행 비트(execute bit)가
  없으면 하네스가 `chmod +x`를 시도한다. 그것에 의존하기보다 직접 설정하라.
- `engine`은 어떤 실행 파일이든 될 수 있다: 네이티브 바이너리, 또는
  인터프리터를 `exec`하는 래퍼 스크립트(예제는 `python3 engine.py`를 감싼다).

## 실행 환경

- 엔진은 argv만으로 — `[<workspace>/engine]`, 결코 셸을 통하지 않고 —
  `cwd` = 워크스페이스로 스폰된다. 워크스페이스에 상대적인 경로를 사용하거나
  `$0` / `argv[0]`에서 경로를 해석하라.
- stdin/stdout은 UCI 텍스트를 줄 버퍼링(line-buffered)으로 운반한다. **모든
  응답 후 stdout을 flush하라** — flush되지 않은 `bestmove`는 타임아웃과
  구별할 수 없다.
- stderr은 폐기된다. 8192자보다 긴 줄은 잘린다.
- 종료 시 하네스는 `quit`을 보낸 다음, 전체 프로세스 그룹에 SIGTERM/SIGKILL을
  보낸다. 엔진보다 오래 살아남아야 하는 프로세스를 스폰하지 마라.
- 엔진은 자기 완결적(self-contained)이어야 한다(MUST): `ceb` 패키지나 다른
  벤치마크 코드를 import하지 않고, 네트워크 접근 없이, 벤치마크 내부를 읽지
  않는다. 엔진은 워크스페이스와 기본(stock) 인터프리터 또는 자체적으로 정적
  가용한 의존성만으로 실행되어야 한다.

## 필수 UCI 부분집합

| 받는 것 | 응답해야 하는 것 | 마감 |
|---|---|---|
| `uci` | `id name <name>`(권장), 그다음 `uciok` | `uciok`까지 8s |
| `isready` | `readyok` | `readyok`까지 8s |
| `ucinewgame` | 없음(상태 리셋) | 다음 `isready`가 여전히 `readyok`을 받아야 함 |
| `position startpos [moves ...]` | 없음 | — |
| `position fen <FEN> [moves ...]` | 없음 | — |
| `go movetime N` | `bestmove <uci-move>` | **N + grace ms** (grace 기본 3000ms) |
| `setoption name <x> value <y>` | 없음 | 견뎌야 하며, 결코 크래시 금지(매치는 `setoption name Seed value <n>`을 보냄) |
| `quit` | 종료 | SIGTERM 이전 ~1.5s |

타임아웃은 `tracks/a_from_scratch/public/gate_config.yaml`에서 온다. 게이트는
bestmove 검사에 movetime 200ms + 3000ms grace를 사용하며, 더 엄격한 전용 시간
검사를 둔다: `go movetime 100`은 100 + 2500ms 이내에 `bestmove`를 내야 한다.
`go movetime N`을 강한 예산(hard budget)으로 취급하라: 탐색이 끝나지 않았더라도
항상 마감까지 `bestmove` 줄을 내보내라.

수는 UCI long algebraic 표기를 사용한다(`e2e4`, `e7e8q`, 캐슬링은 킹의 수
`e1g1`). 모든 `bestmove`는 현재 포지션에서 합법적이어야 한다 — 하네스는 각각을
내부 오라클에 대해 검증한다.

## 매치 시점 행위

- 게임은 항상 초기 포지션이 아니라 오프닝 스위트(opening suite)에서 시작한다:
  하네스는 각 오프닝(공개 스위트:
  `tracks/a_from_scratch/public/openings_public.jsonl`, 선택적으로 운영자가
  마운트한 숨겨진 팩으로 확장됨)을 시작 포지션으로 해석하고, 표준 시작 위치가
  아닌 한 이를 `position fen <FEN> [moves ...]`로 공급한다. 엔진은 임의의 합법
  FEN — 캐슬링 권리, 앙파상 칸, 수 카운터 — 를 처리해야 하며(MUST), startpos를
  가정할 수 없다.
- 모든 수 이전에 하네스는 전체 포지션을 재전송한다
  (`position startpos moves <지금까지의 모든 수>` 또는 `position fen ... moves
  ...`), 그다음 `go movetime N`. 증분(incremental) 상태에 의존하지 마라.
- 하네스는 결코 종료(terminal) 포지션에서 수를 요청하지 않는다. 게임은
  체크메이트, 스테일메이트, 50수 규칙, 또는 max-plies 판정에서 끝난다.
  합법 수가 없을 때 `bestmove 0000`으로 응답하는 것은 허용되는 안전 관례이며
  (예제 엔진 참고), 결코 필수가 아니다.
- 결함은 게임을 패배로 끝내고 라운드 점수에서 페널티를 받는다:
  불법 수(−30점), 타임아웃(−15), stdout에서 크래시/EOF(−25).

## `go perft <depth>` 확장 — official 라운드에 필수

게이트는 두 가지 모드로 실행된다. 기본 공개 게이트는 확장이 없을 때만 경고하며
(그리고 잘못된 카운트에는 실패한다). strict 게이트
(`ceb gate run --strict` — 그리고 official 라운드가 먼저 실행하는 게이트는
**항상**)는 이를 필수로 만든다: 지원이 없거나 카운트가 틀리면 게이트가 실패하고,
이는 어떤 게임 전에 라운드를 중단시킨다. 올바른 `go perft`가 없는 제출물은
공개 게이트를 통과할 수 있지만 official 라운드를 플레이할 수 없다.

`go perft D`에 대해, 한 줄로 응답한다:

    info string perft <nodes>

(Stockfish 스타일의 `Nodes searched: <nodes>`도 허용됨). 세부 사항은
`specs/uci_extension_perft.md`에 있다. 공개 포지션에 대한 기대 카운트는
`tracks/a_from_scratch/public/perft_examples.jsonl`에 있다(게이트는 depth ≤ 3을 검사).

## 준수 검증

```sh
ceb gate run --track A --workspace <dir> --json-out gate.json   # exit 0 = pass
ceb gate run --track A --workspace <dir> --strict               # official-round policy
ceb gate run --track A --workspace <dir> --no-match             # skip mini match
```

게이트는 무제한이며 결코 라운드 예산을 소비하지 않는다. 검사는 순서대로 실행된다
(format, build, engine, handshake, position, bestmove, perft, time,
BenchRandom 대비 mini match). 리포트(`ceb.gate.report/v1`, 자신의 모드를
`strict` 필드에 기록함)는 첫 번째로 실패한 검사를 세부 정보와 함께 명명한다.
strict 모드에서 `perft`는 강한(hard) 검사다: 실패하면 나머지 검사를 건너뛴다.
실패 세부 정보는 테스트 row를 id로만 참조하며, 결코 FEN으로 참조하지 않으므로,
숨겨진 eval-pack 포지션이 유출될 수 없다. 이 계약을 통과하지 못하는 반례
(counterexample)는 `examples/submissions/broken_engine_examples/`에 있다.
