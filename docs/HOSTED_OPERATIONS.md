# 호스티드 운영 런북 (v0.3 MVP)

운영자가 chess_en_bench v0.3.0의 공식 호스티드 평가를 실행하는 방법.

이것은 **MVP 런북**이다. 호스티드 파이프라인은 일회성 워커(`worker run-once`)로
구동되는 단일 노드 SQLite + 로컬 객체 스토어 설계이며, API는 서버 로컬
워크스페이스 경로를 제공하고(업로드 없음), 결과 서명은 공개키 증명이 아니라
**대칭 HMAC**이다. 신뢰된 운영자 머신에서 재현 가능하고 검증된 결과를 만들기에는
충분하지만 — 견고한 멀티테넌트 서비스는 아니다. 아래 절들은 각 MVP 경계를
짚는다.

모든 명령은 리포지토리 루트를 작업 디렉터리로, 그리고 `.venv`의 편집 가능
설치를 전제로 한다. `ceb`가 PATH에 있으면 `.venv/bin/ceb`를 `ceb`로 대체하라.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev,server]"   # 'server' (== 'hosted') extra pulls FastAPI/uvicorn
ceb doctor                        # confirms python deps, docker, git, stockfish
```

호스티드 데이터베이스와 워커는 Python 표준 라이브러리(`sqlite3`, `hashlib`,
`hmac`)만 필요로 한다. `server`/`hosted` extra는 `ceb server start`와 HTTP
API에만 필요하다.

---

## 1. Docker 이미지 빌드

공식 호스티드 평가는 신뢰할 수 없는 엔진을 `--engine-jail docker`로 격리한다.
먼저 그 이미지를 빌드한다(태그 `chess-en-bench-jail:0.3`):

```bash
bash scripts/build_jail_image.sh          # builds chess-en-bench-jail:0.3
```

감옥 이미지(`infra/docker/engine_jail.Dockerfile`)는 의도적으로 최소화되어
있다: `python:3.12-slim` 런타임뿐이며 벤치마크는 아무것도 들어 있지 않다. `ceb`
패키지가 그 안에 설치되지 **않으므로**, 격리된 엔진은 평가기 코드를 import할 수
없다. `docker_engine.py`는 각 엔진을 `--network none`, `--read-only`,
`--tmpfs /tmp`, `--cpus 1`, `--memory 1g`, `--pids-limit 128`,
`--security-opt no-new-privileges`, 비루트 호스트 uid:gid로 실행하며, 제출
워크스페이스만 `/submission`에 읽기 전용으로 마운트한다.

**레거시 평가기 이미지**(`--sandbox docker`, 컨테이너 안의 하니스)는 별개의
선택적 경로이며 호스티드 평가에서는 사용되지 **않는다**. 레거시 샌드박스도
함께 실행하려는 경우에만 빌드한다:

```bash
bash scripts/build_evaluator_image.sh     # builds chess-en-bench-evaluator:0.2
```

Docker나 감옥 이미지가 없으면 `--engine-jail docker`는 조치 가능한
`EngineJailError`와 함께 중단되며, `scripts/build_jail_image.sh`를 실행하라고
안내한다. `--engine-jail none`(호스트 실행, 신뢰된 제출물 전용)으로 호스티드
실행을 종단 간 검증할 수 있다. 공식 정책은 `docker`다.

---

## 2. 로컬 TOY 호스티드 평가를 종단 간으로 실행

이 절은 번들된 예제 제출물과 번들된 가짜 비공개 pack
(`examples/eval_packs/tiny_private`)에 대해 전체 파이프라인을 따라간다.
`runs/hosted.sqlite`를 건드리지 않도록 임시 데이터베이스를 사용한다.
`--quick-test-mode`는 CI/스모크용으로 아주 작은 토이 매치 프로파일(상대 1,
게임 2)을 선택한다 — 실제 채점에는 **절대** 사용하지 말 것(§3 참조).

```bash
DB=/tmp/ceb_toy/hosted.sqlite

# (a) initialize the database + object store (<db>_store/ next to the db file)
.venv/bin/ceb hosted init --db "$DB"

# (b) snapshot + enqueue a submission (symlinks rejected; tree-hashed)
.venv/bin/ceb hosted submit \
    --track A \
    --workspace examples/submissions/minimal_uci_engine_python \
    --run-id toy-001 \
    --db "$DB"

# (c) drain one queued job: static scan -> strict gate vs the private pack ->
#     official_round with the pack -> public/private artifacts -> signed result.
#     Add --engine-jail docker for the jailed engine; --final-eval for a
#     final_eval instead of an official_round.
.venv/bin/ceb hosted worker run-once \
    --db "$DB" \
    --eval-pack examples/eval_packs/tiny_private \
    --quick-test-mode

# (d) inspect the recorded result and the verified-only leaderboard
.venv/bin/ceb hosted result show --run-id toy-001 --db "$DB"
.venv/bin/ceb hosted leaderboard --db "$DB" --track A
```

`worker run-once`는 JSON 상태(`{"status": "done", ...,
"verified": true}`)를 출력하고 `<db>_store/<run-id>/job_<n>/` 아래에
`official_result.json`(스키마 `ceb.hosted.official_result/v1`, 공개 산출물)을
작성한다. 워커는 `verified: true` 결과를 만드는 **유일한** 생산자다. 다음의 경우
워커는 검증된 결과 작성을 거부하며 — 그리고 작업은 정제된 사유와 함께
`failed`로 표시된다:

- 비공개 eval pack이 주어지지 않음(검증하려면 `--eval-pack`이 필수),
- 정적 스캔 실패, 또는
- strict 게이트 실패.

호스티드 리더보드(`db.verified_leaderboard`)는 검증 전용이다: 실행별 최고
`final_eval`, 없으면 최고 `official_round`; quick 라운드는 절대 나타나지 않는다.

### 결과 서명 및 검증

서명은 `CEB_SIGNING_KEY`로 키잉된 **대칭 HMAC-SHA256**이다. 키가 없으면
`worker run-once`는 여전히 결과를 작성하지만 "NO cryptographic authenticity"
안내와 함께 `signature.status: "unsigned"`로 스탬프를 찍는다. 환경에 키를 설정해
명시적으로 서명한다:

```bash
RESULT=/tmp/ceb_toy/hosted_store/toy-001/job_1/official_result.json

# verify BEFORE signing -> authentic:false, signature_detail "unsigned result"
.venv/bin/ceb hosted verify-result --result "$RESULT"

# sign with the operator key, then verify with the same key -> authentic:true
CEB_SIGNING_KEY="change-me-operator-secret" \
    .venv/bin/ceb hosted sign-result   --result "$RESULT"
CEB_SIGNING_KEY="change-me-operator-secret" \
    .venv/bin/ceb hosted verify-result --result "$RESULT"

# verify with the wrong key -> authentic:false, "signature MISMATCH"
CEB_SIGNING_KEY="wrong-key" \
    .venv/bin/ceb hosted verify-result --result "$RESULT"
```

`verify-result`는 `authentic`이 true(스키마 일치, 유효한 서명, 누락된 메타데이터
키 없음)가 아니면 0이 아닌 값으로 종료한다. 실제 실행에서는 결과가 나중에 다시
서명되는 대신 작성 시점에 서명되도록 워커에서도 `CEB_SIGNING_KEY`를 export한다.

---

## 3. 프로덕션 게임 수 구성

`--quick-test-mode`는 하드코딩된 토이 프로파일(상대 1, 게임 2, movetime 30ms —
`bench/ceb/hosted/official_eval.py`의 `QUICK_TEST_MODE_CONFIG`)이며 CI/스모크
전용이다. 실제 호스티드 채점은 `--quick-test-mode`를 **생략**하며, 이는 워커가
`tracks/a_from_scratch/scoring.yaml`에 구성된 라운드 모드를 사용하게 한다.

거기서 `final_eval`(그리고/또는 `official_round`) 블록을 편집해 리더보드 품질의
매치 분량을 설정한다:

```yaml
round_modes:
  final_eval:             # leaderboard-quality; strict gate; no budget cost
    opponents: [BenchRandom, BenchGreedyCapture, BenchMaterial1, BenchPST1, BenchMiniMax2, BenchAlphaBeta3]
    games_per_opponent: 8       # raise for tighter Elo confidence intervals
    movetime_ms: 200
    max_plies: 200
    openings_limit: 8           # first N openings of the resolved suite
    anchors: []                 # e.g. [SF18_UCI_Elo_1320, SF18_UCI_Elo_1600]
    anchors_required: true      # hosted: abort if a listed anchor is missing
```

- `games_per_opponent` / `openings_limit`는 실행 시간과 Elo 정밀도를 좌우한다.
- `anchors`는 `anchor_opponents` 아래에 정의된 제한 강도(limited-strength)
  Stockfish 앵커 상대(예: `SF18_UCI_Elo_1320`)를 활성화한다. 앵커는
  `UCI_LimitStrength` / `UCI_Elo` / `Threads=1`을 보내며 PATH에 `stockfish`가
  있어야 한다(`scripts/setup_stockfish.sh`).
- 기본적으로 누락된 앵커 바이너리는 **진행 안내와 함께 건너뛰어지므로** CI가
  Stockfish에 절대 의존하지 않는다. `anchors_required: true`(호스티드 정책)를
  설정하면 나열된 앵커가 없을 때 라운드가 대신 **중단**된다 — 이는 의도한 앵커
  없이 조용히 채점되는 것을 막는다.

워커를 통해 실제 final_eval을 실행한다(`--quick-test-mode` 없이, 감옥과 함께):

```bash
.venv/bin/ceb hosted worker run-once \
    --db runs/hosted.sqlite \
    --eval-pack /secure/path/to/private_pack \
    --engine-jail docker \
    --final-eval
```

비공개 eval pack은 평가기가 호스트 측에서 읽는다. 포지션은 `position fen ...`
UCI 라인의 형태로만 격리된 엔진에 도달하므로, 숨겨진 pack은
`--engine-jail docker`와 안전하게 결합된다(pack 디렉터리는 절대 마운트되지
않는다).

---

## 4. API 제공

HTTP API는 호스티드 엔드포인트와 대시보드를 노출한다. `CEB_HOSTED_DB`(기본
`runs/hosted.sqlite`)로 호스티드 데이터베이스를 가리키게 하고, 관리자 POST
엔드포인트를 활성화하려면 `CEB_ADMIN_TOKEN`을 설정한다:

```bash
export CEB_HOSTED_DB=runs/hosted.sqlite
export CEB_ADMIN_TOKEN="change-me-admin-token"
.venv/bin/ceb server start --host 127.0.0.1 --port 8000
```

**관리자 POST 엔드포인트**(헤더 `X-CEB-Admin-Token: $CEB_ADMIN_TOKEN` 필요):

```bash
ADMIN=change-me-admin-token
curl -X POST localhost:8000/api/hosted/runs \
     -H "X-CEB-Admin-Token: $ADMIN" -H 'content-type: application/json' \
     -d '{"run_id":"api-001","track":"A"}'
curl -X POST localhost:8000/api/hosted/runs/api-001/submissions \
     -H "X-CEB-Admin-Token: $ADMIN" -H 'content-type: application/json' \
     -d '{"workspace":"examples/submissions/minimal_uci_engine_python"}'
curl -X POST localhost:8000/api/hosted/runs/api-001/jobs \
     -H "X-CEB-Admin-Token: $ADMIN" -H 'content-type: application/json' \
     -d '{"kind":"official_eval"}'
```

`CEB_ADMIN_TOKEN`이 구성되지 않으면 관리자 POST는 **503**을 반환하고,
잘못되거나 누락된 토큰은 **403**을 반환한다. 제출 `workspace`는 **서버 로컬
경로**다(MVP — 파일 업로드는 향후 작업). API는 작업을 큐에 넣기만 한다. 여전히
`ceb hosted worker run-once`를 직접 실행해야 한다(워커는 서버가 시작하지
않는다).

**공개 GET 엔드포인트**(토큰 불필요):

```bash
curl localhost:8000/health
curl localhost:8000/api/hosted/runs/api-001
curl localhost:8000/api/hosted/runs/api-001/feedback
curl localhost:8000/api/hosted/runs/api-001/official-result
curl "localhost:8000/api/hosted/leaderboard?track=A"          # verified-only
curl localhost:8000/api/hosted/artifacts/<artifact_id>
```

산출물 엔드포인트는 **기본 거부(deny-by-default)**다: DB 가시성이 `public`인
산출물만 제공하며, 비공개/알 수 없는 id와 경로 순회 시도는 404(잘못된 id는
400)를 반환한다. 자체 리버스 프록시/TLS 뒤에서 `127.0.0.1`에 바인딩하라 — 앱은
관리자 토큰 외에 어떤 인증도 하지 않으며 레이트 리미팅도 제공하지 않는다.

---

## 5. 서명 키 관리 (대칭 HMAC)

`CEB_SIGNING_KEY`는 각 결과의 정규 직렬화에 대한 HMAC-SHA256에 사용되는 공유
비밀이다(`bench/ceb/hosted/signing.py`). 이것은 **대칭**이다: 키를 가진 누구나
서명과 검증을 모두 할 수 있으므로, 결과를 키 보유자(운영자)에게만 인증한다 —
이것은 공개키 증명이 **아니며**, 제3자는 독립적으로 검증할 수 없다. 비대칭
서명은 명시적으로 향후 작업이다.

운영자 지침:

- 키를 비밀로 취급하라: 시크릿 매니저나 전체 사용자에게 읽히지 않는 env 파일에
  저장하고, 리포지토리, 데이터베이스, 결과 파일에는 절대 두지 말 것.
- 공식 결과가 작성 시점에 서명되도록 워커 환경에서 `CEB_SIGNING_KEY`를
  export하라. 동일한 키는 검증해야 하는 당사자에게만 배포하라.
- 키를 교체하면 이전에 서명된 결과의 검증이 무효화된다 — 새 키 아래에서
  `signature MISMATCH`로 표시된다. 검증이 필요하면 보관된 결과를 새 키로 다시
  서명하거나, 검증을 위해 폐기한 키를 보관하라.
- 서명이 없는 결과는 절대 진정한 것으로 취급되지 않는다: `verify-result`는
  `signature_detail` "unsigned result"와 함께 `authentic: false`를 반환한다.

제3자가 검증 가능한 더 강한 진정성 주장을 하려면 비대칭 서명이 필요하다 —
v0.3에는 없다.

---

## 참고 / MVP 경계

- **단일 워커, 수동 드레인.** `worker run-once`는 가장 오래된 대기 작업을
  처리하고 종료한다. 연속 운영하려면 루프나 스케줄러에서 실행하라. 하나의
  데이터베이스에 대해 여러 워커가 동작할 때의 동시성 제어는 내장되어 있지 않다.
- 호스티드 제출은 **Track A 전용**이다. Track B는 자체 파이프라인을 가진다
  (`ceb track-b official run`); 그 CLI 실행은 진단용이다(`verified: false`).
- **재현성 메타데이터**(`bench/ceb/hosted/metadata.py`)는 벤치마크 버전, git
  커밋, 평가기/감옥 이미지 다이제스트, eval-pack / 상대-풀 / 오프닝-스위트 해시,
  하드웨어, 소프트웨어(`stockfish_baseline: sf_18/cb3d4ee` 포함), 랜덤 시드를
  기록한다. 이미지 다이제스트 필드는 Docker를 사용할 수 없을 때 `null`이다.
  다이제스트가 의미를 갖도록 실제로 실행하는 평가기 및 감옥 이미지를 커밋하라.
- **정제된 오류.** 에이전트 대면 출력(CLI, 피드백, 공개 산출물)은 숨겨진 FEN,
  수순, 오프닝 id, 호스트 경로를 절대 출력하지 않는다. 전체 운영자 트레이스백을
  보려면 `CEB_DEBUG=1`을 설정하라 — 에이전트 대면 서비스에서는 절대 사용하지 말
  것.
