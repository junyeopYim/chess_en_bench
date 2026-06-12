# 호스티드 아키텍처 (v0.3.1)

Track A·Track B 제출물이 어떻게 *검증된(verified)* 공식 결과가 되는지, 그리고
신뢰 경계(trust boundary)가 어디에 놓이는지 설명한다. 본 문서는 현재 코드를
기준으로 하며, 변경 이력은 `docs/RELEASE_NOTES.md`에 있다.

다른 모든 것이 떠받치는 단 하나의 불변식: **신뢰할 수 없는 엔진은 평가기
내부나 숨겨진 데이터를 절대 읽지 못하며, 검증된 점수는 오직 공식
워커(worker)만 생성한다.**

검증된(verified) 결과는 오직 호스티드 공식 워커(`ceb hosted worker run-once`)가
다음을 *모두* 만족할 때만 생성한다: 깨끗한 제출 스냅샷, 비공개 eval pack,
정적 스캔 통과, strict 게이트 통과, Docker 엔진 감옥(`--engine-jail docker`),
verifiable 프로파일(`official` / `final-production`), 서명, 공개 산출물 누출
스캔 통과. 로컬 CLI 라운드와 직접 실행한 Track B CLI는 자가
보고(self-reported)·진단(diagnostic)이며 결코 verified가 아니다. `smoke`
프로파일은 절대 공식 리더보드에 오르지 않는다 — 호스티드 리더보드는 verified
결과만 담는다.

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
- `--dev-allow-unjailed`로 verifiable 프로파일을 감옥 없이 돌리면 결과가 강제로
  `verified=false` + 등급 `diagnostic-unjailed`가 되어 리더보드에 절대 오르지
  않는다.

프로파일이 `verifiable`인 것은 verified 결과의 **필요조건이지 충분조건이 아니다**:
워커는 여전히 비공개 eval pack, 정적 스캔, strict 게이트, Docker 엔진 감옥, 서명,
누출 스캔을 모두 강제한다. `profile`과 `verification_grade`는 결과 JSON과 DB
`results` 행에 함께 저장된다.

## 데이터 흐름: 하나의 호스티드 공식 평가

```
  submit ──▶ snapshot + tree-hash ──▶ queue job (official_eval | track_b_official_eval)
                                          │
                                          ▼
                       worker.run_once  (claim_next_job: atomic queued→running)
                                          │  ┌─ kind=track_b_official_eval ─▶ run_hosted_track_b
                                          ▼  │
                    ┌─────────── official_eval ───────────┐
                    │ engine-jail guard (verifiable→docker)│
                    │ require PRIVATE eval pack            │
                    │ static scan (deny on fail)          │
                    │ strict gate vs PRIVATE pack         │
                    │ profile round mode (matches, jail)   │
                    │ artifacts: public / private split   │
                    │ public-artifact leak scan (P0.8)    │
                    │ metadata + Ed25519/HMAC signature   │
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
   - 엔진 감옥 가드(P0.1): verifiable 프로파일은 `engine_jail == docker`여야
     verified가 된다. 아니면 평가 전에 거부하거나(기본), `--dev-allow-unjailed`로
     `diagnostic-unjailed`로 강등한다.
   - 비공개 eval pack을 요구한다. 없으면 거부한다(공개 데이터만으로는 검증 안 함).
   - 정적 부정행위 방지 스캔을 실행한다. `fail` 발견 시 중단한다.
   - 비공개 eval pack에 대해 **strict** 게이트를 실행한다.
   - 프로파일의 라운드 모드(`smoke`는 tiny, 그 외는 설정값)를 엔진 감옥 안에서
     실행한다.
   - 산출물을 공개와 비공개로 분리한다(가시성 매니페스트).
   - 공개 산출물 누출 스캔(P0.8)을 실행한다. 비공개 pack 비밀이 새면 검증을
     거부한다.
   - 재현성 메타데이터와 서명(Ed25519 > HMAC > unsigned)을 첨부한다.
   - 검증된 결과를 `profile` / `verification_grade`와 함께 기록하고 각 산출물의
     가시성을 등록한다.

   비공개 eval pack이 없거나, 감옥이 docker가 아니거나, 스캔이 실패하거나, strict
   게이트가 실패하거나, 누출이 탐지되면 워커는 **검증을 거부한다** — 검증된 결과가
   기록되지 않는다. 어떤 실패든 작업은 정제된 공개 사유와 함께 `failed`로
   표시되며, 전체 세부 정보는 비공개 로그에만 남는다.
4. **리더보드(Leaderboard).** `db.verified_leaderboard(track=...)`는 검증된
   결과만 순위화하며, 실행별로 단일 best verified 결과를 공유 선택자
   `select_best_verified_result`로 고른다(아래 "공유 결과 선택자" 참조).
   `smoke`/진단 결과는 verified가 아니므로 결코 나타나지 않는다. 자가 보고된
   로컬 CLI 라운드는 `verified: false`를 지니며 이 경로에 절대 도달하지 않는다.

재현성 메타데이터(`hosted/metadata.py`)는 다음을 기록한다:
`benchmark_version`(0.3.1), `git_commit`, `evaluator_image_digest`,
`engine_jail_image_digest`, `eval_pack_id`, `eval_pack_hash`(pack 디렉터리의
sha256), `opponent_pool_hash`(`opponents.py`의 sha256), `opening_suite_hash`,
`hardware`(cpu_model/cpu_cores/memory_limit), `software`
(python/platform/compiler/fastchess/`stockfish_baseline: sf_18/cb3d4ee`),
`random_seed`, `verified`. 로컬에서 확정할 수 없는 필드는 명시적으로 `null`이며,
조용히 누락되지 않는다.

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
| 공식 워커 | `bench/ceb/hosted/worker.py` | 작업 하나를 원자적으로 클레임·분기(Track A/B)하고, 검증된 결과 + 산출물 가시성을 기록 |
| Track A 평가 파이프라인 | `bench/ceb/hosted/official_eval.py` | jail guard → 비공개 pack → scan → strict gate → round → artifacts → leak scan → metadata+sign; 전제 조건 실패 시 검증 거부 |
| Track B 평가 파이프라인 | `bench/ceb/hosted/track_b_eval.py` | `run_hosted_track_b`: source-first 파이프라인 + jail guard + 누출 스캔 + 서명 → delta Elo 결과 |
| 재현 메타데이터 | `bench/ceb/hosted/metadata.py` | 버전, git 커밋, 이미지 다이제스트, 콘텐츠 해시, 하드웨어/소프트웨어, 시드 |
| 서명 | `bench/ceb/hosted/signing.py` | Ed25519(공개키) > HMAC-SHA256(`CEB_SIGNING_KEY`, 레거시) > unsigned |
| 누출 스캐너 | `bench/ceb/scan/leak_scan.py` | `scan_public_artifacts`: 공개 산출물에 비공개 pack 비밀이 새는지 검사 |
| 검증기 | `bench/ceb/hosted/verifier.py` | 서명 + 스키마 + 메타데이터 완전성 판정; v1 결과도 수용 |
| 결과 번들 내보내기 | `bench/ceb/hosted/result_bundle.py` | 공개 산출물만 담은 zip(`VERIFY.txt` + `bundle_manifest.json`; 비공개/admin 없음) |
| 호스티드 API | `bench/ceb/api/main.py` | 관리자 게이트가 적용된 POST, 공개 전용 GET; 공개로 표시된 산출물만 제공 |
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
unsigned 순으로 서명한다. Ed25519 개인키(`CEB_SIGNING_PRIVATE_KEY`)가 설정되면
**공개키** 서명을 붙여 키 없는 제3자도 검증할 수 있다(`hosted` extra의
`cryptography` 사용). 그렇지 않고 `CEB_SIGNING_KEY`만 있으면 **대칭** HMAC-SHA256을
붙이며, 이는 동일 키를 가진 운영자만 검증할 수 있는 내부용이다. 어느 키도 없으면
결과는 `signature.status = "unsigned"`로 기록되며 암호학적 진정성을 주장하지
않는다 — `verify_result`는 `(False, "unsigned ...")`를 반환한다. 변조된 결과나
잘못된 키는 서명 불일치를 낳는다. 키 생성·서명·검증 세부는
`docs/RESULT_SIGNING.md`를 참조한다. (`hosted/signing.py`, `hosted/verifier.py`)

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
  콘텐츠 스캔 + baseline·candidate 동일 빌드 스크립트)에 더해 verifiable
  프로파일(`official` / `final-production`), 비공개/공식 오프닝 팩, candidate
  엔진 Docker 감옥(P0.1), 공개 산출물 누출 스캔(P0.8), 서명이 모두 필요하다.
  `smoke`이거나 `--dev-allow-unjailed`이면 `verified=false` 진단 결과가 되어
  리더보드에 오르지 않는다. 매치 규모는 프로파일 tier별로 다르다(`smoke`는 tiny,
  프로덕션은 신뢰구간을 좁힐 만큼 충분한 게임). 실제 고정 Stockfish 빌드 래퍼
  배선은 운영자 단계다.

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
  토큰 미설정 → 503, 잘못된 토큰 → 403): `POST /api/hosted/runs`,
  `/runs/{id}/submissions`, `/runs/{id}/upload`(아카이브 안전 추출,
  `upload.py`의 `safe_extract_archive`), `/runs/{id}/jobs`.
- **공개 GET:** `/api/hosted/runs/{id}`, `/runs/{id}/feedback`,
  `/runs/{id}/official-result`(공유 선택자 사용), `/leaderboard?track=A`(또는
  `B`, 검증 전용), `/artifacts/{id}`(DB 가시성이 `public`인 산출물만 제공;
  비공개/알 수 없음 → 404, 경로 순회 → 400/404). `/health`는 변경 없음.

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
    --eval-pack <private-pack> --engine-jail docker \
    --profile final-production                              # leaderboard-quality verified
ceb hosted result show   --run-id demo --db runs/hosted.sqlite
ceb hosted leaderboard   --db runs/hosted.sqlite --track A
ceb hosted result export --run-id demo --db runs/hosted.sqlite --out demo_bundle.zip

# Track B (source-first patch on pinned Stockfish)
ceb hosted submit-track-b --candidate-src <cand> --baseline-src <base> \
    --run-id demoB --db runs/hosted.sqlite
ceb hosted worker run-once --db runs/hosted.sqlite \
    --eval-pack <private-pack> --engine-jail docker --profile official

# Sign / verify a result (see docs/RESULT_SIGNING.md for key setup)
ceb hosted sign-result   --result <official_result.json>
ceb hosted verify-result --result <official_result.json>
```

Stockfish나 Docker 없이 CI/스모크를 돌리려면 워커에 `--profile smoke`(레거시
별칭 `--quick-test-mode`)를 쓴다. tiny 토이 설정으로 감옥 없이 돌고 결과는
`config_profile: quick-test`로 기록되며 절대 verified가 아니다. 여러 워커를 함께
돌릴 때는 각 워커에 `--worker-id`와 `--lease-seconds`를 주어 원자적 클레임과
lease 회수를 활성화한다.

## MVP 이음새: 이것이 실제 서비스가 되는 지점

호스티드 파이프라인은 MVP이며 프로덕션 서비스가 아니다. 남은 이음새(seam)를
정직하게 짚는다:

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
- **서명.** Ed25519(공개키)와 HMAC(운영자) 모두 지원(위 참조). 운영자는
  공개 검증을 위해 Ed25519 키를 배포한다(`docs/RESULT_SIGNING.md`).
- **Track B 빌드 래퍼.** 호스티드 Track B 파이프라인은 토이 트리로 테스트되며
  (verified 경로는 `CEB_DOCKER_TESTS=1`로 Docker opt-in), 실제 고정 Stockfish
  빌드 래퍼 배선은 운영자 단계다.

인터페이스(DB 접근자, 스냅샷+해시, 원자적 잡 클레임, 워커 `run_once`, 산출물
가시성)는 안정적이며, 그 뒤의 스토리지 및 실행 백엔드가 실제 서비스가 교체할
대상이다.
