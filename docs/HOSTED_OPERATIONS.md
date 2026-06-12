# 호스티드 운영 런북

운영자가 chess_en_bench의 **공식(verified)** 호스티드 평가를 실행하는 방법.

호스티드 파이프라인은 단일 노드 SQLite + 로컬 객체 스토어 설계이며, 잡을
원자적으로 클레임하는 워커(`ceb hosted worker run-once`)로 구동된다. 동일한 DB에
대해 여러 워커를 동시에 돌릴 수 있다(원자적 클레임 + lease 회수). API는 잡을
큐에 넣고 공개 산출물을 제공하며, 워커는 별도로 드레인한다.

**핵심 정직성 원칙.** 공식(verified) 결과는 오직 호스티드 공식 워커만,
다음 조건을 **모두** 만족할 때 생성한다: 깨끗한 스냅샷 + 비공개 eval 팩 + 정적
스캔 통과 + strict 게이트 통과 + Docker 엔진 감옥(`--engine-jail docker`) +
verifiable 프로파일(official / final-production) + 공개 아티팩트 누출 스캔 통과 +
서명. 로컬 CLI 라운드와 직접 실행한 Track B CLI는 자가보고(self-reported) /
진단(diagnostic)이며 **결코 verified가 아니다**. smoke/quick 결과는 절대 공식
리더보드에 오르지 않으며, 호스티드 리더보드는 verified 결과만 담는다.

모든 명령은 리포지토리 루트를 작업 디렉터리로, 그리고 `.venv`의 편집 가능
설치를 전제로 한다. `ceb`가 PATH에 있으면 `.venv/bin/ceb`를 `ceb`로 대체하라.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev,server]"   # 'server' (== 'hosted') extra pulls FastAPI/uvicorn + cryptography
ceb doctor                        # confirms python deps, docker, git, stockfish
```

호스티드 데이터베이스와 워커는 대부분 Python 표준 라이브러리(`sqlite3`,
`hashlib`, `hmac`)만 필요로 한다. Ed25519 서명은 `cryptography`(hosted/server
extra에 포함)를, HTTP API는 FastAPI/uvicorn을 추가로 요구한다.

---

## 1. 엔진 감옥 이미지 빌드

공식 호스티드 평가는 신뢰할 수 없는 엔진을 `--engine-jail docker`로 격리한다.
먼저 그 이미지를 빌드한다(태그 `chess-en-bench-jail:0.4`):

```bash
bash scripts/build_jail_image.sh          # builds chess-en-bench-jail:0.4
```

감옥 이미지(`infra/docker/engine_jail.Dockerfile`)는 `python:3.12-slim` +
`build-essential`(gcc/g++/make) + bash + python3로 구성된 **빌드 툴체인**이며,
벤치마크는 아무것도 들어 있지 않다. `ceb` 패키지가 그 안에 설치되지
**않으므로**, 격리된 엔진은 평가기 코드를 import할 수 없다.
`bench/ceb/jail/docker_engine.py`는 제출 워크스페이스를 `/submission`에
마운트하되 `build.sh` 빌드 단계에서는 **쓰기 가능**(`build.sh`가 `./engine`을
생성), 엔진 실행 시에는 **읽기 전용**으로 두며, 항상 `--network none`,
`--read-only` 루트 + `--tmpfs /tmp`, `--cpus 1`, `--memory 1g`,
`--pids-limit 128`, `--security-opt no-new-privileges`, 비루트 uid:gid로
실행한다.

**언어 정책.** 빌드 단계와 엔진 실행 모두 네트워크가 없으므로 제출물은
self-contained / from scratch여야 한다. `build.sh`가 감옥 내 툴체인만으로
`/submission/engine` 실행 파일을 만드는 한 어떤 언어든 허용한다. 파이썬 예제는
`examples/submissions/minimal_uci_engine_python`, C++ 소스 전용 예제는
`examples/submissions/minimal_uci_engine_cpp`(`engine.cpp` + `build.sh`;
감옥/게이트가 평가 시 `./engine`을 컴파일)이다.

Docker나 감옥 이미지가 없으면 `--engine-jail docker`는 조치 가능한
`EngineJailError`와 함께 중단되며, `scripts/build_jail_image.sh`를 실행하라고
안내한다. 공식 정책은 `docker`다.

**레거시 평가기 이미지**(`--sandbox docker`, 컨테이너 안의 **전체 하니스**)는
별개의 호환/개발 경로이며 공식 경로가 **아니다**. 공식 경로는 엔진만 가두는
`--engine-jail docker`다. 둘을 혼동하지 말 것. 레거시 샌드박스를 별도로
빌드하려면:

```bash
bash scripts/build_evaluator_image.sh     # builds chess-en-bench-evaluator:0.2
```

---

## 2. 프로파일과 검증 등급

**프로파일**(`bench/ceb/hosted/profiles.py`,
`tracks/a_from_scratch/eval_profiles.yaml`)은 워커·DB·API·문서가 공유하는 단일
진실이다: 어떤 라운드 모드(매치 설정)를 쓰는지, 그리고 결과가 verified가 되어
공식 리더보드에 오를 수 있는지를 결정한다.

| 프로파일 | 라운드 모드 | verifiable | verification_grade | 용도 |
|---|---|---|---|---|
| `smoke` | tiny 토이 매치 | **false** | `diagnostic-smoke` | CI/플러밍 — 절대 verified 아님, 감옥 없이 실행 |
| `official` | `official_round` | true | `verified-official` | 표준 공식 라운드 |
| `final-production` | `final_production` | true | `verified-final-production` | 프로덕션 규모 최종 평가(리더보드가 official보다 선호) |

레거시 `final-eval` 프로파일은 `final_eval` 라운드 모드로 매핑되며 final-tier
verified 결과(`verified-final-eval`)로 취급된다(`--final-eval` 플래그가 선택).

프로파일이 `verifiable`인 것은 verified 결과의 **필요 조건이지 충분 조건이
아니다**. 워커는 비공개 eval 팩, 정적 스캔, strict 게이트, 엔진 감옥, 누출 스캔,
서명을 여전히 강제한다. `smoke`처럼 verifiable=false인 프로파일은 어떤 플래그를
줘도 **절대** verified가 되지 않는다("magic verified" 없음). `profile`과
`verification_grade`는 결과 JSON과 DB 행에 함께 저장되며, 그 등급에는
`diagnostic-unjailed`(아래 §3 참조)도 포함된다.

`final_production` 라운드 모드(`tracks/a_from_scratch/scoring.yaml`
`round_modes.final_production` / `DEFAULT_ROUND_MODES`)는 6상대 x 336게임 =
2016게임, paired openings, movetime 1000ms이다. **CI는 절대 이 기본값으로
실행하지 않는다**(테스트는 tiny override / smoke 프로파일).

---

## 3. 엔진 감옥 가드와 워커

verifiable 프로파일이 verified가 되려면 `engine_jail == docker`가 **필수**다
(`bench/ceb/hosted/official_eval.py`). 감옥이 docker가 아니면 워커는 평가 **전에**
거부한다. `--dev-allow-unjailed`(개발 전용)는 verifiable 프로파일을 감옥 없이
실행하되 결과를 강제로 `verified=false`(`diagnostic-unjailed`)로 만들어
리더보드에 **절대** 오르지 않게 한다. CLI 워커의 기본값은 `--engine-jail
docker`다. `smoke`는 verifiable=false이므로 플래그와 무관하게 감옥 없이
실행된다(따라서 CI는 docker가 필요 없다).

`ceb hosted worker run-once` 플래그:

- `--db` — 호스티드 SQLite 경로(기본 `runs/hosted.sqlite`)
- `--eval-pack <dir>` — 비공개 eval 팩(**verified에 필수**)
- `--engine-jail none|docker` — 기본 `docker`
- `--profile smoke|official|final-production` — 기본 `official`
- `--dev-allow-unjailed` — 개발 전용; 결과를 강제 진단으로 강등
- `--worker-id <id>` — 클레임한 잡에 기록(다중 워커)
- `--lease-seconds <n>` — 클레임 lease; 만료된 running 잡은 다른 워커가 회수
- `--final-eval` — 레거시: `final-eval` 프로파일로 매핑
- `--quick-test-mode` — 레거시: `smoke` 프로파일로 매핑(절대 verified 아님)

워커는 가장 오래된 대기 잡을 **원자적으로 클레임**해 한 건 처리하고 종료한다
(`bench/ceb/hosted/db.py` `claim_next_job`이 `BEGIN IMMEDIATE`로 queued→running
전이). connection은 autocommit + `busy_timeout` + WAL이라 여러 워커가 동일 DB를
안전하게 드레인한다. lease가 만료된 stale running 잡은 다른 워커가 회수한다.
`jobs` 테이블은 `worker_id` / `started_at` / `lease_expires_at` /
`attempt_count` / `public_detail` 컬럼을 가진다. `finish_job`은
`public_detail`(정제됨)과 `detail`(비공개)를 모두 저장한다. `migrate()`는 기존
DB를 데이터 손실 없이 가산적으로 마이그레이션한다.

---

## 4. 로컬 TOY 호스티드 평가(종단 간)

번들된 예제 제출물과 번들된 가짜 비공개 팩(`examples/eval_packs/tiny_private`)에
대해 전체 파이프라인을 따라간다. `--quick-test-mode`(== `smoke` 프로파일)는
아주 작은 토이 매치를 선택한다 — 진단용이며 절대 채점에 쓰지 말 것(§6 참조).

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
#     official_round with the pack -> public/private artifacts -> leak scan ->
#     signed result. smoke runs unjailed; add --engine-jail docker for the
#     jailed engine on verifiable profiles.
.venv/bin/ceb hosted worker run-once \
    --db "$DB" \
    --eval-pack examples/eval_packs/tiny_private \
    --quick-test-mode

# (d) inspect the recorded result and the verified-only leaderboard
.venv/bin/ceb hosted result show --run-id toy-001 --db "$DB"
.venv/bin/ceb hosted leaderboard --db "$DB" --track A
```

`submit`은 `--workspace <dir>`(서버 로컬 디렉터리) 또는 `--archive
<.tar.gz|.tar|.zip>` 중 **정확히 하나**를 받는다. 아카이브는 안전 추출된다
(심볼릭/하드 링크, 절대 경로, 경로 탐색, 과대 파일 거부 — §7 참조).

`worker run-once`는 JSON 상태(`{"status": "done", ..., "verified": ...,
"profile": ..., "verification_grade": ...}`)를 출력하고
`<db>_store/<run-id>/job_<n>/`에 `official_result.json`(스키마
`ceb.hosted.official_result/v2`, 공개 산출물)을 쓴다. 워커는 `verified: true`
결과를 만드는 **유일한** 생산자다. 비공개 eval 팩이 없거나, 정적 스캔이
실패하거나, strict 게이트가 실패하거나, 누출이 감지되거나, verifiable
프로파일인데 감옥이 docker가 아니면, 워커는 verified 작성을 거부하고 잡을 정제된
사유와 함께 `failed`로 표시한다.

### 공유 결과 선택자

리더보드, `ceb hosted result show`, `GET
/api/hosted/runs/{id}/official-result`는 모두 동일한 선택자
(`bench/ceb/hosted/db.py` `select_best_verified_result`)를 사용하므로 한 run이
광고하는 공식 결과는 리더보드 항목과 **항상 일치**한다. 정책: run별 단일 best
verified 결과를 고르되, final-tier
(`final_production`/`final_eval`/`track_b_official`)를
official-tier(`official_round`/`official`)보다 선호한다. smoke는 verified가
아니므로 절대 선택되지 않는다.

---

## 5. 결과 서명 및 검증 (Ed25519 > HMAC > unsigned)

서명은 `bench/ceb/hosted/signing.py`가 처리하며, 작성 시점에
`sign_official_result`이 **가장 강한 구성된 알고리즘**을 선택한다: Ed25519(공개키
서명) → 레거시 HMAC → unsigned. 자세한 보안 모델과 키 배포는
`docs/RESULT_SIGNING.md`를 참조하라.

키 생성 및 서명/검증:

```bash
# generate an Ed25519 keypair (private stays with the operator; public is published)
.venv/bin/ceb hosted keygen \
    --private-key /secure/ceb_ed25519.pem \
    --public-key  /secure/ceb_ed25519.pub.pem

RESULT=/tmp/ceb_toy/hosted_store/toy-001/job_1/official_result.json

# sign explicitly with the private key (or set CEB_SIGNING_PRIVATE_KEY)
.venv/bin/ceb hosted sign-result --result "$RESULT" \
    --private-key /secure/ceb_ed25519.pem

# anyone can verify against the operator's PUBLIC key
.venv/bin/ceb hosted verify-result --result "$RESULT" \
    --public-key /secure/ceb_ed25519.pub.pem
```

**서명 키 환경 변수:**

- `CEB_SIGNING_PRIVATE_KEY` — Ed25519 비공개 키 PEM 경로. 설정 시 워커가 결과를
  Ed25519로 서명한다(공개키 검증 가능; 권장).
- `CEB_SIGNING_KEY` — 레거시 대칭 HMAC-SHA256 비밀. Ed25519 키가 없을 때만
  사용되며, 키 보유자에게만 인증하는 운영자 내부용이다(제3자 검증 불가).
- `CEB_PUBLIC_KEY` — Ed25519 공개 키 PEM 경로(검증용).

키가 전혀 없으면 결과는 `signature.status: "unsigned"`로 기록되며 어떤 암호학적
진정성도 주장하지 않는다. 실제 실행에서는 결과가 나중에 다시 서명되는 대신
작성 시점에 서명되도록 **워커 환경에서** `CEB_SIGNING_PRIVATE_KEY`(또는 레거시
`CEB_SIGNING_KEY`)를 export하라. `verify-result`는 `authentic`이 true(스키마
일치, 유효한 서명, 키 누락 없음)가 아니면 0이 아닌 값으로 종료한다. 검증기는
v1 결과 파일도 backward-compat로 수용한다.

---

## 6. 프로덕션 final eval 실행

실제 호스티드 채점은 `--quick-test-mode`를 **생략**하고 verifiable 프로파일을
쓴다. 매치 분량은 `tracks/a_from_scratch/scoring.yaml`의 `round_modes` 블록에서
구성하며(`final_production` / `final_eval` / `official_round`), 프로파일 floor는
`tracks/a_from_scratch/eval_profiles.yaml`에 문서화되어 있다.

```yaml
round_modes:
  final_production:       # production leaderboard CI; strict gate; NEVER run by CI
    opponents: [BenchRandom, BenchGreedyCapture, BenchMaterial1, BenchPST1, BenchMiniMax2, BenchAlphaBeta3]
    games_per_opponent: 336   # 6 opponents x 336 = 2016 games (paired openings)
    movetime_ms: 1000
    max_plies: 300
    openings_limit: 24
    # anchors: [SF18_UCI_Elo_1320, SF18_UCI_Elo_1600, SF18_UCI_Elo_1900, SF18_UCI_Elo_2200]
    # anchors_required: true
```

- `games_per_opponent` / `openings_limit`는 실행 시간과 Elo 정밀도를 좌우한다.
  공식 공개 실행에서는 floor 아래로 낮추지 말 것.
- `anchors`는 `anchor_opponents` 아래에 정의된 제한 강도 Stockfish 앵커 상대(예:
  `SF18_UCI_Elo_1320`)를 활성화한다. 앵커는 `UCI_LimitStrength` / `UCI_Elo` /
  `Threads=1`을 보내며 PATH에 `stockfish`가 있어야 한다
  (`scripts/setup_stockfish.sh`).
- 기본적으로 누락된 앵커 바이너리는 진행 안내와 함께 건너뛴다(CI가 Stockfish에
  의존하지 않도록). `anchors_required: true`(호스티드 정책)를 설정하면 나열된
  앵커가 없을 때 라운드가 대신 **중단**되어, 의도한 앵커 없이 조용히 채점되는
  것을 막는다.

프로덕션 final-production 실행(감옥 + 서명 키와 함께):

```bash
CEB_SIGNING_PRIVATE_KEY=/secure/ceb_ed25519.pem \
.venv/bin/ceb hosted worker run-once \
    --db runs/hosted.sqlite \
    --eval-pack /secure/path/to/private_pack \
    --engine-jail docker \
    --profile final-production
```

비공개 eval 팩은 평가기가 **호스트 측에서만** 읽는다. 포지션은 `position fen ...`
UCI 라인의 형태로만 격리된 엔진에 도달하므로, 숨겨진 팩은 `--engine-jail
docker`와 안전하게 결합된다(팩 디렉터리는 엔진 컨테이너에 절대 마운트되지
않는다).

### 비공개 eval 팩 구성

eval 팩은 공개 토큰과 비공개(숨겨진) 토큰을 함께 담는다. verified 결과를
기록하기 전에 공개 아티팩트 누출 스캐너(`bench/ceb/scan/leak_scan.py`
`scan_public_artifacts`)가 공개 산출물에 숨겨진 비밀이 새지 않았는지 검사한다.
스캐너는 비공개 팩의 비밀 토큰(`fen_hidden.jsonl`, `perft_hidden.jsonl`,
`openings_hidden.jsonl`의 숨겨진 FEN/배치 문자열·오프닝 id·행 id·수순, 비공개
팩 경로)을 수집하되 공개 팩 토큰은 제외해 오탐을 막는다. 누출 시 verified가
거부되고 잡이 `failed`로 표시되며, 비밀을 직접 echo하지 않고 해시만 담은 비공개
`leak_scan.json`이 기록된다. Track A는 `official_eval`에, Track B는
`official_pipeline`에 통합되어 있다.

---

## 7. Track B 호스티드

Track B(고정 baseline 대비 엔진 소스 편집)도 호스티드 워커에서 verified
delta-Elo 결과를 만들 수 있다(잡 종류 `track_b_official_eval`). 후보/baseline
스냅샷·해시, 빌드 스크립트, 엔진 상대 경로는 `track_b_submissions` 테이블에
저장된다.

```bash
.venv/bin/ceb hosted submit-track-b \
    --candidate-src /path/to/candidate_src \
    --baseline-src  /path/to/baseline_src \
    --run-id trackb-001 \
    --db runs/hosted.sqlite
    # --build-script ceb_build.sh   --engine-relpath ceb_engine (기본값)

.venv/bin/ceb hosted worker run-once \
    --db runs/hosted.sqlite \
    --eval-pack /secure/path/to/private_pack \
    --engine-jail docker \
    --profile final-production
```

워커는 잡 종류로 분기(`bench/ceb/hosted/worker.py`)해
`bench/ceb/hosted/track_b_eval.py` `run_hosted_track_b`를 호출한다. verified
Track B 요건: source-first 파이프라인의 보장(diff 화이트리스트 + 콘텐츠 스캔 +
baseline/candidate 동일 빌드 스크립트) + verifiable 프로파일 + candidate 엔진
Docker 감옥 + 비공개 eval 팩 + 누출 스캔 통과 + 서명. 결과는
`mode=track_b_official`, score는 final delta Elo이며, `verified_leaderboard(track
="B")`에 들어간다. smoke 프로파일이나 `--dev-allow-unjailed`는 verified=false
진단 결과를 만든다. Docker가 필요한 verified 경로 테스트는 opt-in이다
(`CEB_DOCKER_TESTS=1`). 실제 고정 Stockfish 빌드 래퍼 준비는 운영자 단계다.

---

## 8. API 제공

HTTP API는 호스티드 엔드포인트와 대시보드를 노출한다(`bench/ceb/api/main.py`).
`CEB_HOSTED_DB`(기본 `runs/hosted.sqlite`)로 호스티드 데이터베이스를 가리키게
하고, 관리자 POST 엔드포인트를 활성화하려면 `CEB_ADMIN_TOKEN`을 설정한다:

```bash
export CEB_HOSTED_DB=runs/hosted.sqlite
export CEB_ADMIN_TOKEN="change-me-admin-token"
.venv/bin/ceb server start --host 127.0.0.1 --port 8000
```

**관리자 POST 엔드포인트**(헤더 `X-CEB-Admin-Token: $CEB_ADMIN_TOKEN` 필요):

```bash
ADMIN=change-me-admin-token
# create a run
curl -X POST localhost:8000/api/hosted/runs \
     -H "X-CEB-Admin-Token: $ADMIN" -H 'content-type: application/json' \
     -d '{"run_id":"api-001","track":"A"}'
# submit a server-local workspace path
curl -X POST localhost:8000/api/hosted/runs/api-001/submissions \
     -H "X-CEB-Admin-Token: $ADMIN" -H 'content-type: application/json' \
     -d '{"workspace":"examples/submissions/minimal_uci_engine_python"}'
# OR safely upload a .tar.gz/.tar/.zip body (extracted: no symlinks/traversal/oversized)
curl -X POST "localhost:8000/api/hosted/runs/api-001/upload?filename=ws.tar.gz" \
     -H "X-CEB-Admin-Token: $ADMIN" --data-binary @ws.tar.gz
# enqueue a job (kind: official_eval | track_b_official_eval)
curl -X POST localhost:8000/api/hosted/runs/api-001/jobs \
     -H "X-CEB-Admin-Token: $ADMIN" -H 'content-type: application/json' \
     -d '{"kind":"official_eval"}'
```

`CEB_ADMIN_TOKEN`이 구성되지 않으면 관리자 POST는 **503**을, 잘못되거나 누락된
토큰은 **403**을 반환한다. 제출 `workspace`는 **서버 로컬 경로**다. 업로드 본문은
안전 추출되며(`bench/ceb/hosted/upload.py` `safe_extract_archive`), 200 MiB
상한이 적용된다. API는 작업을 큐에 넣기만 하며, 여전히 `ceb hosted worker
run-once`를 직접 실행해야 한다(워커는 서버가 시작하지 않는다).

**공개 GET 엔드포인트**(토큰 불필요):

```bash
curl localhost:8000/health
curl localhost:8000/api/hosted/runs/api-001
curl localhost:8000/api/hosted/runs/api-001/feedback
curl localhost:8000/api/hosted/runs/api-001/official-result          # shared best-verified selector
curl "localhost:8000/api/hosted/leaderboard?track=A"                 # verified-only
curl localhost:8000/api/hosted/artifacts/<artifact_id>
```

산출물 엔드포인트는 **기본 거부(deny-by-default)**다: DB 가시성이 `public`인
산출물만 제공하며, 비공개/알 수 없는 id와 경로 순회 시도는 404(잘못된 id는
400)를 반환한다. 자체 리버스 프록시/TLS 뒤에서 `127.0.0.1`에 바인딩하라 — 앱은
관리자 토큰 외에 어떤 인증도 하지 않으며 레이트 리미팅도 제공하지 않는다.

### 공개 결과 번들 내보내기

운영자는 검증 가능한 공개 번들을 zip으로 내보낼 수 있다
(`bench/ceb/hosted/result_bundle.py`):

```bash
.venv/bin/ceb hosted result export \
    --run-id api-001 --db runs/hosted.sqlite --out /tmp/api-001.zip
```

번들은 **공개 아티팩트만** 담는다: 서명된 `official_result.json`(+ 재현성
메타데이터 + 서명), `feedback.json`, `report.public.json`과 함께 `VERIFY.txt`,
`bundle_manifest.json`. 비공개/admin 산출물은 포함되지 않는다.

---

## 9. 에이전트 궤적(선택)

제출 출처를 기록하는 선택적 스키마 `ceb.agent.trajectory/v1`
(`bench/ceb/agent_trajectory.py`)이 있다: `model_id` / `agent_id` /
`prompt_version` / `tool_budget` / `gate_attempts` / `round_attempts` /
`command_log_hash` / `source_snapshot_hash`. 비공개 사고 과정(chain of thought)은
요구하지 않으며, 명령 로그는 내용이 아니라 해시만 기록한다.

---

## 참고 / 운영 경계

- **여러 워커**를 동일 DB에 안전하게 돌릴 수 있다(원자적 클레임 + lease 회수).
  연속 운영하려면 루프나 스케줄러에서 `worker run-once`를 반복 실행하라.
- **재현성 메타데이터**(`bench/ceb/hosted/metadata.py`)는 벤치마크 버전, git
  커밋, 평가기/감옥 이미지 다이제스트, eval-팩 / 상대-풀 / 오프닝-스위트 해시,
  하드웨어, 소프트웨어, 랜덤 시드를 기록한다. 이미지 다이제스트 필드는 Docker를
  쓸 수 없을 때 `null`이다. 다이제스트가 의미를 갖도록 실제로 실행하는 평가기
  및 감옥 이미지를 빌드/커밋하라.
- **스키마 버전.** 결과 `ceb.hosted.official_result/v2`, 리더보드
  `ceb.hosted.leaderboard/v2`, 잡 `ceb.hosted.job/v2`(v2는 `profile` +
  `verification_grade` + Track B를 추가). 검증기는 v1 결과도 수용한다.
- **정제된 오류.** 에이전트 대면 출력(CLI, 피드백, 공개 산출물)은 숨겨진 FEN,
  수순, 오프닝 id, 호스트 경로를 절대 출력하지 않는다. 전체 운영자 트레이스백을
  보려면 `CEB_DEBUG=1`을 설정하라 — 에이전트 대면 서비스에서는 절대 쓰지 말 것.
