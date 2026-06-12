# Track A 에이전트 프롬프트 — 처음부터 UCI 체스 엔진 만들기

이 프롬프트는 평가 대상 에이전트에게 그대로 전달된다. `ceb workspace prepare`가
이를 `runs/<run_id>/instructions.md`로 복사한다. `<run_id>` 같은 꺾쇠괄호
필드는 실행 시작 전에 운영자가 채운다.

## 역할

당신은 chess_en_bench 벤치마크, Track A에서 평가받는 코딩 에이전트이다.
당신은 모든 코드를 워크스페이스 안에서 직접 작성한다. 벤치마크와는 아래
나열된 `ceb` CLI 명령을 통해서만 상호작용한다.

## 맥락

벤치마크는 당신이 빌드한 체스 엔진을 6개의 고정된 상대 사다리(BenchRandom 400
… BenchAlphaBeta3 1400 명목 Elo)와 대국시켜 채점한다. 공개 정확성 게이트는
**무제한** 무료로 실행할 수 있다. 공식 채점 라운드는 예산이 있다:
**실행당 3회**이며, 당신의 최종 점수는 당신의 최고 공식 라운드이다. quick
라운드(`--quick`)는 무료 스모크 평가이다. 게임은 공개 오프닝 모음에서
시작되며 — 공식 라운드는 숨겨진 오프닝을 추가할 수 있으므로 — 당신의 엔진은
본 적 있는 라인뿐 아니라 임의의 포지션에서도 올바르게 플레이해야 한다. 라운드
피드백은 집계 전용이다(W/D/L, 득점률, 결함 횟수, 점수) — 무브 로그, FEN,
오프닝 id는 없다.

## 과제

워크스페이스에 자체 완결적인 UCI 체스 엔진을 만들고 당신의 최고 공식 라운드
점수를 극대화한다. 결함은 발생당 패널티가 부과된다: 불법 무브
−30, 타임아웃 −15, 크래시 −25점. 정확성이 먼저, 강함이 그 다음이다.

## 입력

- 워크스페이스(여기에 제출물을 둔다): `runs/<run_id>/workspace/`
- 구현해야 하는 UCI 하위집합: `specs/uci_minimal.md`
- perft 확장, 공식 라운드에 필수: `specs/uci_extension_perft.md`
- 공개 데이터: `tracks/a_from_scratch/public/` — `fen_examples.jsonl`,
  `perft_examples.jsonl`, `gate_config.yaml`, `openings_public.jsonl`
  (오프닝 모음; `openings_public.pgn`은 사람을 위한 동일한 라인)
- 규칙과 채점 상세: `docs/track_a_from_scratch.md`,
  `tracks/a_from_scratch/scoring.yaml`

## 제약

- **처음부터.** 보드 표현, 무브 생성, 합법성, 탐색을 당신이 직접 구현한다.
  제출물에 외부 체스 라이브러리, 엔진 바이너리, 오프닝 북, 또는
  테이블베이스(예: python-chess, Stockfish)는 없어야 한다.
- 워크스페이스는 실행 가능한 `engine`, 또는 120초 이내에 `./engine`을
  생성하는 `build.sh`를 담아야 한다.
- 엔진은 `uci`, `isready`, `ucinewgame`, `position`, `go movetime N`에
  답해야 하며 — movetime에 약간의 유예를 더한 시간 내에 항상 `bestmove <uci>`로
  응답한다. 불법 무브에 대해 bestmove를 절대 출력하지 않으며; 알 수 없는
  입력에 결코 크래시하지 않는다.
- **공식 라운드는 `go perft <depth>`를 요구한다.** 이들은 perft 미지원이나
  잘못된 노드 수가 게이트를 실패시키는 strict 게이트를 실행하며, 게이트
  실패는 라운드를 중단시킨다. 기본 `ceb gate run`은 perft가 빠졌을 때만
  경고한다; 공식 정책을 미리 보려면 `--strict`를 추가한다.
- 게임은 오프닝 포지션에서 시작하며(오프닝마다 양쪽 컬러), 숨겨진 것을 포함할
  수 있다 — startpos 라인을 외우는 것보다 모든 곳에서의 올바른 무브
  생성(캐슬링, 앙파상, 승급, 핀)이 더 중요하다.
- 벤치마크 코드, 러너 상태, 또는 워크스페이스 밖의 어떤 것도 읽거나 수정하지
  않는다. 네트워크 접근 없음.
- 공식 라운드 예산은 3이다; 게이트 실행과 quick 라운드는 무제한이다.

## 반복 루프

1. 최소한의 올바른 엔진을 작성하고(무작위 합법 무브가 유효한 시작이다)
   `go perft`를 일찍 구현한다 — 이는 채점에 필수이며 최고의 무브젠 디버깅
   도구이다.
2. 게이트를 실행하고 통과할 때까지 실패를 고친다 — 이것은 무료이다:
   `ceb gate run --track A --workspace runs/<run_id>/workspace`
3. quick 라운드로 강함을 무료로 스모크 테스트한다:
   `ceb round run --track A --workspace runs/<run_id>/workspace --round 1 --quick`
4. 탐색과 평가를 개선하고(합법 무브젠 → 기물 평가 → 알파-베타 →
   무브 정렬 → 시간 관리), 각 변경 후 게이트를 다시 실행한다.
5. STRICT 게이트가 통과하고
   (`ceb gate run --track A --workspace runs/<run_id>/workspace --strict`)
   quick 라운드 결과가 강해 보일 때만 공식 라운드를 쓴다:
   `ceb round run --track A --workspace runs/<run_id>/workspace --round 2`
6. `runs/<run_id>/round_N/feedback.json`을 읽고, 개선하고, 반복한다. 가장
   강한 버전을 위해 최소 하나의 공식 라운드를 예비로 남겨둔다 — 당신의 최종
   점수는 유효한 최고 공식 라운드이므로, 낭비된 라운드는 결코 회복할 수
   없다.

strict 게이트가 통과하기 전에 공식 라운드를 실행하지 않는다: 라운드는 먼저
strict 게이트를 다시 실행하고 실패하면(예산을 소모하지 않고) 중단하지만, 그
시도는 당신의 시간을 낭비한다.

## 출력 형식

마치면 워크스페이스는 최종 `engine`(또는 그것을 빌드하는 `build.sh`)과 그
소스를 담아야 한다. 다음을 명시하는 짧은 평문 요약으로 끝낸다:

- 어느 라운드 번호가 당신의 최고 공식 라운드이며 그 최종 점수가 무엇인지,
- 사용한 공식 예산(3 중),
- 당신의 엔진을 기술하는 한 단락(무브젠 접근, 탐색, 평가).

## 수용 기준

- `ceb gate run --strict`가 최종 워크스페이스에서 종료 코드 0(perft를 포함한
  모든 검사 통과).
- 최소 하나의 공식 라운드가 완료됨; `runs/<run_id>/state.json`이 이를 기록함.
- 최고 라운드에서 후보 결함(불법 무브, 타임아웃, 크래시) 0건.
- 제출물에 외부 체스 라이브러리나 엔진이 없음.
