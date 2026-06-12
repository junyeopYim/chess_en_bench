# Track B — Stockfish 탐색 최적화

Track B는 에이전트가 **탐색 관련 파일만** 수정하여 고정된 Stockfish 베이스라인에
얼마나 많은 기력(playing strength)을 더할 수 있는지를 측정한다. 후보는 수정되지
않은 베이스라인 대비 델타 Elo로 채점된다. 에이전트는 평가(evaluation), NNUE
네트워크, 수 생성, 프로토콜, 빌드 파일을 절대 건드리지 않는다.

## 고정된 베이스라인

베이스라인은 **Stockfish 18**(태그 `sf_18`, 커밋 `cb3d4ee`)이며,
`tracks/b_stockfish_opt/stockfish.lock`에 고정되어 있다:

- repo: `https://github.com/official-stockfish/Stockfish.git`
- 위치: `third_party/stockfish`(gitignored — 여기에 절대 커밋되지 않음)

공식 평가는 이 정확한 커밋을 사용해야 하며, 움직이는 브랜치를 사용해서는 안 된다.
status 명령과 설정 스크립트는 둘 다 HEAD를 lock과 대조 검증한다.

Stockfish는 GPLv3이며 이 저장소와 함께 배포되지 **않는다**. `NOTICE`를 참고하라.
Stockfish 소스 또는 파생 바이너리의 재배포는 GPLv3를 준수해야 한다.

## 설정

```bash
bash scripts/setup_stockfish.sh        # clone + checkout sf_18, verify cb3d4ee
ceb track-b status                     # confirm the checkout
cd third_party/stockfish/src && make -j build   # needs make + a C++17 compiler
```

HEAD가 고정된 커밋과 일치하지 않으면 스크립트는 계속 진행하기를 거부한다.
설정 후 `ceb track-b status`는 HEAD 커밋, 그것이 lock과 일치하는지 여부, 그리고
준비됨/다음 단계 액션 라인을 보고한다(내부적으로 스키마 `ceb.track_b.status/v1`).

## diff 화이트리스트 정책

`tracks/b_stockfish_opt/`의 세 파일이 후보가 변경할 수 있는 것을 정의한다:

- `allowed_paths.txt` — 베이스라인과 다를 수 있는 유일한 파일들(fnmatch glob,
  Stockfish 소스 루트 기준 상대 경로): `src/search.cpp`, `src/search.h`,
  `src/movepick.cpp`, `src/movepick.h`, `src/history.h`, `src/timeman.cpp`,
  `src/timeman.h`, `src/tt.cpp`, `src/tt.h`.
- `forbidden_paths.txt` — 향후 화이트리스트 편집과 겹치더라도 절대 금지:
  `src/evaluate.*`, `src/nnue/*`, `**/*.nnue`, `src/position.*`,
  `src/movegen.*`, `src/bitboard.*`, `src/uci.*`, `src/ucioption.cpp`,
  Makefile, `scripts/*`.
- `patch_policy.yaml` — 정책 요약: forbidden이 allowed보다 우선한다. 파일 추가
  또는 삭제 금지. 화이트리스트된 9개 파일까지만 변경. 후보는 여전히 **수정되지
  않은** Makefile로 빌드되어야 하고 베이스라인의 `bench` 명령을 통과해야 한다.

체커(`bench/ceb/track_b/diff_policy.py`)는 두 트리를 SHA-256 콘텐츠 해시로
비교하고(`.git` 등은 건너뜀), 추가/삭제/수정된 모든 파일을 분류하며, forbidden
패턴과 일치하거나 화이트리스트가 다루지 않는 변경이 있으면 실패한다. 단독 명령은
`ceb track-b check-diff --baseline <dir> --candidate <dir>`이다(통과 시 종료 코드
0, 위반 시 2; 리포트 스키마 `ceb.track_b.diff_check/v1`; `--allowed` / `--forbidden`은
패턴 파일을 덮어쓰며 주로 테스트용).

## 자동 라운드: `ceb track-b round run`

라운드는 후보 빌드를 베이스라인 빌드와 대전시키고 채점된 리포트를 작성한다:

```bash
ceb track-b round run \
  --candidate-engine /path/to/candidate/src/stockfish \
  --baseline-engine third_party/stockfish/src/stockfish \
  --baseline-src third_party/stockfish \
  --candidate-src /path/to/candidate
```

플래그: `--round N`(기본 1), `--run-id ID`(기본 `track_b_local`), `--games N`(기본
8), `--movetime MS`(기본 100), `--max-plies N`(기본 300), `--openings-limit N`,
`--eval-pack DIR`, `--runs-dir DIR`, `--engine-jail none|docker`(기본 `none`),
그리고 `--runner internal|fastchess`(기본 `internal`). 엔진 spec은 실행 파일
경로이거나 벤치마크 상대 이름(`BenchRandom` … `BenchAlphaBeta3`)이다 — 이 이름들은
테스트 전용으로만 존재한다.

`--engine-jail docker`는 신뢰할 수 없는 **후보** 엔진만 Docker 감옥(engine jail,
`chess-en-bench-jail:0.4`)에 가둔다. 베이스라인은 호스트에서 신뢰된 상태로
실행된다. 이 경우 후보는 자신의 워크스페이스 디렉터리 안의 단일 실행 파일이어야
한다. `--runner fastchess`는 대량 매치를 위해 선택적 fastchess 백엔드
(`bench/ceb/match/fastchess_runner.py`)로 교체한다. `internal` 러너가 기본이자
신뢰된 레퍼런스이며, 바이너리가 없을 때 fastchess 명령은 실행 가능한 안내
메시지와 함께 실패한다.

러너(`bench/ceb/track_b/round_runner.py`)는 엄격히 순서대로 실행한다:

1. **diff 화이트리스트 검사** — `--baseline-src`/`--candidate-src`가 주어지면
   실행된다(둘이 함께 필수). 위반이 있으면 **단 한 판도 두기 전에** 라운드를
   중단한다(종료 코드 2; diff 리포트가 첨부됨).
2. 두 엔진에 대한 **UCI handshake 검증**; handshake 실패도 대국 전에 중단시킨다.
3. **쌍 오프닝, 색 교대 게임**: 오프닝은 쌍으로 순환되어 후보가 각 오프닝을 백으로
   한 번, 흑으로 한 번 둔다(`ceil(games/2)` 쌍). `Threads=1`과 `Hash=16`이 **양쪽**
   엔진에 전송된다.
4. `compute_delta_elo_report`를 통한 **채점**, 그 후 `runs/<run-id>/track_b_round_<n>/`
   아래에 산출물 생성: `report.json`(`ceb.track_b.round.report/v1` — 엔진 id, UCI
   옵션, `openings_used` id, `eval_pack`, `diff_check`, 합계, 결함, 점수), 운영자용
   전체 `match.json`과 `games.txt`, 그리고 위생 처리된 `feedback.json`
   (`ceb.track_b.feedback/v1` — 집계만: W/D/L, 결함, CI 포함 델타 Elo, 페널티, 오프닝
   *개수*; 수나 게임 로그 없음).

오프닝은 마운트된 비공개 평가 팩이 있으면 거기서 온다(`--eval-pack`, 또는 라운드가
공식 평가로 집계되므로 `CEB_PRIVATE_EVAL_DIR`). 없으면
`tracks/b_stockfish_opt/public/quick_openings.jsonl`(검증된 오프닝 4개; `.pgn`
파일은 사람 독자용으로만 유지됨)에서 온다. 그것도 없으면 Track A 공개 스위트에서
온다.

**실제 평가의 고정 조건:** 두 엔진은 모두 동일한 컴파일러 플래그로 빌드된 고정
Stockfish 18(`sf_18` / `cb3d4ee`) 빌드여야 하며, `Threads=1`, 고정된 `Hash`,
Syzygy 테이블베이스 없음이어야 한다. 러너는 UCI 옵션을 강제한다. 빌드 출처(build
provenance)는 문서화된 정책이며 코드로 강제되지 **않는다** — 러너는 주어진 실행
파일이 무엇이든 그대로 대국시킨다.

## 소스 우선 공식 파이프라인: `ceb track-b official run`

위의 `ceb track-b round run`은 이미 빌드한 두 엔진을 대국시킨다. 소스 우선
파이프라인(`ceb track-b official run`)은 대신 후보 *소스 트리*를 받아 스캔 →
같은 빌드 스크립트로 베이스라인 + 후보 빌드 → 쌍 매치 → 두 트리의 콘텐츠 해시를
포함한 서명된 `ceb.track_b.official_result/v1`를 실행한다. CLI 실행은
`verified:false`다(진단용). 실제 고정 Stockfish 빌드 래퍼, 동일한 컴파일러
플래그, `bench`/속도 정합성 검사는 운영자가 제공하며 코드로 강제되지 않는다.
전체 플래그 집합, 순서, 후보용 engine-jail 옵션, 그리고 구현됨/운영자 단계 구분은
**`docs/TRACK_B_OFFICIAL_PIPELINE.md`**를 참고하라.

## 델타 Elo 채점 모델

W/D/L은 `ceb.scoring.track_b`(스키마 `ceb.score.track_b/v1`)에 입력되며, 이는
`ceb.scoring.elo` 위에 구축된다:

- `score_rate = (W + 0.5*D) / games`, `eps = 1 / (2*(games+1))`로 (0,1)에 클램프
- `delta_elo = -400 * log10(1/score_rate - 1)`
- 게임별 점수에 대한 정규 근사를 통한 95% CI(z = 1.96)
- 후보 결함당 페널티: illegal_move 30, timeout 15, crash 25 Elo점;
  `final_delta_elo = delta_elo - penalty_points`

`tracks/b_stockfish_opt/track.yaml` 기준, 한 실행은 공식 라운드 3회를 가진다.
`tracks/b_stockfish_opt/public/quick_eval_config.yaml`은 참조용 quick-eval
파라미터를 문서화하며, 위의 CLI 기본값이 실제로 적용되는 값이다.

## 구현됨 vs 계획됨

구현됨:

- `stockfish.lock` 고정 + 커밋 검증이 포함된 `scripts/setup_stockfish.sh`
- `ceb track-b status`, `ceb track-b check-diff`
- `ceb track-b round run` — 게임 전 중단 diff 검사, handshake 검증, 쌍 오프닝,
  고정 UCI 옵션, 델타 Elo 채점, 위생 처리된 피드백을 갖춘 자동 후보-대-베이스라인
  라운드; 이제 `--engine-jail none|docker`(후보를 감옥에 가둠)와
  `--runner internal|fastchess`도 지원
- `ceb track-b official run` — 소스 우선 파이프라인(스캔 → 같은 빌드 스크립트로
  두 트리 빌드 → 매치 → 서명된 `ceb.track_b.official_result/v1`);
  `docs/TRACK_B_OFFICIAL_PIPELINE.md` 참고
- 선택적 fastchess 어댑터(`--runner fastchess`); internal 러너가 기본이자 신뢰된
  레퍼런스로 유지됨
- 공유 평가 팩 로더를 통한 숨겨진 오프닝 팩(`--eval-pack` / `CEB_PRIVATE_EVAL_DIR`);
  이 저장소에는 숨겨진 데이터가 배포되지 않음

계획됨 / 운영자 책임:

- 실제 고정 Stockfish 빌드 래퍼, 동일한 컴파일러 플래그, `bench`/속도 정합성
  검사는 운영자가 제공한다. 파이프라인은 빌드 스크립트가 산출하는 것을 빌드하고
  대국시킬 뿐 이들을 강제하지 않는다
- 집계된 Track B 리더보드(리더보드 명령은 Track A를 위한 것이며, Track B 리포트는
  실행별 산출물일 뿐)
