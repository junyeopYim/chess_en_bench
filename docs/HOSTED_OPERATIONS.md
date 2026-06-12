# 호스티드 운영 런북

운영자가 chess_en_bench의 **공식(verified)** 호스티드 평가를 실행하는 방법.

호스티드 파이프라인은 단일 노드 SQLite + 로컬 객체 스토어 설계이며, 잡을
원자적으로 클레임하는 워커(`ceb hosted worker run-once`)로 구동된다. 동일한 DB에
대해 여러 워커를 동시에 돌릴 수 있다(원자적 클레임 + lease 회수). API는 잡을
큐에 넣고 공개 산출물을 제공하며, 워커는 별도로 드레인한다.

**핵심 정직성 원칙.** 공개 공식(verified) 결과는 오직 호스티드 워커만,
다음 조건을 **모두** 만족할 때 생성한다: 깨끗한 스냅샷 + **해시 핀(hash-pin)된
신뢰된 공식 eval 팩**(커밋된 데모 팩 아님) + 정적 스캔 통과 + strict 게이트 통과
+ Docker 엔진 감옥(`--engine-jail docker`) + (Track B) **신뢰된 baseline** +
**해시 핀된 신뢰 운영자 빌드 래퍼**를 쓰는 격리 빌드 감옥 + **검증된 빌드 출력**
+ **bench/speed 정합성** + **스테이징된** 아티팩트에 대한 공개 아티팩트 누출 스캔
통과 + **Ed25519 서명** + 원자적 소유권 펜싱 DB 기록. 로컬 CLI 라운드와 직접
실행한 Track B CLI는 자가보고(self-reported) / 진단(diagnostic)이며 **결코
verified가 아니다**. smoke/quick 결과는 절대 공식 리더보드에 오르지 않으며,
호스티드 리더보드는 verified 결과만 담는다. 정직한 라벨은 "public official
single-node hosted benchmark"다 — 단일 노드(SQLite + 로컬 FS) 설계는 정직함을
유지하며 분산 프로덕션 서비스가 아니다.

**리포지토리는 `ceb hosted readiness declare`(항상 strict) 또는 `ceb hosted
readiness check --strict-public-official`이 통과할 때에만** Track A와 Track B에
대해 "public official single-node hosted benchmark ready"라고 선언할 수 있다(§9).
이 둘만이 공식 선언 게이트다(비-strict `readiness check`는 진단용). strict 모드는
핀/공개 키/키페어 일치/baseline/래퍼 해시 앵커를 경고가 아니라 **차단(blocking)**
검사로 승격시키며, readiness가 유일한 선언 게이트다
(`public_official_declaration` + `blocking_failures`). 마지막 모호함도 제거되었다:
어떤 `--dev-*` 플래그도 verified=true를 유지하지 못하고, 신뢰 앵커(키페어·
baseline·래퍼)는 실제로 검증되며, 단일 노드(SQLite + 로컬 FS) 설계는 정직함을
유지하되 분산 프로덕션 SaaS가 아니다.

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

**선언 전 사전 점검(pre-flight).** `scripts/public_official_smoke.sh [A|BOTH]`
(기본 `BOTH`)는 임시 디렉터리 안에 **완전히 모킹된** 공식 셋업을 만들어
(리포 밖 공식 팩, Ed25519 키페어, Track B baseline/candidate 트리, 트리 밖의 신뢰
래퍼, bench 지원 baseline 엔진, 핀된 해시, 임시 DB, 서명된 릴리스 매니페스트) `ceb
hosted readiness declare`를 돌린다. Docker + 감옥 이미지가 있으면 **READY**에
도달하고, 없으면 감옥 앵커에서 올바르게 **BLOCK**하며 완전한 verified e2e에는
Docker가 필요하다고 안내한다. 아티팩트는 종료 시 정리되어 커밋되지 않으며
PASS/FAIL을 출력한다.

```bash
bash scripts/public_official_smoke.sh BOTH
```

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
아니다**. 워커는 신뢰된 공식 eval 팩(§6), 정적 스캔, strict 게이트, 엔진 감옥,
스테이징 누출 스캔, Ed25519 서명(§5)을 여전히 강제한다. `smoke`처럼
verifiable=false인 프로파일은 어떤 플래그를 줘도 **절대** verified가 되지
않는다("magic verified" 없음). `profile`과 `verification_grade`는 결과 JSON과 DB
행에 함께 저장되며, 진단 등급에는 `diagnostic-unjailed`(§3), 서명 키 없이 강등된
`diagnostic-unsigned`(§5), 데모/비신뢰 팩으로 강등된
`diagnostic-untrusted-pack`(§6)도 포함된다.

`final_production` 라운드 모드(`tracks/a_from_scratch/scoring.yaml`
`round_modes.final_production` / `DEFAULT_ROUND_MODES`)는 6상대 x 336게임 =
2016게임, paired openings, movetime 1000ms이다. **CI는 절대 이 기본값으로
실행하지 않는다**(테스트는 tiny override / smoke 프로파일).

진단 등급(`bench/ceb/hosted/profiles.py`)에는 `diagnostic-unjailed`(§3),
`diagnostic-unsigned`(§5), `diagnostic-untrusted-pack`(데모/비신뢰 팩, §6),
`diagnostic-unpinned-pack`(핀 안 된 공식 팩, §6),
`diagnostic-untrusted-baseline`(비신뢰 baseline, §7),
`diagnostic-untrusted-wrapper`(핀 안 된 빌드 래퍼, §7),
`diagnostic-no-bench`(bench 정합성 우회/실패 강등, §7)가 있다. 어떤 `--dev-*`
플래그도 verifiable 실행을 실패시키거나 진단(unverified) 등급을 강제할 뿐, verified를
유지하지 못한다.

**진단 결과는 verified와 시각적으로 혼동할 수 없다.** 모든 진단 결과(어떤 dev
플래그 강등이든)는 `verified:false`, `"diagnostic-"`로 시작하는
`verification_grade`, 평문 `diagnostic_reason`, `public_official_eligible:false`를
함께 담는다(`bench/ceb/hosted/profiles.py` `diagnostic_reason`,
`is_public_official_eligible`). `ceb hosted result show`는 `*** DIAGNOSTIC — NOT
PUBLIC OFFICIAL: <reason> ***`를 출력하고, 번들 export는 기본적으로 진단 결과를
거부하며(선택된 best verified 결과만 번들), `GET .../official-result`도 verified
결과만 반환한다. 호스티드 리더보드는 verified-only이므로 진단 결과를 무시한다.

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
- `--eval-pack <dir>` — 신뢰된 공식 eval 팩(**verified에 필수**; §6)
- `--engine-jail none|docker` — 기본 `docker`
- `--profile smoke|official|final-production` — 기본 `official`
- `--official-pack-hash <hash>` — 허용된 공식 eval 팩 콘텐츠 해시(반복/콤마 가능;
  env `CEB_OFFICIAL_EVAL_PACK_HASHES`와 합산). **verified에는 핀이 필수**(§6).
- `--official-pack-registry <file>` — 허용 해시 목록을 담은 JSON/텍스트 파일
- `--signing-key <pem>` — Ed25519 비공개 키 PEM(없으면
  `CEB_SIGNING_PRIVATE_KEY`). **verified에 필수**(§5)
- `--build-wrapper <file>` — 신뢰된 Track B 빌드 래퍼(후보/baseline 트리 **밖**의
  파일; verified Track B에 필수; §7)
- `--build-wrapper-hash <hash>` — 허용된 빌드 래퍼 파일 해시(Track B; 반복/콤마;
  env `CEB_TRACK_B_BUILD_WRAPPER_HASHES`). **verified Track B에는 핀이 필수**(§7).
- `--build-wrapper-registry <file>` — 허용 래퍼 해시 목록 JSON/텍스트 파일
- `--track-b-baseline-hash <hash>` — 허용된 Track B baseline 트리 해시(반복/콤마;
  env `CEB_TRACK_B_BASELINE_HASHES`). baseline 신뢰 모드 중 하나(§7).
- `--track-b-baseline-registry <file>` — 허용 baseline 해시 목록 JSON/텍스트 파일
- `--bench-min-nps-ratio <f>` — verified Track B의 최소 candidate/baseline NPS
  비율(기본 0.3; 두 엔진이 모두 `bench`를 지원할 때만 강제; §7)
- `--dev-allow-unjailed` — 개발 전용; 결과를 강제 진단(`diagnostic-unjailed`)으로 강등
- `--dev-allow-demo-pack` — 개발 전용; 커밋/데모 경로의 팩을 허용(여전히 유효한
  공식 manifest 필요; 경로 체크만 우회; `diagnostic-untrusted-pack`)
- `--dev-allow-unpinned-pack` — 개발 전용; 해시 허용목록 없는 공식 팩을 허용하되
  결과를 강제 `verified=false`(`diagnostic-unpinned-pack`)로 강등
- `--dev-allow-unsigned` — 개발 전용; Ed25519 키 없이 실행하되 결과를 강제
  `verified=false`(`diagnostic-unsigned`)로 강등
- `--dev-allow-toy-baseline` — 개발 전용; 비신뢰 toy baseline을 허용하되 결과를
  강제 `verified=false`(`diagnostic-untrusted-baseline`)로 강등(§7)
- `--dev-allow-unpinned-wrapper` — 개발 전용; 해시 허용목록 없는 빌드 래퍼를
  허용하되 결과를 강제 `verified=false`(`diagnostic-untrusted-wrapper`)로 강등(§7)
- `--dev-allow-no-bench` — 개발 전용; bench/NPS 실패로 verified Track B를
  하드 실패시키는 대신 결과를 강제 `verified=false`(`diagnostic-no-bench`)로 강등(§7)
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

번들된 예제 제출물과 번들된 데모 팩(`examples/eval_packs/tiny_private`)에 대해
전체 파이프라인을 따라간다. `--quick-test-mode`(== `smoke` 프로파일)는 아주 작은
토이 매치를 선택한다 — 진단용이며 절대 채점에 쓰지 말 것(§6 참조). 커밋된 데모
팩은 공식 manifest가 없어 **절대 verified가 될 수 없다**(smoke 프로파일에만
적합). verified 실행은 §6의 신뢰된 공식 팩을 요구한다.

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
결과를 만드는 **유일한** 생산자다. 신뢰된 공식 eval 팩이 없거나, 정적 스캔이
실패하거나, strict 게이트가 실패하거나, 누출이 감지되거나, verifiable
프로파일인데 감옥이 docker가 아니거나, Ed25519 서명 키가 없으면, 워커는 verified
작성을 거부하고(서명 키 부재는 평가 **전에** 거부) 잡을 정제된 사유와 함께
`failed`로 표시한다.

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

**verified는 Ed25519를 요구한다(하드 규칙).** verified 결과는 반드시 Ed25519로
서명되어야 한다. verifiable 프로파일에서는 Ed25519 비공개 키를 정적 스캔 / strict
게이트 / 빌드 / 매치 **전에** 해석하고 load-검증한다(`signing.py`
`require_ed25519_private_key`; `official_eval.py`, `track_b_eval.py`). 키
(`CEB_SIGNING_PRIVATE_KEY` env 또는 `--signing-key`)가 **없으면** 평가 전에 verified가
거부되며 — `--dev-allow-unsigned`로 강제하면
`verified=false`(`diagnostic-unsigned`) — 키가 **형식 오류**면 정제된 메시지와 함께
일찍 하드 실패하므로 서명 실패 때문에 스테이징된 공개 아티팩트가 남지 않는다.
검증된 키 경로는 서명 시점에 그대로 재사용된다.
HMAC 결과는 **절대** public-official verified가 될 수 없다(HMAC은 레거시/진단
전용). `official_eval`은 verified 결과의 `signature.algorithm == "ed25519"`를
단언한다. 검증기(`verify_result_file`)는 Ed25519가 아닌 verified 결과를
`authentic=false`로 두며(필드 `public_official_signing`), `authentic`이 되려면
out-of-band로 **공급된 공개 키**가 필요하다(임베디드 키 단독은 서명 신뢰가
`embedded-self-described`, authentic은 false).

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

프로덕션 final-production 실행(감옥 + 신뢰된 공식 팩 + 서명 키와 함께):

```bash
.venv/bin/ceb hosted worker run-once \
    --db runs/hosted.sqlite \
    --eval-pack /secure/path/to/official_pack \
    --engine-jail docker \
    --profile final-production \
    --signing-key /secure/ceb_ed25519.pem \
    --official-pack-hash sha256:...        # 선택: 허용된 팩 콘텐츠 해시
```

비공개 eval 팩은 평가기가 **호스트 측에서만** 읽는다. 포지션은 `position fen ...`
UCI 라인의 형태로만 격리된 엔진에 도달하므로, 숨겨진 팩은 `--engine-jail
docker`와 안전하게 결합된다(팩 디렉터리는 엔진 컨테이너에 절대 마운트되지
않는다).

### 신뢰된 공식 eval 팩

verified 결과는 **신뢰된 공식 팩**에 대해서만 생성된다
(`bench/ceb/hosted/eval_pack_trust.py` `validate_official_eval_pack`). 공식 팩
디렉터리는 다음을 만족하는 `manifest.json`을 가져야 한다: 스키마
`ceb.eval_pack.manifest/v1` + 키 `pack_id` / `name` / `track` / `season` /
`official`(true) / `visibility`("private") / `openings_mode`. 또한 팩은
리포지토리의 `examples/`나 `tests/` **밖**에 존재해야 한다(개발 플래그
`--dev-allow-demo-pack`는 경로 체크만 우회).

**하드 규칙 — 핀이 verified의 필수 조건.** verified 결과는 팩 콘텐츠
해시가 **핀(allowlist)되어 있어야** 한다: env `CEB_OFFICIAL_EVAL_PACK_HASHES`
(콤마), CLI `--official-pack-hash`(반복/콤마), `--official-pack-registry`(JSON
`{"hashes":[...]}` / 리스트 / 라인 텍스트 파일) 중 하나로 허용목록을 제공해야
한다. 허용목록이 **없으면** verified는 평가 **전에** 거부된다(trust 보고의
`allowlist_checked`가 false). `--dev-allow-unpinned-pack`은 핀 없이 진행하되
결과를 강제 `verified=false`(`diagnostic-unpinned-pack`)로 강등한다. smoke는
여전히 비신뢰 데모 팩으로 실행된다.

커밋된 데모 팩 `examples/eval_packs/tiny_private`는 공식 manifest가 없으므로
**절대 verified가 될 수 없다**(smoke 프로파일에는 적합). verified 결과 메타데이터는
`eval_pack_id` / `eval_pack_hash` / `eval_pack_manifest_hash` /
`eval_pack_trusted`(true) / `eval_pack_track` / `eval_pack_season`를 기록한다.

### 누출 스캔과 스테이징

verified 결과를 기록하기 전, 공개 대상 아티팩트는 먼저 **스테이징**으로
기록된다(manifest visibility=private + staged_public 마커이므로 그 시점에는
아무것도 서빙되지 않는다 — `bench/ceb/storage/promotion.py`). 공개 아티팩트
누출 스캐너(`bench/ceb/scan/leak_scan.py` `scan_public_artifacts(..., staged
=True)`)가 스테이징 집합을 재귀적으로 검사하고, **통과 시에만** 가시성을
`public`으로 승격한다. 누출 시 워커는 공개 항목을 하나도 등록하지 않는다(해당 잡
시도에 대한 공개 manifest 항목 없음). Track A는 `official_eval`에, Track B는
`official_pipeline`에 통합되어 있다.

eval 팩은 공개 토큰과 비공개(숨겨진) 토큰을 함께 담는다. 누출 스캐너는 비공개
팩의 비밀 토큰(`fen_hidden.jsonl`, `perft_hidden.jsonl`, `openings_hidden.jsonl`의
숨겨진 FEN/배치 문자열·오프닝 id·행 id·수순, 비공개 팩 경로)을 수집하되 공개 팩
토큰은 제외해 오탐을 막는다. 누출 시 verified가 거부되고 잡이 `failed`로
표시되며, 비밀을 직접 echo하지 않고 해시만 담은 비공개 `leak_scan.json`이
기록된다.

---

## 7. Track B 호스티드

Track B(고정 baseline 대비 엔진 소스 편집)도 호스티드 워커에서 verified
delta-Elo 결과를 만들 수 있다(잡 종류 `track_b_official_eval`). 후보/baseline
스냅샷·해시, 빌드 스크립트, 엔진 상대 경로는 `track_b_submissions` 테이블에
저장된다.

### 빌드 격리(verified는 호스트 빌드를 절대 안 한다)

verified Track B는 후보 소유의 빌드 스크립트를 **호스트에서 절대 실행하지
않는다**. **신뢰된 운영자 빌드 래퍼**(후보/baseline 트리 **밖**의 파일; 워커에
`--build-wrapper`로 전달)가 baseline과 candidate를 **동일한 래퍼**로 Docker 빌드
감옥 안에서 빌드한다: source는 `/src`에 **읽기 전용** 마운트, `/out`는 쓰기 가능,
래퍼는 `/wrapper.sh`에 읽기 전용, `--network none`, read-only 루트 + tmpfs,
cpu/mem/pids 제한, 비루트, 리포/eval-팩 **미마운트**
(`bench/ceb/track_b/build_jail.py` `build_in_jail`). 래퍼 계약:
`/wrapper.sh <source_ro> <out_writable> <engine_relpath>`. 래퍼 경로 검증은
`bench/ceb/hosted/build_wrappers.py` `validate_build_wrapper`가 수행하며, 테스트/
로컬 진단용 데모 래퍼는 `write_demo_wrapper`가 만든다. 빌드된 candidate 엔진은
이후 매치 동안 엔진 감옥에서 실행된다. 결과/메타데이터는 `build_isolation`을
기록한다(`"jail"` | `"host"`).

**빌드 출력 하드닝(req5).** 감옥 빌드 직후
`build_jail.py` `validate_build_output`이 출력 트리를 검사한다: 엔진은 존재 +
실행 가능 + 일반 파일(심볼릭 링크 아님)이어야 하고, 출력 트리 어디에도 심볼릭
링크가 없어야 하며, 총 크기는 **512 MiB 이하**, 파일 수는 **10000개 이하**여야
한다. 빌드 출력 트리 해시는 `metadata.track_b.build_output`에 기록된다.

**baseline 신뢰(req3).** verified baseline은 `bench/ceb/track_b/baseline_trust.py`
`validate_track_b_baseline`이 인정하는 세 모드 중 하나로 신뢰되어야 한다:
`stockfish-lock`(baseline git HEAD가 `tracks/b_stockfish_opt/stockfish.lock`의
커밋과 일치 **그리고** 워킹 트리가 깨끗함(`git status --porcelain`이 비어 있는
`git_worktree_clean`) **그리고** 서브모듈이 깨끗함(`git_submodules_clean`); 더럽거나
추적되지 않은 체크아웃은 stockfish-lock으로 신뢰되지 **않고** hash 모드로 떨어지거나
실패한다), `hash`(트리 콘텐츠 해시가 `--track-b-baseline-hash` /
`CEB_TRACK_B_BASELINE_HASHES` / `--track-b-baseline-registry` 허용목록에 있음 —
`.git` 없는 스냅샷 baseline에도 동작), `toy`(`--dev-allow-toy-baseline`;
`verified=false`, `diagnostic-untrusted-baseline`). `metadata.track_b`는
`baseline_trusted` / `baseline_trust_mode` / `baseline_tree_hash`(콘텐츠 해시 기록)
/ `stockfish_lock`을 기록한다.

**빌드 래퍼 해시 핀(req4).** verified Track B는 래퍼 **파일 해시**가 핀되어 있어야
한다(`build_wrappers.py` `compute_wrapper_hash` / `resolve_wrapper_hashes`):
`--build-wrapper-hash` / `CEB_TRACK_B_BUILD_WRAPPER_HASHES` /
`--build-wrapper-registry`. 핀이 없으면 verified가 거부되며,
`--dev-allow-unpinned-wrapper`는 `verified=false`(`diagnostic-untrusted-wrapper`)로
강등한다. `metadata.track_b`는 `build_wrapper_hash` / `build_wrapper_trusted` /
`build_isolation` / `build_jail_image_digest`를 기록한다.

**bench/speed 정합성(req6).** verified Track B에서는 baseline과 candidate 양쪽이
`bench`를 실행하고(`bench/ceb/track_b/bench_sanity.py` `run_bench_sanity`),
보고에 엔진별 `nodes` / `nps` / `output_hash`와 `nps_ratio`가 기록된다. **verified
Track B는 baseline과 candidate가 모두 bench를 지원할(SUPPORTED) 것을 요구한다.**
baseline이 NPS를 보고하지 못하면(unsupported) verified Track B는 **실패**한다
(예전의 "지원 안 함 = 조용히 통과"는 사라졌다); `--dev-allow-no-bench`를 줘야만
진행하되 **언제나** `verified=false`(`diagnostic-no-bench`)로 강등하며 검증을 결코
유지하지 않는다. baseline은 bench하는데 candidate가 못 하면 실패/강등이며 결코
verified가 아니다. verified 경로에서 candidate의 엔진 감옥 bench 명령 구성이
실패하면 candidate bench는 **거부(에러)**되며 **호스트에서 실행되지 않는다**(호스트
폴백 없음; 내부적으로 `_run_bench(require_candidate_jail=...)`). NPS 비율
임계값(`--bench-min-nps-ratio`, 기본 0.3)은 **두 엔진이 모두 bench를 지원할
때에만** 강제된다(jailing 시 candidate는 bench를 위해 감옥에서 실행). bench 정책은
**우회 불가**다: NPS가 임계값 미달이면 verified Track B는 **하드 실패**(결과
없음)하고, `--dev-allow-no-bench`는 실패를 무시하는 대신 결과를 강제
`verified=false`(`diagnostic-no-bench`)로 **강등**시켜 **결코 리더보드에 오르지
않게** 한다(`track_b/official_pipeline.py`). 즉 어떤 `--dev-*` 플래그도
verified=true를 유지하지 못한다. `metadata.track_b`는 `bench_required` /
`bench_supported` / `bench_passed` / `nps_ratio` / `min_nps_ratio`와
`bench_policy` 객체(`supported_required_for_verified` /
`enforced_when_baseline_supports_bench` / `override_downgrades_to_diagnostic`),
그리고 전체 bench 보고를 기록한다. 실제 공개 Track B는 bench를 지원하는 핀된
Stockfish가 필요하다.

빌드 감옥 이미지는 기본적으로 `chess-en-bench-jail:0.4`를 재사용한다(gcc/g++/make/
bash/python3 보유). 원하면 전용 이미지를 빌드할 수 있다:

```bash
bash scripts/build_track_b_build_image.sh   # builds chess-en-bench-build-jail:0.4
```

진단 CLI 경로(`ceb track-b official run`)는 호스트 빌드를 유지하므로 **항상
verified=false**다(`run_official_track_b`는 `build_isolation="host"`에서
verified=True를 거부한다). 실제 고정 Stockfish를 빌드하는 신뢰된 래퍼 준비는
운영자 단계다.

### CLI 제출과 워커 실행

```bash
.venv/bin/ceb hosted submit-track-b \
    --candidate-src /path/to/candidate_src \
    --baseline-src  /path/to/baseline_src \
    --run-id trackb-001 \
    --db runs/hosted.sqlite
    # --build-script ceb_build.sh   --engine-relpath ceb_engine (기본값)

.venv/bin/ceb hosted worker run-once \
    --db runs/hosted.sqlite \
    --eval-pack /secure/path/to/official_pack \
    --engine-jail docker \
    --profile final-production \
    --signing-key /secure/ceb_ed25519.pem \
    --build-wrapper /secure/path/to/trusted_build_wrapper.sh \
    --official-pack-hash sha256:...        # 공식 팩 핀(필수)
    --build-wrapper-hash sha256:...        # 빌드 래퍼 핀(필수)
    --track-b-baseline-hash sha256:...     # baseline hash 모드(또는 stockfish-lock)
```

워커는 잡 종류로 분기(`bench/ceb/hosted/worker.py`)해
`bench/ceb/hosted/track_b_eval.py` `run_hosted_track_b`를 호출한다. verified
Track B 요건: source-first 파이프라인의 보장(diff 화이트리스트 + 콘텐츠 스캔 +
baseline/candidate 동일 래퍼) + **신뢰된 baseline**(stockfish-lock/hash) + 격리
빌드 감옥(트리 밖 + **해시 핀된** 신뢰 래퍼) + **검증된 빌드 출력** +
**bench/speed 정합성** + verifiable 프로파일 + candidate 엔진 Docker 감옥 +
**해시 핀된** 신뢰 공식 eval 팩 + 스테이징 누출 스캔 통과 + Ed25519 서명. 결과는
`mode=track_b_official`, score는 final delta Elo이며,
`verified_leaderboard(track="B")`에 들어간다. smoke 프로파일이나 임의의 `--dev-*`
플래그는 verified=false 진단 결과를 만든다. Docker가 필요한 verified 경로
테스트는 opt-in이다(`CEB_DOCKER_TESTS=1`).

### Track B 호스티드 API 제출

관리자 전용 `POST /api/hosted/runs/{run_id}/track-b-submissions`는 JSON
`{candidate_src, baseline_src, build_script?, engine_relpath?}`를 받는다. 후보/
baseline 트리를 스냅샷(심볼릭 링크/안전하지 않은 파일 거부)하고 해시한 뒤 Track B
run을 만들거나 사용하고 `track_b_official_eval` 잡을 큐에 넣으며,
`submission_id` / `candidate_hash` / `baseline_hash` / `job_id`를 반환한다.
신뢰된 빌드 래퍼는 **워커에**(`--build-wrapper`) 공급하며 후보가 제공하지
**않는다**.

```bash
curl -X POST localhost:8000/api/hosted/runs/trackb-001/track-b-submissions \
     -H "X-CEB-Admin-Token: $ADMIN" -H 'content-type: application/json' \
     -d '{"candidate_src":"/srv/cand","baseline_src":"/srv/base"}'
```

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
# OR stream-upload a .tar.gz/.tar/.zip body (extracted: no symlinks/traversal/oversized)
curl -X POST "localhost:8000/api/hosted/runs/api-001/upload?filename=ws.tar.gz" \
     -H "X-CEB-Admin-Token: $ADMIN" --data-binary @ws.tar.gz
# enqueue a job (kind: official_eval | track_b_official_eval)
curl -X POST localhost:8000/api/hosted/runs/api-001/jobs \
     -H "X-CEB-Admin-Token: $ADMIN" -H 'content-type: application/json' \
     -d '{"kind":"official_eval"}'
```

`CEB_ADMIN_TOKEN`이 구성되지 않으면 관리자 POST는 **503**을, 잘못되거나 누락된
토큰은 **403**을 반환한다. 제출 `workspace`는 **서버 로컬 경로**다. 업로드
엔드포인트는 본문을 `async for chunk in request.stream()`으로 임시 파일에
**스트리밍**하며 읽는 동안 `_MAX_UPLOAD_BYTES`(200 MiB) 상한을 강제한다(초과 시
413; 실패 시 임시 디렉터리 삭제). 이후 안전 추출되며
(`bench/ceb/hosted/upload.py` `safe_extract_archive` — 심볼릭/하드 링크, 절대
경로, 경로 탐색, 비정규/과대 파일 거부) 스냅샷·해시된다. **리버스 프록시 뒤에
배포할 때는 프록시 자체의 본문 한도**(예: nginx `client_max_body_size`)**도
설정**하라. API는 작업을 큐에 넣기만 하며, 여전히 `ceb hosted worker run-once`를
직접 실행해야 한다(워커는 서버가 시작하지 않는다).

**공개 GET 엔드포인트**(토큰 불필요):

```bash
curl localhost:8000/health
curl localhost:8000/api/hosted/runs/api-001
curl localhost:8000/api/hosted/runs/api-001/feedback
curl localhost:8000/api/hosted/runs/api-001/official-result          # shared best-verified selector
curl "localhost:8000/api/hosted/leaderboard?track=A"                 # verified-only
curl "localhost:8000/api/leaderboard?track=B"                        # hosted DB가 있으면 verified Track B 보드로 위임
curl localhost:8000/api/hosted/readiness/public                      # secret-free 공개 readiness
curl localhost:8000/api/hosted/release-manifest                      # secret-free 릴리스 매니페스트(CEB_RELEASE_MANIFEST)
curl localhost:8000/api/hosted/artifacts/<artifact_id>
```

`GET /api/leaderboard?track=B`는 hosted DB가 존재하면 verified 호스티드 Track B
리더보드(`verified_leaderboard(track="B")`)로 **위임**하며, 없으면 `GET
/api/hosted/leaderboard?track=B`를 가리키는 빈 보드를 반환한다(Track B 리더보드가
없다고 오해를 주지 않기 위함). 비밀 없는(secret-free) `GET
/api/hosted/readiness/public`(스키마 `ceb.hosted.readiness.public/v1`)은 벤치마크
버전, 프로파일 verifiable 여부, 리더보드 정책만 노출한다 — eval 팩·키·이미지 같은
운영자 전용 앵커는 여기서 검사하지 않고 `ceb hosted readiness check
--strict-public-official` CLI(§9)가 검사한다. `GET
/api/hosted/release-manifest`(§9b)는 `CEB_RELEASE_MANIFEST`가 가리키는 릴리스
매니페스트를 서빙한다(미설정 시 **503**, 파일 없으면 **404**). 관리자 토큰이 필요
없는 공개 GET이며, 매니페스트는 구성상 secret-free다. 관리자 POST 엔드포인트는
여전히 상수 시간 토큰 비교(`hmac.compare_digest`)로 보호된다.

산출물 엔드포인트는 **기본 거부(deny-by-default)**다: DB 가시성이 `public`인
산출물만 제공하며, 비공개/알 수 없는 id와 경로 순회 시도는 404(잘못된 id는
400)를 반환한다. 자체 리버스 프록시/TLS 뒤에서 `127.0.0.1`에 바인딩하라 — 앱은
관리자 토큰 외에 어떤 인증도 하지 않으며 레이트 리미팅도 제공하지 않는다.

### 공개 결과 번들 내보내기

운영자는 검증 가능한 공개 번들을 zip으로 내보낼 수 있다
(`bench/ceb/hosted/result_bundle.py`):

```bash
.venv/bin/ceb hosted result export \
    --run-id api-001 --db runs/hosted.sqlite --out /tmp/api-001.zip \
    --release-manifest /tmp/release_B.json \
    --public-key /secure/ceb_ed25519.pub.pem    # 또는 --public-key-fingerprint <fp>
```

번들은 기본적으로 **선택된 best verified 결과**(`select_best_verified_result`)의
공개 아티팩트만 담는다(그 결과의 job-attempt 디렉터리 아래):
`official_result.json`, `feedback.json`, `report.public.json`,
`bundle_manifest.json`, `VERIFY.txt`. smoke/오래된/비선택 결과나 비공개
아티팩트(스캔/누출 리포트, 매치 로그, 게임 텍스트)는 **절대** 포함되지 않으며,
비공개 키나 숨겨진 팩 데이터도 결코 담기지 않는다. verified 결과가 없으면 기본
export는 오류로 끝난다. `--include-all-public`은 모든 공개 아티팩트를 담는 진단
번들이며 비공식임이 명확히 표시된다.

`--release-manifest <path>`를 주면 번들에 `release_manifest.json`(secret-free,
§9b)이 함께 담겨 제3자가 결과를 해당 공식 시즌에 매칭할 수 있다. `--public-key
<pem>`(지문 계산) 또는 `--public-key-fingerprint <fp>`를 주면 운영자 공개 키 지문이
번들에 기록된다. `VERIFY.txt`는 out-of-band 공개 키 / 릴리스 매니페스트 지문에
대해 검증하라는 안내를 담는다. `bundle_manifest`는 `schema` / `version` /
`selected_result_id` / `selected_mode` / `selected_grade` / `official` /
`selected_only` / `release_manifest_included` / `operator_public_key_fingerprint`를
담는다.

---

## 9. 사전 점검 (readiness check)

배포가 public-official-ready인지 한 번에 검사한다
(`bench/ceb/hosted/readiness.py`). 긍정 검사 배터리를 돌려 구조화된 JSON
리포트(스키마 `ceb.hosted.readiness/v2`)와 사람용 요약을 출력하고, ready가 아니면
0이 아닌 값으로 종료한다. 리포트는 `checks[name, ok, required, detail]`, 최상위
`ready`(required 검사가 모두 ok일 때 true), 그리고 단일 **선언 게이트**로 쓰이는
`public_official_declaration`(`"ready"` | `"not-ready"`)와
`blocking_failures`(실패한 required 검사 이름 목록)을 담는다. `--json` 플래그는
**JSON만** 출력해 깨끗한 기계 판독 출력을 보장한다.

```bash
.venv/bin/ceb hosted readiness check \
    --db runs/hosted.sqlite \
    --eval-pack /secure/path/to/official_pack \
    --public-key /secure/ceb_ed25519.pub.pem \
    --signing-key /secure/ceb_ed25519.pem \
    --track B \
    --build-wrapper /secure/path/to/trusted_build_wrapper.sh \
    --official-pack-hash sha256:... \
    --build-wrapper-hash sha256:... \
    --track-b-baseline-hash sha256:... \
    --track-b-baseline-engine /secure/path/to/baseline_engine \
    --strict-public-official --require-server --json
```

**`--strict-public-official`이 단일 선언 게이트다.** strict 모드에서는 핀 / 공개
키 / 키페어 일치 / baseline / 래퍼 해시 앵커가 경고가 아니라
**차단(required=true)** 검사가 된다. 리포지토리는 이 검사가 통과할 때에만 public
official single-node hosted benchmark ready로 선언할 수 있다. `--track BOTH`는 한
번에 Track A 팩 검사와 모든 Track B 검사를 함께 돌린다.

**Track A strict 검사 항목:** 패키지 버전 >= 0.3.5, DB 스키마 마이그레이션됨,
docker 사용 가능, 엔진 감옥 이미지 존재, 공식 eval 팩 **신뢰됨 + 핀됨**, 데모 팩
거부됨, Ed25519 서명 키 로드 가능, 공개 키 로드 가능, **키페어 일치**(비공개 키의
공개 키 지문 == 공급된 공개 키 지문; 리포트에 공개 키 지문 포함), smoke가
verifiable 아님, official/final-production이 verifiable, final-production 게임
floor(2016 >= 2000).

**Track B strict 추가 항목:** 빌드 감옥 이미지 존재, 빌드 래퍼 트리 밖 +
실행 가능 + **해시 핀됨**(`build_wrapper_pinned`), **baseline 신뢰**
(`track_b_baseline_trust` — 허용목록 콘텐츠 해시 또는 **깨끗한** stockfish-lock
체크아웃), **bench/speed 정합성**(`bench_speed_sanity`), **bench 능력 증명**
(`track_b_bench_capability` — **차단**), Track B API 엔드포인트
import 가능(`track_b_api_endpoint`). strict Track B readiness는 이제 bench 능력을
**증명**한다: `--track-b-baseline-engine <bench 지원 엔진>`을 주면 readiness가 그
엔진에서 실제로 bench를 돌려 NPS를 보고하는지 확인한다(`track_b_bench_capability`).
이를 주지 않으면 strict Track B 선언은 **차단(BLOCK)**된다. (예제 `engine.py`는 이제
`bench` 명령에 응답하므로 테스트/smoke에서 bench 지원 토이로 쓸 수 있다.) bench
정책은 **강제이며 우회 불가**다: baseline이 bench를 지원할 때 강제되고, bench
실패나 `--dev-allow-no-bench`는 진단으로 강등될 뿐 **결코 verified가 되지
않는다**.

`--eval-pack` / `--public-key` / `--build-wrapper` / `--signing-key` /
`--official-pack-hash` / `--official-pack-registry` / `--build-wrapper-hash` /
`--build-wrapper-registry` / `--track-b-baseline-hash` /
`--track-b-baseline-registry` / `--baseline-src` / `--track-b-baseline-engine`는
각 검사를 활성화하며, `--track B`(또는 `both`)는 Track B 전용 검사를 켠다.
`--track-b-baseline-engine`은 strict Track B의 `track_b_bench_capability` 차단
검사를 위해 bench 능력을 증명할 baseline 엔진을 지정한다. `--require-server`는
관리자 토큰 설정 여부를 검사한다.

### 선언 게이트: `ceb hosted readiness declare`

전용 선언 명령은 **항상** strict public-official 정책을 적용하므로, 운영자는
`--strict-public-official`을 따로 줄 필요가 없다. `public_official_declaration ==
"ready"`일 때에만 **0으로 종료**하고, 그렇지 않으면 0이 아닌 값으로 끝난다.
`--json`은 **JSON만** 출력한다(깨끗한 기계 판독). 공식 선언 게이트는 이
`readiness declare` **또는** `readiness check --strict-public-official`뿐이며,
비-strict `readiness check`는 진단용이다.

```bash
.venv/bin/ceb hosted readiness declare \
    --db runs/hosted.sqlite \
    --eval-pack /secure/path/to/official_pack \
    --public-key /secure/ceb_ed25519.pub.pem \
    --signing-key /secure/ceb_ed25519.pem \
    --track BOTH \
    --build-wrapper /secure/path/to/trusted_build_wrapper.sh \
    --official-pack-hash sha256:... \
    --build-wrapper-hash sha256:... \
    --track-b-baseline-hash sha256:... \
    --track-b-baseline-engine /secure/path/to/baseline_engine \
    --release-manifest /tmp/release_B.json \
    --require-server --json
```

플래그: `--db` / `--eval-pack` / `--public-key` / `--signing-key` /
`--track {A|B|BOTH}` / `--build-wrapper` / `--official-pack-hash` /
`--official-pack-registry` / `--build-wrapper-hash` / `--build-wrapper-registry` /
`--track-b-baseline-hash` / `--track-b-baseline-registry` / `--baseline-src` /
`--track-b-baseline-engine` / `--release-manifest` / `--require-server` / `--json`.

리포트는 §9의 strict readiness 본문에 더해 최상위 **`declaration_certificate`**
객체(스키마 `ceb.hosted.declaration_certificate/v1`)를 추가한다:
`benchmark_version` / `track` / `ready` / `public_official_declaration` /
`release_manifest_hash`(`--release-manifest`를 주면 그 파일의 해시) /
`operator_public_key_fingerprint` / `official_eval_pack_hash` /
`track_b_baseline_hash` / `build_wrapper_hash` / `timestamp` / `known_limitations`.
인증서는 commit-safe하며(해시·지문·정책만, 비밀/비공개 경로 없음) §9c의 릴리스
체크리스트 입력으로 쓰인다.

---

## 9b. 릴리스 매니페스트

운영자는 한 시즌이 핀한 모든 public-official 신뢰 앵커를 담은 **비밀 없는**
매니페스트를 발행할 수 있다(`bench/ceb/hosted/release_manifest.py`; 스키마
`ceb.release_manifest/v1`). 공개 리더보드가 이 매니페스트를 게시하면 누구나 해당
시즌이 쓴 앵커를 확인할 수 있다.

```bash
.venv/bin/ceb hosted release-manifest create \
    --track B \
    --eval-pack /secure/path/to/official_pack \
    --official-pack-hash sha256:... \
    --public-key /secure/ceb_ed25519.pub.pem \
    --track-b-baseline-hash sha256:... \
    --build-wrapper-hash sha256:... \
    --private-key /secure/ceb_ed25519.pem \
    --out /tmp/release_B.json
```

매니페스트는 `benchmark_version` / `git_commit` / `track` / `season` /
`official_eval_pack_id` + `_hash` + `_manifest_hash` /
`operator_public_key_fingerprint`(**절대 키 자체가 아닌 지문**) /
`engine_jail_image` + `_digest` / (Track B) `track_b_baseline_hash` +
`track_b_baseline_trust_mode`(`"hash"` — 매니페스트는 baseline을 콘텐츠 해시로
핀한다) + `track_b_build_wrapper_hash` + `build_jail_image_digest` + `bench_policy`
(`min_nps_ratio` / `enforced_when_baseline_supports_bench` /
`override_downgrades_to_diagnostic`) / `leaderboard_policy` / `known_limitations`를
담는다. **비밀이 없다**: 비공개 키, 비공개 eval-팩 경로, 숨겨진 FEN/오프닝 id,
비공개 아티팩트 경로를 일절 담지 않는다. 생성에는 **핀된 공식 팩 해시**와 **공개
키**가 필수이며, Track B는 baseline 해시와 빌드 래퍼 해시가 **정확히 하나씩**
필요하다(둘 이상이면 모호하다며 오류). 누락 시 `ReleaseManifestError`로 중단된다.

**서명과 검증(Ed25519).** 공개 배포용 매니페스트는 **서명되어야** 한다
(`bench/ceb/hosted/release_manifest.py` `sign_release_manifest` /
`verify_release_manifest`). `create`에 `--private-key`(또는 env
`CEB_SIGNING_PRIVATE_KEY`)를 주면 작성과 동시에 직접 서명하며, 둘 다 없으면
**UNSIGNED**(읽을 수는 있음)로 쓴다. 기존 매니페스트는 나중에 서명할 수 있다:

```bash
# 기존 매니페스트에 Ed25519 서명 블록 부여(서명은 서명 블록을 제외한 정규
# 매니페스트를 덮으며, 공식 결과와 동일한 방식이다)
.venv/bin/ceb hosted release-manifest sign \
    --manifest /tmp/release_B.json --private-key /secure/ceb_ed25519.pem

# out-of-band 공개 키로 진정성 검증
.venv/bin/ceb hosted release-manifest verify \
    --manifest /tmp/release_B.json --public-key /secure/ceb_ed25519.pub.pem
```

검증은 **out-of-band로 공급된 공개 키**(`--public-key`)에 대해서만 `authentic:
true`가 된다. UNSIGNED 매니페스트는 읽을 수는 있으나 결코 authentic이 아니며,
임베디드 키에 대한 검증은 내부 정합성만 증명할 뿐 진정성은 증명하지 않는다.

운영자는 이 매니페스트를 공개 GET 엔드포인트로도 서빙할 수 있다(§8의 `GET
/api/hosted/release-manifest`, `CEB_RELEASE_MANIFEST` — 서명된 JSON을 그대로
서빙한다). 결과 번들에도 서명된 매니페스트가 함께 담기며, `VERIFY.txt`는
`ceb hosted release-manifest verify --manifest release_manifest.json --public-key
<operator.pem>` 명령을 안내한다.

---

## 9c. 공개-공식 릴리스 체크리스트

운영자는 한 시즌의 신뢰 앵커를 요약한 commit-safe **체크리스트 아티팩트**를
렌더링할 수 있다(`bench/ceb/hosted/release_checklist.py`
`build_release_checklist`):

```bash
.venv/bin/ceb hosted release-checklist create \
    --track BOTH \
    --readiness-report readiness.json \
    --release-manifest /tmp/release_B.json \
    --out PUBLIC_OFFICIAL_CHECKLIST.md
```

산출물은 비밀/비공개 경로 없이 **해시·지문·정책만** 담은 Markdown이다: 벤치마크
버전, git 커밋, readiness 선언 상태, 릴리스 매니페스트 해시, 공식 eval 팩
id/hash/season, 운영자 공개 키 지문, Track B baseline 신뢰 모드/해시, 빌드 래퍼
해시, 엔진/빌드 감옥 이미지 다이제스트, 리더보드 정책, 알려진 한계, 정확한 검증
명령들, 그리고 "Do not declare official unless the readiness declaration is ready."
한 줄. 이는 **거버넌스 문서이지 보안 장벽이 아니다**(실제 게이트는 §9의 readiness
선언이다). `--readiness-report`에는 `readiness declare --json` 리포트를 준다.

---

## 10. 에이전트 궤적(선택)

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
  `verification_grade` + Track B를 추가), readiness `ceb.hosted.readiness/v2`,
  공개 readiness `ceb.hosted.readiness.public/v1`, 릴리스 매니페스트
  `ceb.release_manifest/v1`, 선언 인증서
  `ceb.hosted.declaration_certificate/v1`. 검증기는 v1 결과도 수용한다.
- **정제된 오류.** 에이전트 대면 출력(CLI, 피드백, 공개 산출물)은 숨겨진 FEN,
  수순, 오프닝 id, 호스트 경로를 절대 출력하지 않는다. 전체 운영자 트레이스백을
  보려면 `CEB_DEBUG=1`을 설정하라 — 에이전트 대면 서비스에서는 절대 쓰지 말 것.
