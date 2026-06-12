# 금지 행위 (규범)

이 목록은 평가 대상이 되는 모든 에이전트와 그 에이전트가 제출하는 모든 것
(엔진 바이너리, 소스, `build.sh`, Track B 패치)에 적용된다. "MUST NOT"은
규범적이다. 어떤 규칙이든 위반하면 해당 평가가 무효가 된다. 즉 게이트
시도가 실패하거나, official/quick 라운드가 무효화되며 — official
라운드의 경우 — 그래도 라운드 예산을 소비한다. 고의적이거나 반복적인 위반은
실행(run) 전체를 무효화한다.

벤치마크가 이미 규칙을 기계적으로 강제하는 경우에는 강제 지점을
명시한다. 그 외 모든 것은 운영자(operator)가 워크스페이스와
아티팩트를 검토하여 강제한다. "자동으로 탐지되지 않음"이 결코 "허용됨"을 의미하지는 않는다.

## 양쪽 트랙 공통

1. **실행 시점 네트워크 접근 금지.** 제출물은 빌드(`build.sh`), 게이트,
   어떤 매치 중에도 네트워크 연결을 열어서는 안 된다(MUST NOT) — 다운로드,
   온라인 엔진이나 테이블베이스, 텔레메트리 모두 금지.
   *(`--sandbox docker`(`--network none`)로 평가를 실행할 때 강제된다.
   기본 host 모드는 이를 차단하지 않는다 — docs/security.md 참고.)*

2. **벤치마크 내부나 상대(opponent)를 읽거나 패치하는 행위 금지.** 제출물은
   `bench/ceb/`(`bench/ceb/chess/`의 오라클과 `bench/ceb/match/opponents.py`의
   상대 포함), `tracks/*/private/`, 또는 다른 실행의 데이터를 읽거나, import하거나,
   수정하거나, 링크해서는 안 된다(MUST NOT). 공개 트랙 데이터(`tracks/*/public/`,
   public으로 표시된 설정)는 설계상 읽을 수 있다.

3. **워크스페이스 외부 쓰기 금지.** 제출물이 생성하거나 수정하는 모든
   파일은 자신의 워크스페이스 디렉터리
   (`runs/<run-id>/workspace/`, `ceb workspace prepare`가 생성) 안에 머물러야 한다(MUST).

4. **하네스(harness) 프로세스나 파일을 표적으로 삼는 행위 금지.** 제출물은
   하네스나 형제(sibling) 프로세스에 시그널을 보내거나, kill하거나, ptrace하거나,
   그 밖의 방식으로 간섭해서는 안 되며(MUST NOT), `runs/`, `artifacts/`, 리포트, 또는
   PGN/게임 파일을 조작해서도 안 된다. *(강제됨: 엔진은 자체 프로세스 그룹에서
   실행되며 종료 시 그룹 단위로 kill된다 — `bench/ceb/uci/client.py`.)*

5. **출력 폭주(flooding)나 프로토콜 남용 금지.** 엔진은 평가를 지연시키려고
   stdout을 도배해서는 안 되며(MUST NOT), 설정된 타임아웃 안에 UCI 명령에 응답해야 한다.
   *(강제됨: 줄은 8,192자에서 잘리고, 인테이크는 큐에 쌓인 10,000줄로 제한되며,
   stderr은 폐기되고, 모든 읽기는 타임아웃을 가진다 — 폭주는 엔진 자신에게만
   해가 되고, 타임아웃은 `tracks/a_from_scratch/scoring.yaml`에 따른 페널티와 함께
   결함(fault)으로 채점된다.)*

6. **불법 수(illegal move) 금지.** 모든 수는 내부 오라클에 대해 검증된다.
   불법 수는 결함이며 페널티를 받는다.
   *(강제됨 — `bench/ceb/match/internal_runner.py`.)*

## Track A (밑바닥부터 만든 엔진)

7. **외부 체스 라이브러리나 엔진 금지.** 엔진은 밑바닥부터 빌드되어야 한다(MUST).
   즉 `python-chess` 금지, Stockfish/Lc0(바이너리, 소스, 또는 NNUE 가중치) 금지,
   수 생성(move-generation)이나 탐색 라이브러리 금지, 오프닝 북이나 테이블베이스
   금지. 일반적인 비(非)체스 라이브러리(stdlib, 빌드 도구)는 괜찮다. 기존 엔진의
   코드를 벤더링(vendoring)하거나 옮겨 적는(transcribing) 것은 그것을 사용한
   것으로 간주한다.

8. **공개 테스트 데이터에 대한 사전 계산 정답 금지.** `tracks/a_from_scratch/public/fen_examples.jsonl`의
   bestmove나 `perft_examples.jsonl`의 perft 카운트를 계산하지 않고 하드코딩하는 것은
   위반이다.

## Track B (Stockfish 탐색 최적화)

9. **움직이는 브랜치 베이스라인 금지.** 베이스라인은 정확히
   `tracks/b_stockfish_opt/stockfish.lock`의 핀(Stockfish 18, 태그 `sf_18`,
   커밋 `cb3d4ee`)이어야 하며(MUST), `scripts/setup_stockfish.sh`를 통해 가져온다 — 결코
   `master`나 다른 움직이는 ref가 아니다. 다른 베이스라인에 대한 결과는
   무효다. *(강제됨: 설정 스크립트는 핀된 커밋과 일치하지 않는 HEAD를 거부한다.)*

10. **diff 화이트리스트 외부 편집 금지.** 후보(candidate)는 베이스라인과
    `tracks/b_stockfish_opt/allowed_paths.txt`에 매칭되는 파일
    (search/movepick/history/timeman/tt)에서만 달라질 수 있다.
    `forbidden_paths.txt`에 매칭되는 파일(evaluation, NNUE, movegen, position, bitboards,
    UCI, Makefile, 스크립트)은 화이트리스트 편집이 혹시라도 겹쳤더라도 변경되어서는
    안 된다(MUST NOT) — forbidden이 우선한다. 파일을 추가하거나 제거할 수 없다
    (`patch_policy.yaml`). *(강제됨 — 직접 실행해 보라:)*

    ```sh
    ceb track-b check-diff --baseline third_party/stockfish --candidate <dir>
    ```

11. **후보는 완전한 Stockfish로 남아 있어야 한다.** 후보는 수정되지 않은
    Makefile로 빌드되어야 하며(MUST) 베이스라인 `bench` 명령을 통과해야 한다.
    화이트리스트 파일을 통해 evaluation을 도려내는 것은 diff 검사를 통과하더라도
    의도에 대한 위반이다.

## 결과

- 게이트 단계(Track A): 위반 = 게이트 시도 실패. 시도 횟수는 무제한이므로
  고쳐서 재실행하면 된다: `ceb gate run --track A --workspace <dir>`.
- 라운드: 위반 = 해당 라운드가 무효화되고 최종 점수에서 제외된다(최종 점수는
  가장 좋은 **유효한(valid)** 라운드). 무효화된 official 라운드도 3개의
  official-round 슬롯 중 하나를 여전히 소비한다.
- Track B: `check-diff` 실패나 잘못된 베이스라인은 후보를 채점 대상에서
  부적격으로 만든다.
- 타이밍이나 합법성 위반에 해당하는 결함(illegal_move, timeout, crash)은
  추가로 결함당 점수 페널티(30/15/25점)를 받는다.
