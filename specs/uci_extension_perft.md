# UCI 확장: `go perft <depth>`

게이트가 여러분의 수 생성기(move generator)를 직접 검증할 수 있게 해 주는,
최소 UCI 부분집합(`specs/uci_minimal.md`)에 대한 작은 벤치마크 특화 확장이다.
요구 사항은 두 단계(two-tier)다:

- **공개 게이트** (`ceb gate run`, 기본): 권장. 지원이 없으면 `warn`이며 —
  게이트는 여전히 통과한다 — 그러나 잘못된 카운트는 `fail`이다. 출하되는
  설정은 `perft_required: false`다
  (`tracks/a_from_scratch/public/gate_config.yaml`).
- **strict 게이트** (`ceb gate run --strict`; official 라운드는 어떤 게임
  전에든 항상 strict 게이트를 실행한다): 필수(REQUIRED). 지원이 없거나 **또는**
  잘못된 카운트가 게이트를 실패시키며, 실패한 게이트는 예산을 소비하지 않고
  라운드를 중단시킨다. 이 확장 없이는 official 라운드를 플레이할 수 없다.

게이트를 넘어, 잘못된 수 생성기는 매치에서 불법 수 결함(illegal-move fault)으로
드러나 게임과 페널티 점수를 잃게 한다 — perft를 일찍 구현하라.

## 명령

```
go perft <depth>
```

`perft(depth)`는 현재 포지션(앞선 `position` 명령으로 설정됨)에서 정확히
`<depth>` 플라이(plies) 떨어진 합법 수 트리(legal-move tree)의 리프 노드
개수다. Depth 1은 합법 수의 개수와 같다.

## 응답

**정확히 한 줄**을 출력한다:

```
info string perft <nodes>
```

여기서 `<nodes>`는 10진수 노드 카운트이며, 그다음 idle 상태로 돌아간다(게이트는
각 perft 후 `isready`를 보내고 `readyok`을 기대한다).

파서(`bench/ceb/uci/protocol.py`)는 다음을 매칭한다:

- `^info\s+string\s+perft\s+(\d+)\s*$` — 이 스펙이 정의하는 형식.
- `^Nodes searched:\s*(\d+)\s*$` — 역시 허용되므로, Stockfish 스타일의
  응답(수별 줄 다음에 `Nodes searched: N`)이 변경 없이 동작한다.
  카운트 이전의 매칭되지 않는 줄은 건너뛴다.

`go perft`에 대한 응답으로 `bestmove` 줄을 출력하지 마라.

## 게이트 동작

게이트의 `perft` 검사(`bench/ceb/gate/gate_runner.py`의 `check_perft`)는
해석된 평가 팩의 모든 perft row를 `depth <= perft_max_depth`(기본 3)로
실행하며, 오라클로 검증된 카운트와 비교한다.
공개 row는 `tracks/a_from_scratch/public/perft_examples.jsonl`에 있다.
strict(official 라운드) 평가는 운영자가 마운트한 평가 팩에서 숨겨진 row를
추가할 수 있다.

- **미지원 -> 공개에서 WARN, strict에서 FAIL.** 엔진이 `go perft`에 `bestmove`
  줄로 응답하면(즉 일반 탐색을 시작했으면), 또는 20초 이내에 인식 가능한
  응답을 내지 못하면(그러면 하네스는 `stop`을 보내고 늦은 `bestmove`를 비운다)
  엔진은 확장을 지원하지 않는 것으로 취급된다. strict 게이트는
  `perft_required: true`를 강제한다(게이트 설정에서 이를 설정하면 공개 게이트도
  동등하게 엄격해진다).
- **잘못된 카운트 -> 양쪽 모드에서 FAIL.** 기대값과 다른 어떤 노드 카운트든
  검사를 실패시키며, 실패한 검사는 전체 게이트를 실패시킨다(`passed`는
  건너뛰지 않은(non-skipped) 모든 비(非)warn 검사가 통과할 것을 요구한다 —
  `bench/ceb/gate/reports.py` 참고).
- 공개 게이트에서 `perft`는 약한(soft) 검사다: 이후 검사도 여전히 실행되어
  전체 리포트를 받게 된다. strict 모드에서는 강한(hard) 검사다 — 실패하면
  나머지 검사를 건너뛴다. 실패 세부 정보는 row id만 인용하며(예:
  `perft mismatch on hidden_perft_2 ...`), 결코 FEN을 인용하지 않는다.

실용적 결론: 확장을 구현하고 올바르게 만들어라. 꾸며낸 숫자로 응답하는 것은
구현하지 않는 것보다 엄밀히 더 나쁘다 — 그리고 구현하지 않으면 공개 게이트와
quick 라운드로 상한이 정해진다.

## 샘플 트랜스크립트

`>`는 하네스에서 엔진으로, `<`는 엔진에서 하네스로 가는 것이다.

```
> uci
< id name MyEngine 0.1
< uciok
> isready
< readyok
> position fen rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1
> isready
< readyok
> go perft 2
< info string perft 400
> isready
< readyok
```

Startpos 참조 값(공개 예제 파일에서): depth 1 = 20,
depth 2 = 400, depth 3 = 8902.

## 로컬에서 테스트하기

모든 공개 테스트 포지션과 기대 카운트를 사용할 수 있다:

```
cat tracks/a_from_scratch/public/perft_examples.jsonl
ceb gate run --track A --workspace <your-workspace> --strict
```

리포지토리의 오라클은 `bench/ceb/chess/perft.py`(`from ceb.chess import parse_fen;
from ceb.chess.perft import perft; perft(parse_fen(fen), depth)`)를 통해 임의
포지션에 대한 참조 카운트를 생성할 수 있다.
