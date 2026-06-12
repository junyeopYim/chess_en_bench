# Track B — 소스 우선 공식 파이프라인

이것은 Track B 후보 *소스 트리*를 채점되고 서명된 델타 Elo 결과로 바꾸는
소스 빌드 경로다. 실행 파일만 다루는 `ceb track-b round run`(이미 빌드한 두 엔진을
대국시킴)과 나란히 존재한다. 트랙 규칙, diff 화이트리스트, 고정 베이스라인, 델타
Elo 채점은 `docs/track_b_stockfish_optimization.md`를 참고하라.

핵심은 **빌드 격리**다. 본문(`run_official_track_b`,
`bench/ceb/track_b/official_pipeline.py`)은 `build_isolation` 인자로 두 가지
빌드 전략 중 하나를 고른다:

- `"host"` — 각 트리가 자체 제공하는 빌드 스크립트를 **호스트에서** 실행한다.
  **진단 전용**이며 결코 verified가 되지 않는다.
- `"jail"` — Docker **빌드 감옥** 안에서, 후보/베이스라인 트리 바깥에 있는
  **신뢰된 운영자 래퍼**로 빌드한다. 이것이 verified 경로다.

`run_official_track_b`는 `verified=True`이면서 `build_isolation != "jail"`이면
즉시 거부한다 — 호스트 빌드는 verified 결과를 만들 수 없다. 두 빌드 전략 모두
스캔 통과 후 같은 래퍼/스크립트로 베이스라인과 후보를 **동일하게** 빌드하고,
산출 결과를 STAGED 공개 아티팩트로 쓴 뒤 누출 스캔하고 통과 시에만 공개로
승격한다.

두 가지 진입점이 있고, 혼동해서는 안 된다:

- **진단 CLI**: `ceb track-b official run` (`cmd_track_b_official_run`). 항상
  `build_isolation="host"`, `verified=False`로 호출한다. 직접 실행은
  자가보고/진단용이며 결코 verified가 아니고 리더보드에 오르지 않는다.
- **호스티드 verified 경로**: 관리자 제출(API 또는 `ceb hosted submit-track-b`)
  → 호스티드 워커(`ceb hosted worker run-once`) → `run_hosted_track_b`
  (`bench/ceb/hosted/track_b_eval.py`) → `build_isolation="jail"`의
  `run_official_track_b`. 모든 verified 게이트를 만족할 때만 `verified: true`를
  생성하며, 이것만이 호스티드 리더보드(`track="B"`)에 오른다.

**v0.3.5 verified Track B 신뢰 앵커.** v0.3.2의 보증(빌드 감옥 격리, engine
jail, Ed25519, STAGED→스캔→승격) 위에 다음이 **추가로 필수**다. 각 앵커는
신뢰되지 않으면 평가 전에 hard-fail하거나, 해당 DEV 플래그가 있으면 결과를
진단 등급(`verified=false`, 리더보드 제외)으로 강등한다. **어떤 `--dev-*`
플래그도 `verified=true`를 유지시키지 못한다 — 검증 가능한 실행을 실패시키거나
진단(미검증) 등급으로 강제한다.** 첫 번째 미신뢰 앵커가 등급을 결정한다
(`run_hosted_track_b`의 `gate()` 헬퍼):

- **고정된 신뢰 공식 eval 팩**(req1) — 팩 콘텐츠 해시가 허용 목록에 PIN되어야
  한다.
- **신뢰된 베이스라인**(req3) — 콘텐츠 해시 허용 목록, 또는 **깨끗한 작업
  트리**의 고정 Stockfish 체크아웃.
- **해시-고정된 빌드 래퍼**(req4) — 래퍼 파일 해시가 허용 목록에 PIN.
- **검증된 빌드 산출**(req5, 빌드 감옥 안) + **bench/속도 정합성**(req6) —
  verified Track B는 bench가 신뢰된 베이스라인 **및** 후보 양쪽에서 **지원
  (supported)**되어야 한다. 베이스라인이 NPS를 보고하지 못하면(미지원) verified는
  **실패**한다(예전의 "미지원 = 조용한 통과"는 사라졌다). bench 실패나
  `--dev-allow-no-bench`는 verified를 유지하지 못하고 `diagnostic-no-bench`로
  강등한다. verified 경로에서 후보 bench 명령을 engine jail 안에서 구성하지
  못하면 후보 bench는 **거부**되며 호스트에서 대체 실행되지 않는다(no host
  fallback).

저장소가 "Track A·B용 공개 공식 단일 노드 호스티드 벤치마크 준비 완료"로
선언되는 것은 **오직** `ceb hosted readiness check --strict-public-official`이
통과할 때뿐이며, 이 strict readiness가 단일 선언 게이트다. 단일 노드(SQLite +
로컬 FS)임을 정직하게 유지하며 분산 프로덕션 서비스가 아니다.

아래에서 두 경로를 차례로 설명한다.

## 진단 CLI: `ceb track-b official run` (verified=false)

```bash
ceb track-b official run \
  --candidate-src /path/to/candidate \
  [--baseline-src third_party/stockfish] \
  [--eval-pack DIR] \
  [--engine-jail none|docker] \
  [--build-script ceb_build.sh] \
  [--engine-relpath ceb_engine] \
  [--games 8] [--movetime 100] [--max-plies 300] \
  [--run-id track_b_official] [--runs-dir DIR]
```

- `--candidate-src`는 필수다.
- `--baseline-src`의 기본값은 `third_party/stockfish`다. 그 디렉터리가 없고
  `--baseline-src`도 주어지지 않으면 파이프라인은 `scripts/setup_stockfish.sh`와
  고정 태그(`sf_18`)를 가리키는 메시지와 함께 중단한다.
- `--build-script`(기본 `ceb_build.sh`)와 `--engine-relpath`(기본 `ceb_engine`)는
  각 트리가 제공하는 빌드 래퍼와 그것이 산출하는 엔진의 이름을 지정한다.
  베이스라인과 후보는 **동일한** 빌드 스크립트와 엔진 relpath로 빌드된다.
- `--engine-jail docker`는 후보 엔진만 가둔다(아래 참고).
- 모든 중단(스캔 실패, 빌드 스크립트 누락, 빌드 실패, handshake 실패)에서 종료
  코드 2이며, 위생 처리된 한 줄 메시지가 함께 나온다.

CLI는 `run_official_track_b(..., build_isolation="host", verified=False)`를
호출하므로 **항상 호스트 빌드 + `verified: false`**다. 각 트리의 빌드 스크립트가
호스트에서 신뢰되어 실행되는데, 이는 본질적으로 진단용이다 — `verified=True`와
호스트 빌드는 코드에서 함께 거부된다.

### 무엇이, 어떤 순서로 실행되는가 (호스트 빌드)

`run_official_track_b`는 엄격히 다음 순서로 실행한다:

1. **verified/격리 정합성 확인.** `verified=True`인데 `build_isolation != "jail"`
   이면 중단한다.
2. **베이스라인 트리 해소.** `--baseline-src`, 또는 고정된 `sf_18` / `cb3d4ee`
   상태의 `third_party/stockfish`. (고정값은 `tracks/b_stockfish_opt/stockfish.lock`에
   있다. 파이프라인은 커밋 해시를 재검증하지 않는다 — 그것은
   `scripts/setup_stockfish.sh` / `ceb track-b status`의 일이다.)
3. `scan_track_b`(`bench/ceb/scan/track_b_scan.py`)로 베이스라인 대비 후보를
   **스캔**: diff 화이트리스트(`allowed_paths.txt` / `forbidden_paths.txt`) 및
   콘텐츠 규칙(바이너리/NNUE/북/테이블베이스 페이로드, 하네스 핑거프린팅, 변경된
   소스에 도입된 네트워크/프로세스 syscall, 심볼릭 링크). `fail` 발견 또는
   화이트리스트 위반이 있으면 **무엇도 빌드하기 전에** 중단한다.
4. **베이스라인 빌드**, 그 다음 **후보 빌드**(`_build_tree_host`). 각각 트리를
   작업 디렉터리로 하여 `bash <build-script>`를 실행한다(빌드 타임아웃 1800초).
   0이 아닌 종료, 스크립트 누락, 또는 `<engine-relpath>`를 산출하지 못하는 빌드는
   중단을 일으킨다. 산출된 엔진은 실행 가능하게 만들어진다(`chmod +x`).
5. **bench/속도 정합성**(req6, `_run_bench`): 베이스라인과 후보에 각각 `bench`를
   실행해 nodes/nps/output_hash를 기록한다. 호스트 빌드(토이 엔진)는 보통
   `supported=false`라 NPS 비율을 강제하지 않는다.
6. `run_track_b_round`(internal 러너 — 신뢰된 레퍼런스)를 통해 **후보-대-베이스라인
   쌍 매치 진행**. UCI handshake, 쌍 색-교대 오프닝, 양쪽 엔진에 `Threads=1` /
   `Hash=16`, 델타 Elo 채점.
7. **메타데이터 조립**(`build_metadata`)과 `track_b` 블록 추가:
   `baseline_tree_hash`/`candidate_tree_hash`(`hash_directory`를 통한 트리별
   sha256), `build_isolation`, `build_script`(jail이면 None), `build_wrapper`
   (jail에서만 채워짐), `build_wrapper_hash`/`build_wrapper_trusted`,
   `build_output`(jail에서만), `build_jail_image_digest`(jail에서만), `bench`,
   그리고 베이스라인 신뢰 정보 `baseline_trusted`/`baseline_trust_mode`/
   `stockfish_lock`.
8. 결과 **서명**(`sign_official_result`)과 STAGED 공개 산출물 작성.
9. eval 팩이 주어진 경우 STAGED 아티팩트에 대해 **공개 아티팩트 누출 스캔**
   (`scan_public_artifacts(..., staged=True)`)을 실행한다. 누출이 발견되면
   중단한다.
10. **승격**(`promote_public_artifacts`): 누출 스캔을 통과한 STAGED 아티팩트만
    `visibility=public`으로 올린다.

### 출력

스키마 `ceb.track_b.official_result/v1`의 단일 결과 dict이며 다음을 포함한다:
`run_id`, `track`, `round`, `finished_at`, `engine_jail`, `build_isolation`
(`"host"`|`"jail"`), `scan.passed`, `score`(`ceb.score.track_b/v1`: W/D/L,
결함, `delta_elo`, `delta_elo_ci95`, 페널티, `final_delta_elo`), `feedback`,
`metadata`(`track_b` 블록은 트리 해시/격리 정보 + 위의 v0.3.5 신뢰 필드
[`baseline_trusted`/`baseline_trust_mode`/`baseline_tree_hash`/`stockfish_lock`,
`build_wrapper_hash`/`build_wrapper_trusted`, `build_output`,
`build_jail_image_digest`, `bench`] + bench 정책 필드 [`bench_required`,
`bench_supported`, `bench_passed`, `nps_ratio`, `min_nps_ratio`, 그리고
`bench_policy` 객체(`supported_required_for_verified`,
`enforced_when_baseline_supports_bench`, `override_downgrades_to_diagnostic`)]
포함; verified일 때 `eval_pack_trusted`,
`eval_pack_id`, `eval_pack_manifest_hash`, `eval_pack_track`,
`eval_pack_season`), `verified`, 그리고 `signature` 블록. 호스티드 경로에서는
`profile`과 `verification_grade`도 추가된다.

`runs/<run-id>/track_b_official_<round>/` 아래의 산출물:

- `official_result.json` — 공개(위의 결과). 먼저 STAGED로 쓰이고 누출 스캔
  통과 후 승격된다.
- `scan_report.json` — 비공개(전체 스캔 발견 사항).
- `leak_scan.json` — 비공개(eval 팩이 주어졌을 때, 비밀을 직접 echo하지 않고
  해시만 기록).

서명은 `sign_official_result`가 Ed25519 > HMAC > unsigned 순으로 선택한다.
`verified=True`인데 서명 알고리즘이 `ed25519`가 아니면 내부 오류로 중단한다.
대칭 HMAC은 같은 키를 가진 당사자에게만 인증되며 공개키 증명(attestation)이
아니다 — 자세한 내용은 `docs/RESULT_SIGNING.md`를 참고하라.

### 후보용 engine jail

`--engine-jail docker`는 `run_track_b_round`로 전달되며, **후보** 엔진을
Docker 감옥(engine jail, `bench/ceb/jail/`, `scripts/build_jail_image.sh`로
빌드된 이미지 `chess-en-bench-jail:0.4`)에 가둔다. 베이스라인은 운영자가 제공한
신뢰된 빌드이므로 호스트에서 실행된다. 후보는 자신의 워크스페이스 디렉터리 안의
단일 실행 파일이어야 하며, 그렇지 않으면 감옥 요청이 거부된다. Docker가 없거나
이미지가 없으면 실행 가능한 `EngineJailError`가 발생한다. `--engine-jail none`
(CLI 기본)이면 두 엔진 모두 호스트에서 실행된다.

이 engine jail은 평가 시 **엔진 실행**을 가두며, 아래의 **빌드 감옥**(소스
컴파일 격리)과는 별개의 메커니즘이다. 전체 하니스를 컨테이너에 넣는 레거시
`--sandbox docker`(개발/호환 경로)와도 다르며 공식 경로가 아니다.

## 빌드 감옥 — verified 빌드 격리 (req4/req5)

verified Track B는 결코 후보 소유 빌드 스크립트를 호스트에서 실행하지 않는다.
대신 **신뢰된 운영자 래퍼**가 Docker 빌드 감옥 안에서 베이스라인과 후보를
**동일한 래퍼**로 빌드한다(`bench/ceb/track_b/build_jail.py`의 `build_in_jail`).

**마운트/격리 정책** — `build_in_jail`은 다음으로 `docker run --rm`을 띄운다:

- 소스 트리를 `/src`에 **읽기 전용**(`:ro`)으로 마운트,
- 쓰기 가능한 출력 디렉터리를 `/out`에 마운트,
- 신뢰된 래퍼를 `/wrapper.sh`에 **읽기 전용**(`:ro`)으로 마운트,
- `--network none`, `--read-only` 루트 + `--tmpfs /tmp:rw,exec`,
- `--cpus`/`--memory`/`--pids-limit` 한도(기본 2 CPU / 4g / 1024),
  `--security-opt no-new-privileges`, 비루트(`--user <uid>:<gid>`),
- **저장소나 비공개 eval 팩은 무엇도 마운트하지 않는다.**

마운트 경로에 `:`나 개행이 있으면 안전하지 않은 마운트로 거부하고,
`engine_relpath`에 `/`가 있거나 `.`/`..`이면 거부한다. 빌드 타임아웃은
1800초이고 초과 시 컨테이너를 `docker kill`한다.

**래퍼 계약** — 컨테이너는 다음 명령으로 래퍼를 실행한다:

```
/wrapper.sh <source_dir_readonly> <output_dir_writable> <engine_relpath>
```

즉 `bash /wrapper.sh /src /out <engine_relpath>`. 래퍼는 읽기 전용 `/src`에서
소스를 읽고(빌드가 트리를 더럽히면 쓰기 가능한 위치로 먼저 복사) `/out`에
빌드하여 `/out/<engine_relpath>`에 실행 가능한 엔진을 남겨야 한다. 같은 래퍼가
베이스라인과 후보를 빌드하므로 빌드 설정이 동일하고 운영자가 통제한다. 빌드가
`<engine_relpath>`를 산출하지 못하면 `BuildJailError`로 중단한다.

**빌드 산출 검증**(req5, `validate_build_output`) — 빌드 감옥이 끝나면 엔진을
사용하기 **전에** 산출 트리를 검증한다: 엔진이 존재하고 실행 가능하며 일반
파일(심볼릭 링크 아님)이어야 하고, 산출 트리 어디에도 심볼릭 링크가 없어야 하며,
총 크기 최대 512 MiB(`MAX_BUILD_OUTPUT_BYTES`), 파일 수 최대 10000개
(`MAX_BUILD_OUTPUT_FILES`)여야 한다. 위반 시 `BuildJailError`로 중단한다.
베이스라인·후보 트리별 산출 해시는 `metadata.track_b.build_output`
(`baseline_output_hash`/`candidate_output_hash`)에 기록된다.

**빌드 이미지** — 기본값은 engine jail 이미지(`chess-en-bench-jail:0.4`,
`docker_engine.JAIL_IMAGE`)를 재사용한다. 이 이미지는 gcc/g++/make + bash +
python3을 갖췄고 벤치마크 코드는 들어있지 않다. 빌드 환경을 engine-run 감옥과
분리하고 싶으면 `infra/docker/track_b_build_jail.Dockerfile`로 전용 이미지
(`chess-en-bench-build-jail:0.4`)를 만들 수 있다
(`bash scripts/build_track_b_build_image.sh`). 이미지가 없으면 `build_in_jail`은
빌드 안내 메시지와 함께 `BuildJailError`를 낸다.

**신뢰된 래퍼 해소 + 해시 고정**(req4, `bench/ceb/hosted/build_wrappers.py`) —
`validate_build_wrapper`는 래퍼가 존재하는 정규 파일이고 **후보/베이스라인 트리
바깥**에 있어야 함을 강제한다(후보가 자체 빌드 로직을 공급하지 못하게 함).
v0.3.5 verified Track B는 추가로 래퍼 **파일 해시**가 PIN되어야 한다:
`compute_wrapper_hash`(`sha256:` 접두 파일 해시)가
`resolve_wrapper_hashes`로 모은 허용 목록(`--build-wrapper-hash` /
`CEB_TRACK_B_BUILD_WRAPPER_HASHES` / `--build-wrapper-registry`)에 있어야 한다.
허용 목록이 없으면 verified는 거부되고, `--dev-allow-unpinned-wrapper`이면
`verified=false` 등급 `diagnostic-untrusted-wrapper`로 강등된다. 래퍼 해시·신뢰
플래그·빌드 격리·빌드 감옥 이미지 다이제스트는 메타데이터
(`build_wrapper_hash`/`build_wrapper_trusted`/`build_isolation`/
`build_jail_image_digest`)에 기록된다. `write_demo_wrapper`는 테스트/로컬
진단용 작은 데모 래퍼(`engine.cpp`를 g++로 빌드하거나 `engine.py`를 감싸는 셸
엔진을 만듦)를 쓰고 `chmod +x`한다. 실제 운영자는 고정 Stockfish를 빌드하는
래퍼를 공급한다.

**베이스라인 신뢰**(req3, `bench/ceb/track_b/baseline_trust.py`의
`validate_track_b_baseline`) — verified Track B의 베이스라인은 세 가지 신뢰
모드 중 하나여야 한다:

- `stockfish-lock` — 베이스라인 트리의 git HEAD가
  `tracks/b_stockfish_opt/stockfish.lock`의 고정 커밋과 일치(짧은 접두 매칭 허용)
  **하고**, 작업 트리가 깨끗하며(`git_worktree_clean`:
  `git status --porcelain --untracked-files=all`가 비어 있음)
  **하고** 서브모듈도 깨끗해야(`git_submodules_clean`:
  `git submodule status --recursive`의 모든 줄이 공백으로 시작) 한다. HEAD가
  lock과 일치하는 것만으로는 부족하다 — 더럽거나 추적되지 않은 파일이 있는
  체크아웃은 stockfish-lock으로 신뢰되지 않고 hash 모드로 떨어진다(없으면 실패).
  신뢰될 때 콘텐츠 해시(`baseline_tree_hash`)도 기록한다.
- `hash` — 베이스라인 트리 콘텐츠 해시가 허용 목록에 있음
  (`--track-b-baseline-hash` / `CEB_TRACK_B_BASELINE_HASHES` /
  `--track-b-baseline-registry`). `.git`이 없는 스냅샷 베이스라인도 이 모드로
  신뢰된다.
- `toy` — `--dev-allow-toy-baseline`로 미신뢰 토이 베이스라인을 허용하되
  `verified=false` 등급 `diagnostic-untrusted-baseline`로 강등.

어떤 모드에도 해당하지 않고 toy 허용이 없으면 `BaselineTrustError`로 거부한다.
신뢰 정보(`baseline_trusted`/`baseline_trust_mode`/`baseline_tree_hash`/
`stockfish_lock`)는 메타데이터에 기록된다.

**bench/속도 정합성**(req6, `bench/ceb/track_b/bench_sanity.py`의
`run_bench_sanity`) — verified Track B에서 두 엔진 모두에 `bench`를 실행해
엔진별 nodes/nps/output_hash와 `nps_ratio`를 기록한다. **verified Track B는
bench가 신뢰된 베이스라인 및 후보 양쪽에서 SUPPORTED(지원)되어야 한다.**
베이스라인이 NPS를 보고하지 못하면(미지원) verified는 **실패**한다 — 예전의
"미지원 = 조용한 통과"는 사라졌다. 베이스라인은 bench를 지원하는데 후보가
지원하지 못하면 마찬가지로 실패하거나 강등되며 결코 verified가 되지 않는다.
NPS 비율 임계(`--bench-min-nps-ratio`, 기본 0.3)는 **두 엔진 모두 bench를
지원할 때** 강제한다(jailing 시 후보는 bench도 감옥 안에서 실행). 후보 NPS가
너무 느리면(임계 미만) verified는 실패한다(결과 없음). verified 경로에서 후보의
engine jail bench 명령 구성이 실패하면 후보 bench는 **거부**되며 호스트에서
대체 실행되지 않는다(no host fallback; 내부적으로
`_run_bench(require_candidate_jail=...)`). `--dev-allow-no-bench`는 그 실패를
**건너뛰지 않고 항상** `verified=false` 등급 `diagnostic-no-bench`로 강등하므로 —
느린 후보가 절대 리더보드에 오를 수 없다(`official_pipeline.py`). 결과
메타데이터의 `metadata.track_b`는 `bench_required`, `bench_supported`,
`bench_passed`, `nps_ratio`, `min_nps_ratio`, 그리고 `bench_policy` 객체
(`supported_required_for_verified`, `enforced_when_baseline_supports_bench`,
`override_downgrades_to_diagnostic`)와 전체 bench 보고서를 기록한다. 실제 공개
Track B는 bench를 지원하는 고정 Stockfish가 필요하다.

빌드 감옥에서 산출된 후보 엔진은 매치 단계에서 다시 **engine jail**(위)에
들어가 실행된다.

## 호스티드 verified 경로

호스티드 워커만이 verified Track B 결과를 생성할 수 있다.

### 제출 API / CLI (req8)

호스티드 제출은 관리자 전용이다:

```
POST /api/hosted/runs/{run_id}/track-b-submissions
  헤더: X-CEB-Admin-Token
  본문: {candidate_src, baseline_src, build_script?, engine_relpath?}
```

엔드포인트(`hosted_submit_track_b`, `bench/ceb/api/main.py`)는
후보+베이스라인을 스냅샷하고(`snapshot_workspace` — 심볼릭 링크/안전하지 않은
파일 거부) 해시한 뒤, Track B run을 만들거나 재사용하고
`track_b_official_eval` 잡을 큐에 넣는다. 응답은
`{submission_id, candidate_hash, baseline_hash, job_id, kind}`다. **신뢰된 빌드
래퍼는 워커에 `--build-wrapper`로 공급되며, 절대 후보가 제출하지 않는다.**

동등한 CLI도 있다:

```bash
ceb hosted submit-track-b \
  --candidate-src /path/to/candidate \
  --baseline-src /path/to/baseline \
  --run-id <id> --db runs/hosted.sqlite \
  [--build-script ceb_build.sh] [--engine-relpath ceb_engine]

ceb hosted worker run-once --db runs/hosted.sqlite \
  --eval-pack <trusted-official-pack> --engine-jail docker \
  --signing-key <ed25519-key> --build-wrapper <trusted-wrapper> \
  --official-pack-hash <pack-hash> --build-wrapper-hash <wrapper-hash> \
  --track-b-baseline-hash <baseline-hash> \
  [--official-pack-registry FILE] [--build-wrapper-registry FILE] \
  [--track-b-baseline-registry FILE] [--bench-min-nps-ratio 0.3] \
  [--profile official|final-production]
```

워커(`bench/ceb/hosted/worker.py`)는 잡을 원자적으로 클레임하고 잡 종류
(`JOB_KIND_TRACK_B`)로 분기한다. Track B 잡이면 `latest_track_b_submission`을
읽어 `run_hosted_track_b`를 호출하고, 결과를 `mode=track_b_official`
(`TRACK_B_OFFICIAL_MODE`), 점수는 최종 델타 Elo(`track_b_score`:
`final_delta_elo`), `track="B"`로 DB에 기록한다.

### 워커 CLI 플래그 (`ceb hosted worker run-once`)

기존 `--profile`/`--engine-jail`(docker 기본)/`--dev-allow-unjailed`/
`--worker-id`/`--lease-seconds` 외에 verified Track B 게이트를 위한 플래그:

- `--build-wrapper` — 신뢰된 운영자 빌드 래퍼(후보 트리 바깥). verified 필수.
- `--official-pack-hash`(append/comma), `--official-pack-registry` — 신뢰
  공식 팩 콘텐츠 해시 허용 목록(req1).
- `--build-wrapper-hash`(append/comma), `--build-wrapper-registry` — 신뢰
  빌드 래퍼 파일 해시 허용 목록(req4).
- `--track-b-baseline-hash`(append/comma), `--track-b-baseline-registry` —
  신뢰 베이스라인 트리 해시 허용 목록(req3).
- `--bench-min-nps-ratio` — verified Track B 최소 후보/베이스라인 NPS 비율
  (두 엔진이 bench를 지원할 때만 강제, req6).
- `--signing-key` — Ed25519 개인키 경로(`CEB_SIGNING_PRIVATE_KEY` 대체).
- 진단 강등 DEV 플래그(어떤 것도 `verified=true`를 유지시키지 못함 — 전부 강제
  `verified=false`): `--dev-allow-demo-pack`(데모 팩 경로 검사 우회),
  `--dev-allow-unpinned-pack`(`diagnostic-unpinned-pack`),
  `--dev-allow-unsigned`(`diagnostic-unsigned`),
  `--dev-allow-toy-baseline`(`diagnostic-untrusted-baseline`),
  `--dev-allow-unpinned-wrapper`(`diagnostic-untrusted-wrapper`),
  `--dev-allow-no-bench`(낮은 NPS 비율 실패를 무시하지 않고
  `diagnostic-no-bench`로 강등).

### verified 요건

`run_hosted_track_b`는 다음을 **모두** 만족할 때만 `verified=true`를 만든다.
하나라도 어긋나면 평가 전에 거부하거나 진단 등급으로 강등한다:

- **verifiable 프로파일**(official / final-production). smoke는 진단 전용이라
  결코 verified가 되지 않는다.
- **후보 엔진 Docker engine jail**(P0.1): verifiable 프로파일은
  `engine_jail == "docker"`여야 한다. 아니면 거부한다.
  `--dev-allow-unjailed`는 감옥 없이 실행하되 강제로 `verified=false`
  (`diagnostic-unjailed`)로 만든다.
- **고정된 신뢰 공식 eval 팩**(req1): `--eval-pack` 필수.
  `validate_official_eval_pack(..., track="B")`로 매니페스트
  (`ceb.eval_pack.manifest/v1`, `official=true`, `visibility="private"`,
  `track`이 B 또는 both)와 저장소 바깥 경로를 확인한다. 커밋된 데모 팩
  (`examples/eval_packs/tiny_private`)은 **절대 verify되지 않는다**(등급
  `diagnostic-untrusted-pack`). v0.3.5에서는 추가로 팩 콘텐츠 해시가
  허용 목록(`--official-pack-hash` / `CEB_OFFICIAL_EVAL_PACK_HASHES` /
  `--official-pack-registry`)에 PIN되어야 한다. 허용 목록이 없으면 verified는
  거부되고, `--dev-allow-unpinned-pack`이면 `verified=false` 등급
  `diagnostic-unpinned-pack`로 강등된다.
- **Ed25519 서명 키**(req2): `require_ed25519_private_key`(`signing.py`)로 키를
  스캔/게이트/빌드/매치보다 **먼저** 해소하고 로드-검증한다. 키가 **없으면**
  `--dev-allow-unsigned` 시 `verified=false`(`diagnostic-unsigned`)로 강등하고
  아니면 거부한다. 키가 **잘못된 형식**이면 위생 처리된 메시지와 함께 일찍
  hard-fail하므로, 서명 실패로 STAGED 공개 아티팩트가 남지 않는다. 검증된 키
  경로는 서명 시점에 그대로 재사용된다. HMAC/unsigned는 verified로 인정되지
  않는다.
- **신뢰 베이스라인**(req3): `validate_track_b_baseline`로 stockfish-lock / hash /
  toy 모드를 판정한다. 신뢰되지 않으면 거부하고, `--dev-allow-toy-baseline`이면
  `diagnostic-untrusted-baseline`로 강등한다.
- **해시-고정된 신뢰 빌드 래퍼**(req4): `validate_build_wrapper`로 후보/베이스라인
  트리 바깥의 래퍼를 확인하고 `build_isolation="jail"`로 설정한다. 추가로
  `compute_wrapper_hash`가 래퍼 해시 허용 목록에 있어야 한다. 없으면 거부하고,
  `--dev-allow-unpinned-wrapper`이면 `diagnostic-untrusted-wrapper`로 강등한다.
- **소스 우선 게이트 + 빌드 감옥 + 산출 검증**(req5): diff 화이트리스트 + 콘텐츠
  스캔 통과, 베이스라인과 후보를 같은 신뢰 래퍼로 빌드 감옥 안에서 빌드,
  `validate_build_output`로 산출 트리 검증.
- **bench/속도 정합성**(req6): 두 엔진에 `bench` 실행. bench는 신뢰된 베이스라인
  **및** 후보 양쪽에서 supported여야 한다 — 베이스라인이 미지원이면 verified
  실패(미지원은 더 이상 조용한 통과가 아니다). 둘 다 bench를 지원하는데 후보
  NPS 비율이 임계 미만이면 verified 실패. 후보의 engine jail bench 명령 구성
  실패 시 후보 bench는 거부되며 호스트 대체 실행이 없다(no host fallback).
  `--dev-allow-no-bench`는 우회가 아니라 **항상** `verified=false` 등급
  `diagnostic-no-bench`로 강등하므로, 느린 후보가 verified로 리더보드에 오르는
  일은 결코 없다.
- **공개 아티팩트 누출 스캔 통과**(req7): STAGED 아티팩트에 대해 스캔하고
  통과해야만 공개로 승격. 누출 시 verify 거부 + 잡 failed.

이 모든 검사를 마친 뒤 워커는 `run_official_track_b`를
`build_isolation="jail"`, `verified=True`, `build_wrapper=<신뢰 래퍼>`,
`trust=<팩 신뢰 정보>`, `baseline_trust=<베이스라인 신뢰 정보>`,
`build_wrapper_hash=<래퍼 해시>`로 호출한다. 워커 CLI의 `--engine-jail` 기본값은
`docker`다. smoke 프로파일은 verifiable이 아니므로 flag와 무관하게 감옥 없이
실행된다.

### 프로파일과 매치 크기

프로파일은 `bench/ceb/hosted/profiles.py`에 정의된다. `run_hosted_track_b`는
`_MATCH_SIZE`로 티어별 매치 크기 `(games, movetime_ms, max_plies)`를 정한다:

- `smoke` — 진단(`diagnostic-smoke`), verifiable=false, 리더보드 제외.
  CI/플러밍용 tiny 매치 `(2, 30, 40)`로 감옥 없이 실행.
- `official` — verifiable(`verified-official`). official 티어 매치
  `(200, 200, 300)`.
- `final-production` — verifiable(`verified-final-production`). 프로덕션 규모
  매치 `(1000, 1000, 300)`. 리더보드는 final 티어를 official보다 선호한다.

`verification_grade`는 결과 JSON과 DB 행에 저장된다: `verified-official` /
`verified-final-production` / `diagnostic-smoke` / `diagnostic-unjailed` /
`diagnostic-unsigned` / `diagnostic-untrusted-pack` / `diagnostic-unpinned-pack` /
`diagnostic-untrusted-baseline` / `diagnostic-untrusted-wrapper` /
`diagnostic-no-bench`.

리더보드 / `ceb hosted result show` / 공식 결과 API는 공유 선택자
`select_best_verified_result`(`bench/ceb/hosted/db.py`)를 통해 run별 단일 best
verified 결과를 고르므로 항상 일치한다. 진단 결과는 verified가 아니므로 절대
선택되지 않는다. `verified_leaderboard(conn, track="B")`가 Track B 리더보드를
제공한다.

## verified vs 진단 — 코드가 강제하는 것, 운영자가 해야 하는 것

**코드가 강제하는 것** (두 경로 공통):

- 어떤 빌드도 하기 전에 스캔이 통과해야 한다;
- 베이스라인과 후보는 *동일한* 래퍼/스크립트와 엔진 relpath로 빌드된다;
- 빌드 실패 / 엔진 누락은 중단을 일으킨다;
- 두 트리의 트리 해시와 `build_isolation`이 메타데이터에 기록된다;
- UCI 옵션(`Threads=1`, `Hash=16`)이 라운드 러너에 의해 양쪽 엔진에 전송된다;
- 공개 아티팩트는 STAGED로 쓰인 뒤 누출 스캔을 통과해야만 공개로 승격된다.

**호스티드 verified 경로가 추가로 강제하는 것:**

- `build_isolation="jail"` (호스트 빌드는 `verified=True`와 함께 거부됨);
- 후보 엔진 engine jail = docker;
- 고정된 신뢰 공식 eval 팩(데모 팩 거부 + 해시 PIN, req1);
- 신뢰 베이스라인(콘텐츠 해시, 또는 깨끗한 작업 트리/서브모듈의 stockfish-lock, req3);
- 후보/베이스라인 트리 바깥의 해시-고정 신뢰 빌드 래퍼(req4);
- 빌드 산출 검증(엔진 일반/실행 가능, 심볼릭 링크 없음, 크기·파일 수 한도, req5);
- bench/속도 정합성(bench가 베이스라인·후보 양쪽에서 supported여야 하며 미지원
  베이스라인은 verified 실패; 둘 다 지원 시 NPS 비율 강제; 후보 bench는 host
  fallback 없이 engine jail에서만; 실패 또는 `--dev-allow-no-bench`는 항상
  `diagnostic-no-bench`로 강등, req6);
- Ed25519 서명(평가 전 로드-검증; HMAC/unsigned 불가).

**운영자 책임 — 코드가 강제하지 않음:**

- 고정 Stockfish를 빌드하는 신뢰 래퍼(예: 빌드 감옥 안에서 `make`를 감싸는
  `/wrapper.sh`) 제공 후 그 래퍼 해시를 허용 목록에 PIN;
- 베이스라인과 후보 빌드 사이의 동일한 컴파일러 플래그 보장;
- bench를 지원하는 실제 고정 Stockfish 공급(토이 베이스라인은 verified 불가).

파이프라인은 래퍼/스크립트가 산출하는 것을 빌드하고 대국시키며, 위의 v0.3.5
신뢰 앵커(고정 팩/베이스라인/래퍼 + 산출 검증 + bench 정합성)를 강제한다.
다만 컴파일러 플래그 자체는 검사하지 않는다. 운영자가 통제하는 호스팅
경로(빌드 감옥 + 고정 신뢰 래퍼 + 신뢰 베이스라인 + 고정 신뢰 팩 + Ed25519 +
strict readiness)를 통해 verify되기 전까지는 진단 결과로 취급하라.

## 엄격 준비도 점검 (req10)

`ceb hosted readiness check`(`bench/ceb/hosted/readiness.py`,
스키마 `ceb.hosted.readiness/v2`)는 verified Track B 운영 준비 상태를 점검한다.
JSON 보고서는 `checks[name, ok, required, detail]`, `ready`,
`public_official_declaration`(`"ready"`|`"not-ready"`), 그리고
`blocking_failures`(실패한 required 검사 이름 목록)을 담고, 준비되지 않았으면
0이 아닌 코드로 종료한다. `--strict-public-official`이면 고정/공개키/
키페어-매치/베이스라인/래퍼-해시 앵커가 **경고가 아닌 BLOCKING(required)**으로
바뀐다 — 저장소를 공개 공식으로 선언하는 **단일 선언 게이트**다. `--track BOTH`는
Track A 팩 점검과 모든 Track B 점검을 함께 실행한다. `--json`은 **JSON만**
출력해(`cmd_hosted_readiness_check`) 기계 파싱이 깨끗하다.

**Track A 엄격 점검:** 패키지 버전 0.3.5 이상, DB 마이그레이션, docker, engine
jail 이미지, **신뢰 + 고정된** 공식 eval 팩, 데모 팩 거부, Ed25519 서명키,
공개키 로드 가능, **키페어 매치**(개인키의 공개키 핑거프린트가 공급된 공개키와
일치, 보고서에 핑거프린트 포함), smoke 비-verifiable, official/final-production
verifiable, final-production 게임 바닥선(2016개 구성, 하한 2000).

**Track B 엄격 점검은 추가로:** 빌드 감옥 이미지(`chess-en-bench-build-jail:0.4`
또는 재사용 `chess-en-bench-jail:0.4`), 빌드 래퍼 존재/실행 가능 + 트리 바깥
(`_build_wrapper_present`), `build_wrapper_pinned`(래퍼 해시가 허용 목록에),
`track_b_baseline_trust`(베이스라인 콘텐츠 해시 PIN, 또는 깨끗한 stockfish-lock
체크아웃), `bench_speed_sanity`(우회 불가 정책: 실패한 bench나
`--dev-allow-no-bench`는 강등할 뿐 verified가 되지 않는다고 명시),
`track_b_bench_capability`(v0.3.5, BLOCKING: bench 역량을 **증명**한다 —
`--track-b-baseline-engine`으로 bench 지원 베이스라인 엔진을 공급하면 readiness가
그 엔진에 실제로 `bench`를 실행해 NPS를 보고하는지 확인한다. 공급하지 않으면
strict Track B 선언이 BLOCK된다),
`track_b_api_endpoint` import 가능.

```bash
ceb hosted readiness check --db runs/hosted.sqlite \
  --eval-pack <trusted-pack> --public-key <ed25519.pub> --track B \
  --build-wrapper <trusted-wrapper> --strict-public-official \
  --official-pack-hash H --build-wrapper-hash WH --track-b-baseline-hash BH \
  --track-b-baseline-engine <bench-capable-engine> \
  [--signing-key KEY] [--baseline-src DIR] \
  [--official-pack-registry FILE] [--build-wrapper-registry FILE] \
  [--track-b-baseline-registry FILE] [--require-server] [--json]
```

## 릴리스 매니페스트 (req9)

`ceb hosted release-manifest create`(`bench/ceb/hosted/release_manifest.py`,
스키마 `ceb.release_manifest/v1`)는 한 시즌의 모든 공개 공식 신뢰 앵커를 PIN하는
**비밀 없는** 매니페스트를 만든다: `benchmark_version`, `git_commit`, `track`,
`season`, `official_eval_pack_id`/`official_eval_pack_hash`/
`official_eval_pack_manifest_hash`, `operator_public_key_fingerprint`(**키 자체는
절대 포함하지 않음**), `engine_jail_image` + 다이제스트, Track B는
`track_b_baseline_hash` + `track_b_baseline_trust_mode`(`"hash"` — 매니페스트는
베이스라인을 가장 강한 콘텐츠 해시 모드로 PIN) + `track_b_build_wrapper_hash` +
`build_jail_image_digest` + `bench_policy`(`min_nps_ratio`,
`enforced_when_baseline_supports_bench`, `override_downgrades_to_diagnostic`),
`leaderboard_policy`, `known_limitations`. 매니페스트는 비밀이 없다: 개인키,
비공개 eval 팩 경로, 숨김 FEN/오프닝 id, 비공개 아티팩트 경로를 담지 않는다.
고정된 공식 팩 해시와 공개키가 필수이며(없으면 `ReleaseManifestError`), Track B는
베이스라인·래퍼 해시가 **각각 정확히 하나**여야 한다(모호하면 오류). 공개
리더보드는 이 매니페스트를 게시해 누구나 시즌이 쓴 앵커를 확인할 수 있게 한다.

```bash
ceb hosted release-manifest create --track B \
  --eval-pack <trusted-pack> --official-pack-hash H --public-key <ed25519.pub> \
  --track-b-baseline-hash BH --build-wrapper-hash WH --out release.json
```

## 결과 번들 (result bundle)

`ceb hosted result export`(`bench/ceb/hosted/result_bundle.py`,
스키마 `ceb.hosted.result_bundle/v1`)는 run의 **선택된 best verified 결과**의
공개 아티팩트만 zip으로 묶는다. `--release-manifest <path>`와
`--public-key <pem>`(또는 `--public-key-fingerprint <fp>`)를 주면 번들에
`release_manifest.json`과 운영자 공개키 핑거프린트를 포함하고, `VERIFY.txt`에
아웃오브밴드 공개키 / 릴리스 매니페스트 핑거프린트로 검증하는 절차를 적어 둔다.
선택되지 않은 smoke/진단 결과와 모든 비공개 아티팩트(스캔/누출 보고서, 매치
로그)는 절대 포함하지 않으며, 개인키나 숨김 팩 데이터도 담지 않는다.

```bash
ceb hosted result export --run-id <id> --db runs/hosted.sqlite --out bundle.zip \
  --release-manifest release.json --public-key <ed25519.pub>
```

## 호스티드 API (req8)

- `GET /api/leaderboard?track=B`는 호스티드 DB가 있으면 verified 호스티드 Track B
  리더보드(`verified_leaderboard(track="B")`)에 위임하고, 없으면
  `GET /api/hosted/leaderboard?track=B`를 가리키는 안내를 반환한다.
- `GET /api/hosted/readiness/public`(스키마 `ceb.hosted.readiness.public/v1`)은
  비밀 없는 공개 메타데이터(버전, 프로파일 verifiability, 리더보드 정책)만
  노출한다. 운영자 전용 앵커(팩/키/이미지)는 `ceb hosted readiness check
  --strict-public-official` CLI에서만 점검한다.
- `GET /api/hosted/release-manifest`(`hosted_release_manifest`)는 `CEB_RELEASE_MANIFEST`
  경로의 릴리스 매니페스트를 그대로 제공한다 — 미설정 시 503, 파일이 없으면 404.
  공개 GET이라 관리자 토큰이 필요 없으며, 매니페스트는 구성상 비밀이 없다.
- 관리자 POST/업로드 엔드포인트는 `CEB_ADMIN_TOKEN` 미설정 시 503으로 비활성화하고,
  토큰 비교는 상수 시간(`hmac.compare_digest`)으로 한다. 스트리밍 업로드는 변동
  없음. API를 통한 Track B 아카이브 업로드는 향후 작업이며, 현재는 서버 로컬
  `candidate_src`/`baseline_src`다.

## 테스트와 CI

`tests/test_track_b_official.py`는 **작은 가짜 소스 트리와 번들된 Python UCI
엔진을 제자리에 복사하는 데모 래퍼/빌드 스크립트**로 진단 파이프라인과 호스티드
통합을 처음부터 끝까지 검증한다 — 실제 Stockfish도 컴파일러도 관여하지 않는다.
토이 트리 테스트는 happy path(빌드, 채점, 구별되는 트리 해시 기록,
STAGED→승격된 `official_result.json` 작성), 금지 파일 거부(스캐너 중단), 빌드
스크립트 누락 중단, verified=True + 호스트 빌드 거부, 신뢰 팩/서명/래퍼 게이트,
그리고 `--dev-allow-unjailed`/`--dev-allow-unsigned`/`--dev-allow-unpinned-pack`/
`--dev-allow-toy-baseline`/`--dev-allow-unpinned-wrapper`/`--dev-allow-no-bench`가
진단 등급을 만드는지를 다룬다(req3/req4/req5/req6 게이트 포함). 릴리스
매니페스트는 `tests/test_release_manifest.py`, strict readiness는
`tests/test_readiness.py`가 검증한다. 비-docker 테스트 스위트는 현재 311 passed,
6 skipped다.

verified-in-jail 경로는 **Docker opt-in**이다: `CEB_DOCKER_TESTS=1`이고 docker와
`chess-en-bench-jail:0.4` 이미지가 준비된 경우에만 실행되며, 빌드 감옥 안 빌드 +
engine jail 안 후보 엔진 + 신뢰 팩 + Ed25519 서명으로 `verified-official` 결과가
나고 `verified_leaderboard(track="B")`에 오르는지를 확인한다. **실제 고정
Stockfish 빌드 래퍼는 운영자 단계**다 — 테스트는 토이 트리만 쓴다.

CI는 이 파이프라인을 실행하지 않는다. CI는 토이 Track B *라운드*
(`BenchRandom`을 쓰는 `ceb track-b round run`)만 실행한다. CI에는 Stockfish,
Docker, 클라우드 실행이 없다.
