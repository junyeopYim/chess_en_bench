# 보안 모델 (v0.3.4)

chess_en_bench는 직접 작성하지 않은 코드를 평가한다. 두 트랙 모두 신뢰할 수
없는 제출물을 받는다. Track A 엔진(과 그 `build.sh`)과 Track B 후보 패치는
평가 대상인 LLM 에이전트가 생성한다. 이 문서는 호스팅된 공식 벤치마크의 정식
신뢰 모델이다. 무엇을 방어하는지, 엔진 감옥(engine jail)이 이를 어떻게
집행하는지, 그리고 — 명시적으로 — 아직 집행하지 *않는* 것이 무엇인지를 다룬다.

이 저장소는 `ceb hosted readiness check --strict-public-official`이 통과할
**때에만** "Track A와 Track B를 위한 공개 공식 단일 노드 호스팅 벤치마크 준비
완료" 상태가 된다(아래 "공식 준비도 점검" 참조 — strict 준비도가 유일한
선언 게이트다). 단일 노드(SQLite + 로컬 FS)는 분산 프로덕션 서비스가 아니라
정직한 범위로 유지된다. verified 결과는 v0.3.2의 모든 보장 위에 다음을 추가로
요구한다: **고정(pin)된 신뢰 공식 eval 팩**; Track B의 경우 **신뢰된
베이스라인** + **해시 고정 빌드 래퍼** + **검증된 빌드 출력** + **bench 정합성**;
Ed25519 서명; 그리고 strict 준비도 통과.

v0.3.4는 마지막 공개 공식 감사 강화로 모호함을 제거했다: **어떤 `--dev-*`
플래그도 verified를 유지하지 못한다**(verifiable 실행을 실패시키거나 진단
등급으로 강제 강등). 신뢰 앵커는 실제로 검증된다(서명 키는 비싼 작업 이전에
로드 검증된다). 그리고 strict 준비도가 단일 선언 게이트로서 결과 JSON에
`public_official_declaration`("ready"/"not-ready")과 `blocking_failures`를
방출한다.

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
  하네스 핑거프린팅, 또는 바이너리 아티팩트를 몰래 들여오려 할 수 있다. 또한
  **빌드 단계 자체가 공격 표면**이다 — 후보가 빌드 스크립트를 통해 호스트에서
  코드를 실행하려 할 수 있으므로, verified 빌드는 신뢰된 운영자 래퍼로 빌드 감옥
  안에서만 수행한다.

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
기계적 점검이 하나 더 있다. 호스팅된 공식 평가는 공개 예정 아티팩트를 공개로
승격하기 *전에* `bench/ceb/scan/leak_scan.py::scan_public_artifacts(...,
staged=True)`를 **스테이징된 집합**에 대해 실행한다(위 "공개 아티팩트 스테이징
→ 스캔 → 승격" 참조). 스캐너는 트리 전체를 재귀적으로 훑어 워커가 공개로
등록·제공하는 집합 그대로를 덮는다.

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
2. **신뢰되고 고정된 공식 eval 팩** — 커밋된 데모 팩이 아니라 운영자의 공식
   팩이어야 하며(아래 "신뢰된 공식 eval 팩" 참조), 그 콘텐츠 해시가 **허용
   목록에 고정(pin)**되어야 한다. 고정되지 않으면 평가 이전에 거부.
3. **정적 스캔 통과** — `scan_workspace`가 실패하면 거부.
4. **strict 게이트 통과** — 비공개 팩에 대한 게이트가 실패하면 거부.
5. **Docker 엔진 감옥** — verifiable 프로파일은 `engine_jail == docker`여야
   한다(P0.1, 아래 참조). 아니면 평가 전에 거부.
6. **(Track B) 신뢰된 베이스라인** — verified Track B는 신뢰된 베이스라인에
   대해서만 채점된다(stockfish-lock / hash / toy, 아래 "Track B 베이스라인
   신뢰" 참조).
7. **(Track B) 격리된 빌드 감옥 + 해시 고정 래퍼 + 검증된 빌드 출력** — verified
   Track B는 후보의 빌드 스크립트를 호스트에서 실행하지 않는다. **해시 고정된**
   신뢰 운영자 래퍼가 빌드 감옥 안에서 빌드하고, 빌드 출력은 사용 전에 검증된다
   (아래 "Track B 빌드 격리"와 "빌드 출력 강화" 참조). 호스트 빌드는 항상
   `verified=false`다.
8. **(Track B) bench/속도 정합성** — verified Track B는 두 엔진에 `bench`를
   돌려 노드/NPS를 기록하고, 두 엔진이 모두 bench를 지원할 때 NPS 비율 임계값을
   강제한다(아래 "Track B bench/속도 정합성" 참조).
9. **verifiable 프로파일** — `official` 또는 `final-production`. `smoke`는 결코
   verified가 아니다(아래 참조).
10. **Ed25519 서명** — verified 결과는 **반드시 Ed25519로 서명**되어야 한다
    (아래 "verified는 Ed25519를 요구한다" 참조). HMAC/unsigned는 공식 verified가
    될 수 없다. 상세는 [RESULT_SIGNING.md](RESULT_SIGNING.md).
11. **스테이징된 공개 아티팩트 누출 스캔 통과** (P0.8) — 공개 예정 아티팩트는
    먼저 스테이징되고, 스캔을 통과한 뒤에만 공개로 승격된다(아래 "공개 아티팩트
    스테이징 → 스캔 → 승격" 참조). 누출 시 아무것도 공개되지 않고 잡은 실패한다.

이 단계 중 팩 신뢰·핀, 베이스라인 신뢰, 래퍼 핀, Ed25519 가드는 **평가 작업
이전에** 실패한다(`official_eval.py`, `track_b_eval.py`). 신뢰되지 않거나
고정되지 않은 각 앵커는 하드 실패(결과 없음)이거나, 해당 개발 전용 플래그가
주어지면 결과를 진단(`verified=false`, 리더보드 제외)으로 강등한다 — 첫 번째
미신뢰 앵커가 등급을 결정한다.

**어떤 `--dev-*` 플래그도 verified를 유지하지 못한다(v0.3.4).** 모든 개발
전용 플래그는 verifiable 실행을 실패시키거나 진단(unverified) 등급으로 강제
강등한다. 특히 v0.3.3까지 bench 실패 시 `--dev-allow-no-bench`가 verified를
지킬 여지가 있었으나, 이제 그 경로는 verified를 보존하지 않고
`diagnostic-no-bench`로 **강등**한다(`track_b/official_pipeline.py`,
`profiles.py`) — 따라서 bench 실패는 리더보드에 결코 닿지 못한다. 플래그가
없으면 bench 실패는 하드 실패(결과 없음)다.

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
/ `diagnostic-smoke` / `diagnostic-unjailed` / `diagnostic-unsigned` /
`diagnostic-untrusted-pack` / `diagnostic-unpinned-pack` /
`diagnostic-untrusted-baseline` / `diagnostic-untrusted-wrapper` /
`diagnostic-no-bench` 중 하나다(`profiles.py`). `diagnostic-unsigned`는
Ed25519 키가 없을 때 `--dev-allow-unsigned`로 강제 비검증된 결과에 쓰이고,
`diagnostic-untrusted-pack`은 신뢰된 공식 팩이 아닌 진단 평가용 등급이다.
진단 등급은 고정되지 않은 팩(`--dev-allow-unpinned-pack`), 미신뢰 베이스라인
(`--dev-allow-toy-baseline`), 고정되지 않은 래퍼(`--dev-allow-unpinned-wrapper`),
bench 미통과(`--dev-allow-no-bench` → `diagnostic-no-bench`)에 각각 대응한다.
공식 경로에서 신뢰/핀 검증 실패는 평가 자체를 거부하며, **개발 전용 플래그
중 어느 것도 verified를 유지하지 못한다 — 모두 verifiable 실행을 실패시키거나
진단 등급으로 강등한다.**

### P0.1 엔진 감옥 가드

verifiable 프로파일이 verified가 되려면 `engine_jail == docker`여야 한다
(`official_eval.py`, `track_b_eval.py`). 아니면 평가 전에 거부된다. 개발 전용
플래그 `--dev-allow-unjailed`는 verifiable 프로파일을 감옥 없이 실행하되 결과를
강제로 `verified=false`(`diagnostic-unjailed`)로 만들어 리더보드에 절대 오르지
않게 한다. CLI 워커 기본값은 `--engine-jail docker`다(프로그램 호출용
`run_once`의 기본값은 `none`). smoke는 `verifiable=false`이므로 플래그와 무관하게
감옥 없이 실행된다.

### 신뢰된 공식 eval 팩 (데모 팩 거부)

공개 공식 verified 결과는 운영자의 **신뢰된 공식 팩**에 대해서만 만들어지며,
저장소에 커밋된 데모 팩(`examples/eval_packs/tiny_private`)에 대해서는 결코 만들
수 없다. 정책은 `bench/ceb/hosted/eval_pack_trust.py`
(`validate_official_eval_pack(private_dir, track=, allowed_hashes=, allow_demo=)`)
에 있다. 신뢰된 팩이 되려면 `manifest.json`에 스키마
`ceb.eval_pack.manifest/v1`과 키 `pack_id`/`name`/`track`/`season`/
`official`(=`true`)/`visibility`(=`"private"`)/`openings_mode`가 있어야 하고,
선언된 `track`이 평가 트랙과 맞아야 하며(`A`/`B`/`both`), 팩이 저장소의
`examples/`나 `tests/` **바깥**에 있어야 한다(운영자 비공개). 개발 전용 플래그
`--dev-allow-demo-pack`은 경로 검사만 우회한다.

**콘텐츠 해시 고정(pin)은 verified의 필수 조건이다.** 허용 목록은
환경변수 `CEB_OFFICIAL_EVAL_PACK_HASHES`(쉼표 구분), CLI
`--official-pack-hash`(반복/쉼표), `--official-pack-registry`(JSON/텍스트 파일)로
준다(공통 리졸버 `resolve_hash_allowlist`). 허용 목록이 주어지면 팩의 콘텐츠
해시가 그 안에 있어야 하고, **허용 목록이 전혀 없으면 평가 이전에 verified가
거부된다**(`official_eval.py`, `track_b_eval.py`). 개발 전용 플래그
`--dev-allow-unpinned-pack`은 결과를 `verified=false`(등급
`diagnostic-unpinned-pack`)로 강등한다. 커밋된 데모 팩은 공식 매니페스트가
없으므로 **결코 verified될 수 없으며**(smoke 프로파일에는 그대로 적합),
데모 경로만 `--dev-allow-demo-pack`으로 우회하면 등급은
`diagnostic-untrusted-pack`이다. smoke는 여전히 데모 팩을 unverified로 쓴다.
verified 결과 메타데이터는 `eval_pack_id`, `eval_pack_hash`,
`eval_pack_manifest_hash`, `eval_pack_trusted`(=`true`), `eval_pack_track`,
`eval_pack_season`을 기록한다.

### verified는 Ed25519를 요구한다

verified 결과는 **반드시 Ed25519로 서명**되어야 한다(`bench/ceb/hosted/signing.py`,
`official_eval.py`, `track_b_eval.py`, `verifier.py`). Ed25519 키
(`CEB_SIGNING_PRIVATE_KEY` 환경변수 또는 `--signing-key`)가 없는 verifiable
프로파일은 verified를 **거부한다**(평가 이전에 실패) — 단,
`--dev-allow-unsigned`를 주면 강제로 `verified=false`(등급
`diagnostic-unsigned`)로 강등된다. `sign_official_result(result,
private_key_path=)`는 Ed25519 > HMAC > unsigned 순으로 고르며, official_eval은
verified 결과의 `signature.algorithm == "ed25519"`를 단언한다. HMAC 결과는 공식
verified가 **될 수 없다**(HMAC은 레거시/진단으로 남는다).

**키는 비싼 작업 이전에 로드 검증된다(v0.3.4).** verifiable 프로파일의 경우
Ed25519 비공개 키는 정적 스캔 / strict 게이트 / 빌드 / 매치 **이전에**
`signing.py::require_ed25519_private_key`로 해석되고 **로드 검증**된다
(`official_eval.py`, `track_b_eval.py`). **잘못된(malformed) 키**는 정제된
메시지와 함께 즉시 하드 실패하므로 — 비싼 평가가 끝난 뒤 서명 단계에서 실패해
**스테이징된 공개 아티팩트가 좌초되는 일이 없다.** 키가 아예 없으면
`--dev-allow-unsigned`로 강등하거나 하드 실패한다. 검증된 키 경로는 서명
시점에 그대로 재사용된다.

검증기(`verify_result_file`)는 verified 결과가 Ed25519가 아니면 `authentic`을
거짓으로 둔다(필드 `public_official_signing`). 그리고 `authentic`은 **대역외로
공급된 공개 키**를 요구한다 — 임베디드 키만 있으면 `signature_trust`는
`embedded-self-described`이고 `authentic`은 거짓이다(임베디드 키는 자기
일관성만 증명하며, 공격자가 자기 키로 위조 결과에 서명·임베드할 수 있다).
서명 세부는 [RESULT_SIGNING.md](RESULT_SIGNING.md)를 참고한다.

**키쌍 일치 (strict 준비도).** strict 준비도(아래 참조)는 로드 가능한 Ed25519
비공개 키, 로드 가능한 공개 키, 그리고 **키쌍 일치**를 함께 요구한다 — 즉
`public_key_fingerprint(private.public_key())`가 공급된 공개 키의 핑거프린트와
같아야 한다(`readiness.py::_key_checks`). 준비도 리포트는 공개 키 핑거프린트를
담는다. 공개 리더보드는 운영자 공개 키 핑거프린트와 그 배포 경로를 게시하여
제3자가 대역외로 공개 키를 받아 진정성을 독립 검증할 수 있게 한다.

### Track B 빌드 격리 (빌드 감옥)

verified Track B는 후보가 소유한 빌드 스크립트를 호스트에서 결코 실행하지 않는다.
신뢰된 운영자 빌드 래퍼(후보/베이스라인 트리 **바깥**의 파일로, 워커에
`--build-wrapper`로 전달됨)가 baseline과 candidate를 **같은 래퍼**로 Docker 빌드
감옥 안에서 빌드한다(`bench/ceb/track_b/build_jail.py::build_in_jail`).

빌드 감옥 마운트/정책(`build_in_jail`이 방출하는 `docker run` 플래그):

- 소스는 `/src`에 **읽기 전용**, 쓰기 가능한 출력은 `/out`, 신뢰된 래퍼는
  `/wrapper.sh`에 읽기 전용으로 마운트된다.
- `--network none`, `--read-only` 루트 + `--tmpfs /tmp`, cpu/mem/pids 상한
  (`2`/`4g`/`1024`), `--security-opt no-new-privileges`, non-root(`--user`).
- **저장소도 eval 팩도 마운트되지 않는다.**

래퍼 계약은 `/wrapper.sh <source_ro> <out_writable> <engine_relpath>`이며,
같은 래퍼가 baseline과 candidate를 빌드하므로 빌드 설정이 동일하고
운영자가 통제한다. 래퍼 경로 검증
(`bench/ceb/hosted/build_wrappers.py::validate_build_wrapper`)은 래퍼가 후보/
베이스라인 트리 안에 있으면 거부한다(후보가 자기 빌드 로직을 공급할 수 없음).
`write_demo_wrapper`는 테스트/로컬 진단용 데모 래퍼만 작성한다.

**래퍼 해시 고정 (req4).** 트리 밖 검증에 더해, verified Track B는 래퍼 **파일
해시**가 허용 목록에 고정되어야 한다(`compute_wrapper_hash` /
`resolve_wrapper_hashes`): `--build-wrapper-hash` /
`CEB_TRACK_B_BUILD_WRAPPER_HASHES` / `--build-wrapper-registry`. 고정되지 않으면
하드 실패하거나, `--dev-allow-unpinned-wrapper`로 `verified=false`(등급
`diagnostic-untrusted-wrapper`)로 강등된다. 메타데이터 `track_b`는
`build_wrapper_hash`, `build_wrapper_trusted`, `build_isolation`,
`build_jail_image_digest`를 기록한다.

빌드 감옥 이미지는 기본적으로 엔진 감옥 이미지 `chess-en-bench-jail:0.4`를
재사용한다(gcc/g++/make/bash/python3 보유). 전용 이미지
`chess-en-bench-build-jail:0.4`를 `infra/docker/track_b_build_jail.Dockerfile`과
`scripts/build_track_b_build_image.sh`로 빌드할 수도 있다. 빌드된 candidate 엔진은
이후 매치에서 엔진 감옥에 갇혀 실행된다. 결과/메타데이터는 `build_isolation`
(`"jail"` 또는 `"host"`)을 기록한다. 진단 CLI 경로(`ceb track-b official run`)는
호스트 빌드를 유지하며 **항상 `verified=false`**다 —
`run_official_track_b`는 `build_isolation="host"`로 `verified=True`를 거부한다.

### Track B 베이스라인 신뢰 (req3)

verified Track B는 **신뢰된 베이스라인**에 대해서만 채점된다
(`bench/ceb/track_b/baseline_trust.py::validate_track_b_baseline`). 신뢰 모드는
세 가지다:

- **stockfish-lock** — 베이스라인 트리의 git HEAD가
  `tracks/b_stockfish_opt/stockfish.lock`의 고정 커밋과 일치하고, **추가로**
  작업 트리가 깨끗하며(`git_worktree_clean`: `git status --porcelain
  --untracked-files=all`이 비어 있음), **서브모듈도 깨끗해야**(`git_submodules_clean`)
  한다. 이 세 조건을 모두 만족할 때만 신뢰되고, 그때 콘텐츠 해시
  `baseline_tree_hash`를 기록한다. **더럽거나(dirty) 추적되지 않은(untracked)
  파일이 있는 체크아웃은 stockfish-lock으로 신뢰되지 않으며**, hash 모드로
  떨어지거나 실패한다 — 채점되는 바이너리가 고정 소스와 다를 수 있기 때문이다.
- **hash** — 베이스라인 트리의 콘텐츠 해시가 운영자 허용 목록에 있다
  (`--track-b-baseline-hash` / `CEB_TRACK_B_BASELINE_HASHES` /
  `--track-b-baseline-registry`). `.git`이 없는 스냅샷 베이스라인은 이 허용
  목록 해시 모드로 신뢰된다.
- **toy** — `--dev-allow-toy-baseline`로 미신뢰 토이 베이스라인을 허용하되
  결과를 `verified=false`(등급 `diagnostic-untrusted-baseline`)로 강등한다.

어느 모드에도 해당하지 않고 토이 플래그도 없으면 평가가 거부된다. 메타데이터
`track_b`는 `baseline_trusted`, `baseline_trust_mode`, `baseline_tree_hash`,
`stockfish_lock`을 기록한다.

### 빌드 출력 강화 (req5)

감옥 빌드 직후, 엔진을 한 번도 실행하기 전에 빌드 출력 트리를 검증한다
(`bench/ceb/track_b/build_jail.py::validate_build_output`): 엔진은 존재해야 하고,
실행 가능해야 하며, 심링크가 아닌 일반 파일이어야 한다. 출력 트리 어디에도
심링크가 없어야 하고, 총 크기는 최대 512 MiB, 파일 수는 최대 10,000개다. 이를
어기면 `BuildJailError`로 거부된다. 빌드 출력 트리 해시는 메타데이터
`track_b.build_output`(baseline/candidate 출력 해시)에 기록된다.

### Track B bench/속도 정합성 (req6)

verified Track B는 baseline과 candidate 모두에 `bench`를 돌린다
(`bench/ceb/track_b/bench_sanity.py::run_bench_sanity`). 리포트는 엔진별
`nodes`/`nps`/`output_hash`와 `nps_ratio`를 기록한다. NPS 비율 임계값
(`--bench-min-nps-ratio`, 기본 0.3)은 **두 엔진이 모두 bench를 지원할 때에만**
강제된다 — 토이 엔진은 `supported=false`를 보고하며 허용되고, 너무 느린 후보만
의심 대상이다. bench 실행 시 jailing이 켜져 있으면 후보는 감옥에 갇혀 bench를
돈다. **`--dev-allow-no-bench`는 verified를 유지하지 않는다**: NPS 실패를 건너뛰는
대신 결과를 `verified=false`(등급 `diagnostic-no-bench`)로 강등하므로 bench
실패가 리더보드에 닿을 수 없다. 플래그가 없으면 bench 실패는 하드 실패다.
실제 공개 Track B는 bench를 지원하는 고정 Stockfish가 필요하다.

### 공개 아티팩트 스테이징 → 스캔 → 승격

공개 공식 평가는 공개 파일을 직접 쓰지 않는다(`bench/ceb/storage/promotion.py`).
공개 예정 아티팩트는 먼저 **스테이징**되어 쓰인다: 파일은 디스크에 존재하지만
매니페스트 항목은 `visibility: private` + `staged_public` 마커이므로 아무것도
이를 제공하지 않는다(`write_staged_public_artifact`,
`round_runner`의 `run_round` `stage_public=True`). 재귀 누출 스캐너
(`scan_public_artifacts(..., staged=True)`)가 스테이징된 집합 전체를 스캔하고,
**통과한 경우에만** `promote_public_artifacts`가 이들을 `visibility: public`으로
승격한다. 누출 시 워커는 아무것도 공개로 등록하지 않으며, 해당 잡 시도에 대한
공개 매니페스트 항목 자체가 존재하지 않는다. Track A(`official_eval`)와
Track B(`official_pipeline`) 모두 이 스테이징 → 스캔 → 승격 순서를 따른다.

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
스냅샷과 해시, `build_script`, `engine_relpath`를 저장한다. 관리자 전용 API
`POST /api/hosted/runs/{run_id}/track-b-submissions`는 JSON `{candidate_src,
baseline_src, build_script?, engine_relpath?}`를 받아 candidate+baseline을
스냅샷(심링크/위험 파일 거부)·해시하고, track B 실행을 만들거나 사용하고,
`track_b_official_eval` 잡을 큐에 넣은 뒤 `submission_id`/`candidate_hash`/
`baseline_hash`/`job_id`를 반환한다. **신뢰된 빌드 래퍼는 워커에
(`--build-wrapper`) 공급되며, 후보가 절대 제공하지 않는다.**

verified Track B 요건: 소스 우선(source-first) + diff 화이트리스트 + 콘텐츠
스캔에 더해 verifiable 프로파일 + **고정된** 신뢰 공식 오프닝 팩(req1) +
**신뢰된 베이스라인**(req3) + 격리된 빌드 감옥(**해시 고정** 신뢰 래퍼,
`build_isolation="jail"`, req4) + **검증된 빌드 출력**(req5) +
**bench/속도 정합성**(req6) + candidate 엔진 Docker 감옥(P0.1) + 스테이징된
공개 아티팩트 누출 스캔(P0.8) + Ed25519 서명이다. 미신뢰/미고정 앵커는 순서대로
게이트되며(`track_b_eval.py::run_hosted_track_b`의 `gate`), 첫 번째 미신뢰
앵커가 진단 등급을 결정한다. 결과는 `mode=track_b_official`, 점수는 final delta
Elo이며, `verified_leaderboard(track="B")`가 이를 자체 final-tier로 다룬다.
테스트는 토이 트리로 하고, verified 경로는 Docker opt-in(`CEB_DOCKER_TESTS=1`)
이다. 실제 고정 Stockfish 빌드 래퍼는 운영자 단계다.

## 안전 업로드 (P1.2)

관리자 인증 `POST /api/hosted/runs/{run_id}/upload`(`bench/ceb/api/main.py`)는
요청 본문을 `async for chunk in request.stream()`으로 임시 파일에 **스트리밍**하며,
읽는 동안 `_MAX_UPLOAD_BYTES`(200 MiB)를 초과하면 413으로 거부한다(임시 디렉터리는
어떤 실패에도 삭제된다) — 전체 본문을 메모리에 적재하지 않는다. 자체 본문 한도를
가진 리버스 프록시 뒤에 배포하라(예: nginx `client_max_body_size`).

`bench/ceb/hosted/upload.py::safe_extract_archive`는 `.tar.gz`/`.tar`/`.zip`
작업공간 업로드를 추출하되, 쓰기 전에 고전적 아카이브 공격을 거부한다:
심볼릭/하드 링크, 절대 경로, 경로 탐색(`..`), 비정규 멤버(디바이스/fifo),
과대 파일/총량(파일당 50 MiB, 합계 200 MiB, 멤버 10,000개 상한). `extractall`을
**쓰지 않고** 멤버를 하나씩 검증하여 직접 쓴다. 추출 후 호출자가 트리를
스냅샷하고 해시한다. 진입점은 CLI `ceb hosted submit --archive`와 위 업로드
엔드포인트다.

## 결과 번들 내보내기 (P1.3)

`ceb hosted result export --run-id --db --out <zip> [--release-manifest <path>]
[--public-key <pem> | --public-key-fingerprint <fp>]`
(`bench/ceb/hosted/result_bundle.py`)는 기본적으로 `select_best_verified_result`로
고른 **단일 best verified 결과의 공개 아티팩트만** zip으로 묶는다(그 결과의
잡 시도 디렉터리 아래의): 서명된 `official_result.json`(메타데이터 + 서명 블록
포함), `feedback.json`, `report.public.json`, 그리고 `bundle_manifest.json`과
`VERIFY.txt`. v0.3.4부터 선택-전용 공개 번들은 **릴리스 매니페스트
(`release_manifest.json`)와 운영자 공개 키 핑거프린트**를 함께 담을 수 있으며,
`VERIFY.txt`는 대역외 공개 키 / 릴리스 매니페스트 핑거프린트에 대조해 검증하는
지침을 담는다. smoke/이전/비선택 결과나 비공개 아티팩트(스캔/누출 리포트, 매치
로그, 게임 텍스트)는 결코 포함되지 않으며, 비공개 키나 숨겨진 팩 데이터도
결코 담지 않는다. `--include-all-public`은 모든 공개 아티팩트를 담는 진단용
번들로, **비공식임이 명확히 표시**된다. verified 결과가 없으면 기본 내보내기는
오류를 낸다. `bundle_manifest`는 `schema`/`version`/`selected_result_id`/
`selected_mode`/`selected_grade`/`official`/`selected_only`를 담는다. 제3자가
운영자의 공개 키로 결과 진정성을 독립적으로 검증하는 데 필요한 것만 담는다.

## 공식 준비도 점검 — strict가 유일한 선언 게이트다 (req10)

`ceb hosted readiness check --strict-public-official --db --eval-pack
--public-key --track [--build-wrapper] [--signing-key] [--official-pack-hash]
[--official-pack-registry] [--track-b-baseline-hash] [--build-wrapper-hash]
[--require-server] [--json]`(`bench/ceb/hosted/readiness.py`, 스키마
`ceb.hosted.readiness/v2`)은 배포가 공개 공식 결과를 만들 수 있는지를 점검한다.
`--strict-public-official`를 주면 핀 / 공개 키 / 키쌍 일치 / 베이스라인 / 래퍼
해시 앵커가 경고가 아니라 **차단(required) 점검**이 된다. 이 strict 점검이
"Track A·B 공개 공식 준비 완료"의 **유일한 선언 게이트**다.

리포트는 전체 `ready` 불리언에 더해 **`public_official_declaration`**
(`"ready"`/`"not-ready"`)과 **`blocking_failures`**(실패한 required 점검 이름
목록)를 담는다. **버전 바닥선은 이제 0.3.4**다(`_MIN_VERSION = (0, 3, 4)`).
**`--track BOTH`**가 지원되어 Track A 팩 점검과 모든 Track B 점검을 함께
돌린다. CLI **`--json` 플래그는 JSON만 출력**하여 기계 파싱이 깨끗하다
(사람용 텍스트와 섞이지 않음).

Track A strict 점검: 버전 0.3.4 이상, DB 마이그레이션, docker, 엔진 감옥 이미지,
신뢰되고 **고정된** 공식 eval 팩, 데모 팩 거부, Ed25519 키, 공개 키, **키쌍
일치**, smoke 비verifiable, official/final-production verifiable,
final-production 게임 바닥선(2016 >= 2000). Track B strict는 추가로: 빌드 감옥
이미지, 빌드 래퍼 존재/실행 가능/트리 밖/해시 고정, `track_b_baseline_trust`
(콘텐츠 해시 핀 또는 깨끗한 stockfish-lock), bench 정책(강제되며 우회 불가:
bench 실패나 `--dev-allow-no-bench`는 강등할 뿐 결코 verified가 아님),
`track_b_api_endpoint` 임포트 가능을 확인한다.

JSON 리포트는 `checks[name, ok, required, detail]`와 전체 `ready`,
`public_official_declaration`, `blocking_failures`를 담고, 사람용 요약도
출력하며, 준비되지 않았으면 0이 아닌 값으로 종료한다.

## 공개 릴리스 매니페스트 (req9)

`ceb hosted release-manifest create --track --eval-pack --official-pack-hash
--public-key [--track-b-baseline-hash --build-wrapper-hash] --out`
(`bench/ceb/hosted/release_manifest.py`, 스키마 `ceb.release_manifest/v1`)은
한 시즌의 모든 공개 공식 신뢰 앵커를 고정하는 **비밀 없는** 매니페스트를
방출한다: `benchmark_version`, `git_commit`, `track`, `season`,
`official_eval_pack_id`/`_hash`/`_manifest_hash`,
`operator_public_key_fingerprint`(**키 자체는 절대 아님**),
`engine_jail_image` + 다이제스트, Track B의 베이스라인·래퍼 해시 +
`build_jail_image_digest`, `leaderboard_policy`, `known_limitations`. v0.3.4는
Track B 매니페스트에 **`track_b_baseline_trust_mode`(`"hash"`)**와
**`bench_policy`**(`min_nps_ratio`, `enforced_when_baseline_supports_bench`,
`override_downgrades_to_diagnostic`)를 더해, 매니페스트만 보고도 베이스라인이
콘텐츠 해시로 고정되며 bench 정책이 우회 불가(override는 진단으로 강등)임을
알 수 있다. **비밀 없음**: 비공개 키도, 비공개 eval 팩 경로도, 숨겨진
FEN/오프닝 id도, 비공개 아티팩트 경로도 담지 않는다. 매니페스트 생성은
**고정된** 공식 팩 해시와 공개 키를 요구하며(없으면 거부), Track B는 정확히
하나의 베이스라인 해시와 하나의 래퍼 해시를 요구한다(모호하면 오류). 공개
리더보드가 이 매니페스트를 게시하여 누구나 그 시즌이 쓴 앵커를 확인할 수 있다.

## API 표면 (req8)

`bench/ceb/api/main.py`. `GET /api/leaderboard?track=B`는 호스팅된 DB가 있으면
verified 호스티드 Track B 리더보드(`verified_leaderboard(track="B")`)로
위임하고, 없으면 `GET /api/hosted/leaderboard?track=B`를 가리킨다. 비밀 없는
엔드포인트 `GET /api/hosted/readiness/public`(스키마
`ceb.hosted.readiness.public/v1`)은 버전·정책·프로파일 verifiability만 노출하며
운영자 전용 앵커(eval 팩, 키, 이미지)는 노출하지 않는다 — 그것은 CLI
`ceb hosted readiness check --strict-public-official`로 확인한다.

v0.3.4 신규 **공개** 엔드포인트 `GET /api/hosted/release-manifest`는
`CEB_RELEASE_MANIFEST` 경로의 릴리스 매니페스트를 그대로 제공한다(미설정 시
503, 파일 없으면 404). **공개 GET이므로 관리자 토큰이 필요 없다** — 매니페스트가
구조적으로 비밀 없음이기 때문이다. 관리자 POST/업로드 엔드포인트는
`CEB_ADMIN_TOKEN`이 설정되지 않으면 503으로 남고, 토큰 비교는 **상수 시간**
`hmac.compare_digest`로 수행한다(`_require_admin`, 타이밍 공격 방지).
스트리밍 업로드(아래 "안전 업로드")는 그대로다. API를 통한 Track B 아카이브
업로드는 향후 과제이며, 현재는 서버 로컬 `candidate_src`/`baseline_src`를 쓴다.

## 에이전트 궤적 스키마 (P1.4, 선택)

`bench/ceb/agent_trajectory.py`는 선택적 스키마 `ceb.agent.trajectory/v1`을
제공한다: `model_id` / `agent_id` / `prompt_version` / `tool_budget` /
`gate_attempts` / `round_attempts` / `command_log_hash` /
`source_snapshot_hash`. 비공개 사고 과정(chain of thought)은 요구하지 않는다.

## 스키마 버전

결과 `ceb.hosted.official_result/v2`, 리더보드 `ceb.hosted.leaderboard/v2`,
잡 `ceb.hosted.job/v2`이며, v2는 `profile` + `verification_grade` + Track B
지원을 더한다. 검증기는 하위 호환을 위해 v1 결과 파일도 수용한다. 준비도
`ceb.hosted.readiness/v2`는 strict 앵커 + per-check 결과에 더해
`public_official_declaration`과 `blocking_failures`를 담는다. 그 밖의 스키마:
공개 준비도 `ceb.hosted.readiness.public/v1`, 릴리스 매니페스트
`ceb.release_manifest/v1`(Track B에서 `track_b_baseline_trust_mode`와
`bench_policy` 포함), 베이스라인 신뢰 보고, bench 정합성
`ceb.track_b.bench_sanity/v1`.

## 비목표 / 아직 집행되지 않음 (정직한 한계)

- **호스트 실행이 여전히 기본값이다(비호스팅 CLI).** `--engine-jail none`(과
  `--sandbox none`)은 제출물을 당신 사용자의 평범한 자식 프로세스로 실행하며,
  파일시스템/네트워크/리소스 격리가 없다. 공식 워커 CLI는 `--engine-jail
  docker`를 기본값으로 두고 verified를 위해 그것을 *요구*하지만, 로컬 CLI 라운드는
  운영자가 감옥을 선택해야 한다.
- **단일 노드 호스팅.** 호스팅된 파이프라인은 SQLite + 로컬 오브젝트 디렉터리
  (`<db>_store/`)다 — 정직한 범위로 유지되며 분산 프로덕션 서비스가 아니다.
  `claim_next_job`은 한 DB의 여러 워커를 안전하게 다루지만, 분산 큐도, 멀티
  테넌트 격리도, 테넌트별 리소스 회계도 없다.
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
| 신뢰된 공식 팩만 verified; 커밋된 데모 팩은 결코 verified 불가 | `hosted/eval_pack_trust.py::validate_official_eval_pack` | `tests/test_eval_pack_trust.py::test_official_pack_validates_and_reports_hashes`, `test_demo_pack_cannot_be_official`, `test_committed_demo_path_rejected_even_with_manifest`, `test_allowlist_must_match` |
| verified는 팩 해시 핀 요구; 핀 없으면 평가 전 거부 (req1) | `hosted/eval_pack_trust.py::resolve_hash_allowlist`, `hosted/official_eval.py`, `hosted/track_b_eval.py` | `tests/test_hosted.py::test_official_eval_requires_pinned_pack` |
| verified는 Ed25519 서명 요구; 키 없으면 거부(또는 강제 비검증) | `hosted/signing.py`, `hosted/official_eval.py`, `hosted/verifier.py` | `tests/test_hosted.py::test_official_eval_requires_ed25519_key` |
| Ed25519 키는 스캔/게이트/빌드/매치 이전에 로드 검증; malformed 키는 조기 하드 실패(좌초 아티팩트 없음) | `hosted/signing.py::require_ed25519_private_key`, `hosted/official_eval.py`, `hosted/track_b_eval.py` | `tests/test_signing.py`, `tests/test_hosted.py::test_official_eval_requires_ed25519_key` |
| Track B 베이스라인은 신뢰되어야 (stockfish-lock/hash/toy) (req3); stockfish-lock은 깨끗한 작업 트리·서브모듈도 요구 | `track_b/baseline_trust.py::validate_track_b_baseline`, `git_worktree_clean`, `git_submodules_clean` | `tests/test_track_b_official.py::test_baseline_trust_stockfish_lock_mode`, `test_baseline_trust_hash_mode`, `test_baseline_trust_toy_and_untrusted` |
| verified Track B는 빌드 감옥 + 트리 밖 신뢰 래퍼; 호스트 빌드는 verified 불가 | `track_b/build_jail.py::build_in_jail`, `hosted/build_wrappers.py::validate_build_wrapper`, `track_b/official_pipeline.py` | `tests/test_track_b_official.py::test_validate_build_wrapper`, `test_run_official_track_b_validates_wrapper_outside_tree`, `test_run_official_track_b_refuses_verified_host_build` |
| 빌드 출력 검증: 일반-파일 엔진/심링크 없음/크기·파일 수 상한 (req5) | `track_b/build_jail.py::validate_build_output` | `tests/test_track_b_official.py::test_validate_build_output` |
| bench/속도 정합성: NPS 비율은 두 엔진 bench 지원 시에만 강제 (req6); `--dev-allow-no-bench`는 verified 유지 못 하고 `diagnostic-no-bench`로 강등 | `track_b/bench_sanity.py::run_bench_sanity`, `track_b/official_pipeline.py`, `hosted/profiles.py` | `tests/test_track_b_official.py::test_bench_sanity_nps_threshold`, `test_bench_sanity_unsupported` |
| 공개 아티팩트는 스테이징 후 스캔 통과 시에만 공개로 승격; 누출 시 아무것도 공개 안 됨 (req7) | `storage/promotion.py`, `scan/leak_scan.py::scan_public_artifacts` | `tests/test_hosted.py::test_official_eval_refuses_when_public_artifact_would_leak`, `test_leak_scan_catches_nested_public_report`, `test_failed_leak_scan_leaves_no_public_artifacts` |
| 공개 아티팩트 누출 스캐너가 숨겨진 비밀 노출 시 verified 거부; 해시만 기록 | `scan/leak_scan.py::scan_public_artifacts`, `hosted/official_eval.py` | `tests/test_scan.py` (누출 스캔 테스트) |
| 숨겨진 오프닝 오류는 보드/수를 보류; 행 id + basename 인용 | `sanitize.py`, `match/openings.py`, eval 팩 로더 | `tests/test_sanitization.py::test_hidden_opening_illegal_move_does_not_leak_board`, `test_hidden_suite_file_errors_use_basename` |
| 알려지지 않은 예외는 보류; CLI는 정제된 한 줄 반환, rc 3 | `sanitize.py::sanitize_exception`, `cli.py::main` | `tests/test_sanitization.py::test_cli_unknown_exception_is_withheld`, `test_cli_returns_sanitized_error_not_traceback` |
| Track A 스캐너가 부정행위 표시 (라이브러리/엔진/네트워크/생성/핑거프린트/바이너리/심링크/과대) | `scan/static_scan.py` | `tests/test_scan.py::test_python_chess_import_fails`, `test_stockfish_invocation_fails`, `test_network_usage_fails`, `test_harness_fingerprinting_fails`, `test_symlink_escape_fails`, `test_book_extension_and_oversize_fail` |
| Track B 스캐너가 금지된 diff, 핑거프린팅, 심링크 표시 | `scan/track_b_scan.py` | `tests/test_scan.py::test_track_b_forbidden_change_fails`, `test_track_b_fingerprinting_and_symlink_fail` |
| 잡 클레임은 원자적; lease 만료 시 회수 | `hosted/db.py::claim_next_job` | `tests/test_hosted.py` (원자적 클레임/회수 테스트) |
| 워커만 검증된 결과 생성; 팩 없음 / 스캔 실패 / 게이트 실패 시 거부 | `hosted/worker.py`, `hosted/official_eval.py` | `tests/test_hosted.py::test_worker_produces_verified_result`, `test_worker_refuses_without_eval_pack`, `test_worker_refuses_when_scan_fails`, `test_worker_refuses_when_strict_gate_fails` |
| 제출물은 스냅샷됨; 심링크 거부 | `hosted/submissions.py::snapshot_workspace` | `tests/test_hosted.py::test_snapshot_rejects_symlinks` |
| 안전 업로드가 링크/탐색/절대경로/과대 멤버 거부 | `hosted/upload.py::safe_extract_archive` | `tests/test_hosted.py` (안전 추출 테스트) |
| 스트리밍 업로드가 200 MiB 한도 초과 시 413 거부 | `api/main.py::hosted_upload` | `tests/test_hosted.py::test_api_upload_streaming_rejects_oversized` |
| 준비도 점검: 데모 팩이면 not ready, 공식 셋업이면 ready | `hosted/readiness.py::readiness_check` | `tests/test_hosted.py::test_readiness_check_not_ready_with_demo_pack`, `test_readiness_check_ready_with_official_setup` |
| strict 준비도: 핀/공개 키/키쌍 일치/베이스라인/래퍼 핀이 차단 점검 (req2/req10) | `hosted/readiness.py::readiness_check` (strict) | `tests/test_readiness.py::test_strict_readiness_track_a_pass`, `test_strict_readiness_fails_without_pin`, `test_strict_readiness_fails_without_public_key`, `test_strict_readiness_fails_mismatched_keypair`, `test_strict_readiness_track_b_requires_baseline_and_wrapper`, `test_strict_readiness_track_b_pass`, `test_non_strict_readiness_pinning_is_warning` |
| 릴리스 매니페스트는 비밀 없음; 공개 키 핑거프린트만, 핀 요구 (req9) | `hosted/release_manifest.py::build_release_manifest` | `tests/test_release_manifest.py::test_release_manifest_track_a`, `test_release_manifest_requires_pin`, `test_release_manifest_rejects_demo_pack`, `test_release_manifest_track_b_requires_baseline_and_wrapper`, `test_release_manifest_cli` |
| 공개 readiness 엔드포인트는 비밀이 없음; Track B 리더보드 위임 (req8) | `api/main.py::hosted_readiness_public`, `leaderboard` | `tests/test_hosted.py::test_api_public_readiness_has_no_secrets` |
| 공개 release-manifest 엔드포인트는 관리자 토큰 불필요; 미설정 503 / 파일 없음 404; 비밀 없음 | `api/main.py::hosted_release_manifest` | `tests/test_hosted.py` (공개 매니페스트 테스트) |
| 준비도는 단일 선언 게이트; `public_official_declaration`/`blocking_failures` 방출, `--track BOTH`, `--json`은 JSON만 | `hosted/readiness.py::readiness_check`, `cli.py::cmd_hosted_readiness_check` | `tests/test_readiness.py` (선언/BOTH/json 테스트) |
| 호스팅된 리더보드는 검증된 것 전용; 단일 best verified 선택 공유 | `hosted/db.py::verified_leaderboard`, `select_best_verified_result` | `tests/test_hosted.py::test_hosted_leaderboard_is_verified_only`, `test_self_reported_rounds_never_appear_verified` |
| 결과 번들은 선택된 single best verified 결과의 공개 아티팩트만; 비공개/비선택 제외; 선택 시 릴리스 매니페스트·공개 키 핑거프린트 포함 | `hosted/result_bundle.py::export_result_bundle`, `select_best_verified_result` | `tests/test_hosted.py` (번들 내보내기 테스트) |
| API는 공개 아티팩트만 제공; 경로 순회(traversal) 거부 | `api/main.py::hosted_artifact` | `tests/test_hosted.py::test_api_private_artifact_not_served`, `test_api_path_traversal_rejected` |
| API 관리자 POST는 상수 시간 토큰 비교로 게이팅 (미설정 503 / 잘못된 토큰 403) | `api/main.py::_require_admin` (`hmac.compare_digest`) | `tests/test_hosted.py::test_api_admin_endpoints_gated` |
| 서명: 왕복, 변조 탐지, 잘못된 키, unsigned은 절대 진정하지 않음 | `hosted/signing.py` | `tests/test_signing.py::test_sign_and_verify_roundtrip`, `test_tampered_result_fails_verification`, `test_wrong_key_fails_verification`, `test_unsigned_mode_is_explicit_and_never_authentic` |
| 재현성 메타데이터가 완전함; eval 팩 해시는 내용에 바인딩됨 | `hosted/metadata.py::build_metadata`, `hash_directory` | `tests/test_signing.py::test_metadata_required_keys`, `test_eval_pack_hash_changes_with_contents` |
| 레거시 `--sandbox docker`는 잠긴 상태 유지하고 중첩 거부 | `sandbox/docker_runner.py` | `tests/test_sandbox_docker.py::test_gate_argv_is_locked_down`, `test_recursion_guard` |
| UCIClient 프로세스 수준 안전성 (argv 전용, 타임아웃, 제한된 수용) | `uci/client.py` | `tests/test_uci_client.py` |

제출물에 대한 정책 수준 규칙(네트워크 금지, 하네스 내부 읽기 금지)과 그
결과는 `specs/forbidden_behaviors.md`에 규범적으로 명시되어 있다.
