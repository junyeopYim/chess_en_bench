# 호스티드 아키텍처 (v0.3)

Track A 제출물이 어떻게 *검증된(verified)* 공식 결과가 되는지, 그리고 신뢰
경계(trust boundary)가 어디에 놓이는지 설명한다. 본 문서는 현재 코드를 기준으로
하며, 변경 이력은 `docs/RELEASE_NOTES.md`에 있다.

다른 모든 것이 떠받치는 단 하나의 불변식: **신뢰할 수 없는 엔진은 평가기
내부나 숨겨진 데이터를 절대 읽지 못하며, 검증된 점수는 오직 공식
워커(worker)만 생성한다.**

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
`chess-en-bench-jail:0.3`, `scripts/build_jail_image.sh`로 빌드)는 순수한
Python+bash 런타임으로, 의도적으로 `ceb` 패키지를 설치하지 **않는다**. 따라서
감옥 안의 적대적 엔진조차 평가기 코드를 import할 수 없다. Docker
플래그: `--network none --read-only --tmpfs /tmp --cpus 1 --memory 1g
--pids-limit 128 --security-opt no-new-privileges`, 비루트
(`--user <host-uid:gid>`), UCI용 `-i`. `:` 또는 개행을 포함하는 워크스페이스
경로는 거부되며, `/`를 포함하는 `engine_name`도 거부된다. Docker가 없거나
이미지가 없으면 조치 가능한 `EngineJailError`가 발생한다.

## 데이터 흐름: 하나의 호스티드 공식 평가

```
  submit ──▶ snapshot + tree-hash ──▶ queue job
                                          │
                                          ▼
                          worker.run_once  (drains oldest job)
                                          │
                                          ▼
                    ┌─────────── official_eval ───────────┐
                    │ static scan (deny on fail)          │
                    │ strict gate vs PRIVATE pack         │
                    │ official_round | final_eval         │
                    │   (matches, engine jail optional)   │
                    │ artifacts: public / private split   │
                    │ metadata + HMAC signature           │
                    └──────────────┬──────────────────────┘
                                   ▼
                       verified result recorded
                                   │
                                   ▼
                       verified-only leaderboard
```

1. **제출(Submit).** `ceb hosted submit`(또는 `POST /runs/{id}/submissions`)는
   활성 워크스페이스를 변경 불가능한 스냅샷으로 복사하며, 심볼릭 링크와 일반
   파일이 아닌 항목을 거부하고 결정론적 트리 해시를 계산한다. 워커는 오직
   스냅샷만 평가하므로, 제출 이후의 수정이나 심볼릭 링크 트릭은 채점 대상을
   바꿀 수 없다. (`hosted/submissions.py`)
2. **큐(Queue).** `official_eval` 작업 행이 큐에 등록된다. (`hosted/db.py`)
3. **워커(Worker).** `ceb hosted worker run-once`는 가장 오래된 대기 작업을
   꺼내 `run_official_eval`을 호출한다. (`hosted/worker.py`,
   `hosted/official_eval.py`)
   공식 워커는 `verified: true` 결과를 만드는 *유일한* 생산자다. 워커는:
   - 정적 부정행위 방지 스캔을 실행한다. `fail` 발견 시 중단한다.
   - 비공개 eval pack에 대해 **strict** 게이트를 실행한다.
   - `official_round`(또는 `--final-eval`과 함께 `final_eval`)를 실행하며,
     엔진은 선택적으로 `--engine-jail docker`로 격리한다.
   - 산출물을 공개와 비공개로 분리한다(가시성 매니페스트).
   - 재현성 메타데이터와 HMAC 서명을 첨부한다.
   - 검증된 결과를 기록하고 각 산출물의 가시성을 등록한다.

   비공개 eval pack이 없거나, 스캔이 실패하거나, strict 게이트가 실패하면
   워커는 **검증을 거부한다** — 검증된 결과가 기록되지 않는다. 어떤 실패든
   작업은 정제된 공개 사유와 함께 `failed`로 표시되며, 전체 세부 정보는 비공개
   로그에만 남는다.
4. **리더보드(Leaderboard).** `db.verified_leaderboard`는 검증된 결과만
   순위화한다: 실행별 최고 `final_eval`, 없으면 최고 `official_round`.
   `quick` 라운드는 절대 검증되지 않으므로 결코 나타나지 않는다. 자가 보고된
   로컬 CLI 라운드는 `verified: false`를 지니며 이 경로에 절대 도달하지 않는다.

재현성 메타데이터(`hosted/metadata.py`)는 다음을 기록한다:
`benchmark_version`(0.3.0), `git_commit`, `evaluator_image_digest`,
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
| 호스티드 DB | `bench/ceb/hosted/db.py` | SQLite 테이블(runs, submissions, jobs, results, artifacts); `verified_leaderboard` |
| 제출 스냅샷 | `bench/ceb/hosted/submissions.py` | 워크스페이스 복사, 심볼릭 링크 거부, 트리 해시 |
| 공식 워커 | `bench/ceb/hosted/worker.py` | 대기 작업 하나를 처리하고, 검증된 결과 + 산출물 가시성을 기록 |
| 공식 평가 파이프라인 | `bench/ceb/hosted/official_eval.py` | scan → strict gate → round/final → artifacts → metadata+sign; 전제 조건 실패 시 검증 거부 |
| 재현 메타데이터 | `bench/ceb/hosted/metadata.py` | 버전, git 커밋, 이미지 다이제스트, 콘텐츠 해시, 하드웨어/소프트웨어, 시드 |
| 서명 | `bench/ceb/hosted/signing.py` | `CEB_SIGNING_KEY`로 키잉된 HMAC-SHA256; 키가 없으면 미서명 |
| 검증기 | `bench/ceb/hosted/verifier.py` | 서명 + 스키마 + 메타데이터 완전성 판정 |
| 호스티드 API | `bench/ceb/api/main.py` | 관리자 게이트가 적용된 POST, 공개 전용 GET; 공개로 표시된 산출물만 제공 |
| 라운드 러너 | `bench/ceb/rounds/round_runner.py` | quick / official_round / final_eval; `engine_command`를 호출하는 신뢰된 매치 루프 |

## 산출물 가시성 (Artifact visibility)

모든 산출물 디렉터리에는 각 파일의 가시성을 기록한 `artifacts_manifest.json`이
들어 있다. `public_artifacts()`는 *명시적으로* 공개로 표시된 파일만 반환한다 —
목록에 없는 것은 모두 비공개로 취급된다(기본 거부). 한 라운드의 경우:

- **공개:** `feedback.json`, `report.public.json`(스키마
  `ceb.round.report.public/v1`, 자가 보고 실행은 `verified: false`,
  비공개 pack은 `opening_ids`가 null; 워크스페이스/호스트 경로와 숨겨진 오프닝
  id를 생략). 호스티드 `official_result.json`
  (`ceb.hosted.official_result/v1`)과 워커가 작성하는 최상위 `feedback.json`도
  공개다.
- **비공개:** `report.json`, `match_vs_*.json`, `games_vs_*.txt`,
  `gate_report.json`, `scan_report.json` — 시작 FEN, 수순 목록, 게임 텍스트,
  숨겨진 데이터에 대한 게이트 세부 정보.

워커는 각 파일의 가시성을 DB에 등록하여 API가 이를 제공할 수 있게 한다.

## 서명과 검증

서명은 정규(canonical) JSON 직렬화에 대한 **대칭(symmetric)** HMAC-SHA256이며,
`CEB_SIGNING_KEY`로 키잉된다. 이는 동일한 키를 보유한 누구(운영자)에게나 결과를
인증해 준다. 이것은 공개키 증명(attestation)이 **아니다** — 키가 없는 제3자는
검증할 수 없다. 키가 없으면 결과는 `signature.status = "unsigned"`와 암호학적
진정성이 없다는 안내와 함께 기록되며, `verify_result`는
`(False, "unsigned ...")`를 반환한다. 변조된 결과나 잘못된 키는 서명 불일치를
낳는다. (`hosted/signing.py`, `hosted/verifier.py`)

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
  `/runs/{id}/submissions`, `/runs/{id}/jobs`.
- **공개 GET:** `/api/hosted/runs/{id}`, `/runs/{id}/feedback`,
  `/runs/{id}/official-result`, `/leaderboard?track=A`(검증 전용),
  `/artifacts/{id}`(DB 가시성이 `public`인 산출물만 제공; 비공개/알 수 없음 →
  404, 경로 순회 → 400/404). `/health`는 변경 없음.

## 실행하기

```bash
# Build the engine jail image (once)
bash scripts/build_jail_image.sh

# Hosted pipeline end to end (SQLite + local object store)
ceb hosted init   --db runs/hosted.sqlite
ceb hosted submit --track A \
    --workspace examples/submissions/minimal_uci_engine_python \
    --run-id demo --db runs/hosted.sqlite
ceb hosted worker run-once --db runs/hosted.sqlite \
    --eval-pack <private-pack> --engine-jail docker        # add --final-eval for leaderboard quality
ceb hosted result show --run-id demo --db runs/hosted.sqlite
ceb hosted leaderboard --db runs/hosted.sqlite --track A

# Sign / verify a result (needs CEB_SIGNING_KEY set to verify authenticity)
ceb hosted sign-result   --result <official_result.json>
ceb hosted verify-result --result <official_result.json>
```

Stockfish나 Docker 없이 CI/스모크를 돌리려면 워커에 `--quick-test-mode`를
추가한다(아주 작은 토이 프로파일이며 `config_profile: quick-test`로 기록된다).

## MVP 이음새: 이것이 실제 서비스가 되는 지점

호스티드 파이프라인은 MVP이며 프로덕션 서비스가 아니다. 두 이음새(seam)에 대해
정직하게 짚는다:

- **SQLite + 로컬 파일시스템 백엔드.** 상태는 하나의 SQLite 파일
  (`hosted/db.py`)과 그 옆의 `<db>_store/` 객체 디렉터리에 존재한다. 네트워크
  스토리지도, 복제도, 동시 쓰기에 대한 대책도 없다. 실제 배포를 위해서는
  `hosted/db.py`와 `hosted/submissions.py`(스냅샷 스토리지)가 실제 데이터베이스
  및 객체 스토어로 교체되는 지점이다.
- **단일 노드, 단일 작업 워커.** `worker.run_once`는 호출당 정확히 하나의 대기
  작업을 동일 프로세스 내에서 처리한다. 분산 큐도, 리스/재시도도, 수평 확장도
  없다. DB `jobs` 테이블과 `next_queued_job`이 실제 큐로 가는 이음새다.
- **제출 수집.** API는 서버 로컬 워크스페이스 경로를 받는다. 파일 업로드는 향후
  작업이다.
- **서명.** 대칭 HMAC만 지원(위 참조); 비대칭 공개키 증명은 향후 작업이다.

인터페이스(DB 접근자, 스냅샷+해시, 워커 `run_once`, 산출물 가시성)는 안정적이며,
그 뒤의 스토리지 및 실행 백엔드가 실제 서비스가 교체할 대상이다.
