# 벤치마크 프로토콜 (Track A 실행 수명 주기)

Track A 실행의 전체 수명 주기다. **로컬** 경로(1~6절)는 반복 작업과
진단용이며, **호스티드 공식(hosted official)** 경로(7절)는 검증된,
리더보드 등재 가능한 결과를 산출하는 권위 있는 경로다.
진실의 원천(source of truth): `bench/ceb/rounds/state.py`(예산 및 상태),
`bench/ceb/rounds/round_runner.py`(라운드 실행),
`bench/ceb/gate/gate_runner.py`(게이트), `bench/ceb/eval_pack.py`(데이터 팩),
`bench/ceb/scoring/track_a.py`(채점 및 리더보드),
`bench/ceb/hosted/`(호스티드 파이프라인), `bench/ceb/storage/`(아티팩트
가시성), `bench/ceb/scan/`(정적 스캔).

## 1. 워크스페이스 준비

```bash
ceb workspace prepare --track A --run-id demo [--runs-dir DIR]
```

`runs/demo/workspace/`를 생성하고, 트랙 프롬프트를
`runs/demo/instructions.md`로 복사하며, 워크스페이스 README를 작성하고,
`tracks/a_from_scratch/track.yaml`(`official_rounds: 3`)에서 가져온
`budget_total`로 `runs/demo/state.json`(스키마 `ceb.run.state/v1`)을
초기화한다. 에이전트는 제출물을 워크스페이스에 넣는다: 실행 가능한 `engine`,
또는 이를 생성하는 `build.sh`.

## 2. 공개 게이트에 반복 검증 (무제한, 무료)

```bash
ceb gate run --track A --workspace runs/demo/workspace \
    [--strict] [--engine-jail docker] [--eval-pack DIR] [--sandbox docker] \
    [--json-out F] [--no-match]
```

게이트 시도는 무제한이며 라운드 예산을 절대 소비하지 않는다. 검사는 순서대로
실행되며, 하드 실패(hard failure)가 발생하면 남은 무거운 검사를 건너뛴다:

1. `format` — 워크스페이스에 `engine` 또는 `build.sh`가 있음
2. `build` — `build.sh`가 있으면 실행 (120초 제한)
3. `engine` — 빌드 후 실행 가능한 `./engine`이 존재함
4. `handshake` — `uci`/`uciok`, `isready`/`readyok`
5. `position` — `position startpos` / `position fen` / 수(move) 허용
6. `bestmove` — 팩의 FEN들에 대한 합법적 bestmove, 오라클(oracle)이 검증
7. `perft` — `go perft` 확장 대 오라클 카운트. 기본 모드: 지원 누락은
   경고이고, 잘못된 카운트는 실패. **엄격 모드(`--strict`)**: perft는
   필수이며 하드 검사다 — 지원 누락 또는 잘못된 카운트는 게이트를 실패시키고
   남은 검사를 건너뛴다.
8. `time` — bestmove가 `go movetime` 예산 내에 반환됨
9. `mini_match` — BenchRandom 상대 2게임에서 후보(candidate) 결함 0건
   (`--no-match`로 건너뜀)

종료 코드 0 = 통과, 2 = 실패. JSON 보고서(`ceb.gate.report/v1`, `strict`
필드 포함)는 `--json-out`에 기록되거나, 기본적으로
`runs/_gate/<workspace>-<timestamp>.json`에 기록된다. Bestmove/perft 실패
세부 정보는 FEN이 아니라 행 id(row id)만 인용하므로 숨겨진 위치(hidden
positions)가 유출될 수 없다. 독립 실행된 `ceb gate run`은 기본적으로
비엄격(non-strict)이며 `state.json`을 건드리지 않는다. 게이트 결과는
라운드가 실행될 때마다 실행 상태에 기록된다(아래 참조). `--engine-jail docker`는
엔진을 감옥(jail) 안에서 실행하며(6절), 레거시 `--sandbox docker`는 대신
전체 게이트를 컨테이너에서 다시 실행한다.

## 3. 로컬 라운드 실행 (세 가지 eval 모드)

```bash
ceb round run --track A --workspace runs/demo/workspace --round 1 \
    [--quick | --final-eval] [--run-id X] [--runs-dir DIR] \
    [--eval-pack DIR] [--engine-jail docker] [--sandbox docker]
```

`--run-id`가 생략되면 워크스페이스 경로에서 추론된다(`default_run_id`):
부모 디렉터리에 `state.json`이 있는 `workspace`라는 이름의 디렉터리는 부모
이름을 사용하고(`runs/demo/workspace` → `demo`), 그 외에는 워크스페이스
디렉터리 이름을 사용한다. `--run-id`는 항상 이를 재정의한다.

세 가지 eval 모드가 있다(`scoring.yaml`의 `round_modes`; 기본값은
`round_runner.py`에 있음). 단순 `ceb round run`은 `official_round`이고,
`--quick`은 `quick`, `--final-eval`은 `final_eval`이다:

| 모드 | 게이트 | 예산 | 상대 | 상대당 게임 | 오프닝 | 리더보드 |
|---|---|---|---|---|---|---|
| `quick` | non-strict | free | BenchRandom, BenchMaterial1 | 2 | 2 | never |
| `official_round` | strict | consumes 1 of 3 | all six | 4 | 6 | eligible |
| `final_eval` | strict | none | all six | 8 | 8 | preferred |

"all six" 상대는 BenchRandom, BenchGreedyCapture, BenchMaterial1,
BenchPST1, BenchMiniMax2, BenchAlphaBeta3이다(movetime 200 ms, 최대 200 plies).

모든 라운드는 **게이트 재실행**으로 시작하므로 라운드는 항상 검증된
엔진에서 출발한다. **엄격** 게이트(`go perft` 필수)는 양쪽 공식 등급
모드 모두의 전제 조건이며, quick 라운드는 비엄격 게이트를 실행한다. 결과는
`runs/<run_id>/gate_report.json`에 저장되고 `state.json`에 기록된다
(`gate.attempts`, `gate.passed`). 게이트가 실패하면 라운드는 중단되고
예산은 건드리지 않는다.

라운드의 데이터는 해결된 **eval 팩**(`bench/ceb/eval_pack.py`)에서 온다:
공개 FEN, perft 기대값, 오프닝 스위트(`tracks/a_from_scratch/public/`),
선택적으로 운영자가 마운트한 비공개 팩으로 확장된다. 명시적
`--eval-pack DIR`은 모든 게이트나 라운드에 적용되며, `CEB_PRIVATE_EVAL_DIR`
환경 변수는 공식 등급 라운드와 엄격 게이트에만 적용된다. 이 저장소에는
숨겨진 데이터가 들어 있지 않다(`examples/eval_packs/tiny_private/`가 그 형태를
문서화한다. `docs/EVAL_PACKS.md` 참조).

예산 규칙(`RunState.can_start_round` / `record_round`): quick과 `final_eval`은
무료이며, `official_round`만 예산을 소비하고(실행당 3회), 게임을 하기 전에
남은 예산 전제 조건이 검사된다. 모든 **로컬** 라운드는 `verified: false`다
— 자가 보고(self-reported) 진단이다. 검증된 결과는 호스티드 워커에서만
나온다(7절).

게임은 오프닝 스위트에서 시작한다(정규 JSONL, 모든 수가 오라클 검증됨.
`bench/ceb/match/openings.py`). 연속된 게임 쌍은 색을 바꿔 동일한 오프닝을
사용하며, 스위트는 상대들에 걸쳐 회전된다(`rotate_suite`, 오프셋
`j * pairs`)므로 라운드는 단일 매치보다 더 많은 오프닝을 다룬다. 매치는
내부 러너에서 실행된다(`bench/ceb/match/internal_runner.py`): 모든 수가
오라클 검증되고, 각 게임은 결정론적으로 시드된다(`base_seed = 1000 *
round_number`). 게임은 최대 plies, halfmove 임계값(`halfmove_draw_plies`,
100 = 50수 / 150 = 75수), 3회 동형 반복(위치 키에서 클록 제외), 또는
보수적인 불충분 기물(K 대 K, K+B 대 K, K+N 대 K만)에 대해 무승부로
판정된다. 불법 수, 타임아웃, 크래시는 위반한 쪽이 게임을 패하고 페널티로
집계된다(illegal_move 30, timeout 15, crash 25). 선택적인 제한 강도
**앵커 상대(anchor opponents)**(Stockfish `UCI_Elo` 레벨, `scoring.yaml`의
`anchor_opponents`)는 모드의 `anchors` 리스트에 추가할 수 있다. 엔진 바이너리가
없으면 진행 메모와 함께 앵커를 건너뛰지만, 모드에 `anchors_required`(호스티드)가
설정되어 있으면 중단한다.

## 4. 라운드별 아티팩트와 가시성

```
runs/<run_id>/
  state.json                      # ceb.run.state/v1: budget, gate, round trajectory  [private]
  gate_report.json                # ceb.gate.report/v1 from the latest round's gate    [private]
  instructions.md                 # copy of the track prompt
  workspace/                      # the submission (if prepared via ceb workspace)
  round_N/
    artifacts_manifest.json       # ceb.artifacts.manifest/v1: per-file visibility
    feedback.json                 # ceb.round.feedback/v1: sanitized aggregates         [PUBLIC]
    report.public.json            # ceb.round.report.public/v1: sanitized round report  [PUBLIC]
    report.json                   # ceb.round.report/v1: full matches + score           [private]
    match_vs_<Opponent>.json      # full internal-runner match report                   [private]
    games_vs_<Opponent>.txt       # UCI-movetext game records                           [private]
```

각 아티팩트 디렉터리는 `artifacts_manifest.json`(`bench/ceb/storage/`)을
지닌다. `public`으로 명시 표시된 파일만 서빙 가능하며, 알려지지 않은/등재되지
않은 파일은 비공개로 취급된다(기본 거부). 분류:

- **공개:** `feedback.json`(상대별 W/D/L, 점수율, 결함 수, 페널티 점수,
  점수, 일반 조언 — FEN, 수, 오프닝 id 없음)과
  `report.public.json`(`ceb.round.report.public/v1`, `verified:false`.
  워크스페이스/호스트 경로 생략. 비공개 팩의 경우 `opening_ids`는 null).
- **비공개(운영자 전용):** `report.json`은 `mode`, `strict_gate`,
  `eval_pack`, `openings_used`를 기록하고, 라운드 점수
  (`ceb.score.track_a/v1`: 상대별 성능, `score_rate`와
  `delta_elo_vs_pool` + 95% CI를 담은 `overall` 블록, 결함, 페널티 점수,
  사다리(ladder) 및 최종 점수, `opening_coverage`)를 포함한다.
  `match_vs_*.json`과 `games_vs_*.txt`는 전체 수 세부 정보를 담는다.

## 5. 로컬 리더보드

```bash
ceb leaderboard compute --track A --results runs [--json-out F] [--include-quick]
```

각 실행을 최고 `final_eval` 기준으로, 없으면 최고 `official_round` 기준으로
순위 매긴다(레거시 `official` 모드 키도 여전히 집계됨). quick 라운드는
기본적으로 제외되며, `--include-quick`은 명확히 라벨링된 진단 뷰다. 모든
항목은 `verified:false`(자가 보고)다. `ceb server start`는 읽기 전용
대시보드와 `/api/leaderboard`를 동일한 실행 아티팩트 위에서 서빙한다(`server`
extra). 권위 있는, 검증된 순위는 7절과 `docs/LEADERBOARD_GOVERNANCE.md`를
참조한다.

## 6. 엔진 감옥과 레거시 샌드박스

**엔진 감옥(engine jail)**(`--engine-jail docker`, `bench/ceb/jail/`)은
신뢰할 수 없는 엔진만 격리한다. 평가기(evaluator)는 호스트에서 신뢰된 채로
유지된다. 한 번 빌드한다:

```bash
bash scripts/build_jail_image.sh                 # tag chess-en-bench-jail:0.4
ceb round run --track A --workspace <dir> --round 1 --eval-pack <pack> --engine-jail docker
```

감옥에 갇힌 엔진은 `/submission`에 읽기 전용으로 마운트된 워크스페이스에서
`--network none`, 읽기 전용 root + tmpfs `/tmp`, `--cpus 1 --memory 1g
--pids-limit 128`, `no-new-privileges`, 비루트(non-root, 호스트 uid:gid),
stdio 전용 UCI로 실행된다. 저장소, eval 팩, 상대 마운트가 없으며, 감옥
이미지는 `ceb` 패키지를 생략하므로 갇힌 엔진은 평가기 코드를 import할 수
없다. 숨겨진 팩은 호스트 측에서 읽혀 `position fen ...` UCI 라인으로만
엔진에 도달하므로 `--engine-jail docker`는 `--eval-pack`과 결합된다. `:`나
줄바꿈을 포함하는 워크스페이스 경로와 `/`를 포함하는 엔진 이름은 거부된다.
Docker가 없거나 이미지가 없으면 조치 가능한 `EngineJailError`가 발생한다.
기본값은 `--engine-jail none`이다.

레거시 `--sandbox docker`(`bench/ceb/sandbox/`,
`infra/docker/evaluator.Dockerfile`, tag `chess-en-bench-evaluator:0.2`)는
저장소를 읽기 전용으로 마운트한 컨테이너에서 전체 하니스를 다시 실행한다.
호환성을 위해 유지되며, 여전히 `--eval-pack`을 거부하고, 호스티드 공식
경로가 **아니다**.

## 7. 호스티드 공식 평가 (권위 있는 경로)

호스티드 파이프라인(`bench/ceb/hosted/`)은 `verified: true` 결과를 산출하는
유일한 경로다. 기본 백엔드는 단일 노드(SQLite + 로컬 `<db>_store/` 객체
디렉터리)이지만 다중 워커에 안전한 원자적 잡 클레임(`claim_next_job`,
`BEGIN IMMEDIATE`)을 갖추며, 서명은 Ed25519 공개키(권장)다. 평가
**프로파일**(`smoke`/`official`/`final-production`)이 결과가 검증될 자격을
결정한다 — `smoke`는 절대 verified가 아니다.

```bash
bash scripts/build_jail_image.sh                       # jail image, once
ceb hosted keygen --private-key op.pem --public-key op.pub.pem   # Ed25519 (once)

ceb hosted init   --db runs/hosted.sqlite
ceb hosted submit --track A --workspace <dir> --run-id myrun --db runs/hosted.sqlite
CEB_SIGNING_PRIVATE_KEY=op.pem ceb hosted worker run-once --db runs/hosted.sqlite \
    --eval-pack <private-pack> --profile official    # --engine-jail docker is the default
ceb hosted result show --run-id myrun --db runs/hosted.sqlite
ceb hosted leaderboard --track A --db runs/hosted.sqlite
```

수명 주기(**submit → job → worker → verified result**):

1. **제출(Submit).** `ceb hosted submit`은 라이브 워크스페이스를 객체
   저장소로 스냅샷하면서 **심링크를 거부**하고 비정규 파일도 거부하며,
   스냅샷을 트리 해시한다(`bench/ceb/hosted/submissions.py`). 워커는 라이브
   워크스페이스가 아니라 항상 스냅샷만 평가한다 — 이는 평가된 대상을
   고정하고 제출 후 편집을 차단한다. 작업(`official_eval`)이 큐에 추가된다.
2. **워커(Worker).** `ceb hosted worker run-once`는 큐 작업을 **원자적으로
   클레임**(`claim_next_job`)하고 작업 종류로 분기한다. Track A
   (`official_eval`)는 `run_official_eval`을 실행한다: 비공개 팩 필수 →
   **엔진 감옥 가드**(verifiable 프로파일은 `engine_jail == docker`가 아니면
   평가 전 거부) → 정적 스캔(`ceb.scan.workspace/v1`) → 비공개 팩에 대한 엄격
   게이트 → 비공개 팩 + Docker 엔진 감옥으로 라운드 → 공개/비공개 아티팩트 →
   **공개 아티팩트 누출 스캔**(`ceb.scan.leak/v1`) → 메타데이터 + 서명 →
   검증된 결과. `smoke` 프로파일(=`--quick-test-mode`)은 작은 토이 설정이며
   절대 verified가 아니다(프로파일·등급은 결과에 기록됨).
3. **검증 거부.** 비공개 eval 팩이 없거나, 감옥이 docker가 아니거나(개발 플래그
   없이), 정적 스캔이 실패하거나, 엄격 게이트가 실패하거나, 누출이 탐지되면
   워커는 검증된 결과를 **전혀** 기록하지 않는다. 작업은 정제된 공개 사유와
   비공개 사유를 함께 담아 실패로 표시된다.
4. **검증된 결과.** 성공 시 워커는 점수, 정제된 피드백, 메타데이터 블록,
   서명, `profile`/`verification_grade`를 담은 `official_result.json`
   (`ceb.hosted.official_result/v2`, 공개 아티팩트)을 기록한다. 결과를 DB에
   `verified: true`로 기록하고 각 아티팩트의 가시성을 API 서빙용으로
   등록한다. 리더보드/`result show`/official-result API는 공유 선택자
   `select_best_verified_result`(final-tier 우선)로 동일 결과를 고른다.

**재현성 메타데이터**(`bench/ceb/hosted/metadata.py`)는 `benchmark_version`
(0.3.5), `git_commit`, 평가기와 엔진 감옥 이미지 다이제스트,
`eval_pack_id`, `eval_pack_hash`(팩 디렉터리의 sha256),
`opponent_pool_hash`(`opponents.py`의 sha256), `opening_suite_hash`, 하드웨어
(cpu 모델/코어, 메모리 제한), 소프트웨어(python, platform, compiler,
fastchess, `stockfish_baseline: sf_18/cb3d4ee`), `random_seed`, `verified`를
기록한다. 로컬에서 판별할 수 없는 필드는 명시적 null이다.

**서명**(`bench/ceb/hosted/signing.py`)은 정규 직렬화(canonical
serialization)에 대해 이뤄진다. 권장 알고리즘은 **Ed25519 비대칭 서명**으로,
운영자는 비공개 키로 서명하고 **누구나** 게시된 공개 키로 진정성을 독립
검증한다(`ceb hosted verify-result --public-key`). 레거시 대칭 HMAC-SHA256
(`CEB_SIGNING_KEY`)은 운영자 내부 용도로 유지된다. `sign_official_result`는
Ed25519 > HMAC > unsigned 순으로 선택한다. 키가 없으면 결과는 명시적인 "NO
cryptographic authenticity" 메모와 함께 `signature.status = "unsigned"`로
기록되며 결코 진정한 것으로 취급되지 않는다. 변조된 결과나 잘못된 키는 불일치로
검증된다. 자세한 내용은 `docs/RESULT_SIGNING.md`를 참조한다.

```bash
ceb hosted sign-result   --result <official_result.json>   # re-sign with CEB_SIGNING_KEY
ceb hosted verify-result --result <official_result.json>   # ceb.hosted.verification/v1 verdict
```

**호스티드 리더보드**(`ceb hosted leaderboard`, `db.verified_leaderboard`,
`ceb.hosted.leaderboard/v1`)는 검증된 결과 전용이다: 실행당 최고 `final_eval`,
없으면 최고 `official_round`. quick은 절대 나타나지 않는다(워커는 quick을
검증으로 표시하지 않는다).

동일한 작업이 HTTP로도 노출된다(`bench/ceb/api/main.py`, `server` extra):
관리자 게이트 POST `/api/hosted/runs`, `/runs/{id}/submissions`,
`/runs/{id}/jobs`(`X-CEB-Admin-Token == CEB_ADMIN_TOKEN` 필요. 토큰 없음 →
503, 잘못됨 → 403), GET `/api/hosted/runs/{id}`, `/feedback`,
`/official-result`, `/leaderboard?track=A`(검증된 결과 전용),
`/artifacts/{id}`(DB 가시성이 `public`인 아티팩트만 서빙. 비공개/알 수 없음
→ 404, 경로 탐색(path traversal) → 400/404). DB 경로는 `CEB_HOSTED_DB`
또는 `runs/hosted.sqlite`에서 온다.

## Track B 라운드

```bash
ceb track-b round run --candidate-engine X --baseline-engine Y \
    [--baseline-src D --candidate-src D] [--games N --movetime MS] \
    [--engine-jail docker] [--runner internal|fastchess]

ceb track-b official run --candidate-src <tree> [--baseline-src <tree>] \
    [--eval-pack DIR] [--engine-jail docker] \
    [--build-script ceb_build.sh] [--engine-relpath ceb_engine]
```

`round run`은 두 바이너리를 대국시킨다: diff 화이트리스트 검사(위반 시 게임
전에 중단) → UCI 핸드셰이크 → 양쪽에 `Threads=1 Hash=16`을 보낸 짝지은
오프닝의 색 교대 게임 → 델타 Elo 채점 → `report.json`
(`ceb.track_b.round.report/v1`) 및 정제된 `feedback.json`. `official run`
(`bench/ceb/track_b/official_pipeline.py`)은 소스 우선 파이프라인이다: 스캔
(`ceb.scan.track_b/v1`) → **동일한** 빌드 스크립트로 baseline + candidate
빌드 → 짝지은 매치 → 서명된 `ceb.track_b.official_result/v1`. CLI 실행은
`verified: false`(진단)다. 동일 플래그와 bench 정상성 검사를 갖춘 실제 고정
Stockfish 빌드는 운영자 단계이며 코드로 강제되지 않는다. 내부 러너가
기본값이자 신뢰되는 기준이며, `--runner fastchess`
(`bench/ceb/match/fastchess_runner.py`)는 선택적 고용량 백엔드다.
`docs/track_b_stockfish_optimization.md`와
`docs/TRACK_B_OFFICIAL_PIPELINE.md`를 참조한다.
