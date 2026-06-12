# 에이전트 프로토콜 (Track A)

이 문서는 평가 대상인 당신, 에이전트를 향한 것이다. 당신이 수행하는 루프,
받는 입력, 사용할 수 있는 명령, 그리고 지켜야 하는 경계를 정의한다.
워크스페이스 안에 무엇이 들어가야 하는지에 대한 산출물 계약은
`specs/submission_contract.md`에 있다. 절대 금지 사항은
`specs/forbidden_behaviors.md`에 있으니 — 코드를 작성하기 전에 먼저 읽는다.

## 받는 것

| 입력 | 위치 | 목적 |
|---|---|---|
| 과제 지시문 | `runs/<run-id>/instructions.md` (`tracks/a_from_scratch/prompt.md`의 사본) | 무엇을 만들지 |
| 제출 계약 | `specs/submission_contract.md` | 정확한 워크스페이스/UCI 요구사항 |
| 공개 FEN 포지션 | `tracks/a_from_scratch/public/fen_examples.jsonl` | 게이트가 `bestmove` 합법성을 검사하는 포지션 (캐슬링, 앙파상, 승급, 체크 회피, 엔드게임) |
| 공개 perft 데이터 | `tracks/a_from_scratch/public/perft_examples.jsonl` | 무브 생성기를 검증하기 위한 정확한 노드 수 |
| 공개 오프닝 | `tracks/a_from_scratch/public/openings_public.jsonl` | 매치 게임이 시작되는 오프닝 모음 (옆의 `.pgn`은 사람이 읽기 위한 사본이며, 실제로는 JSONL만 사용됨) |
| 게이트 설정 | `tracks/a_from_scratch/public/gate_config.yaml` | 공개 게이트의 타임아웃과 제한; strict 모드에서는 추가로 `go perft`가 필수가 됨 |
| 게이트 리포트 | 출력된 요약 + JSON (`ceb.gate.report/v1`, `strict` 필드 포함), `runs/_gate/` 또는 `--json-out`에 저장됨 | 검사별 pass/fail/warn/skip와 상세 내용 |
| 라운드 피드백 | `runs/<run-id>/round_N/feedback.json` (`ceb.round.feedback/v1`) | 각 라운드 이후의 집계 결과 |

운영자는 추가 FEN, perft, 오프닝 행으로 이루어진 숨겨진 평가 팩(hidden eval
pack)을 마운트할 수 있으며, 이는 공식 라운드와 strict 게이트에 적용된다.
당신은 그 내용을 절대 볼 수 없다: 게이트 실패 상세는 행 id만 인용하며(FEN은
절대 인용하지 않음), 라운드 피드백은 집계 전용이다.

## 실행할 수 있는 명령

```sh
ceb workspace prepare --track A --run-id <id>          # create runs/<id>/workspace
ceb gate run --track A --workspace <dir> [--strict] [--json-out F] [--no-match]
ceb round run --track A --workspace <dir> --round N --quick   # free smoke round
ceb round run --track A --workspace <dir> --round N           # official (budgeted, strict gate)
ceb doctor                                              # environment diagnosis
```

`ceb`는 `python -m ceb.cli`로도 실행할 수 있다. 라운드의 경우 준비된
워크스페이스 경로(`runs/<id>/workspace`)에서 `--run-id`가 추론되며, 그렇지
않으면 명시적으로 전달한다. 공개 트랙 데이터와 `runs/<run-id>/` 아래 자신의
실행 산출물은 자유롭게 읽을 수 있다. 채점에 영향을 주기 위해 벤치마크
내부를 읽거나 수정해서는 안 된다 — `specs/forbidden_behaviors.md` 참고.

## 루프: 관찰하고, 수정하고, 게이트를 다시 실행한다

1. 워크스페이스에 엔진을 둔다: 실행 가능한 `./engine`, 또는 그것을 생성하는
   `build.sh` (계약: `specs/submission_contract.md`).
2. 게이트를 실행한다. 무료이며 무제한이다 — 의미 있는 변경마다 매번
   사용한다:
   ```sh
   ceb gate run --track A --workspace runs/<id>/workspace --json-out gate.json
   ```
3. 리포트를 읽는다. 검사는 순서대로 실행된다 — `format`, `build`, `engine`,
   `handshake`, `position`, `bestmove`, `perft`, `time`, `mini_match` — 그리고
   하드 실패는 나머지를 건너뛰므로 첫 번째 `fail`을 먼저 고친다. 각 검사의
   `details` 문자열이 무엇이 잘못되었는지 알려준다 (예: 행 id와 발견된 불법
   무브). 종료 코드 0 = 통과, 2 = 실패.
4. `perft`는 2단계이다: 기본 공개 게이트에서는 `go perft` 미지원이 `warn`이지만
   (잘못된 노드 수는 언제나 `fail`), 공식 라운드는 **strict** 게이트를
   실행하며 거기서는 미지원이 하드 `fail`이다. 확장을 구현하고
   `perft_examples.jsonl`에 대해 일찍 검증한다 — 나중에 발견되는 불법 무브
   버그는 라운드 예산을 소모한다.
5. 게이트를 통과하면 quick 라운드(무료, 예산을 소모하지 않음)를 실행해 실제
   매치 결과를 본다. 공식 라운드를 쓰기 전에 `ceb gate run --strict`가
   통과하는지 확인한다 — 이것이 바로 공식 라운드가 다시 실행할 게이트이다.

## 라운드와 예산

- 예산: 실행당 공식 라운드 3회. quick 라운드와 게이트 실행은 무료이다.
- quick 모드: 상대 2명(BenchRandom, BenchMaterial1), 각각 2게임,
  movetime 50ms, 모음의 첫 2개 오프닝. 공식 모드: BenchAlphaBeta3까지 상대
  6명, 각각 4게임, movetime 200ms, 6개 오프닝을 상대마다 로테이션하여
  라운드가 전체 모음을 다룸.
- 게임은 오프닝 모음에서 시작된다: 각 오프닝은 두 번 플레이되며, 한 번은
  당신이 백, 한 번은 흑이다. 시작 포지션은 `position fen ...`로 도착하므로
  절대 startpos를 가정하지 않는다.
- 모든 라운드는 먼저 게이트를 다시 실행한다(공식 라운드는 strict); 게이트가
  실패하면 예산을 소모하지 않고 라운드를 중단한다.
- 당신의 최종 실행 점수는 유효한 최고 라운드이므로, 초반의 약한 공식
  라운드는 예산을 소모하지만 점수를 절대 낮추지 않는다.

## 피드백이 반복을 이끄는 방식

각 라운드 이후 정제된 집계 전용 피드백을 받는다
(`ceb.round.feedback/v1`): 상대별 W/D/L과 득점률, 결함 횟수,
패널티 점수, 사다리/최종 점수, 일반적인 조언. 무브 로그, FEN, 오프닝 id,
숨겨진 평가 데이터에서 나온 어떤 것도 포함하지 않는다 — 이를 요청하거나
재구성하려 하지 않는다.

다음 순서로 읽는다:

1. **결함 먼저.** 후보 결함당 패널티: illegal_move −30,
   timeout −15, crash −25점이며, 각 결함은 해당 게임도 잃게 한다.
   - `illegal`: 공개 perft 데이터에 대해 합법성을 다시 확인한다 (캐슬링
     권리, 앙파상, 핀).
   - `timeout`: `go movetime N`을 존중한다 — 탐색이 끝나지 않았더라도 예산
     내에 항상 `bestmove` 줄을 출력한다.
   - `crash`: 입력 파싱을 견고하게 한다; 예외가 프로세스를 죽이도록 두지
     않는다.
2. **그 다음 강함.** 결함이 0이면 상대별 득점률이 사다리에서 당신의 위치를
   보여준다 (명목 레이팅 400 → 1400). BenchMaterial1(800)에게 진다는 것은
   기물 계산이 빠졌다는 뜻이고, BenchMiniMax2(1200)에게 진다는 것은 실제
   탐색 깊이가 필요하다는 뜻이다. 탐색과 평가를 개선하는 것이 더 높은
   사다리 점수의 주된 지렛대이다.
3. 게이트와 quick 라운드에 대해 반복한다; 다음 공식 라운드는 quick 라운드
   결과가 분명히 개선될 때만 쓴다.

## 절대 해서는 안 되는 것

`specs/forbidden_behaviors.md`가 권위 있는 목록이다. 요약하면: 엔진에서
벤치마크 코드를 임포트하거나 셸 아웃하지 않는다, 무브를 만들기 위해 다른
체스 엔진이나 라이브러리를 호출하지 않는다, 네트워크를 사용하지 않는다,
벤치마크 내부·상대·채점을 읽거나 조작하지 않는다, 그리고 체스를 두는 대신
평가 하니스를 노리지 않는다. 엔진은 자체 완결적이어야 하며 당신이 처음부터
직접 빌드해야 한다. 위반 시 실행이 무효화된다.
