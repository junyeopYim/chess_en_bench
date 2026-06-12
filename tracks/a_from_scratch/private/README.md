# Track A — 비공개 평가 팩 (마운트 지점)

**이 저장소는 어떤 숨겨진 데이터도 배포하지 않는다.** 이 디렉터리는 이
README를 제외하면 비어 있으며 관례적인 마운트 경로를 git에 유지하기 위해
존재한다. 로더는 실재한다: `bench/ceb/eval_pack.py`가 운영자가 관리하는
비공개 팩 디렉터리를 읽어 공개 Track A 데이터와 병합한다.

전체 eval-pack 인터페이스 — 공개 파일, 비공개 팩 파일
(`fen_hidden.jsonl`, `perft_hidden.jsonl`, `openings_hidden.jsonl`,
`manifest.json`), 숨겨진 행 id 부여, 숨김 안전 로딩, 해결
규칙, jail 결합 보장, `eval_pack_hash` 버전 관리 — 는
**[`docs/EVAL_PACKS.md`](../../../docs/EVAL_PACKS.md)**에 한 번 문서화된다. 아래
노트는 Track A 고유 사항이다.

## Track A의 해결 방식

- `ceb gate run`, `ceb round run`, `ceb hosted worker run-once`의
  `--eval-pack <dir>`는 어디서든 명시적으로 팩을 로드한다.
- `CEB_PRIVATE_EVAL_DIR`은 옵트인하는 평가만 소비한다: strict
  게이트(`ceb gate run --strict`)와 공식 라운드. 평범한 공개
  게이트와 quick 라운드는 결코 이를 읽지 않는다.
- 이 디렉터리를 암묵적으로 읽는 것은 아무것도 없다 — 배포는 플래그나
  환경 변수를 이곳(또는 운영자가 관리하는 다른 경로)으로 가리켜야 한다.
- `--eval-pack`은 `--engine-jail docker`와 결합하지만(팩은 호스트 측에서
  읽히며 결코 마운트되지 않음) 레거시 `--sandbox docker` 모드에서는 **지원되지
  않는다**.

정확한 레이아웃을 가진 가짜 데모 팩은
`examples/eval_packs/tiny_private/`에 있으며; 테스트 스위트가 이를 사용한다.

## 상태

| 조각 | 상태 |
|---|---|
| 비공개 팩 로더(`bench/ceb/eval_pack.py`) | 구현됨 |
| 데모 팩 + 테스트(`examples/eval_packs/tiny_private/`) | 구현됨 |
| 실제 숨겨진 FEN/perft/오프닝 데이터 | 미배포 — 운영자 관리, 배포마다 마운트 |
| 숨겨진 상대 | 팩 인터페이스의 일부가 아님(앵커 엔진은 대신 `../scoring.yaml`에 설정됨) |

숨겨진 팩에 의존하는 결과는 정제된 피드백 계약
(`specs/round_feedback_contract.md`)을 통해서만 에이전트에 도달한다.
