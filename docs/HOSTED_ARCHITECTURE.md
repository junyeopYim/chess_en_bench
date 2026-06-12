# 호스티드 아키텍처 (v0.3.4)

Track A·Track B 제출물이 어떻게 *검증된(verified)* 공식 결과가 되는지, 그리고
신뢰 경계(trust boundary)가 어디에 놓이는지 설명한다. 본 문서는 현재 코드를
기준으로 하며, 변경 이력은 `docs/RELEASE_NOTES.md`에 있다. 이 서비스는 정직하게는
**공개 공식 단일 노드 호스티드 벤치마크**다. 단일 노드(SQLite + 로컬 파일시스템)
임을 숨기지 않으며, 분산 프로덕션 서비스가 아니다.

이 리포지토리가 **"Track A와 Track B에 대한 공개 공식 단일 노드 호스티드
벤치마크 준비 완료"**라고 선언할 수 있는 것은 오직
`ceb hosted readiness check --strict-public-official`이 통과할 때뿐이다(req10).
v0.3.4의 최종 공개 공식 감사 강화로 마지막 모호함이 제거되었다: **어떤
`--dev-*` 플래그도 verified=true를 유지하지 못하며**(검증 실패시키거나 진단으로
강등), **신뢰 앵커는 실제로 검증되고**(Ed25519 키는 스캔·게이트·빌드·매치보다
먼저 로드 검증, baseline은 콘텐츠 무결성까지 확인), **준비도(readiness)가 단일
선언 게이트**다.

다른 모든 것이 떠받치는 단 하나의 불변식: **신뢰할 수 없는 엔진은 평가기
내부나 숨겨진 데이터를 절대 읽지 못하며, 검증된 점수는 오직 공식
워커(worker)만 생성한다.**

공개 공식 검증된(verified) 결과는 오직 호스티드 공식 워커(`ceb hosted worker
run-once`)가 다음을 *모두* 만족할 때만 생성한다: 깨끗한 제출 스냅샷,
**신뢰된 공식(OFFICIAL) eval pack** 그리고 그 콘텐츠 해시의 **핀(pin)**(req1,
리포지토리에 커밋된 데모 pack이 아님), 정적 스캔 통과, strict 게이트 통과,
Docker 엔진 감옥(`--engine-jail docker`), verifiable 프로파일(`official` /
`final-production`), **Ed25519 서명**, Track B의 경우 추가로 **신뢰된
baseline**(req3) + **해시 핀 빌드 래퍼**(req4) + **신뢰된 운영자 래퍼로 빌드
격리(build jail)와 검증된 빌드 산출물**(req5) + **bench/속도 정합성**(req6),
**스테이징된 산출물**에 대한 공개 산출물 누출 스캔 통과 후 승격(req7), 소유권
펜스가 걸린 원자적 DB 기록. 로컬 CLI 라운드와 직접 실행한 Track B CLI는 자가
보고(self-reported)·진단(diagnostic)이며 결코 verified가 아니다. `smoke`
프로파일은 절대 공식 리더보드에 오르지 않으며 여전히 데모 pack을 unverified로
쓴다 — 호스티드 리더보드는 verified 결과만 담는다.

## 신뢰 경계 (Trust boundary)

두 진영이 있으며, 이들은 서로 겹치지 않는다.

**평가기 컨트롤러 — 신뢰 가능, 호스트 위에서 실행.** 이것이 하니스(harness)다.
게이트, 라운드 러너, 오라클, 채점, eval-pack 로딩, 스캐너, 호스티드
파이프라인, 서명을 담당한다. *비공개* eval pack과 상대 풀(opponent pool)을
읽고, 매치를 실행하며, 공개·비공개 산출물(artifact)을 모두 작성한다. 평범한
호스트 프로세스로 실행되며, 어떤 부분도 샌드박스화되지 않는다.

**엔진 감옥(engine jail) — 신뢰 불가, 워크스페이스 전용.** 제출물의 UCI
엔진만이 유일하게 격리되는 대상이다. `--engine-jail docker` 아래에서는
*자기 자신의 워크스페이스 외에는 아무것도 보지 못하는* 컨테이너 안에서
실행되며, 워크스페이스는 `/submission`에 읽기 전용으로 마운트된다. 리포지토리,
eval pack, 상대, 다른 실행 어느 것도 보이지 않는다. 엔진은 stdin/stdout으로
UCI를 주고받으며, 그것이 세상에 대한 엔진의 전부다.

eval pack은 호스트 측에 머문다. 숨겨진 포지션은 `position fen ...` UCI 라인의
형태로만 격리된 엔진에 도달한다 — pack 디렉터리는 절대 마운트되지 않는다. 이
때문에 비공개 pack은 감옥과 안전하게 결합되며(`--eval-pack`은
`--engine-jail docker`와 함께 동작한다), `--eval-pack`을 여전히 거부하는
레거시 `--sandbox docker` 모드(컨테이너 안의 하니스)와 대비된다.

```
                         HOST  (trusted)                 │  JAIL (untrusted)
                                                         │
  private eval pack ──▶ evaluator controller            │
  opponents.py      ──▶  (gate, oracle, scoring,         │
                          round runner, signing)         │
                              │     ▲                     │
              position fen …  │     │  bestmove …         │
                  (UCI line)  ▼     │  (UCI line)         │
                          ┌─────────────────┐  stdin/out ┌──────────────────┐
                          │ engine_command  │ ─────────▶ │ docker run -i     │
                          │ (jail front-end)│ ◀───────── │  submission/engine│
                          └─────────────────┘            │  /submission (ro) │
                                                         │  --network none   │
   public artifacts ◀── feedback.json, report.public,    │  --read-only      │
   private artifacts ◀── report.json, match_vs_*, games  │  cpu/mem/pids cap │
                                                         │  non-root, nnp    │
```

감옥 이미지(`infra/docker/engine_jail.Dockerfile`,
`chess-en-bench-jail:0.4`, `scripts/build_jail_image.sh`로 빌드)는
`python:3.12-slim` 위에 `build-essential`(gcc/g++/make) + bash + python3를 올린
빌드 툴체인으로, 의도적으로 `ceb` 패키지를 설치하지 **않는다**. 따라서 감옥 안의
적대적 엔진조차 평가기 코드를 import할 수 없다. Docker 플래그: `--network none
--read-only --tmpfs /tmp --cpus 1 --memory 1g --pids-limit 128 --security-opt
no-new-privileges`, 비루트(`--user <host-uid:gid>`), UCI용 `-i`. `:` 또는 개행을
포함하는 워크스페이스 경로는 거부되며, `/`를 포함하는 `engine_name`도 거부된다.
Docker가 없거나 이미지가 없으면 조치 가능한 `EngineJailError`가 발생한다.

**언어 정책과 감옥 내 빌드.** 호스티드 Track A는 `build.sh`가 감옥 내 툴체인만으로
`/submission/engine` 실행 파일을 만드는 어떤 언어든 허용한다(네트워크 없음,
from scratch). 빌드 단계에서는 `/submission`이 쓰기 가능하고, 엔진 실행 시에는
읽기 전용이며, 항상 `--network none`이다. 소스 전용 C++ 예제는
`examples/submissions/minimal_uci_engine_cpp`(`engine.cpp` + `build.sh`)로, 감옥과
게이트가 평가 시 `./engine`을 컴파일한다.

## 평가 프로파일과 검증 등급

*프로파일(profile)*은 (1) 평가가 쓰는 라운드 모드(매치 설정)와 (2) 결과가
검증(verified)되어 공식 리더보드에 오를 자격이 있는지를 결정하는 단일 진실
원천이며, 워커·DB·API·문서가 이를 공유한다. (`bench/ceb/hosted/profiles.py`,
`tracks/a_from_scratch/eval_profiles.yaml`)

| 프로파일 | 라운드 모드 | tier | verifiable | 검증 등급(`verification_grade`) |
| --- | --- | --- | --- | --- |
| `smoke` | `official_round`(tiny config) | diagnostic | 아니오 | `diagnostic-smoke` |
| `official` | `official_round` | official | 예 | `verified-official` |
| `final-production` | `final_production` | final | 예 | `verified-final-production` |
| `final-eval`(레거시) | `final_eval` | final | 예 | `verified-final-eval` |

- `smoke`는 CI·플러밍용 진단 프로파일이다. `verifiable=false`이므로 어떤
  플래그를 줘도 절대 verified가 아니고 리더보드에서 제외되며, tiny 매치
  설정(`QUICK_TEST_MODE_CONFIG`)으로 감옥 없이 실행된다("magic verified"는 없다).
- `official`은 표준 `official_round`를 실행한다.
- `final-production`은 프로덕션 규모 `final_production` 라운드 모드(6상대 x
  336게임 = 2016게임, paired openings, movetime 1000ms — `scoring.yaml`의
  `round_modes.final_production` / `DEFAULT_ROUND_MODES`)이며, 리더보드가
  `official`보다 선호한다. CI는 절대 이 기본값으로 돌지 않는다(테스트는 tiny
  override).
- **어떤 `--dev-*` 플래그도 verified=true를 유지하지 못한다(item1).** DEV 강등
  플래그는 verifiable 프로파일을 강제로 `verified=false`로 만들어 리더보드에서
  제외하며, 각각 진단 등급을 남긴다(`bench/ceb/hosted/profiles.py`):
  `--dev-allow-unjailed`(`diagnostic-unjailed`),
  `--dev-allow-unsigned`(`diagnostic-unsigned`),
  `--dev-allow-demo-pack`로 통과한 데모 pack(`diagnostic-untrusted-pack`),
  `--dev-allow-unpinned-pack`(핀되지 않은 pack, `diagnostic-unpinned-pack`),
  `--dev-allow-toy-baseline`(신뢰되지 않은 Track B baseline,
  `diagnostic-untrusted-baseline`),
  `--dev-allow-unpinned-wrapper`(핀되지 않은 빌드 래퍼,
  `diagnostic-untrusted-wrapper`),
  `--dev-allow-no-bench`(bench 정합성 실패, `diagnostic-no-bench`).
  특히 verified Track B의 bench/속도 정합성이 실패할 때 `--dev-allow-no-bench`는
  검증을 **우회(bypass)하지 않는다 — `verified=false` +
  `diagnostic-no-bench`로 강등한다**(`official_pipeline.py`의 `run_official_track_b`:
  `verified = False; verification_grade = GRADE_DIAGNOSTIC_NO_BENCH`). 플래그가
  없으면 hard-fail이라 결과 자체가 없다. 실패한 bench는 결코 리더보드에 오르지
  못한다.

프로파일이 `verifiable`인 것은 verified 결과의 **필요조건이지 충분조건이 아니다**:
워커는 여전히 비공개·**신뢰된 공식** eval pack과 그 **해시 핀**(A/req1), 정적
스캔, strict 게이트, Docker 엔진 감옥, **Ed25519 서명**(B), Track B의 경우
**신뢰된 baseline**(req3) + **해시 핀 빌드 래퍼**(req4) + **빌드 격리·검증된
산출물**(C/req5) + **bench 정합성**(req6), STAGED 누출 스캔 후 승격(D/req7)을 모두
강제한다. `profile`과 `verification_grade`는 결과 JSON과 DB `results` 행에 함께
저장된다.

## 데이터 흐름: 하나의 호스티드 공식 평가

```
  submit ──▶ snapshot + tree-hash ──▶ queue job (official_eval | track_b_official_eval)
                                          │
                                          ▼
                       worker.run_once  (claim_next_job: atomic queued→running)
                                          │  ┌─ kind=track_b_official_eval ─▶ run_hosted_track_b
                                          ▼  │
                    ┌─────────── official_eval ───────────┐
                    │ require PRIVATE eval pack            │
                    │ engine-jail guard (verifiable→docker)│
                    │ (A) TRUSTED official eval pack guard │
                    │ (B) Ed25519 key LOAD-validated       │
                    │ static scan (deny on fail)          │
                    │ strict gate vs PRIVATE pack (jail)   │
                    │ (D) public artifacts written STAGED  │
                    │ leak scan over STAGED set; refuse    │
                    │ metadata + Ed25519 signature         │
                    │ (D) promote STAGED → public          │
                    └──────────────┬──────────────────────┘
                                   ▼
                       verified result recorded
                                   │
                                   ▼
                       verified-only leaderboard
```

1. **제출(Submit).** Track A는 `ceb hosted submit`(또는 `POST
   /runs/{id}/submissions`, 또는 `--archive` 안전 업로드)로 활성 워크스페이스를
   변경 불가능한 스냅샷으로 복사하며, 심볼릭 링크와 일반 파일이 아닌 항목을
   거부하고 결정론적 트리 해시를 계산한다. 워커는 오직 스냅샷만 평가하므로, 제출
   이후의 수정이나 심볼릭 링크 트릭은 채점 대상을 바꿀 수 없다.
   (`hosted/submissions.py`) Track B는 `ceb hosted submit-track-b
   --candidate-src --baseline-src --run-id --db`(`--build-script`,
   `--engine-relpath` 포함)로 candidate·baseline 두 트리를 각각 스냅샷·해시하여
   `track_b_submissions`에 기록한다.
2. **큐(Queue).** 작업 행이 큐에 등록된다 — Track A는 `official_eval`,
   Track B는 `track_b_official_eval`. (`hosted/db.py`, `hosted/models.py`의
   `JOB_KIND_TRACK_A` / `JOB_KIND_TRACK_B`)
3. **워커(Worker).** `ceb hosted worker run-once`는 `claim_next_job`으로 가장
   오래된 클레임 가능한 작업을 **원자적으로** 꺼내(아래 "잡 수명주기" 참조) 잡
   종류로 분기한다. Track A는 `run_official_eval`, Track B는 `run_hosted_track_b`를
   호출한다. (`hosted/worker.py`, `hosted/official_eval.py`,
   `hosted/track_b_eval.py`) 공식 워커는 `verified: true` 결과를 만드는 *유일한*
   생산자다. Track A 파이프라인은:
   - 비공개 eval pack을 요구한다. 없으면 거부한다(공개 데이터만으로는 검증 안 함).
   - 엔진 감옥 가드(P0.1): verifiable 프로파일은 `engine_jail == docker`여야
     verified가 된다. 아니면 평가 전에 거부하거나(기본), `--dev-allow-unjailed`로
     `diagnostic-unjailed`로 강등한다.
   - **(A/req1) 신뢰된 + 핀된 공식 eval pack 가드**: verified가 될 결과는
     *공식(OFFICIAL)* pack을 요구한다 — manifest 검증 + 비데모 경로. 나아가 pack
     콘텐츠 해시가 **핀(pin)**되어야 한다: `--official-pack-hash`(반복/콤마),
     `CEB_OFFICIAL_EVAL_PACK_HASHES`, `--official-pack-registry`로 제공된
     허용목록에 있어야 한다. 허용목록이 없으면 평가 전에 검증을 거부하며,
     `--dev-allow-unpinned-pack`만이 이를 `verified=false`(등급
     `diagnostic-unpinned-pack`)로 강등한다. 커밋된 데모 pack은 절대 verified될
     수 없다(`eval_pack_trust.py`).
   - **(B/item3) Ed25519 서명 키 로드 검증**: verified가 될 결과는 Ed25519
     개인키를 요구하며, 그 키는 정적 스캔·strict 게이트·빌드·매치보다 **먼저**
     `require_ed25519_private_key`(`signing.py`)로 해석 *및 로드 검증*된다.
     키가 없으면(`--signing-key` / `CEB_SIGNING_PRIVATE_KEY` 미설정) 평가 전에
     거부하거나 `--dev-allow-unsigned`로 `verified=false` + `diagnostic-unsigned`로
     강등한다. **형식이 깨진(malformed) 키는 정제된 메시지와 함께 조기에
     hard-fail**하므로, 서명 단계에서의 실패로 인해 스테이징된 공개 산출물이
     남는 일이 없다. 검증된 키 경로는 서명 시점에 그대로 재사용된다. (A)·(B)
     둘 다 어떤 평가 작업보다 **먼저** 실패한다. HMAC/unsigned는 진단 전용이다.
   - 정적 부정행위 방지 스캔을 실행한다. `fail` 발견 시 중단한다.
   - 비공개 pack에 대해 **strict** 게이트와 매치를 엔진 감옥 안에서 실행한다.
   - **(D) 공개 대상 산출물을 STAGED로 작성한다**(가시성은 private이고
     `staged_public` 마커가 붙어 아무도 제공하지 않음). 어떤 것도 스캔 전에
     공개되지 않는다.
   - STAGED 집합에 대해 공개 산출물 누출 스캔(P0.8)을 실행한다
     (`scan_public_artifacts(..., staged=True)`). 비공개 pack 비밀이 새면 검증을
     거부하며, 이때 공개 매니페스트 항목이 존재하지 않으므로 워커는 아무것도
     공개하지 않는다.
   - 재현성 메타데이터와 Ed25519 서명을 첨부한다. 방어적으로, verified 결과의
     `signature.algorithm`이 `ed25519`가 아니면 거부한다.
   - 누출 스캔 통과 후에만 STAGED 산출물을 `visibility: public`으로 **승격**한다.
   - 검증된 결과를 `profile` / `verification_grade`와 함께 소유권 펜스가 걸린
     `record_result_if_owned`로 기록하고 각 산출물의 가시성을 등록한다.

   비공개/신뢰된 eval pack이 없거나, 감옥이 docker가 아니거나, Ed25519 키가
   없거나, 스캔이 실패하거나, strict 게이트가 실패하거나, 누출이 탐지되면 워커는
   **검증을 거부한다** — 검증된 결과가 기록되지 않는다. 어떤 실패든 작업은 정제된
   공개 사유와 함께 `failed`로 표시되며, 전체 세부 정보는 비공개 로그에만 남는다.
4. **리더보드(Leaderboard).** `db.verified_leaderboard(track=...)`는 검증된
   결과만 순위화하며, 실행별로 단일 best verified 결과를 공유 선택자
   `select_best_verified_result`로 고른다(아래 "공유 결과 선택자" 참조).
   `smoke`/진단 결과는 verified가 아니므로 결코 나타나지 않는다. 자가 보고된
   로컬 CLI 라운드는 `verified: false`를 지니며 이 경로에 절대 도달하지 않는다.

재현성 메타데이터(`hosted/metadata.py`)는 다음을 기록한다:
`benchmark_version`(0.3.4), `git_commit`, `evaluator_image_digest`,
`engine_jail_image_digest`, `eval_pack_id`, `eval_pack_hash`(pack 디렉터리의
sha256), `opponent_pool_hash`(`opponents.py`의 sha256), `opening_suite_hash`,
`hardware`(cpu_model/cpu_cores/memory_limit), `software`
(python/platform/compiler/fastchess/`stockfish_baseline: sf_18/cb3d4ee`),
`random_seed`, `verified`. verified 결과는 신뢰 팩 메타데이터도 함께 기록한다:
`eval_pack_trusted: true`, `eval_pack_manifest_hash`, `eval_pack_track`,
`eval_pack_season`(그리고 `eval_pack_id`는 신뢰 보고서의 `pack_id`로 갱신).
로컬에서 확정할 수 없는 필드는 명시적으로 `null`이며, 조용히 누락되지 않는다.

## 구성 요소

| 개념 | 모듈 | 하는 일 |
| --- | --- | --- |
| 엔진 감옥 프런트엔드 | `bench/ceb/jail/engine_jail.py` | 감옥 모드(`none`/`docker`)를 해석; Docker/이미지가 없으면 `EngineJailError` |
| Docker 감옥 백엔드 | `bench/ceb/jail/docker_engine.py` | `docker run` argv 구성, 워크스페이스 경로 / 엔진 이름 검증, 잔류 프로세스 회수 |
| 정적 스캐너 (Track A) | `bench/ceb/scan/static_scan.py` | 외부 체스 라이브러리, 엔진, 네트워크, subprocess, 하니스 핑거프린팅, 과대 파일, book/tablebase/NNUE, 바이너리, 심볼릭 링크 탈출 |
| Track B 스캐너 | `bench/ceb/scan/track_b_scan.py` | diff 화이트리스트 + 바이너리/NNUE 페이로드 + 핑거프린팅 + 네트워크/프로세스 + tablebase + 심볼릭 링크 |
| 산출물 가시성 | `bench/ceb/storage/artifacts.py` | `artifacts_manifest.json`; `public_artifacts()`는 기본 거부(deny-by-default) |
| 정제된 오류 | `bench/ceb/sanitize.py` | `SanitizedError(public, private)`; 공개 텍스트에서 FEN/수순/경로를 차단 |
| 호스티드 DB | `bench/ceb/hosted/db.py` | SQLite 테이블(runs, submissions, track_b_submissions, jobs, results, artifacts); `claim_next_job`, `select_best_verified_result`, `verified_leaderboard` |
| 평가 프로파일 | `bench/ceb/hosted/profiles.py` | 프로파일·검증 등급·결과 tier의 단일 진실 원천 |
| 스키마/잡 종류 | `bench/ceb/hosted/models.py` | v2 스키마 문자열, `JOB_KIND_TRACK_A`/`JOB_KIND_TRACK_B` |
| 제출 스냅샷 | `bench/ceb/hosted/submissions.py` | 워크스페이스 복사, 심볼릭 링크 거부, 트리 해시 |
| 안전 업로드 | `bench/ceb/hosted/upload.py` | `safe_extract_archive`: 심볼릭/하드 링크, 절대 경로, 경로 탐색, 과대 파일 거부 |
| 공식 워커 | `bench/ceb/hosted/worker.py` | 작업 하나를 원자적으로 클레임·분기(Track A/B)하고, 소유권 펜스(`record_result_if_owned`)로 검증된 결과 + 산출물 가시성을 기록 |
| Track A 평가 파이프라인 | `bench/ceb/hosted/official_eval.py` | 비공개 pack → jail guard → (A/req1) 신뢰+핀된 팩 guard → (B/item3) Ed25519 키 **로드 검증** → scan → strict gate → STAGED artifacts → 누출 스캔 → metadata+sign → promote; 전제 조건 실패 시 검증 거부 |
| Track B 평가 파이프라인 | `bench/ceb/hosted/track_b_eval.py` | `run_hosted_track_b`: source-first 파이프라인 + jail guard + 핀된 pack(req1) + baseline 신뢰(req3) + 핀된 래퍼(req4) + 빌드 격리·산출물 검증(req5) + bench 정합성(req6) + Ed25519 서명 + 누출 스캔/승격(req7) → delta Elo 결과 |
| 신뢰 팩 정책 (A/req1) | `bench/ceb/hosted/eval_pack_trust.py` | `validate_official_eval_pack`: 공식 manifest(`ceb.eval_pack.manifest/v1`) + 비데모 경로 + 해시 허용목록(`resolve_hash_allowlist`); 핀 안 되면 verified 거부 |
| Track B baseline 신뢰 (req3/item2) | `bench/ceb/track_b/baseline_trust.py` | `validate_track_b_baseline`: stockfish-lock(HEAD가 `stockfish.lock` 커밋과 일치 **+** `git_worktree_clean` **+** `git_submodules_clean`) / hash 허용목록 / toy 중 하나로 신뢰; `baseline_tree_hash` 콘텐츠 해시 기록 |
| 빌드 감옥 + 산출물 검증 (C/req5) | `bench/ceb/track_b/build_jail.py` | `build_in_jail`: 신뢰 래퍼로 Docker 빌드 감옥 안에서 baseline·candidate 빌드; `validate_build_output`이 엔진·심볼릭 링크·크기·파일 수 검증 |
| 빌드 래퍼 정책 (C/req4) | `bench/ceb/hosted/build_wrappers.py` | `validate_build_wrapper`(candidate/baseline 트리 밖의 정규 파일) + `compute_wrapper_hash`/`resolve_wrapper_hashes`(해시 핀); `write_demo_wrapper` |
| bench/속도 정합성 (req6) | `bench/ceb/track_b/bench_sanity.py` | `run_bench_sanity`: 두 엔진 bench 실행, nodes/nps/output_hash + nps_ratio 기록; 둘 다 bench 지원 시에만 NPS-비율 임계 강제 |
| 스테이징/승격 (D/req7) | `bench/ceb/storage/promotion.py` | 공개 대상 산출물을 STAGED로 작성하고, 누출 스캔 통과 후에만 public으로 승격 |
| 릴리스 매니페스트 (req9/items5,7) | `bench/ceb/hosted/release_manifest.py` | `build_release_manifest`: 시즌별 신뢰 앵커를 핀하는 비밀 없는 `ceb.release_manifest/v1`(공개키는 핑거프린트만); Track B는 `track_b_baseline_trust_mode`("hash")와 `bench_policy`도 포함 |
| 공식 준비도 (req10/item4) | `bench/ceb/hosted/readiness.py` | `readiness_check`: `--strict-public-official`에서 핀/공개키/키쌍/baseline/래퍼 해시 앵커를 차단(blocking)으로; `public_official_declaration` + `blocking_failures` 선언; `--track BOTH` 지원; `ceb.hosted.readiness/v2`(버전 플로어 0.3.4) |
| 재현 메타데이터 | `bench/ceb/hosted/metadata.py` | 버전, git 커밋, 이미지 다이제스트, 콘텐츠 해시, 하드웨어/소프트웨어, 시드 |
| 서명 | `bench/ceb/hosted/signing.py` | Ed25519(공개키) > HMAC-SHA256(`CEB_SIGNING_KEY`, 레거시) > unsigned; verified는 Ed25519 강제; `require_ed25519_private_key`가 평가 전 키를 로드 검증(malformed→hard-fail) |
| 누출 스캐너 | `bench/ceb/scan/leak_scan.py` | `scan_public_artifacts(..., staged=)`: 공개(또는 STAGED) 산출물에 비공개 pack 비밀이 새는지 검사 |
| 검증기 | `bench/ceb/hosted/verifier.py` | 서명 + 스키마 + 메타데이터 완전성 판정; v1 결과도 수용 |
| 결과 번들 내보내기 (item7) | `bench/ceb/hosted/result_bundle.py` | 선택된 verified 결과의 공개 산출물만 담은 zip(`VERIFY.txt` + `bundle_manifest.json`); 선택적으로 `release_manifest.json` + 운영자 공개키 핑거프린트 포함; 비공개/admin 없음 |
| 호스티드 API (item6) | `bench/ceb/api/main.py` | 관리자 게이트가 적용된 POST(상수 시간 토큰 비교), 공개 전용 GET; 공개로 표시된 산출물만 제공; 공개 `GET /api/hosted/release-manifest` |
| 라운드 러너 | `bench/ceb/rounds/round_runner.py` | quick / official_round / final_eval / final_production; `engine_command`를 호출하는 신뢰된 매치 루프 |

## 잡 수명주기와 원자적 클레임 (P0.5)

여러 워커가 같은 작업을 두 번 처리하지 않도록 큐 전이는 원자적이다.
(`bench/ceb/hosted/db.py`)

- `claim_next_job(conn, worker_id, lease_seconds)`는 `BEGIN IMMEDIATE`로 쓰기
  락을 먼저 잡은 뒤 가장 오래된 클레임 가능한 작업을 `queued → running`으로
  원자적으로 전이한다. 두 워커가 경합하면 한쪽만 전이에 성공하고, 다른 쪽은
  클레임 가능한 행을 보지 못한다. 워커는 (비원자적 peek인 `next_queued_job`이
  아니라) 항상 이 함수를 쓴다.
- 클레임 시 `worker_id` / `started_at` / `lease_expires_at`이 기록되고
  `attempt_count`가 증가한다.
- **lease 회수(stale recovery).** `lease_seconds`가 설정된 클레임의 lease가
  만료된 채 `running`에 머무는 작업은 다시 클레임 가능해져 다른 워커가 회수한다.
- `finish_job(conn, job_id, status, detail, public_detail)`은 비공개
  `detail`(운영자용)과 정제된 `public_detail`(에이전트 안전)을 모두 저장하고
  `lease_expires_at`을 비운다.
- DB 연결은 autocommit(`isolation_level=None`) + `busy_timeout` + WAL 모드로
  열린다.

## 공유 결과 선택자 (P0.4)

한 실행(run)이 여러 verified 결과를 가질 수 있으므로, "이 실행의 점수"는 단일
선택자 `select_best_verified_result`로 결정한다. (`bench/ceb/hosted/db.py`)

- 실행별 단일 best verified 결과를 고른다. final-tier(`final_production` /
  `final_eval` / `track_b_official`)를 official-tier(`official_round` / 레거시
  `official`)보다 선호하고, 같은 tier 안에서는 최고 점수를 고른다.
- `smoke`/진단 결과는 verified가 아니므로 절대 선택되지 않는다.
- 리더보드(`verified_leaderboard`), `ceb hosted result show`, `GET
  /api/hosted/runs/{id}/official-result`가 모두 이 선택자를 쓰므로 세 경로의
  답이 항상 일치한다.
- tier 매핑은 `profiles.result_tier`가 결과 행의 `mode`로부터 계산한다.

## DB 스키마 (v2)

SQLite 테이블(`bench/ceb/hosted/db.py`). `migrate()`가 기존 DB에 누락된
테이블·컬럼을 데이터 손실 없이 가산적으로 추가하므로 옛 호스티드 DB도 계속
동작한다.

- `runs` — `run_id`, `track`, `status`, `created_at`.
- `submissions` — Track A 스냅샷: `snapshot_path`, `tree_hash`.
- `track_b_submissions` — Track B 제출: `candidate_snapshot` /
  `baseline_snapshot`, `candidate_hash` / `baseline_hash`, `build_script`,
  `engine_relpath`.
- `jobs` — `kind`(`official_eval` | `track_b_official_eval`), `status`,
  비공개 `detail` + 정제된 `public_detail`, `worker_id`, `started_at`,
  `finished_at`, `lease_expires_at`, `attempt_count`.
- `results` — `verified`, `mode`, `profile`, `verification_grade`, `track`,
  `score`, `result_path`.
- `artifacts` — `artifact_id`, `path`, `visibility`.

## 산출물 가시성 (Artifact visibility)

모든 산출물 디렉터리에는 각 파일의 가시성을 기록한 `artifacts_manifest.json`이
들어 있다. `public_artifacts()`는 *명시적으로* 공개로 표시된 파일만 반환한다 —
목록에 없는 것은 모두 비공개로 취급된다(기본 거부). 한 라운드의 경우:

- **공개:** `feedback.json`, `report.public.json`(스키마
  `ceb.round.report.public/v1`, 자가 보고 실행은 `verified: false`,
  비공개 pack은 `opening_ids`가 null; 워크스페이스/호스트 경로와 숨겨진 오프닝
  id를 생략). 호스티드 `official_result.json`
  (`ceb.hosted.official_result/v2`)과 워커가 작성하는 최상위 `feedback.json`도
  공개다.
- **비공개:** `report.json`, `match_vs_*.json`, `games_vs_*.txt`,
  `gate_report.json`, `scan_report.json`, `leak_scan.json` — 시작 FEN, 수순
  목록, 게임 텍스트, 숨겨진 데이터에 대한 게이트 세부 정보, 누출 스캔(비밀은
  echo하지 않고 해시만 기록).

워커는 각 파일의 가시성을 DB에 등록하여 API가 이를 제공할 수 있게 한다.

## 서명과 검증

`sign_official_result`은 정규(canonical) JSON 직렬화에 대해 Ed25519 > HMAC >
unsigned 순으로 서명한다(`private_key_path=`로 명시 지정 가능). Ed25519
개인키(`CEB_SIGNING_PRIVATE_KEY` 또는 `--signing-key`)가 설정되면 **공개키**
서명을 붙여 키 없는 제3자도 검증할 수 있다(`hosted` extra의 `cryptography` 사용).
그렇지 않고 `CEB_SIGNING_KEY`만 있으면 **대칭** HMAC-SHA256을 붙이며, 이는 동일
키를 가진 운영자만 검증할 수 있는 내부용이다. 어느 키도 없으면 결과는
`signature.status = "unsigned"`로 기록되며 암호학적 진정성을 주장하지 않는다.

**(B) 공개 공식 verified는 Ed25519를 요구한다.** verified가 될 결과는 반드시
Ed25519 서명되어야 한다. Ed25519 키가 없는 verifiable 프로파일은 평가 전에
검증을 거부하며, `--dev-allow-unsigned`만이 이를 `verified=false`(등급
`diagnostic-unsigned`)로 강제한다. `official_eval`은 verified 결과의
`signature.algorithm == "ed25519"`를 단언하고, HMAC 결과는 **결코** 공개 공식
verified가 될 수 없다(HMAC은 레거시/진단으로 남는다). 검증기(`verify_result_file`)는
Ed25519가 아닌 verified 결과에 `authentic=false`를 설정하며(필드
`public_official_signing`), `authentic`이 되려면 외부(out-of-band)에서 **공급된**
공개키가 필요하다 — 결과에 임베드된 키만 있으면 서명 신뢰는
`embedded-self-described`이고 `authentic`은 false다(req2). 키 생성·서명·검증
세부는 `docs/RESULT_SIGNING.md`를 참조한다.
(`hosted/signing.py`, `hosted/verifier.py`)

**(req2) 공개키 + 키쌍 일치.** strict 준비도(아래)는 로드 가능한 Ed25519
개인키뿐 아니라 로드 가능한 **공개키**, 그리고 둘의 **키쌍 일치**까지 요구한다 —
`public_key_fingerprint(private.public_key())`가 공급된 공개키의 핑거프린트와
같아야 하며, 보고서에 공개키 핑거프린트가 담긴다(`readiness.py`의 `_key_checks`).
공개 리더보드는 운영자 공개키 핑거프린트와 배포 경로를 공표하여, 제3자가
out-of-band 공개키로 `authentic=true`를 직접 확인할 수 있게 한다.

## Track B 호스티드 (P0.6)

Track B(고정 Stockfish 위에 소스 패치를 얹는 트랙)도 호스티드 워커를 거쳐 검증된
delta Elo 결과를 낼 수 있다. (`bench/ceb/hosted/track_b_eval.py`,
`bench/ceb/track_b/official_pipeline.py`)

- 제출은 `ceb hosted submit-track-b --candidate-src --baseline-src --run-id --db`
  (`--build-script`, `--engine-relpath` 포함)로 하며, candidate·baseline 두
  소스 트리를 각각 스냅샷·해시하여 `track_b_submissions`에 기록하고
  `track_b_official_eval` 잡을 큐에 넣는다.
- 워커는 잡 종류로 분기하여 `run_hosted_track_b`를 호출한다. 결과는
  `mode=track_b_official`, 점수는 final delta Elo이며 `verified_leaderboard(track="B")`로
  순위화된다.
- **verified Track B 요건:** source-first 파이프라인의 보장(diff 화이트리스트 +
  콘텐츠 스캔)에 더해 verifiable 프로파일(`official` / `final-production`),
  **신뢰된 + 핀된 공식 오프닝 팩(A/req1)**, candidate 엔진 Docker 감옥(P0.1),
  **Ed25519 키(B)**, **신뢰된 baseline(req3)**, **해시 핀 빌드 래퍼(req4)**,
  **빌드 격리와 검증된 빌드 산출물(C/req5)**, **bench/속도 정합성(req6)**, STAGED
  산출물에 대한 공개 산출물 누출 스캔과 승격(D/req7), 서명이 모두 필요하다.
  신뢰되지 않은 앵커는 각각 hard-fail하거나(결과 없음) 해당 DEV 플래그로
  진단(`verified=false`)으로 강등되며, **첫 번째** 신뢰되지 않은 앵커가 등급을
  결정한다(`track_b_eval.py`의 `gate`). `smoke`이거나 어떤 DEV 강등 플래그라도
  쓰이면 리더보드에 오르지 않는다. 매치 규모는 프로파일 tier별로 다르다
  (`diagnostic`은 2게임, `official`은 200, `final`은 1000).
- **(req3/item2) baseline 콘텐츠 무결성.** verified baseline은 세 신뢰 모드 중
  하나여야 한다: *stockfish-lock*, *hash*(`--track-b-baseline-hash` /
  `CEB_TRACK_B_BASELINE_HASHES` / `--track-b-baseline-registry` 허용목록),
  *toy*(`--dev-allow-toy-baseline`은 `verified=false`, 등급
  `diagnostic-untrusted-baseline`). **stockfish-lock 모드는 단순히 HEAD가
  `tracks/b_stockfish_opt/stockfish.lock` 커밋과 일치하는 것만으로는 부족하다**:
  추가로 작업 트리가 깨끗하고(`git_worktree_clean`: `git status --porcelain`이
  비어 untracked 파일도 없음) 서브모듈이 깨끗해야(`git_submodules_clean`) 하며,
  콘텐츠 해시(`baseline_tree_hash`)를 기록한다. 더럽거나 untracked가 있는
  체크아웃은 stockfish-lock으로 신뢰되지 않고 hash 모드로 떨어지거나 실패한다.
  hash 모드(허용목록 콘텐츠 해시)는 `.git` 없이 스냅샷된 baseline에도 동작한다.
  메타데이터의 `track_b`에 `baseline_trusted`, `baseline_trust_mode`,
  `baseline_tree_hash`, `stockfish_lock`이 기록된다(`baseline_trust.py`).
- **(req4) 빌드 래퍼 해시 핀.** verified Track B는 래퍼 *파일 해시*가 핀되어야
  한다: `--build-wrapper-hash` / `CEB_TRACK_B_BUILD_WRAPPER_HASHES` /
  `--build-wrapper-registry`. 아니면 `--dev-allow-unpinned-wrapper`로
  `verified=false`(등급 `diagnostic-untrusted-wrapper`). 메타데이터에
  `build_wrapper_hash`, `build_wrapper_trusted`, `build_isolation`,
  `build_jail_image_digest`가 기록된다(`build_wrappers.py`).
- **(req5) 빌드 산출물 강화.** 감옥 빌드 후 `validate_build_output`은 엔진이
  존재·실행 가능·정규 파일(심볼릭 링크 아님)이고, 산출물 트리 어디에도 심볼릭
  링크가 없으며, 총 크기가 512 MiB 이하이고 파일 수가 10000개 이하임을 강제한다.
  산출물 트리 해시가 메타데이터 `track_b.build_output`에 기록된다(`build_jail.py`).
- **(req6/item1) bench/속도 정합성.** verified Track B는 두 엔진을 모두 bench로
  돌려 엔진별 nodes/nps/output_hash와 `nps_ratio`를 보고서에 기록한다. NPS-비율
  임계(`--bench-min-nps-ratio`, 기본 0.3)는 **두 엔진이 모두 bench를 지원할
  때만** 강제된다(토이 엔진은 `supported=false`로 허용; 후보는 jailing 시 bench도
  감옥에서 실행). bench가 실패하고 `--dev-allow-no-bench`가 주어지면 검증을
  우회하지 않고 `verified=false` + `diagnostic-no-bench`로 **강등**하며, 플래그가
  없으면 hard-fail이다 — 실패한 bench는 결코 verified가 아니다. 실제 공개
  Track B는 bench를 지원하는 고정 Stockfish가 필요하다(`bench_sanity.py`).

**(C) 빌드 격리 — 후보 빌드 스크립트는 호스트에서 절대 실행하지 않는다.** verified
Track B는 후보 소유 빌드 스크립트를 호스트에서 실행하지 않는다. 대신 **신뢰된
운영자 빌드 래퍼**(candidate/baseline 트리 *밖*의 파일; 워커에 `--build-wrapper`로
전달)가 *같은 래퍼*로 baseline과 candidate 둘 다 Docker 빌드 감옥 안에서 빌드한다
(`build_jail.py`의 `build_in_jail`). 소스는 `/src`에 **읽기 전용**, 쓰기 가능한
`/out`, 래퍼는 `/wrapper.sh`에 읽기 전용으로 마운트되고, `--network none`,
read-only root + tmpfs, cpu/mem/pids 제한, 비루트이며 리포지토리·eval pack은
어느 것도 마운트되지 않는다. 래퍼 계약:
`/wrapper.sh <source_ro> <out_writable> <engine_relpath>`. 빌드 감옥 이미지는
기본으로 엔진 감옥 이미지(`chess-en-bench-jail:0.4`, gcc/g++/make/bash/python3
포함)를 재사용하며, `infra/docker/track_b_build_jail.Dockerfile` +
`scripts/build_track_b_build_image.sh`로 전용 이미지(`chess-en-bench-build-jail:0.4`)를
빌드할 수도 있다. 이후 candidate 엔진은 매치를 위해 엔진 감옥에서 실행된다.
진단 CLI 경로(`ceb track-b official run`)는 호스트 빌드를 유지하며 **항상**
`verified=false`다 — `run_official_track_b`는 `build_isolation="host"`로
`verified=True`를 거부한다. 결과/메타데이터는 `build_isolation`(`"jail"` |
`"host"`)을 기록한다. 신뢰된 빌드 래퍼는 후보가 아니라 **워커**에 공급되며,
`write_demo_wrapper`가 테스트·로컬 진단용 데모 래퍼를 제공한다.

## 릴리스 매니페스트 (req9/items5,7)

`ceb hosted release-manifest create --track --eval-pack --official-pack-hash
--public-key [--track-b-baseline-hash --build-wrapper-hash] --out`는 한 시즌의
모든 공개 공식 신뢰 앵커를 핀하는 **비밀 없는** `ceb.release_manifest/v1`을
내보낸다(`bench/ceb/hosted/release_manifest.py`). 담기는 것: `benchmark_version`,
`git_commit`, `track`, `season`, 공식 pack의 `official_eval_pack_id` /
`official_eval_pack_hash` / `official_eval_pack_manifest_hash`,
`operator_public_key_fingerprint`(**키 자체는 절대 담지 않음**, 핑거프린트만),
`engine_jail_image`와 그 다이제스트, Track B의 경우 `track_b_baseline_hash` /
`track_b_build_wrapper_hash` / `build_jail_image_digest`, 그리고 새로
`track_b_baseline_trust_mode`(`"hash"` — 매니페스트는 baseline을 콘텐츠 해시로
핀)와 `bench_policy`(`min_nps_ratio`, `enforced_when_baseline_supports_bench`,
`override_downgrades_to_diagnostic`), `leaderboard_policy`, `known_limitations`.
**비밀이 없도록 구성된다**: 개인키도, 비공개 eval-pack 경로도, 숨겨진 FEN/오프닝
id도, 비공개 산출물 경로도 담지 않는다. 생성에는 **핀된 공식 pack 해시와 공개키**가
필수이며, Track B는 추가로 baseline 해시 하나·빌드 래퍼 해시 하나가 필수다(둘 이상
설정되면 모호하므로 오류). 공개 리더보드가 이 매니페스트를 공표하여 누구나 시즌이
사용한 앵커를 확인할 수 있다.

## 공식 준비도 — 단일 선언 게이트 (req10/item4)

`ceb hosted readiness check --strict-public-official`은 배포가 공개 공식 준비
완료인지 보고하며, 이것이 **공개 공식 준비 완료를 선언하는 단일 게이트**다
(`bench/ceb/hosted/readiness.py`, 스키마 `ceb.hosted.readiness/v2`, 버전 플로어
**0.3.4**). `--strict-public-official`이 켜지면 핀 / 공개키 / 키쌍 일치 /
baseline / 래퍼 해시 앵커가 경고가 아니라 **차단(blocking, required)** 체크가
된다. JSON 보고서는 `checks[name, ok, required, detail]`와 `ready`(모든 required
체크가 통과해야 true)에 더해 **`public_official_declaration`**(`"ready"` |
`"not-ready"`)과 **`blocking_failures`**(실패한 required 체크 이름 목록)를 담는다.
`--track BOTH`는 Track A 팩 체크와 모든 Track B 체크를 함께 돌린다. CLI `--json`
플래그는 **JSON만** 출력하여(기계 파싱용 깔끔한 출력) ready면 0, 아니면 2를
반환한다.

**Track A strict**가 요구하는 것: 버전 0.3.4 이상, DB 마이그레이션됨, docker,
엔진 감옥 이미지, 신뢰된 + **핀된** 공식 eval pack, 데모 pack 거부, Ed25519 개인키,
공개키, **키쌍 일치**, smoke가 verifiable이 아님, `official`/`final-production`이
verifiable, final-production 게임 플로어 충족(설정상 6상대 x 336 = 2016게임;
체크 임계는 2000). **Track B strict**는 여기에 더해: 빌드 감옥 이미지, 빌드 래퍼
존재·실행 가능·후보/baseline 트리 밖·해시 핀, baseline 신뢰(콘텐츠 해시 핀 또는
깨끗한 stockfish-lock), bench 정책(강제되며 우회 불가 — 실패한 bench나
`--dev-allow-no-bench`는 강등할 뿐 verified가 되지 않는다), Track B 호스티드 API
엔드포인트 import 가능을 요구한다.

## 정제된 오류 처리 (Sanitized error handling)

숨겨진 데이터를 인용할 가능성이 있는 모든 것은 공개 메시지와 비공개 메시지를
함께 지닌다(`SanitizedError`). `sanitize_exception()`은 공개 텍스트를
반환하거나, 알 수 없는 예외 유형의 경우 고정 문자열 *"internal error (<Type>);
details withheld — operators can rerun with CEB_DEBUG=1"*를 반환한다(임의의
메시지는 FEN을 포함할 수 있기 때문이다). 숨겨진 eval-pack 로드 오류는 파일
basename + 행 id + "content withheld"만 인용하며 — FEN, 수순, 경로는 절대 인용하지
않는다. CLI `main()`은 모든 것을 잡아내 정제된 한 줄을 출력하고, 0이 아닌
값(알 수 없는 경우 3)을 반환하며, `CEB_DEBUG=1`일 때만 전체 트레이스백을 다시
던진다. (`bench/ceb/sanitize.py`, `bench/ceb/cli.py`)

## 호스티드 API 표면

`bench/ceb/api/main.py`(`server` extra 필요). DB 경로는 `CEB_HOSTED_DB`에서,
없으면 `runs/hosted.sqlite`에서 가져온다.

- **관리자 게이트 POST**(`X-CEB-Admin-Token`이 `CEB_ADMIN_TOKEN`과 같아야 함;
  토큰 미설정 → 503, 잘못된 토큰 → 403; 토큰 비교는 **상수 시간**
  `hmac.compare_digest`): `POST /api/hosted/runs`, `/runs/{id}/submissions`,
  `/runs/{id}/upload`(아카이브 안전 추출, `upload.py`의 `safe_extract_archive`),
  `/runs/{id}/jobs`.
- **공개 GET:** `/api/hosted/runs/{id}`, `/runs/{id}/feedback`,
  `/runs/{id}/official-result`(공유 선택자 사용),
  `/api/hosted/leaderboard?track=A`(또는 `B`, 검증 전용),
  `/artifacts/{id}`(DB 가시성이 `public`인 산출물만 제공; 비공개/알 수 없음 →
  404, 경로 순회 → 400/404). `/health`는 변경 없음.
- **(item6) 공개 릴리스 매니페스트 GET:** `GET /api/hosted/release-manifest`는
  `CEB_RELEASE_MANIFEST` 경로의 매니페스트를 제공한다(미설정 → 503, 파일 없음 →
  404). 공개 GET이라 **admin 토큰이 필요 없으며**, 매니페스트는 구성상 비밀이
  없다(`release-manifest create`로 생성).
- **req8 추가 공개 GET:** `GET /api/leaderboard?track=B`는 호스티드 DB가 있으면
  verified 호스티드 Track B 리더보드(`verified_leaderboard(track="B")`)에
  위임하고, 없으면 `GET /api/hosted/leaderboard?track=B`를 가리킨다. 비밀이 없는
  새 엔드포인트 `GET /api/hosted/readiness/public`은 버전·리더보드 정책·프로파일
  verifiability만 노출한다(스키마 `ceb.hosted.readiness.public/v1`; 운영자 전용
  앵커는 CLI `readiness check`에서만 확인). Track B 제출은 서버 로컬
  candidate_src/baseline_src 기반의 `POST
  /api/hosted/runs/{run_id}/track-b-submissions`로 받으며, API를 통한 Track B
  아카이브 업로드는 향후 과제다. 관리자 POST/업로드 엔드포인트는
  `CEB_ADMIN_TOKEN`이 설정되지 않으면 503으로 남고, 스트리밍 업로드는 변경 없다.

## 결과 번들 내보내기 (item7)

`ceb hosted result export --run-id <id> --db <db> --out <zip>
[--release-manifest <path>] [--public-key <pem> | --public-key-fingerprint <fp>]`는
**선택된 best verified 결과**(리더보드·API가 제공하는 그 결과)의 공개 산출물만
담은 zip을 만든다(`bench/ceb/hosted/result_bundle.py`). v0.3.4에서는 번들에
운영자 **릴리스 매니페스트**(`release_manifest.json`)와 **운영자 공개키
핑거프린트**를 함께 담을 수 있으며, `VERIFY.txt`는 out-of-band 공개키 / 릴리스
매니페스트 핑거프린트로 검증하는 방법을 안내한다. 번들은 여전히 비선택
smoke/진단 결과와 모든 비공개 산출물(스캔·누출 보고서, 매치 로그)을 제외하며,
개인키나 숨겨진 pack 데이터는 결코 담지 않는다(`bundle_manifest.json`의
`schema` = `ceb.hosted.result_bundle/v1`, `version` = `v0.3.4`).

## 실행하기

```bash
# Build the engine jail image (once)
bash scripts/build_jail_image.sh

# Track A hosted pipeline end to end (SQLite + local object store)
ceb hosted init   --db runs/hosted.sqlite
ceb hosted submit --track A \
    --workspace examples/submissions/minimal_uci_engine_python \
    --run-id demo --db runs/hosted.sqlite
ceb hosted worker run-once --db runs/hosted.sqlite \
    --eval-pack <official-pack> --official-pack-hash <sha256:...> \
    --engine-jail docker --signing-key <ed25519-private.pem> \
    --profile final-production                              # leaderboard-quality verified
ceb hosted result show   --run-id demo --db runs/hosted.sqlite
ceb hosted leaderboard   --db runs/hosted.sqlite --track A
ceb hosted result export --run-id demo --db runs/hosted.sqlite --out demo_bundle.zip \
    --release-manifest release_A_2026s1.json --public-key operator.pem   # bundle + season anchors

# Track B (source-first patch on pinned Stockfish)
ceb hosted submit-track-b --candidate-src <cand> --baseline-src <base> \
    --run-id demoB --db runs/hosted.sqlite
ceb hosted worker run-once --db runs/hosted.sqlite \
    --eval-pack <official-pack> --official-pack-hash <sha256:...> \
    --engine-jail docker --profile official \
    --signing-key <ed25519-private.pem> --build-wrapper <trusted-wrapper.sh> \
    --build-wrapper-hash <sha256:...> --track-b-baseline-hash <sha256:...>

# Sign / verify a result (see docs/RESULT_SIGNING.md for key setup)
ceb hosted sign-result   --result <official_result.json>
ceb hosted verify-result --result <official_result.json> --public-key <operator.pem>

# Declare public-official readiness (strict gates all v0.3.4 anchors)
ceb hosted readiness check --db runs/hosted.sqlite --track BOTH \
    --eval-pack <official-pack> --official-pack-hash <sha256:...> \
    --signing-key <ed25519-private.pem> --public-key <operator.pem> \
    --strict-public-official --json

# Emit a secret-free public release manifest for a season
ceb hosted release-manifest create --track A --eval-pack <official-pack> \
    --official-pack-hash <sha256:...> --public-key <operator.pem> \
    --out release_A_2026s1.json
```

Stockfish나 Docker 없이 CI/스모크를 돌리려면 워커에 `--profile smoke`(레거시
별칭 `--quick-test-mode`)를 쓴다. tiny 토이 설정으로 감옥 없이 돌고 결과는
`config_profile: quick-test`로 기록되며 절대 verified가 아니다. 여러 워커를 함께
돌릴 때는 각 워커에 `--worker-id`와 `--lease-seconds`를 주어 원자적 클레임과
lease 회수를 활성화한다. 워커는 신뢰 앵커 허용목록(`--official-pack-hash`
(반복/콤마)·`--official-pack-registry`, Track B의 `--track-b-baseline-hash`·
`--build-wrapper-hash`와 각 `*-registry`)과 DEV 우회 플래그(`--dev-allow-demo-pack`은
(A)의 경로 검사만 우회, `--dev-allow-unpinned-pack`, `--dev-allow-toy-baseline`,
`--dev-allow-unpinned-wrapper`, `--dev-allow-no-bench`, `--dev-allow-unsigned`,
`--dev-allow-unjailed`)도 받는다. 배포 시에는
자체 본문 크기 제한을 가진 리버스 프록시(예: nginx `client_max_body_size`) 뒤에
두며, 업로드 엔드포인트는 본문을 임시 파일로 스트리밍하면서 200 MiB
(`_MAX_UPLOAD_BYTES`)를 강제한다.

## 단일 노드 이음새: 정직하게 남는 한계

코드와 신뢰 앵커는 공개 공식 준비를 갖추지만(strict 준비도 통과 시), 백엔드는
의도적으로 단일 노드(SQLite + 로컬 파일시스템)이며 분산 프로덕션 서비스가 아니다.
정직하게 남는 이음새(seam):

- **SQLite + 로컬 파일시스템 백엔드.** 상태는 하나의 SQLite 파일
  (`hosted/db.py`, WAL 모드)과 그 옆의 `<db>_store/` 객체 디렉터리에 존재한다.
  같은 호스트의 여러 워커는 원자적 클레임으로 안전하게 큐를 비우지만, 네트워크
  스토리지도 복제도 없다. 실제 배포를 위해서는 `hosted/db.py`와
  `hosted/submissions.py`(스냅샷 스토리지)가 실제 데이터베이스 및 객체 스토어로
  교체되는 지점이다.
- **호출당 한 작업 워커.** `worker.run_once`는 호출당 정확히 하나의 작업을
  `claim_next_job`으로 원자적으로 클레임·처리한다. 원자적 클레임과 lease
  회수(P0.5)는 같은 DB를 가리키는 여러 워커를 허용하지만, 분산 큐나 수평 확장은
  외부 오케스트레이션(예: 워커를 반복 호출)에 맡긴다.
- **서명.** 공개 공식 verified는 Ed25519(공개키)를 요구하며 HMAC은 레거시/진단
  전용이다(위 참조). 운영자는 공개 검증을 위해 Ed25519 키를 배포한다
  (`docs/RESULT_SIGNING.md`).
- **Track B baseline·래퍼·bench.** 빌드 격리(C/req5) 배선은 존재하며 토이 트리로
  테스트된다(verified 경로는 `CEB_DOCKER_TESTS=1`로 Docker opt-in). 운영자가
  공급하는 것은 실제 고정 Stockfish를 빌드하는 신뢰된 래퍼 *내용*과, 공식 pack·
  baseline·래퍼 해시 허용목록뿐이다. 실제 공개 Track B의 bench/속도 정합성(req6)은
  bench를 지원하는 고정 Stockfish를 필요로 한다(토이 엔진은 bench를 지원하지 않아
  NPS 임계가 적용되지 않는다).

인터페이스(DB 접근자, 스냅샷+해시, 원자적 잡 클레임, 워커 `run_once`, 산출물
가시성)는 안정적이며, 그 뒤의 스토리지 및 실행 백엔드가 실제 서비스가 교체할
대상이다.
