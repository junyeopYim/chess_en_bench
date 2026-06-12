# 보안 모델 (v0.3)

chess_en_bench는 직접 작성하지 않은 코드를 평가한다. 두 트랙 모두 신뢰할 수
없는 제출물을 받는다. Track A 엔진(과 그 `build.sh`)과 Track B 후보 패치는
평가 대상인 LLM 에이전트가 생성한다. 이 문서는 호스팅된 공식 벤치마크의 정식
신뢰 모델이다. 무엇을 방어하는지, 엔진 감옥(engine jail)이 이를 어떻게
집행하는지, 그리고 — 명시적으로 — v0.3이 아직 집행하지 *않는* 것이 무엇인지를
다룬다.

운영자 관점의 "이걸 어떻게 안전하게 실행하는가" 가이드는
[security.md](security.md)를 참고한다. 이 문서는 그 가이드 뒤에 있는 *이유*에
해당한다.

## 위협

공격자는 밑바닥부터 좋은 체스를 두는 것 이외의 모든 수단으로 벤치마크에서
이기려는 신뢰할 수 없는 제출물이다.

- **신뢰할 수 없는 엔진 코드 (Track A).** UCI를 말하는 임의의 네이티브 또는
  인터프리터 프로그램이다. 숨겨진 eval 팩, 상대 엔진, 또는 평가기 소스를 읽으려
  하거나, 더 강한 엔진이나 온라인 오라클을 다운로드하려고 네트워크에
  접근하거나, 프로세스를 생성하거나, CPU/메모리/디스크를 고갈시키거나, I/O를
  멈추게 하거나 범람시키거나, 하네스 프로세스로 탈출하려 할 수 있다.
- **신뢰할 수 없는 Track B 패치.** 고정된 Stockfish 베이스라인에 대한 소스
  diff로, NNUE/북/테이블베이스 페이로드, 네트워크 또는 프로세스 시스템 콜,
  하네스 핑거프린팅, 또는 바이너리 아티팩트를 몰래 들여오려 할 수 있다.

제출물은 단순히 버그가 있는 것이 아니라 능동적으로 적대적이라고 가정한다.

## 자산 (무엇을 보호하는가)

1. **평가기 소스** — `bench/ceb/`. 이를 임포트하거나 읽을 수 있는 제출물은 상대
   엔진, 채점, 팩 레이아웃을 핑거프린팅할 수 있다.
2. **상대 엔진 풀** — `bench/ceb/match/opponents.py`와 그것이 정의하는 엔진들.
3. **숨겨진 eval 팩** — 운영자가 마운트하는 비공개 FEN, perft 포지션, 오프닝
   스위트(`--eval-pack` / `CEB_PRIVATE_EVAL_DIR`). 이것이 누출되면 벤치마크가
   무효가 된다.
4. **비공개 아티팩트** — 전체 라운드/매치 리포트, 게임 movetext, 숨겨진
   데이터에 대한 게이트 리포트(시작 FEN, 수 목록, 호스트 경로).
5. **호스트** — 운영자의 머신, 그 파일시스템, 그리고 자격 증명.

## 엔진 감옥 (engine jail, 주요 통제 수단)

감옥은 평가기가 아니라 **신뢰할 수 없는 엔진만** 격리한다. 평가기는 호스트에서
신뢰된 상태로 유지된다. 평가기는 호스트 측에서 숨겨진 팩을 읽고, 감옥에 갇힌
엔진을 UCI로 구동한다. 코드: `bench/ceb/jail/docker_engine.py`와
`engine_jail.py`. 이미지 `infra/docker/engine_jail.Dockerfile`은
`scripts/build_jail_image.sh`로 빌드되며, 태그는 `chess-en-bench-jail:0.3`이다.

집행 — `docker_engine.py`의 `_base_argv` / `build_engine_argv`가 방출하는 정확한
`docker run` 플래그:

- `--network none` — 외부 통신(egress) 전면 차단.
- `--read-only` 루트 파일시스템 + `--tmpfs /tmp` — 불변(immutable) 컨테이너.
- `--cpus 1`, `--memory 1g`, `--pids-limit 128` (`DEFAULT_LIMITS`).
- `--security-opt no-new-privileges`.
- `--user <host-uid>:<host-gid>` — 컨테이너 안에서 절대 root가 아님 (POSIX).
- `-i` — UCI가 컨테이너의 stdin/stdout으로 흐른다.
- `-v <workspace>:/submission:ro` — **유일한** 마운트이며 읽기 전용이다.
  **저장소 마운트도, eval 팩 마운트도, 상대 엔진 마운트도, 다른 실행 결과
  마운트도 없다.** 엔진은 자신의 작업공간 외에는 아무것도 보지 못한다.
- `-w /submission`, 그리고 엔진은 `/submission/<engine_name>`으로 실행된다.

입력 검증 (`validated_workspace`, `build_engine_argv`):

- 해석된 작업공간 경로에 `:` 또는 개행(`-v` 필드 구분자)이 포함되면
  `DockerJailError`로 거부된다 — 경로로 추가 마운트 옵션을 몰래 끼워넣을 수
  없다.
- `/`를 포함하거나 `""`/`.`/`..`와 같은 `engine_name`은 거부된다.

수명주기: 컨테이너는 `--rm`으로 실행된다. `cleanup_containers()`는 남은 잔여물(
stdin EOF를 무시하는 적대적 엔진)을 `docker kill`로 강제 종료한다.

`build.sh`는 작업공간이 **쓰기 가능**하게 마운트된 상태로(그래야 `./engine`을
생성할 수 있다) 같은 감옥에서 실행되지만 여전히 `--network none`이다
(`build_build_argv`). Docker가 없거나 이미지가 없으면 조용한 호스트 폴백이
아니라 `scripts/build_jail_image.sh`를 가리키는 실행 가능한
`EngineJailError`를 발생시킨다.

### 감옥 이미지 안에는 `ceb`가 없다

감옥 이미지는 의도적으로 최소한이다. Python 런타임과 bash만 있고 **벤치마크의
어떤 것도 없다.** `ceb` 패키지는 의도적으로 설치되지 않는다
(`engine_jail.Dockerfile`). 따라서 Python을 실행하는 감옥 속 엔진이라도
`import ceb`로 평가기 코드, 상대 엔진, 또는 팩 해석 로직을 읽을 수 없다. 이는
마운트 부재 위에 더해지는 심층 방어다.

### 숨겨진 팩은 감옥과 안전하게 결합된다

비공개 팩은 평가기가 **호스트 측**에서 읽는다. 포지션은 컨테이너의 stdin에
기록되는 개별 `position fen ...` UCI 라인으로만 감옥 속 엔진에 도달한다. 팩
디렉터리는 결코 마운트되지 않는다. 따라서 `--eval-pack`은 `--engine-jail
docker`와 함께 동작한다 — 여전히 `--eval-pack`을 거부하고 비공개 팩 평가를
호스트에서 실행하는 레거시 `--sandbox docker`와는 다르다.

## 아티팩트 가시성 (출력에서의 누출 방지)

`bench/ceb/storage/artifacts.py`는 모든 아티팩트 디렉터리에
`artifacts_manifest.json`을 부여한다. `public_artifacts()`는 명시적으로
`public`으로 표시된 파일만 반환한다 — **기본 거부(deny by default)**:
알려지지 않았거나 목록에 없는 파일은 비공개로 취급된다.

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

## 스캐너 (심층 방어 트립와이어)

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

## 검증된 결과는 오직 공식 워커에서만 나온다

호스팅된 워커(`bench/ceb/hosted/worker.py` →
`official_eval.py::run_official_eval`)만이 `verified:true` 결과를 생성한다.
워커는 순서대로 실행한다: 정적 스캔 → 비공개 팩에 대한 strict 게이트 →
비공개 팩과 선택적 엔진 감옥을 사용한 `official_round` 또는 `final_eval` →
공개/비공개 아티팩트 분리 → 재현성 메타데이터 + 서명 → 검증된 결과. 비공개 eval
팩이 없거나, 스캔이 실패하거나, strict 게이트가 실패하면 **검증을 거부한다**
(검증된 것을 아무것도 기록하지 않음). 제출물은 스냅샷되며(심링크 거부,
`submissions.py`) 트리 해시된다. 워커는 라이브 작업공간이 아니라 스냅샷을
평가한다. 호스팅된 리더보드(`db.verified_leaderboard`)는 검증된 것 전용이며,
빠른 라운드는 절대 나타나지 않는다. 자체 보고된 모든 로컬 라운드는
`verified:false`이다.

## 비목표 / 아직 집행되지 않음 (v0.3의 정직한 한계)

- **호스트 실행이 여전히 기본값이다.** `--engine-jail none`(과 `--sandbox
  none`)은 제출물을 당신 사용자의 평범한 자식 프로세스로 실행하며,
  파일시스템/네트워크/리소스 격리가 없다. 그 무엇도 `--engine-jail docker`를
  *강제하지* 않으며, 운영자가 선택해야 한다. 호스팅된 워커는 운영자가 설정한
  감옥 모드를 그대로 전달한다.
- **대칭 서명만 (MVP).** 결과 서명은 `CEB_SIGNING_KEY`로 키가 지정된
  HMAC-SHA256이다(`hosted/signing.py`). 키 보유자만 검증할 수 있으며, 이는
  *운영자에 대한* 진정성이지 공개키 증명(attestation)이 아니다. 키가 없으면
  결과는 `signature.status = "unsigned"`로 기록되며 명시적인 "NO cryptographic
  authenticity" 노트가 붙고, `verify_result`는 `(False, "unsigned ...")`를
  반환한다. 비대칭 증명은 향후 작업이다.
- **단일 노드 MVP.** 호스팅된 파이프라인은 SQLite + 로컬 오브젝트 디렉터리
  (`<db>_store/`)와 단일 워커 `run-once` 루프다. 멀티 테넌트 격리도, 분산
  큐도, 테넌트별 리소스 회계도 없다.
- **Docker 기본값을 넘는 seccomp/AppArmor 프로파일이 없고**, 사용자 네임스페이스
  리매핑도 없다. 감옥은 Docker의 기본 프로파일과 위 플래그에 의존한다.
- **fastchess는 결함을 접어 넣는다.** 선택적 fastchess 어댑터
  (`match/fastchess_runner.py`)는 엔진별 결함을 귀속하지 않으며, 게임 결과에
  접어 넣는다. 내부 Python 러너가 기본값이자 **신뢰된 기준점(trusted
  reference)**이며, fastchess는 선택적 처리량(throughput) 백엔드다.
- **Track B CLI 실행은 진단용이다.** `ceb track-b official run`은
  `verified:false`를 기록한다. 동일한 컴파일러 플래그를 사용한 실제 고정
  Stockfish 빌드와 `bench` 정합성 검사는 운영자 단계이며, 코드로 집행되지 않는다.
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
| 빌드는 쓰기 가능하지만 오프라인으로 실행 | `jail/docker_engine.py::build_build_argv` | `tests/test_engine_jail.py::test_jail_build_argv_is_writable_but_offline` |
| 작업공간 경로 `:`/개행 거부; 잘못된 엔진 이름 거부 | `jail/docker_engine.py::validated_workspace`, `build_engine_argv` | `tests/test_engine_jail.py::test_workspace_validation` |
| 알려지지 않은 감옥 모드 거부; Docker 부재는 실행 가능한 메시지 | `jail/engine_jail.py::_check_mode`, `docker_engine.py::ensure_ready` | `tests/test_engine_jail.py::test_engine_command_modes`, `test_missing_docker_is_actionable` |
| 남은 감옥 컨테이너는 수거됨 | `jail/docker_engine.py::cleanup_containers` | `tests/test_engine_jail.py::test_cleanup_kills_recorded_containers` |
| 감옥 속 엔진이 실제로 UCI를 둠 (통합, 옵트인) | `jail/*` + `uci/client.py` | `tests/test_engine_jail.py::test_jailed_engine_plays_over_uci` (`CEB_DOCKER_TESTS=1` 없으면 건너뜀) |
| 가시성 매니페스트, 기본 거부 | `storage/artifacts.py::public_artifacts`, `visibility_of` | `tests/test_artifact_visibility.py::test_manifest_tracks_visibility` |
| 라운드 아티팩트가 올바른 공개/비공개 분리를 가짐 | `rounds/round_runner.py` | `tests/test_artifact_visibility.py::test_round_artifacts_have_correct_visibility` |
| 어떤 공개 아티팩트에도 숨겨진 비밀이 누출되지 않음 | `rounds/round_runner.py::make_public_report` | `tests/test_artifact_visibility.py::test_public_artifacts_leak_scan` |
| 공개 리포트는 호스트 경로와 숨겨진 오프닝 id를 보류 | `rounds/round_runner.py::make_public_report` | `tests/test_artifact_visibility.py::test_public_report_shape` |
| 숨겨진 오프닝 오류는 보드/수를 보류; 행 id + basename 인용 | `sanitize.py`, `match/openings.py`, eval 팩 로더 | `tests/test_sanitization.py::test_hidden_opening_illegal_move_does_not_leak_board`, `test_hidden_suite_file_errors_use_basename` |
| 알려지지 않은 예외는 보류; CLI는 정제된 한 줄 반환, rc 3 | `sanitize.py::sanitize_exception`, `cli.py::main` | `tests/test_sanitization.py::test_cli_unknown_exception_is_withheld`, `test_cli_returns_sanitized_error_not_traceback` |
| Track A 스캐너가 부정행위 표시 (라이브러리/엔진/네트워크/생성/핑거프린트/바이너리/심링크/과대) | `scan/static_scan.py` | `tests/test_scan.py::test_python_chess_import_fails`, `test_stockfish_invocation_fails`, `test_network_usage_fails`, `test_harness_fingerprinting_fails`, `test_symlink_escape_fails`, `test_book_extension_and_oversize_fail` |
| Track B 스캐너가 금지된 diff, 핑거프린팅, 심링크 표시 | `scan/track_b_scan.py` | `tests/test_scan.py::test_track_b_forbidden_change_fails`, `test_track_b_fingerprinting_and_symlink_fail` |
| 워커만 검증된 결과 생성; 팩 없음 / 스캔 실패 / 게이트 실패 시 거부 | `hosted/worker.py`, `hosted/official_eval.py` | `tests/test_hosted.py::test_worker_produces_verified_result`, `test_worker_refuses_without_eval_pack`, `test_worker_refuses_when_scan_fails`, `test_worker_refuses_when_strict_gate_fails` |
| 제출물은 스냅샷됨; 심링크 거부 | `hosted/submissions.py::snapshot_workspace` | `tests/test_hosted.py::test_snapshot_rejects_symlinks` |
| 호스팅된 리더보드는 검증된 것 전용; 자체 보고는 절대 검증되지 않음 | `hosted/db.py::verified_leaderboard` | `tests/test_hosted.py::test_hosted_leaderboard_is_verified_only`, `test_self_reported_rounds_never_appear_verified` |
| API는 공개 아티팩트만 제공; 경로 순회(traversal) 거부 | `api/main.py::hosted_artifact` | `tests/test_hosted.py::test_api_private_artifact_not_served`, `test_api_path_traversal_rejected` |
| API 관리자 POST는 토큰으로 게이팅 (미설정 503 / 잘못된 토큰 403) | `api/main.py::_require_admin` | `tests/test_hosted.py::test_api_admin_endpoints_gated` |
| 서명: 왕복, 변조 탐지, 잘못된 키, unsigned은 절대 진정하지 않음 | `hosted/signing.py` | `tests/test_signing.py::test_sign_and_verify_roundtrip`, `test_tampered_result_fails_verification`, `test_wrong_key_fails_verification`, `test_unsigned_mode_is_explicit_and_never_authentic` |
| 재현성 메타데이터가 완전함; eval 팩 해시는 내용에 바인딩됨 | `hosted/metadata.py::build_metadata`, `hash_directory` | `tests/test_signing.py::test_metadata_required_keys`, `test_eval_pack_hash_changes_with_contents` |
| 레거시 `--sandbox docker`는 잠긴 상태 유지하고 중첩 거부 | `sandbox/docker_runner.py` | `tests/test_sandbox_docker.py::test_gate_argv_is_locked_down`, `test_recursion_guard` |
| UCIClient 프로세스 수준 안전성 (argv 전용, 타임아웃, 제한된 수용) | `uci/client.py` | `tests/test_uci_client.py` |

제출물에 대한 정책 수준 규칙(네트워크 금지, 하네스 내부 읽기 금지)과 그
결과는 `specs/forbidden_behaviors.md`에 규범적으로 명시되어 있다.
