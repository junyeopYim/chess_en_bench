# 최소 UCI 부분집합 (Track A 제출물)

이것은 벤치마크 하네스가 사용하는 정확한 UCI 부분집합이다. 여러분의 엔진과
대화하는 코드에서 파생되었다: `bench/ceb/uci/client.py`,
`bench/ceb/uci/protocol.py`, `bench/ceb/gate/gate_runner.py`,
`bench/ceb/match/internal_runner.py`. 아래의 모든 것을 구현하면 엔진이 게이트와
매치 러너(match runner)에서 동작한다. 이 부분집합을 넘어서는 것(options, ponder,
infinite search, MultiPV, ...)은 결코 필수가 아니다.

언제든 무료로 구현을 검증하라:

```
ceb gate run --track A --workspace <your-workspace>
```

## 프로세스 모델

- 엔진은 워크스페이스를 작업 디렉터리로 하여 `./engine`(argv만, 셸 없음)으로
  스폰된다.
- 모든 통신은 stdin/stdout을 통한 줄 기반 텍스트다. 줄을 `\n`으로 종료하고
  모든 줄 이후 stdout을 flush하라(줄 버퍼링 사용).
- stderr은 폐기된다. 프로토콜 출력을 거기에 두지 마라.
- 8192자보다 긴 출력 줄은 잘리며, 하네스는 최대 10000개의 대기 줄을
  버퍼링한다. 탐색 잡담(chatter)을 적당히 유지하라. 무제한 도배는 자신의
  stdout 쓰기를 막을 수 있다.

## 필수 명령

| 하네스가 보내는 것 | 엔진이 응답해야 하는 것 | 비고 |
| --- | --- | --- |
| `uci` | `uciok`으로 끝나는 줄들 | `id name <name>`은 파싱되어 있으면 보고된다(권장). `id author`나 `option ...` 같은 다른 줄은 무시된다. |
| `isready` | `readyok` | 핸드셰이크 후, `ucinewgame` 후, `position` 명령 후 동기화 장벽(sync barrier)으로 사용된다. 항상 동작해야 한다. |
| `ucinewgame` | 없음 | 새 게임을 위해 리셋. 항상 `isready`가 뒤따른다. |
| `position startpos` | 없음 | 초기 포지션 설정. |
| `position fen <FEN>` | 없음 | 임의 포지션 설정(6-필드 FEN). |
| `position startpos moves <m1> <m2> ...` | 없음 | 기본 포지션 이후 UCI 수를 적용. `position fen <FEN> moves ...`로도 보내진다. |
| `go movetime <ms>` | `bestmove <move>` | 대략 `<ms>` 밀리초 동안 탐색한 다음, 정확히 하나의 `bestmove` 줄을 출력. |
| `quit` | 종료 | 즉시 종료. |

세부 사항:

- 하네스는 `bestmove` 이전의 모든 줄을 무시한다(예: `info depth 3
  score cp 21`). 따라서 info 출력은 허용되지만 결코 필수가 아니다.
- `bestmove e2e4 ponder e7e5`는 허용된다. `bestmove` 다음의 첫 번째 토큰만
  사용된다.
- 매치 중에 하네스는 모든 수 이전에 **전체** 포지션을 재전송한다:
  `position startpos moves <지금까지의 모든 수>` 다음에
  `go movetime <ms>`. 따라서 여러분의 `moves` 처리는 긴 수 목록에 대해서도
  올바르고 충분히 빨라야 한다.
- 하네스가 기다리기를 포기하면 `stop`이 보내질 수 있다(현재는 perft 검사에서만,
  `specs/uci_extension_perft.md` 참고). 즉각적인 `bestmove`로 이를 존중하면
  복구가 더 깔끔해진다. 무시하는 것 자체는 게이트 실패가 아니다.

## 수 형식

수는 순수 좌표 표기(coordinate notation)이며, `bench/ceb/chess/move.py`가
생성하고 파싱한다:

- `from`+`to` 4글자(`e2e4`, `g8f6`), 또는 프로모션 기물이 있는 5글자.
- 프로모션 기물은 소문자이며, `q r b n` 중 하나: `e7e8q`.
- 캐슬링은 킹의 두 파일(two-file) 이동: `e1g1`, `e1c1`, `e8g8`, `e8c8`.
- 앙파상은 잡는 폰의 앙파상 칸으로의 대각 이동이다(예: FEN ep 필드가
  `f6`일 때 `e5f6`).
- 널 무브(null move)는 없다. 모든 `bestmove`는 내부 오라클에 대해 검증된다.
  불법 수는 게이트의 bestmove 검사를 실패시키고, 매치에서는 `illegal`
  결함으로 게임을 패배시킨다(채점에서 페널티).

## 타이밍 기대치

`tracks/a_from_scratch/public/gate_config.yaml`의 기본값(이 파일은 공개이며,
현재 값은 직접 읽어라):

- 핸드셰이크: `uciok` 다음 `readyok`이 각각 해당 명령으로부터 8초 이내.
- `go movetime T`: 하네스는 `bestmove`를 위해 `T + grace`를 기다린다
  (게이트의 bestmove 검사와 매치에서 grace 3000 ms).
  윈도를 놓치면 게이트 실패이거나, 매치에서는 `timeout` 결함이다
  (패배와 점수 페널티).
- 전용 시간 검사: `go movetime 100`은 `100 + 2500` ms의 총 예산 안에
  반환해야 한다.
- 게이트는 50 ms만큼 낮은 movetime을 시험한다(mini match). 어떤 합법 수든
  빠르게 반환하는 것이 마감을 넘겨 탐색하는 것보다 항상 낫다.
- `quit` 시 하네스가 전체 프로세스 그룹의 SIGTERM 다음 SIGKILL로
  에스컬레이트하기 전에 약 1.5초의 종료 시간을 받는다.

## 샘플 트랜스크립트

`>`는 하네스에서 엔진으로, `<`는 엔진에서 하네스로 가는 것이다.

```
> uci
< id name MyEngine 0.1
< id author Example
< uciok
> isready
< readyok
> ucinewgame
> isready
< readyok
> position startpos moves e2e4 e7e5
> go movetime 100
< info depth 3 score cp 21
< bestmove g1f3
> position fen r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1
> isready
< readyok
> go movetime 200
< bestmove e1g1
> quit
```

터미널에서 `./engine`을 실행하고 하네스 쪽을 손으로 입력하여 대화식으로
테스트하거나, 벤치마크 상대와 비교할 수 있다:
`python -m ceb.match.opponents BenchRandom`이 동일한 부분집합을 말한다.
