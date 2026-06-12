# chess_en_bench — 개요

chess_en_bench는 체스 엔진을 만들거나 최적화하는 LLM 코딩 에이전트를 위한 벤치마크
플랫폼이다. 에이전트는 워크스페이스, 명시적 지시, 공개 테스트 데이터를 받는다. 하니스는
정확성 게이트를 통해 엔진을 검증하고, 검증된 오프닝 모음에서 고정된 상대 풀을 상대로 시드된
매치를 진행하며, 그 결과를 Elo 기반 점수와 리더보드로 바꾼다.

v0.3은 벤치마크를 **호스팅형 공식 평가**로 실행할 수 있도록 준비한다. 신뢰할 수 없는 엔진은
Docker **엔진 감옥(engine jail)** 에 가둘 수 있으며, 신뢰되는 평가자(evaluator)는 호스트에
남아 비공개 평가 팩을 직접 읽는다. 단일 노드 **호스팅형 파이프라인**(SQLite + 로컬 객체
저장소)은 각 제출물을 스냅샷하며 `verified: true` 결과를 생성하는 유일한 경로다. 이는
MVP다 — 단일 노드, 대칭(운영자 전용) 서명, 서버 로컬 제출 경로 — 그리고 모든 v0.2 명령은
여전히 동작한다.

## 두 개의 트랙

**Track A — 처음부터 만드는 엔진**(`tracks/a_from_scratch/`). 에이전트는 UCI 체스 엔진을
무에서 만든다. 워크스페이스에는 실행 가능한 `engine`(또는 그것을 생성하는 `build.sh`)이
있어야 한다. 평가에 앞서 무제한 공개 게이트 시도가 선행된다. 모든 공식 등급 라운드는 먼저
**엄격** 게이트를 다시 실행하고(여기서는 `go perft` 확장이 필수다), 그다음 후보를 번들된 여섯
상대(BenchRandom 400부터 BenchAlphaBeta3 1400 명목 Elo까지)와 맞붙여 사다리 레이팅에서 결함
페널티를 뺀 값으로 채점한다. 선택적인 Stockfish `UCI_Elo` 앵커 상대는 `scoring.yaml`에서
활성화할 수 있다. 바이너리가 없으면 우아하게 건너뛰는데, 단 어떤 모드가
`anchors_required`(호스팅형)를 설정한 경우에는 앵커가 없으면 라운드를 중단한다.

**Track B — Stockfish 탐색 최적화**(`tracks/b_stockfish_opt/`). 에이전트는 고정된 Stockfish
베이스라인(Stockfish 18, 태그 `sf_18`, 커밋 `cb3d4ee` — 움직이는 브랜치는 절대 아님,
`stockfish.lock` 참조)의 탐색 관련 파일만 수정할 수 있다. 채점은 신뢰구간을 동반한 후보 대
베이스라인의 델타 Elo다(`ceb.score.track_b/v1`). `ceb track-b round run`은 바이너리 후보를
바이너리 베이스라인과 맞붙인다(diff 화이트리스트 → 핸드셰이크 → 쌍지어진 오프닝 게임 → 델타
Elo 보고서). `ceb track-b official run`은 소스 우선(source-first) 파이프라인이다: 스캔 →
**동일한** 빌드 스크립트로 베이스라인 + 후보 빌드 → 쌍지어진 매치 → 서명된
`ceb.track_b.official_result/v1`. CLI 실행은 진단용이다(`verified: false`). 내부 러너가
신뢰되는 기준이며 `--runner fastchess`는 선택적 대용량 백엔드다.

## 평가 모드

Track A 라운드는 세 가지 모드 중 하나로 실행된다(`tracks/a_from_scratch/scoring.yaml`의
`round_modes`; 기본값은 `bench/ceb/rounds/round_runner.py`에 있음):

- **quick** — 무료, 진단용, 비엄격 게이트. 상대당 2게임, 처음 2개 오프닝. 예산을 절대
  소비하지 않으며 리더보드에 절대 등장하지 않는다.
- **official_round** — 엄격 게이트. 예산 3단위 중 1단위 소비. 상대당 4게임, 처음 6개 오프닝.
- **final_eval** — 엄격 게이트. 리더보드 품질. 상대당 8게임, 처음 8개 오프닝. 라운드 예산을
  소비하지 **않는다**(언제 실행할지는 호스팅형 정책이 결정한다).

`compute_leaderboard`(및 호스팅형 리더보드)는 최고 `final_eval`로 순위를 매기고, 없으면 최고
`official_round`로, `quick`은 절대 사용하지 않는다. 레거시 `official` 모드 키는 여전히
집계된다. `--include-quick`은 명확히 라벨링된 진단 뷰일 뿐이다.

## 엔진 감옥 대 레거시 샌드박스

서로 다른 두 격리 메커니즘이 존재하며 교체 사용할 수 없다:

- **엔진 감옥**(`--engine-jail docker`, `bench/ceb/jail/`,
  `infra/docker/engine_jail.Dockerfile`, 태그 `chess-en-bench-jail:0.4`).
  **오직** 신뢰할 수 없는 엔진만 가둔다. 평가자는 호스트에서 신뢰된 상태로 남아 비공개 팩을
  읽고 오라클과 채점을 실행한다. 엔진은 `/submission`에 읽기 전용으로 마운트된 자신의
  워크스페이스만 보며, `--network none`, 읽기 전용 루트 + tmpfs `/tmp`,
  `--cpus 1 --memory 1g --pids-limit 128`, `no-new-privileges`, 비-root, stdio 전용
  UCI가 적용된다. 저장소, 평가 팩, 상대 마운트는 없다. 감옥 이미지는 의도적으로 `ceb`
  패키지를 생략하므로 갇힌 엔진은 평가자 코드를 import할 수 없다. 팩은 호스트 측에서 읽히고
  엔진에는 `position fen ...` UCI 줄로만 도달하므로, `--eval-pack`은 `--engine-jail docker`와
  함께 동작한다. 이것이 호스팅형 공식 격리다.
- **레거시 샌드박스**(`--sandbox docker`, `bench/ceb/sandbox/`,
  `infra/docker/evaluator.Dockerfile`, 태그 `chess-en-bench-evaluator:0.2`).
  저장소를 읽기 전용으로 마운트한 컨테이너 안에서 전체 하니스를 다시 실행한다.
  호환을 위해 유지되며, 여전히 `--eval-pack`을 거부하고 호스팅형 공식 경로는 **아니다**.

둘 다 기본값은 `none`(호스트 실행; 신뢰/로컬 용도)이다.

## 검증됨 대 미검증 결과

호스팅형 공식 워커(`bench/ceb/hosted/worker.py`)만 `verified: true`를 기록한다. 정적 스캔 →
비공개 팩에 대한 엄격 게이트 → 비공개 팩과 선택적 엔진 감옥으로
`official_round`/`final_eval` → 공개/비공개 아티팩트 → 메타데이터 + 서명 순으로 실행하며,
비공개 평가 팩이 없거나, 스캔이 실패하거나, 엄격 게이트가 실패하면 **검증을 거부한다**. 로컬
`ceb round run` 결과와 직접 실행한 `ceb track-b` 실행은 항상 `verified: false`(자가 보고
진단)다. 검증 전용 호스팅형 리더보드와 공개 API 표면이 이 구분을 강제한다.
[리더보드 거버넌스](LEADERBOARD_GOVERNANCE.md)를 참조한다.

## 설계 원칙

- **명시적 지시.** 각 트랙은 `prompt.md`를 제공한다. `ceb workspace prepare`는 이를
  `instructions.md`로 실행에 복사한다. 암묵적 규칙은 없다.
- **구조화된 기계 판독 가능 출력.** 모든 아티팩트는 버전이 명시된 JSON이다(아래 스키마 목록
  참조). 에이전트와 운영자는 텍스트를 긁는 대신 결과를 파싱한다.
- **공개 데이터는 제공, 비공개 데이터는 선택.** 게이트 FEN, perft 카운트, 오라클로 검증된
  JSONL 오프닝 모음은 `tracks/*/public/` 아래에 있다. 운영자는 비공개 평가 팩을 마운트할 수
  있다(`--eval-pack <dir>`, 또는 공식 등급 라운드와 엄격 게이트에는 `CEB_PRIVATE_EVAL_DIR`).
  팩은 호스트 측에서 읽히며 엔진 감옥에는 절대 마운트되지 않는다.
  `examples/eval_packs/tiny_private/`가 그 형태를 문서화한다(실제 비공개 데이터는 커밋되지
  않음). [평가 팩](EVAL_PACKS.md)을 참조한다.
- **반복적 게이트 → 라운드 루프.** 게이트 시도는 무제한이며 무료다. 단독 공개 게이트와 quick
  라운드는 비엄격 스모크 테스트다. 공식 등급 라운드는 항상 엄격 게이트를 실행한다.
- **아티팩트 가시성(기본 거부).** 모든 아티팩트 디렉터리는 `artifacts_manifest.json`(스키마
  `ceb.artifacts.manifest/v1`)을 가진다. 명시적으로 `public`으로 표시된 파일만 제공
  가능하다. `feedback.json`과 `report.public.json`(스키마 `ceb.round.report.public/v1`;
  `verified:false`; 비공개 팩에 대해 숨겨진 오프닝 id는 null 처리; 호스트/워크스페이스 경로
  없음)은 공개다. `report.json`, `match_vs_*.json`, `games_vs_*.txt`는 비공개 운영자
  아티팩트다.
- **비공개 안전 오류.** `bench/ceb/sanitize.py`는 오류에 별도의 공개/비공개 메시지를
  부여한다. 숨겨진 평가 팩과 오프닝 로더는 `hidden=True`를 받아 파일 베이스명 + 행 id +
  "content withheld"만 인용하며, FEN, 수, 경로는 절대 인용하지 않는다. CLI는 모든 것을
  포착해 정제된 한 줄을 출력하고, 전체 트레이스백은 오직 `CEB_DEBUG=1`에서만 다시 발생시킨다.
- **재현 가능한 실행 메타데이터.** 각 실행은 `state.json`을 영속한다. 게임은 라운드별로
  시드된다(`base_seed = 1000 * round_number`), 색은 오프닝 쌍마다 번갈아 배정되고, 모음은
  상대들에 걸쳐 회전된다. 공식 결과는 메타데이터 블록(벤치마크 버전, git 커밋, 이미지 다이제스트,
  평가 팩 / 상대 풀 / 오프닝 모음 해시, 하드웨어/소프트웨어, 시드)을 포함한다.
  [reproducibility.md](reproducibility.md)를 참조한다.
- **신뢰할 수 없는 코드 처리.** 엔진은 argv 전용으로 스폰되고(절대 `shell=True` 아님), 읽기에는
  타임아웃이 있으며, stdout은 제한되고, 프로세스는 프로세스 그룹 SIGTERM/SIGKILL로 종료된다.
  **엔진 감옥**은 추가로 엔진을 네트워크 없음, 읽기 전용, 자원 상한 컨테이너에 가둔다.
  레거시 `--sandbox docker` 모드는 전체 하니스를 컨테이너에서 실행한다.
  [security.md](security.md)를 참조한다.

## JSON 스키마

| 스키마 | 위치 |
|---|---|
| `ceb.run.state/v1` | 실행별 `state.json` |
| `ceb.gate.report/v1` | 게이트 보고서 |
| `ceb.round.report/v1` | 전체(비공개) 라운드 보고서 |
| `ceb.round.report.public/v1` | 정제된 공개 라운드 보고서 |
| `ceb.round.feedback/v1` | 에이전트 대상 피드백 |
| `ceb.score.track_a/v1` | Track A 라운드 점수 |
| `ceb.score.track_b/v1` | Track B 델타 Elo 점수 |
| `ceb.track_b.round.report/v1` | Track B 라운드 보고서 |
| `ceb.track_b.feedback/v1` | Track B 피드백 |
| `ceb.track_b.official_result/v1` | Track B 소스 우선 공식 결과 |
| `ceb.leaderboard/v1` | 로컬(자가 보고) 리더보드 |
| `ceb.hosted.official_result/v1` | 호스팅형 검증 결과 |
| `ceb.hosted.leaderboard/v1` | 검증 전용 호스팅형 리더보드 |
| `ceb.hosted.verification/v1` | 결과 검증 판정 |
| `ceb.scan.workspace/v1` | Track A 정적 스캔 보고서 |
| `ceb.scan.track_b/v1` | Track B 후보 스캔 보고서 |
| `ceb.artifacts.manifest/v1` | 디렉터리별 아티팩트 가시성 매니페스트 |

`ceb.score.track_a/v1` 점수는 이제 `overall` 블록
(`games`, `wins`, `draws`, `losses`, `score_rate`, `delta_elo_vs_pool`,
`delta_elo_ci95`)과 `opening_coverage`도 포함한다.

## 저장소 구조

| 경로 | 내용 |
|---|---|
| `bench/ceb/` | Python 패키지: `cli.py`, `eval_pack.py`, `sanitize.py`, `gate/`, `match/`(`openings.py`, 선택적 `fastchess_runner.py` 포함), `rounds/`, `scoring/`, `chess/`(내부 오라클), `uci/`, `track_b/`, `api/` |
| `bench/ceb/jail/` | 엔진 감옥: `engine_jail.py`(프런트엔드), `docker_engine.py`(Docker 백엔드) |
| `bench/ceb/storage/` | 아티팩트 가시성 모델(`artifacts.py`) |
| `bench/ceb/scan/` | 정적 스캐너(`static_scan.py`, `track_b_scan.py`) |
| `bench/ceb/hosted/` | 호스팅형 파이프라인: `db.py`, `submissions.py`, `worker.py`, `official_eval.py`, `metadata.py`, `signing.py`, `verifier.py` |
| `bench/ceb/sandbox/` | 레거시 컨테이너 내 하니스 `--sandbox docker` 러너 |
| `tracks/a_from_scratch/` | Track A 프롬프트, `track.yaml`, `scoring.yaml`, `public/`(FEN, perft, `openings_public.jsonl`, 게이트 설정) |
| `tracks/b_stockfish_opt/` | Track B 프롬프트, `stockfish.lock`, 경로 목록, `patch_policy.yaml`, `public/`(`quick_openings.jsonl` 포함) |
| `specs/` | 프로토콜과 계약 명세(제출 계약, UCI perft 확장) |
| `docs/` | 이 문서 |
| `scripts/` | `setup_dev.sh`, `setup_stockfish.sh`, `run_public_gate.sh`, `build_evaluator_image.sh`, `build_jail_image.sh` |
| `examples/` | `submissions/`(동작하는 + 망가진 엔진), `eval_packs/tiny_private/`(테스트에서 쓰는 가짜 데모 팩) |
| `infra/docker/` | `engine_jail.Dockerfile`(감옥 이미지, 태그 `chess-en-bench-jail:0.4`)와 `evaluator.Dockerfile`(레거시 샌드박스 이미지) |
| `.github/workflows/ci.yml` | Python 3.10–3.12에서의 CI: pytest, doctor, gate, quick-round 스모크, scan, 호스팅형 SQLite 스모크, Track B 토이 라운드(Stockfish, Docker, 클라우드 없음) |
| `web/static/` | `ceb server start`가 제공하는 대시보드 프런트엔드 |
| `tests/` | pytest 스위트(289 passed + 6 skipped; Docker 통합 테스트는 `CEB_DOCKER_TESTS=1`로 opt-in) |
| `runs/` | 실행 아티팩트: `runs/<run_id>/...`, 임시 게이트 보고서는 `runs/_gate/`, 호스팅형 DB + `<db>_store/` |
| `artifacts/` | 기타 빌드/평가 아티팩트 |

## 빠른 시작 (5개 명령)

```bash
bash scripts/setup_dev.sh && . .venv/bin/activate   # venv + pip install -e ".[dev,server]"

ceb doctor                                          # check environment
ceb workspace prepare --track A --run-id demo       # creates runs/demo/workspace
ceb gate run --track A --workspace runs/demo/workspace        # unlimited attempts
ceb round run --track A --workspace runs/demo/workspace --round 1 --quick  # free smoke round
ceb leaderboard compute --track A --results runs    # official + final, quick excluded
```

CLI는 콘솔 스크립트 `ceb`로 설치되며 `python -m ceb.cli`로도 실행할 수 있다. `runs/demo/workspace`에
준비된 워크스페이스는 run id `demo`를 추론한다. `--run-id`는 항상 이를 재정의한다. 공식 라운드
검사를 미리 보려면 게이트에 `--strict`를, 리더보드 품질 평가를 위해 라운드에 `--final-eval`을,
진단 뷰를 위해 리더보드에 `--include-quick`을 추가한다. 신뢰할 수 없는 엔진의 경우, 감옥을 한 번
빌드하고(`bash scripts/build_jail_image.sh`) `--engine-jail docker`를 전달한다(이는 `--eval-pack`과
결합된다). 핵심 게이트/매치/채점은 Python 표준 라이브러리만 필요하다. FastAPI/uvicorn은
`ceb server start`를 위한 선택적 추가 의존성이다.

전체 실행 수명 주기, 예산 규칙, 호스팅형 공식 경로는
[benchmark_protocol.md](benchmark_protocol.md)를 참조한다.
