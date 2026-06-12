# 보안 모델 (v0.3.1)

chess_en_bench는 직접 작성하지 않은 코드를 평가한다. 두 트랙 모두 신뢰할 수
없는 제출물을 받는다. Track A 엔진(과 그 `build.sh`)과 Track B 후보 패치는
평가 대상인 LLM 에이전트가 생성한다. 이 문서는 호스팅된 공식 벤치마크의 정식
신뢰 모델이다. 무엇을 방어하는지, 엔진 감옥(engine jail)이 이를 어떻게
집행하는지, 그리고 — 명시적으로 — 아직 집행하지 *않는* 것이 무엇인지를 다룬다.

운영자 관점의 "이걸 어떻게 안전하게 실행하는가" 가이드는
[security.md](security.md)를 참고한다. 이 문서는 그 가이드 뒤에 있는 *이유*에
해당한다. 공식 결과 서명의 세부는 [RESULT_SIGNING.md](RESULT_SIGNING.md)를
참고한다.

## 신뢰 경계

- **평가자(evaluator)는 신뢰된다.** 호스트에서 실행되며 숨겨진 팩을 읽고,
  채점하고, 매치를 구동하고, 결과에 서명한다.
- **제출물(엔진/패치)은 불신된다.** 단순히 버그가 있는 것이 아니라 능동적으로
  적대적이라고 가정한다. 신뢰할 수 없는 코드는 엔진 감옥 안에 격리되어 실행되며,
  평가자 측에는 절대 닿지 못한다.

## 위협

공격자는 밑바닥부터 좋은 체스를 두는 것 이외의 모든 수단으로 벤치마크에서
이기려는 신뢰할 수 없는 제출물이다.

- **신뢰할 수 없는 엔진 코드 (Track A).** UCI를 말하는 임의의 네이티브 또는
  인터프리터 프로그램이다. 숨겨진 eval 팩, 상대 엔진, 또는 평가자 소스를 읽으려
  하거나, 더 강한 엔진이나 온라인 오라클을 다운로드하려고 네트워크에
  접근하거나, 프로세스를 생성하거나, CPU/메모리/디스크를 고갈시키거나, I/O를
  멈추게 하거나 범람시키거나, 하네스 프로세스로 탈출하려 할 수 있다.
- **신뢰할 수 없는 Track B 패치.** 고정된 Stockfish 베이스라인에 대한 소스
  diff로, NNUE/북/테이블베이스 페이로드, 네트워크 또는 프로세스 시스템 콜,
  하네스 핑거프린팅, 또는 바이너리 아티팩트를 몰래 들여오려 할 수 있다.

## 자산 (무엇을 보호하는가)

1. **평가자 소스** — `bench/ceb/`. 이를 임포트하거나 읽을 수 있는 제출물은 상대
   엔진, 채점, 팩 레이아웃을 핑거프린팅할 수 있다.
2. **상대 엔진 풀** — `bench/ceb/match/opponents.py`와 그것이 정의하는 엔진들.
3. **숨겨진 eval 팩** — 운영자가 마운트하는 비공개 FEN, perft 포지션, 오프닝
   스위트(`--eval-pack` / `CEB_PRIVATE_EVAL_DIR`). 이것이 누출되면 벤치마크가
   무효가 된다.
4. **비공개 아티팩트** — 전체 라운드/매치 리포트, 게임 movetext, 숨겨진
   데이터에 대한 게이트 리포트(시작 FEN, 수 목록, 호스트 경로).
5. **호스트** — 운영자의 머신, 그 파일시스템, 그리고 자격 증명.

## 엔진 감옥 (engine jail, 주요 통제 수단)

감옥은 평가자가 아니라 **신뢰할 수 없는 엔진만** 격리한다. 평가자는 호스트에서
신뢰된 상태로 유지된다. 평가자는 호스트 측에서 숨겨진 팩을 읽고, 감옥에 갇힌
엔진을 UCI로 구동한다. 코드: `bench/ceb/jail/docker_engine.py`와
`engine_jail.py`. 이미지 `infra/docker/engine_jail.Dockerfile`은
`scripts/build_jail_image.sh`로 빌드되며, 태그는 `chess-en-bench-jail:0.4`이다.

집행 — `docker_engine.py`의 `_base_argv` / `build_engine_argv`가 방출하는 정확한
`docker run` 플래그:

- `--network none` — 외부 통신(egress) 전면 차단.
- `--read-only` 루트 파일시스템 + `--tmpfs /tmp` — 불변(immutable) 컨테이너.
- `--cpus 1`, `--memory 1g`, `--pids-limit 128` (`DEFAULT_LIMITS`).
- `--security-opt no-new-privileges`.
- `--user <host-uid>:<host-gid>` — 컨테이너 안에서 절대 root가 아님 (POSIX).
- `-i` — UCI가 컨테이너의 stdin/stdout으로 흐른다(엔진 실행 시).
- `-v <workspace>:/submission[:ro]` — **유일한** 마운트이다(엔진 실행 시 읽기
  전용). **저장소 마운트도, eval 팩 마운트도, 상대 엔진 마운트도, 다른 실행
  결과 마운트도 없다.** 엔진은 자신의 작업공간 외에는 아무것도 보지 못한다.
- `-w /submission`, 그리고 엔진은 `/submission/<engine_name>`으로 실행된다.

입력 검증 (`validated_workspace`, `build_engine_argv`):

- 해석된 작업공간 경로에 `:` 또는 개행(`-v` 필드 구분자)이 포함되면
  `DockerJailError`로 거부된다 — 경로로 추가 마운트 옵션을 몰래 끼워넣을 수
  없다.
- `/`를 포함하거나 `""`/`.`/`..`와 같은 `engine_name`은 거부된다.

수명주기: 컨테이너는 `--rm`으로 실행된다. `cleanup_containers()`는 남은 잔여물(
stdin EOF를 무시하는 적대적 엔진)을 `docker kill`로 강제 종료한다.

### 빌드 툴체인이 감옥 안에 있다 (소스 우선)

감옥 이미지는 `python:3.12-slim` 위에 빌드 툴체인(`build-essential`:
gcc/g++/make)과 bash, python3를 담는다. 호스팅된 Track A 제출물은 `build.sh`가
**감옥 내 툴체인만으로** `/submission/engine` 실행 파일을 만드는 어떤 언어든
허용된다(C/C++ 네이티브 또는 Python, 밑바닥부터). 예: C++ 예제
`examples/submissions/minimal_uci_engine_cpp` — `engine.cpp`와 `build.sh`만
소스로 제출하고, 감옥/게이트가 평가 시 `./engine`을 컴파일한다.

`build.sh`는 작업공간이 **쓰기 가능**하게 마운트된 상태로(그래야 `./engine`을
생성할 수 있다) 같은 감옥에서 실행되지만 여전히 `--network none`이다
(`build_build_argv`). 엔진 실행은 작업공간을 읽기 전용으로 마운트한다. 빌드
시점에도 실행 시점에도 네트워크가 없으므로, 제출물은 자기충족적(self-contained)
이어야 한다. Docker가 없거나 이미지가 없으면 조용한 호스트 폴백이 아니라
`scripts/build_jail_image.sh`를 가리키는 실행 가능한 `EngineJailError`를
발생시킨다.

### 감옥 이미지 안에는 `ceb`가 없다

감옥 이미지에는 의도적으로 **벤치마크의 어떤 것도 없다.** `ceb` 패키지는
설치되지 않는다(`engine_jail.Dockerfile`). 따라서 Python을 실행하는 감옥 속
엔진이라도 `import ceb`로 평가자 코드, 상대 엔진, 또는 팩 해석 로직을 읽을 수
없다. 이는 마운트 부재 위에 더해지는 심층 방어다.

### 숨겨진 팩은 감옥과 안전하게 결합된다

비공개 팩은 평가자가 **호스트 측**에서 읽는다. 포지션은 컨테이너의 stdin에
기록되는 개별 `position fen ...` UCI 라인으로만 감옥 속 엔진에 도달한다. 팩
디렉터리는 결코 마운트되지 않는다. 따라서 `--eval-pack`은 `--engine-jail
docker`와 함께 동작한다.

### 레거시 `--sandbox docker` 대 엔진 감옥

`--sandbox docker`(`bench/ceb/sandbox/docker_runner.py`)는 전체 하네스를
컨테이너에 넣는 레거시 호환/개발 경로이며 **공식 경로가 아니다.** 비공개 팩
평가는 `--eval-pack`을 거부하고 호스트에서 실행한다(중첩 거부 포함). 공식 경로는
신뢰할 수 없는 엔진만 격리하는 `--engine-jail docker`다. 두 플래그는 별개이며,
공식(verified) 평가는 항상 후자를 쓴다.

## 아티팩트 가시성 (출력에서의 누출 방지)

`bench/ceb/storage/artifacts.py`는 모든 아티팩트 디렉터리에
`artifacts_manifest.json`(스키마 `ceb.artifacts.manifest/v1`)을 부여한다.
`public_artifacts()`는 명시적으로 `public`으로 표시된 파일만 반환한다 —
**기본 거부(deny by default)**: 알려지지 않았거나 목록에 없는 파일은 비공개로
취급된다. 가시성 레벨은 `public` / `private` / `admin`이며, API는 알려지지 않은
레벨을 비공개로 취급한다.

라운드의 경우 (`round_runner.py`):

- **공개:** `feedback.json`; `report.public.json` (스키마
  `ceb.round.report.public/v1`, `verified:false`). 비공개 팩의 경우
  호스트/작업공간 경로를 생략하고 `opening_coverage.opening_ids`를 `null`로
  설정한다. 오프닝 id는 완전히 공개된 팩에 대해서만 방출된다.
- **비공개 (운영자 전용):** `report.json` (호스트 경로와 숨겨진 오프닝 id를
  포함하는 전체 리포트), `match_vs_*.json`, `games_vs_*.txt`,
  `gate_report.json`.

호스팅된 워커는 아티팩트를 DB에 등록할 때 매니페스트에서 가시성을 다시
유도하며, 목록에 없는 것은 무엇이든 **비공개**로 폴백한다
(`worker.py::_register_artifacts`). 그러면 API는 DB에서 `public`인 아티팩트만
제공한다.

## 공개 아티팩트 누출 스캐너 (P0.8)

공개 아티팩트는 매니페스트에 따라 분리되지만, 분류 실수에 대비한 마지막
기계적 점검이 하나 더 있다. 호스팅된 공식 평가는 verified 결과를 기록하기 *전에*
`bench/ceb/scan/leak_scan.py::scan_public_artifacts`를 실행한다.

스캐너는 사용된 비공개 팩의 비밀 토큰을 수집한다(`collect_pack_secrets`):
숨겨진 FEN(전체 문자열과 piece-placement 필드), 숨겨진 오프닝 id와 행 id,
숨겨진 수 시퀀스, 그리고 비공개 팩 디렉터리 경로다. **공개 팩에도 포함된
토큰은 제외하여**(`_public_tokens`) 정당하게 공개된 id/FEN이 오탐을 일으키지
않게 한다(`startpos`도 항상 공개로 취급). 그런 다음 모든 공개 아티팩트의
내용을 이 토큰 집합과 대조한다.

누출이 하나라도 발견되면 공식 평가는 **verified를 거부**하고, 잡은 `failed`로
끝나며, 비공개 `leak_scan.json`을 기록한다. 이 리포트는 **비밀 자체를 절대
echo하지 않고** 누출된 토큰의 짧은 SHA-256 해시만 담는다(`scan_text_for_leaks`).
Track A는 `official_eval.py`에, Track B는 `official_pipeline`에 통합되어 있다.

## 정제된 오류 (오류 경로에서의 누출 방지)

`bench/ceb/sanitize.py`: `SanitizedError(public_message, private_message)`는
두 개의 메시지를 담는다. `sanitize_exception()`은 공개 텍스트를 반환하거나,
알려지지 않은 예외 유형에 대해서는 고정 문자열 `"internal error (<Type>);
details withheld — operators can rerun with CEB_DEBUG=1"`을 반환한다 — 임의의
예외 메시지(예: FEN 파싱에서 나온 `ValueError`)가 숨겨진 포지션을 포함할 수 있기
때문이다.

`load_openings_jsonl(path, hidden=False)`와 eval 팩 로더는 `hidden=` 플래그를
받는다. 숨겨진 오류는 파일 **basename**과 행 id, 그리고 리터럴 `"content
withheld"`만 인용한다 — FEN, 수 시퀀스, 또는 전체 경로는 절대 인용하지 않는다.
공개 데이터는 전체를 인용할 수 있다.

CLI `main()` (`cli.py`)은 모든 것을 잡아 정제된 한 줄을 출력하고 0이 아닌 값을
반환한다(알려지지 않은 예외에는 `3`). `CEB_DEBUG=1`일 때만 전체 트레이스백을
다시 발생시킨다.

## 정적 스캐너 (심층 방어 트립와이어)

정적 스캐너는 증명 시스템이 아니라 트립와이어(tripwire)다. 호스팅된 평가는
이를 엔진 감옥과 결합한다.

- **Track A** (`scan/static_scan.py`, `ceb scan workspace`): 외부 체스 라이브러리
  / python-chess, 외부 엔진(stockfish/lc0/등), 네트워크 사용
  (socket/requests/urllib/http.client/aiohttp/httpx), 프로세스 생성
  (subprocess/os.system/os.popen/os.exec*), 하네스 핑거프린팅
  (`bench/ceb`, `CEB_*`, `eval_packs`, 비공개 경로,
  `ceb.match.opponents`), 과대 파일(>2 MB), 북/테이블베이스/`.nnue`
  확장자, 바이너리 아티팩트, 심링크 탈출을 표시한다.
- **Track B** (`scan/track_b_scan.py`, `ceb scan track-b`): diff
  화이트리스트에 더해 바이너리/NNUE/북 페이로드, 핑거프린팅, 소스에 도입된
  네트워크/프로세스 시스템 콜, 테이블베이스 프로빙, 심링크를 표시한다.

둘 다 `passed`와 함께 심각도 `fail`/`warn`을 가진 `findings`를 반환한다.

## 프로세스 수준 보장 (항상, 모든 모드)

감옥과 무관하게 모든 엔진 I/O는
`bench/ceb/uci/client.py::UCIClient`를 거친다: argv 전용 생성(문자열 명령은
`TypeError`를 발생시키며, `shell=True` 없음), 모든 읽기에 데드라인 부여
(`EngineTimeout`/`EngineCrashed`), 제한된 stdout 수용(큐는 10,000 라인으로 상한,
각 라인은 8,192자로 절단), `stderr` 폐기, 프로세스 그룹 해체(`quit` → SIGTERM →
SIGKILL on POSIX). 전체 목록과 그 한계(특히 `send()` 쓰기는 데드라인으로
보호되지 않음)는 [security.md](security.md)를 참고한다.

## verified는 오직 공식 워커에서만 나온다

`verified:true` 결과는 오직 호스팅된 공식 워커(`ceb hosted worker run-once` →
`bench/ceb/hosted/worker.py` → `official_eval.py::run_official_eval`,
Track B는 `track_b_eval.py::run_hosted_track_b`)만 생성한다. 결과가 verified가
되려면 다음을 **모두** 만족해야 한다:

1. **깨끗한 스냅샷** — 제출물은 스냅샷되며(심링크 거부, `submissions.py`) 트리
   해시된다. 워커는 라이브 작업공간이 아니라 스냅샷을 평가한다.
2. **비공개 eval 팩** — 없으면 거부. 공개 데이터만으로는 verified가 될 수 없다.
3. **정적 스캔 통과** — `scan_workspace`가 실패하면 거부.
4. **strict 게이트 통과** — 비공개 팩에 대한 게이트가 실패하면 거부.
5. **Docker 엔진 감옥** — verifiable 프로파일은 `engine_jail == docker`여야
   한다(P0.1, 아래 참조). 아니면 평가 전에 거부.
6. **verifiable 프로파일** — `official` 또는 `final-production`. `smoke`는 결코
   verified가 아니다(아래 참조).
7. **서명** — Ed25519(없으면 HMAC, 없으면 unsigned). 상세는
   [RESULT_SIGNING.md](RESULT_SIGNING.md).
8. **공개 아티팩트 누출 스캔 통과** (P0.8) — 위 참조. 누출 시 거부.

호스팅된 리더보드(`db.verified_leaderboard`)는 verified 결과만 담으며, 실행마다
단일 best verified 결과를 고른다(P0.4). 직접 실행한 로컬 CLI 라운드와 직접
실행한 Track B CLI는 자가보고(self-reported)/진단(diagnostic)이며 이 코드
경로에 닿지 않으므로 **결코 verified가 아니다.** `smoke`/`quick`은 절대 공식
리더보드에 오르지 않는다.

### 프로파일과 verification_grade

프로파일(`bench/ceb/hosted/profiles.py`,
`tracks/a_from_scratch/eval_profiles.yaml`)은 (1) 어떤 라운드 모드(매치 설정)를
쓰는지, (2) 결과가 verified가 되어 공식 리더보드에 오를 수 있는지를 결정하는
단일 진실 원천이다.

- **smoke** — 진단용. `verifiable=false`, tiny 매치 설정으로 실행되고 감옥 없이
  실행된다(CI 플러밍용). 어떤 플래그를 주어도 **결코 verified가 아니며**
  리더보드에서 제외된다.
- **official** — `verifiable=true`. 표준 `official_round` 모드.
- **final-production** — `verifiable=true`. 프로덕션 규모 `final_production`
  라운드 모드. 리더보드가 official보다 선호한다.
- **final-eval** — 레거시 `final_eval` 모드의 별칭. final-tier verified로
  취급된다.

`final_production` 라운드 모드(`DEFAULT_ROUND_MODES`, `scoring.yaml`)는
6상대 × 336게임 = 2016게임, paired openings(내부 러너가 쌍마다 색을 교대),
movetime 1000ms이다. CI는 절대 이 기본값으로 실행하지 않는다(테스트는 tiny
override).

`verification_grade` 필드는 결과 JSON과 DB 행에 `profile`과 함께 저장되며,
값은 `verified-official` / `verified-final-production` / `verified-final-eval`
/ `diagnostic-smoke` / `diagnostic-unjailed` 중 하나다.

### P0.1 엔진 감옥 가드

verifiable 프로파일이 verified가 되려면 `engine_jail == docker`여야 한다
(`official_eval.py`, `track_b_eval.py`). 아니면 평가 전에 거부된다. 개발 전용
플래그 `--dev-allow-unjailed`는 verifiable 프로파일을 감옥 없이 실행하되 결과를
강제로 `verified=false`(`diagnostic-unjailed`)로 만들어 리더보드에 절대 오르지
않게 한다. CLI 워커 기본값은 `--engine-jail docker`다(프로그램 호출용
`run_once`의 기본값은 `none`). smoke는 `verifiable=false`이므로 플래그와 무관하게
감옥 없이 실행된다.

## 동시성과 잡 큐 (P0.5)

호스팅된 DB(`bench/ceb/hosted/db.py`)는 autocommit + `busy_timeout` + WAL
연결을 쓴다. 워커는 `next_queued_job`이 아니라 `claim_next_job(conn,
worker_id, lease_seconds)`을 사용하며, 이는 `BEGIN IMMEDIATE`로 `queued →
running` 원자적 전이를 수행한다 — 두 워커가 경쟁해도 한 잡을 두 번 처리하지
않는다. `jobs` 테이블에는 `worker_id` / `started_at` / `lease_expires_at` /
`attempt_count` / `public_detail` 컬럼이 있다. lease가 만료된 `running` 잡은
다른 워커가 회수한다(stale recovery). `finish_job`은 `public_detail`(정제됨)과
`detail`(비공개)을 모두 저장한다. `migrate()`는 기존 DB에 컬럼/테이블을
가산적으로 추가하여 데이터 손실 없이 마이그레이션한다.

## Track B 호스티드 (P0.6)

잡 종류 `track_b_official_eval`(`models.py`)로 워커가 분기하여
(`worker.py::_run_track_b_job`) `track_b_eval.py::run_hosted_track_b`를
호출한다. 제출은 `ceb hosted submit-track-b --candidate-src --baseline-src
--run-id --db`로 하며, `track_b_submissions` 테이블에 candidate/baseline
스냅샷과 해시, `build_script`, `engine_relpath`를 저장한다.

verified Track B 요건: 소스 우선(source-first) + diff 화이트리스트 + 콘텐츠
스캔 + baseline/candidate 동일 빌드 스크립트(소스 우선 파이프라인 자체 보장)에
더해 verifiable 프로파일 + 비공개/공식 오프닝 팩 + candidate 엔진 Docker 감옥
(P0.1) + 공개 아티팩트 누출 스캔(P0.8) + 서명이다. 결과는 `mode=track_b_official`,
점수는 final delta Elo이며, `verified_leaderboard(track="B")`가 이를 자체
final-tier로 다룬다. 테스트는 토이 트리로 하고, verified 경로는 Docker opt-in
(`CEB_DOCKER_TESTS=1`)이다. 실제 고정 Stockfish 빌드 래퍼는 운영자 단계다.

## 안전 업로드 (P1.2)

`bench/ceb/hosted/upload.py::safe_extract_archive`는 `.tar.gz`/`.tar`/`.zip`
작업공간 업로드를 추출하되, 쓰기 전에 고전적 아카이브 공격을 거부한다:
심볼릭/하드 링크, 절대 경로, 경로 탐색(`..`), 비정규 멤버(디바이스/fifo),
과대 파일/총량(파일당 50 MiB, 합계 200 MiB, 멤버 10,000개 상한). `extractall`을
**쓰지 않고** 멤버를 하나씩 검증하여 직접 쓴다. 추출 후 호출자가 트리를
스냅샷하고 해시한다. 진입점은 CLI `ceb hosted submit --archive`와 관리자 인증
`POST /api/hosted/runs/{id}/upload`다.

## 결과 번들 내보내기 (P1.3)

`ceb hosted result export --run-id --db --out <zip>`
(`bench/ceb/hosted/result_bundle.py`)는 공개 아티팩트만 zip으로 묶는다: 서명된
`official_result.json`(메타데이터 + 서명 블록 포함), `feedback.json`,
`report.public.json`, 그리고 `VERIFY.txt`와 `bundle_manifest.json`. 비공개/admin
아티팩트는 절대 포함되지 않으며, 오브젝트 스토어 밖의 어떤 것도 패키징하지
않는다(심층 방어). 제3자가 운영자의 공개 키로 결과 진정성을 독립적으로 검증하는
데 필요한 것만 담는다.

## 에이전트 궤적 스키마 (P1.4, 선택)

`bench/ceb/agent_trajectory.py`는 선택적 스키마 `ceb.agent.trajectory/v1`을
제공한다: `model_id` / `agent_id` / `prompt_version` / `tool_budget` /
`gate_attempts` / `round_attempts` / `command_log_hash` /
`source_snapshot_hash`. 비공개 사고 과정(chain of thought)은 요구하지 않는다.

## 스키마 버전

결과 `ceb.hosted.official_result/v2`, 리더보드 `ceb.hosted.leaderboard/v2`,
잡 `ceb.hosted.job/v2`이며, v2는 `profile` + `verification_grade` + Track B
지원을 더한다. 검증기는 하위 호환을 위해 v1 결과 파일도 수용한다.

## 비목표 / 아직 집행되지 않음 (정직한 한계)

- **호스트 실행이 여전히 기본값이다(비호스팅 CLI).** `--engine-jail none`(과
  `--sandbox none`)은 제출물을 당신 사용자의 평범한 자식 프로세스로 실행하며,
  파일시스템/네트워크/리소스 격리가 없다. 공식 워커 CLI는 `--engine-jail
  docker`를 기본값으로 두고 verified를 위해 그것을 *요구*하지만, 로컬 CLI 라운드는
  운영자가 감옥을 선택해야 한다.
- **단일 노드 MVP.** 호스팅된 파이프라인은 SQLite + 로컬 오브젝트 디렉터리
  (`<db>_store/`)다. `claim_next_job`은 한 DB의 여러 워커를 안전하게 다루지만,
  분산 큐도, 멀티 테넌트 격리도, 테넌트별 리소스 회계도 없다.
- **Docker 기본값을 넘는 seccomp/AppArmor 프로파일이 없고**, 사용자 네임스페이스
  리매핑도 없다. 감옥은 Docker의 기본 프로파일과 위 플래그에 의존한다.
- **fastchess는 결함을 접어 넣는다.** 선택적 fastchess 어댑터
  (`match/fastchess_runner.py`)는 엔진별 결함을 귀속하지 않으며, 게임 결과에
  접어 넣는다. 내부 Python 러너가 기본값이자 **신뢰된 기준점(trusted
  reference)**이며, fastchess는 선택적 처리량(throughput) 백엔드다.
- **Track B CLI 실행은 진단용이다.** 호스팅 워커를 거치지 않고 직접 실행한
  Track B는 `verified:false`다. 실제 고정 Stockfish 빌드 래퍼와 운영 정합성
  검사는 운영자 단계이며, 코드로 집행되지 않는다.
- **쓰기 가능한 경로(감옥 빌드의 `/submission`, 호스트 `runs/`, 호스팅된 오브젝트
  스토어)에 디스크 쿼터가 없다.**

## 체크리스트 → 집행 → 증명

각 행은 방어되는 속성을 그것을 집행하는 코드와 그것을 증명하는 테스트에
매핑한다.

| 속성 | 집행 위치 | 증명 |
| --- | --- | --- |
| 엔진 감옥은 작업공간만 읽기 전용으로 마운트; 저장소/팩/상대 엔진 마운트 없음 | `jail/docker_engine.py::build_engine_argv` | `tests/test_engine_jail.py::test_jail_argv_mounts_only_the_workspace` |
| 감옥 플래그: `--network none`, `--read-only`, tmpfs, cpu/mem/pids 상한, no-new-privileges, non-root, `-i` | `jail/docker_engine.py::_base_argv` | `tests/test_engine_jail.py::test_jail_argv_mounts_only_the_workspace` |
| 숨겨진 팩은 감옥 안에 절대 마운트되지 않음 | `jail/engine_jail.py` (호스트 측 읽기); `docker_engine.py` (마운트 목록) | `tests/test_engine_jail.py::test_eval_pack_combines_with_jail_without_mounting_it` |
| 빌드는 쓰기 가능하지만 오프라인으로 실행 (툴체인 감옥 내) | `jail/docker_engine.py::build_build_argv` | `tests/test_engine_jail.py::test_jail_build_argv_is_writable_but_offline` |
| 작업공간 경로 `:`/개행 거부; 잘못된 엔진 이름 거부 | `jail/docker_engine.py::validated_workspace`, `build_engine_argv` | `tests/test_engine_jail.py::test_workspace_validation` |
| 알려지지 않은 감옥 모드 거부; Docker 부재는 실행 가능한 메시지 | `jail/engine_jail.py::_check_mode`, `docker_engine.py::ensure_ready` | `tests/test_engine_jail.py::test_engine_command_modes`, `test_missing_docker_is_actionable` |
| 남은 감옥 컨테이너는 수거됨 | `jail/docker_engine.py::cleanup_containers` | `tests/test_engine_jail.py::test_cleanup_kills_recorded_containers` |
| 감옥 속 엔진이 실제로 UCI를 둠 (통합, 옵트인) | `jail/*` + `uci/client.py` | `tests/test_engine_jail.py::test_jailed_engine_plays_over_uci` (`CEB_DOCKER_TESTS=1` 없으면 건너뜀) |
| verifiable 프로파일은 `engine_jail==docker` 없이 verified 거부; `--dev-allow-unjailed`는 강제 비검증 | `hosted/official_eval.py`, `hosted/track_b_eval.py` | `tests/test_hosted.py` (잡 거부/강등 테스트) |
| smoke는 결코 verified 아님; 어떤 플래그로도 검증 불가 | `hosted/profiles.py`, `hosted/official_eval.py` | `tests/test_hosted.py::test_self_reported_rounds_never_appear_verified` |
| 가시성 매니페스트, 기본 거부 | `storage/artifacts.py::public_artifacts`, `visibility_of` | `tests/test_artifact_visibility.py::test_manifest_tracks_visibility` |
| 라운드 아티팩트가 올바른 공개/비공개 분리를 가짐 | `rounds/round_runner.py` | `tests/test_artifact_visibility.py::test_round_artifacts_have_correct_visibility` |
| 공개 리포트는 호스트 경로와 숨겨진 오프닝 id를 보류 | `rounds/round_runner.py::make_public_report` | `tests/test_artifact_visibility.py::test_public_report_shape` |
| 공개 아티팩트 누출 스캐너가 숨겨진 비밀 노출 시 verified 거부; 해시만 기록 | `scan/leak_scan.py::scan_public_artifacts`, `hosted/official_eval.py` | `tests/test_scan.py` (누출 스캔 테스트) |
| 숨겨진 오프닝 오류는 보드/수를 보류; 행 id + basename 인용 | `sanitize.py`, `match/openings.py`, eval 팩 로더 | `tests/test_sanitization.py::test_hidden_opening_illegal_move_does_not_leak_board`, `test_hidden_suite_file_errors_use_basename` |
| 알려지지 않은 예외는 보류; CLI는 정제된 한 줄 반환, rc 3 | `sanitize.py::sanitize_exception`, `cli.py::main` | `tests/test_sanitization.py::test_cli_unknown_exception_is_withheld`, `test_cli_returns_sanitized_error_not_traceback` |
| Track A 스캐너가 부정행위 표시 (라이브러리/엔진/네트워크/생성/핑거프린트/바이너리/심링크/과대) | `scan/static_scan.py` | `tests/test_scan.py::test_python_chess_import_fails`, `test_stockfish_invocation_fails`, `test_network_usage_fails`, `test_harness_fingerprinting_fails`, `test_symlink_escape_fails`, `test_book_extension_and_oversize_fail` |
| Track B 스캐너가 금지된 diff, 핑거프린팅, 심링크 표시 | `scan/track_b_scan.py` | `tests/test_scan.py::test_track_b_forbidden_change_fails`, `test_track_b_fingerprinting_and_symlink_fail` |
| 잡 클레임은 원자적; lease 만료 시 회수 | `hosted/db.py::claim_next_job` | `tests/test_hosted.py` (원자적 클레임/회수 테스트) |
| 워커만 검증된 결과 생성; 팩 없음 / 스캔 실패 / 게이트 실패 시 거부 | `hosted/worker.py`, `hosted/official_eval.py` | `tests/test_hosted.py::test_worker_produces_verified_result`, `test_worker_refuses_without_eval_pack`, `test_worker_refuses_when_scan_fails`, `test_worker_refuses_when_strict_gate_fails` |
| 제출물은 스냅샷됨; 심링크 거부 | `hosted/submissions.py::snapshot_workspace` | `tests/test_hosted.py::test_snapshot_rejects_symlinks` |
| 안전 업로드가 링크/탐색/절대경로/과대 멤버 거부 | `hosted/upload.py::safe_extract_archive` | `tests/test_hosted.py` (안전 추출 테스트) |
| 호스팅된 리더보드는 검증된 것 전용; 단일 best verified 선택 공유 | `hosted/db.py::verified_leaderboard`, `select_best_verified_result` | `tests/test_hosted.py::test_hosted_leaderboard_is_verified_only`, `test_self_reported_rounds_never_appear_verified` |
| 결과 번들은 공개 아티팩트만; 스토어 밖 패키징 금지 | `hosted/result_bundle.py::export_result_bundle` | `tests/test_hosted.py` (번들 내보내기 테스트) |
| API는 공개 아티팩트만 제공; 경로 순회(traversal) 거부 | `api/main.py::hosted_artifact` | `tests/test_hosted.py::test_api_private_artifact_not_served`, `test_api_path_traversal_rejected` |
| API 관리자 POST는 토큰으로 게이팅 (미설정 503 / 잘못된 토큰 403) | `api/main.py::_require_admin` | `tests/test_hosted.py::test_api_admin_endpoints_gated` |
| 서명: 왕복, 변조 탐지, 잘못된 키, unsigned은 절대 진정하지 않음 | `hosted/signing.py` | `tests/test_signing.py::test_sign_and_verify_roundtrip`, `test_tampered_result_fails_verification`, `test_wrong_key_fails_verification`, `test_unsigned_mode_is_explicit_and_never_authentic` |
| 재현성 메타데이터가 완전함; eval 팩 해시는 내용에 바인딩됨 | `hosted/metadata.py::build_metadata`, `hash_directory` | `tests/test_signing.py::test_metadata_required_keys`, `test_eval_pack_hash_changes_with_contents` |
| 레거시 `--sandbox docker`는 잠긴 상태 유지하고 중첩 거부 | `sandbox/docker_runner.py` | `tests/test_sandbox_docker.py::test_gate_argv_is_locked_down`, `test_recursion_guard` |
| UCIClient 프로세스 수준 안전성 (argv 전용, 타임아웃, 제한된 수용) | `uci/client.py` | `tests/test_uci_client.py` |

제출물에 대한 정책 수준 규칙(네트워크 금지, 하네스 내부 읽기 금지)과 그
결과는 `specs/forbidden_behaviors.md`에 규범적으로 명시되어 있다.
