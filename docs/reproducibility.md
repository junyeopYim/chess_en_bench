# 재현성(Reproducibility)

chess_en_bench 실행을 반복 가능하게 만드는 요소, 나중에 감사할 수 있도록 영속화되는
대상, 그리고 결정성(determinism)이 솔직히 어디서 끝나는지.

## 구현됨

### 게임별 시드

내부 매치 러너(`bench/ceb/match/internal_runner.py`)는 모든 게임에 시드를 부여한다.
`play_match(..., base_seed=N)`은 게임 `i`에 시드 `base_seed + i`를 주고,
`play_game`은 첫 수 이전에 그 시드를 **두** 엔진 모두에게 보낸다.

    setoption name Seed value <base_seed + i>

맥락별 시드 부여:

- 공식/quick 라운드(`bench/ceb/rounds/round_runner.py`)와 Track B 라운드
  (`bench/ceb/track_b/round_runner.py`): `base_seed = 1000 * round_number`. 같은
  라운드 번호를 다시 실행하면 동일한 시드를 재생한다.
- 게이트 미니 매치(`bench/ceb/gate/gate_runner.py`): `play_match`의 기본값,
  `base_seed = 1`.

벤치마크 상대(`python -m ceb.match.opponents <Name>`)는 `Seed` UCI 옵션을 구현하고
이로부터 자신의 `random.Random`을 재설정한다. `setoption`을 거부하는 후보 엔진도
허용된다. 색상은 결정적으로 교대된다(짝수 인덱스 게임에서 후보가 백). 무승부 판정은
규칙 기반(fifty-move rule, `max_plies` 상한)이며 판단 기반이 아니다.

### 결정적 오프닝

시작 포지션은 검증된 JSONL 스위트(`bench/ceb/match/openings.py`)에서 온다. 모든
오프닝의 모든 수는 로드 시점에 오라클로 점검되므로, 손상된 스위트는 조용히 포지션을
바꾸는 대신 `OpeningError`를 일으킨다. 선택은 순수 산술이며 무작위성이 없다.

- 라운드 모드는 해석된 스위트의 처음 `openings_limit`개 오프닝을 취한다(quick 2,
  공식 6 — `tracks/a_from_scratch/scoring.yaml`).
- 상대 `j`는 `rotate_suite(suite, pairs, j * pairs)`를 받는다 — 고정된 순환 윈도우
  이므로 라운드가 스위트 전체를 덮고 같은 상대는 항상 같은 오프닝을 본다.
- 게임은 쌍으로 진행된다. 연속된 두 게임이 하나의 오프닝을 색상만 바꿔 재사용하므로
  후보가 각 오프닝을 백과 흑 양쪽으로 두게 된다.

매치 보고서는 스위트(`"openings"`)와 각 게임의 `opening_id`를 기록하고, 라운드
보고서는 `"openings_used"`를 기록한다.

### 평가 팩은 평가 조건의 일부다

공식 라운드와 strict 게이트는 평가 팩을 해석한다(`bench/ceb/eval_pack.py`). 공개
데이터에 선택적 비공개 디렉터리(`--eval-pack`, 또는 공식/strict 실행에서는
`CEB_PRIVATE_EVAL_DIR`)가 더해진다. 팩의 FEN, perft, 오프닝 내용은 게이트 결과와
라운드 시작 포지션을 바꾸므로, **두 실행은 같은 팩 아래에서만 비교 가능하다**.
비공개 팩에 버전을 매겨라. 개정마다 안정적인 `manifest.json` `"name"`을 부여하면
라운드 보고서의 `"eval_pack"` 블록이 이름, 소스, 행 수를 기록하며, 이것이 점수가
무엇에 대해 측정되었는지 감사하는 방법이다.

### 고정된 Track B baseline

`tracks/b_stockfish_opt/stockfish.lock`은 Stockfish 18, 태그 `sf_18`, 커밋
`cb3d4ee`로 고정한다 — 움직이는 브랜치가 아니다. `scripts/setup_stockfish.sh`는 그
태그를 체크아웃하고 커밋이 불일치하면 단호히 실패한다. Track B 라운드
(`ceb track-b round run`)는 어떤 게임이든 시작하기 전에 diff 화이트리스트를 점검한
뒤, `Threads=1 Hash=16`을 두 엔진 모두에게 보내 쌍 오프닝·색상 교대 게임을 둔다.
두 바이너리에 동일한 컴파일러 플래그와 빌드 조건을 두는 것은 실제 평가에서 정책상
요구되며 — 문서화되어 있으나 코드로 강제되지는 않는다.

### 영속화되는 실행 메타데이터

평가가 생성하는 모든 것은 `runs/<run_id>/` 아래에 떨어진다.

- `state.json` (`ceb.run.state/v1`) — 게이트 상태/시도, 공식 라운드 예산, 점수가
  포함된 전체 라운드 궤적.
- `gate_report.json` (`ceb.gate.report/v1`) — 체크별 결과와 어떤 게이트 정책이
  실행됐는지 알려주는 `"strict"` 필드.
- `round_<N>/report.json` (`ceb.round.report/v1`) — 모드, `strict_gate`,
  `eval_pack`, `openings_used`, 상대별 합계, 결함, 점수.
- `round_<N>/match_vs_<Opponent>.json` (`ceb.match.report/v1`) — 모든 게임의 전체
  UCI 수 목록, 오프닝 id, 결과, 종료 사유, 최종 FEN.
- `round_<N>/feedback.json` (`ceb.round.feedback/v1`) — 에이전트에게 보여주는 정제된
  집계값(FEN, 수, 오프닝 id 없음).

수 목록, 오프닝 id, 시드(`base_seed + game_index`로 도출 가능)가 저장되므로, 어떤
게임이든 내부 오라클(`bench/ceb/chess/`)로 재생하고 재검증할 수 있다.

### 설정 주도 파라미터

게이트와 라운드 파라미터는 버전 관리되는 파일에 있다.
`tracks/a_from_scratch/public/gate_config.yaml`,
`tracks/a_from_scratch/scoring.yaml`(라운드 모드, 오프닝 한도, 상대 및 앵커 레이팅,
페널티), `tracks/a_from_scratch/track.yaml`(공식 라운드 예산). 동일한 설정에 동일한
시드와 팩을 더하면 동일한 평가 조건이 된다.

### 버전 교차 점검으로서의 CI

`.github/workflows/ci.yml`은 전체 파이프라인을 실행한다 — 테스트, doctor, 공개 및
strict 게이트, 준비된 워크스페이스 quick 라운드(`runs/ci_smoke/round_1/report.json`
존재 단언), 두 모드의 리더보드 — Python 3.10/3.11/3.12에서 매 push와 PR마다 실행되어
평가 파이프라인이 지원 인터프리터 전반에서 지속적으로 점검된다. CI는 Stockfish도
Docker도 사용하지 않는다.

## 동일한 quick 라운드 다시 실행하기

quick 라운드는 무료이므로(공식 예산을 소비하지 않음) 안정성 점검을 위해 반복할 수
있다.

    ceb workspace prepare --track A --run-id demo
    # put your engine in runs/demo/workspace, then:
    ceb round run --track A --workspace runs/demo/workspace --round 1 --quick
    cp runs/demo/round_1/match_vs_BenchRandom.json /tmp/first.json
    ceb round run --track A --workspace runs/demo/workspace --round 1 --quick
    diff /tmp/first.json runs/demo/round_1/match_vs_BenchRandom.json

실행 id `demo`는 `runs/demo/workspace` 레이아웃에서 추론된다(`default_run_id`).
`--run-id`로 재정의할 수 있다. 같은 라운드 번호는 같은 `base_seed`(1000), 같은 상대,
같은 오프닝, 같은 movetime을 뜻한다. 라운드 번호를 다시 실행하면 `round_<N>/`
아티팩트를 **덮어쓰고** `state.json`에 덧붙이므로 — 보고서를 먼저 복사하라. 동일한
수 목록은 아래 주의사항 범위 안에서만 기대하라(`elapsed_s`는 항상 다르다).

## 솔직한 주의사항

- **Movetime 타이밍은 벽시계(wall-clock)다.** 탐색 깊이가 경과 시간에 의존하는 엔진은
  머신 부하가 다르면 다른 수를 고를 수 있다.
- **깊이 기반 상대도 시간 제한을 받는다.** `BenchRandom`과 `BenchGreedyCapture`는
  시드가 주어지면 완전히 결정적이지만, 나머지는 마감 시한에 맞서 반복 심화
  (iterative deepening)를 사용하므로 부하가 걸린 머신은 같은 시드에서도 선택된 수를
  바꿀 수 있다. 활성화된 선택적 앵커 엔진(`UCI_Elo` 수준의 Stockfish)에도 같은 것이
  적용된다.
- **후보 엔진은 비결정적일 수 있다.** 제출물이 `Seed`를 따르도록 강제하는 것은 없다.
  스레드, 해시 테이블, 자체 타이밍 로직이 실행마다 달라질 수 있다.
- **타임아웃과 결함 경계는 `movetime + grace_ms` 근처에서 타이밍에 민감하다.**
- **환경 고정은 부분적이다.** `--sandbox docker`는 평가를
  `chess-en-bench-evaluator:0.2` 이미지(`python:3.12-slim` 베이스)에서 실행하여
  Python 런타임을 고정하지만 — 베이스 태그가 digest로 고정되어 있지 않아 다른 날
  재빌드하면 달라질 수 있고, 호스트 실행(기본값)은 머신에 있는 것을 그대로 사용한다.

## 러너

내부 Python 러너가 기본값이며 모든 매치와 테스트의 신뢰 기준이다. 대량 Track B
매치를 위한 선택적 `fastchess` 어댑터(`ceb track-b round run --runner fastchess`)가
제공되지만, 결함을 귀속시키지 않고 결과에 접어 넣으며 아직 오라클 PGN 사후 검증이
없으므로 내부 러너가 권위 있는 기준으로 남는다. `cutechess-cli` 어댑터는 구현되어
있지 않다.
