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
5. `run_track_b_round`(internal 러너 — 신뢰된 레퍼런스)를 통해 **후보-대-베이스라인
   쌍 매치 진행**. UCI handshake, 쌍 색-교대 오프닝, 양쪽 엔진에 `Threads=1` /
   `Hash=16`, 델타 Elo 채점.
6. **메타데이터 조립**(`build_metadata`)과 `track_b` 블록 추가:
   `baseline_tree_hash`/`candidate_tree_hash`(`hash_directory`를 통한 트리별
   sha256), `build_isolation`, `build_script`(jail이면 None), `build_wrapper`
   (jail에서만 채워짐).
7. 결과 **서명**(`sign_official_result`)과 STAGED 공개 산출물 작성.
8. eval 팩이 주어진 경우 STAGED 아티팩트에 대해 **공개 아티팩트 누출 스캔**
   (`scan_public_artifacts(..., staged=True)`)을 실행한다. 누출이 발견되면
   중단한다.
9. **승격**(`promote_public_artifacts`): 누출 스캔을 통과한 STAGED 아티팩트만
   `visibility=public`으로 올린다.

### 출력

스키마 `ceb.track_b.official_result/v1`의 단일 결과 dict이며 다음을 포함한다:
`run_id`, `track`, `round`, `finished_at`, `engine_jail`, `build_isolation`
(`"host"`|`"jail"`), `scan.passed`, `score`(`ceb.score.track_b/v1`: W/D/L,
결함, `delta_elo`, `delta_elo_ci95`, 페널티, `final_delta_elo`), `feedback`,
`metadata`(`track_b` 트리 해시/격리 정보 포함; verified일 때 `eval_pack_trusted`,
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

## 빌드 감옥 — verified 빌드 격리 (섹션 C)

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

**빌드 이미지** — 기본값은 engine jail 이미지(`chess-en-bench-jail:0.4`,
`docker_engine.JAIL_IMAGE`)를 재사용한다. 이 이미지는 gcc/g++/make + bash +
python3을 갖췄고 벤치마크 코드는 들어있지 않다. 빌드 환경을 engine-run 감옥과
분리하고 싶으면 `infra/docker/track_b_build_jail.Dockerfile`로 전용 이미지
(`chess-en-bench-build-jail:0.4`)를 만들 수 있다
(`bash scripts/build_track_b_build_image.sh`). 이미지가 없으면 `build_in_jail`은
빌드 안내 메시지와 함께 `BuildJailError`를 낸다.

**신뢰된 래퍼 해소**(`bench/ceb/hosted/build_wrappers.py`) —
`validate_build_wrapper`는 래퍼가 존재하는 정규 파일이고 **후보/베이스라인 트리
바깥**에 있어야 함을 강제한다(후보가 자체 빌드 로직을 공급하지 못하게 함).
`write_demo_wrapper`는 테스트/로컬 진단용 작은 데모 래퍼(`engine.cpp`를 g++로
빌드하거나 `engine.py`를 감싸는 셸 엔진을 만듦)를 쓰고 `chmod +x`한다. 실제
운영자는 고정 Stockfish를 빌드하는 래퍼를 공급한다.

빌드 감옥에서 산출된 후보 엔진은 매치 단계에서 다시 **engine jail**(위)에
들어가 실행된다.

## 호스티드 verified 경로

호스티드 워커만이 verified Track B 결과를 생성할 수 있다.

### 제출 API / CLI (섹션 E)

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
  [--official-pack-hash H] [--official-pack-registry FILE] \
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
  공식 팩 콘텐츠 해시 허용 목록.
- `--signing-key` — Ed25519 개인키 경로(`CEB_SIGNING_PRIVATE_KEY` 대체).
- `--dev-allow-demo-pack` — 데모 팩 경로 검사만 우회(개발 전용).
- `--dev-allow-unsigned` — Ed25519 키 없이 강제 `verified=false`
  (`diagnostic-unsigned`).

### verified 요건

`run_hosted_track_b`는 다음을 **모두** 만족할 때만 `verified=true`를 만든다.
하나라도 어긋나면 평가 전에 거부하거나 진단 등급으로 강등한다:

- **verifiable 프로파일**(official / final-production). smoke는 진단 전용이라
  결코 verified가 되지 않는다.
- **후보 엔진 Docker engine jail**(P0.1): verifiable 프로파일은
  `engine_jail == "docker"`여야 한다. 아니면 거부한다.
  `--dev-allow-unjailed`는 감옥 없이 실행하되 강제로 `verified=false`
  (`diagnostic-unjailed`)로 만든다.
- **신뢰 공식 eval 팩**(섹션 A): `--eval-pack` 필수.
  `validate_official_eval_pack(..., track="B")`로 매니페스트
  (`ceb.eval_pack.manifest/v1`, `official=true`, `visibility="private"`,
  `track`이 B 또는 both)와 저장소 바깥 경로를 확인한다. 해시 허용 목록이 있으면
  팩 해시가 일치해야 한다. 커밋된 데모 팩(`examples/eval_packs/tiny_private`)은
  공식 매니페스트가 없어 **절대 verify되지 않는다**. 팩이 거부되면 거부한다
  (등급 `diagnostic-untrusted-pack`).
- **Ed25519 서명 키**(섹션 B): `ed25519_private_key_path`로 키가 있어야 한다.
  없는데 `--dev-allow-unsigned`이면 `verified=false`(`diagnostic-unsigned`)로
  강등하고, 아니면 거부한다. HMAC은 verified로 인정되지 않는다.
- **신뢰 빌드 래퍼**(섹션 C): `validate_build_wrapper`로 후보/베이스라인 트리
  바깥의 래퍼를 확인하고 `build_isolation="jail"`로 설정한다.
- **소스 우선 게이트 + 빌드 감옥**: diff 화이트리스트 + 콘텐츠 스캔 통과,
  베이스라인과 후보를 같은 신뢰 래퍼로 빌드 감옥 안에서 빌드.
- **공개 아티팩트 누출 스캔 통과**(섹션 D): STAGED 아티팩트에 대해 스캔하고
  통과해야만 공개로 승격. 누출 시 verify 거부 + 잡 failed.

이 모든 검사를 마친 뒤 워커는 `run_official_track_b`를
`build_isolation="jail"`, `verified=True`, `build_wrapper=<신뢰 래퍼>`,
`trust=<팩 신뢰 정보>`로 호출한다. 워커 CLI의 `--engine-jail` 기본값은
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
`diagnostic-unsigned` / `diagnostic-untrusted-pack`.

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
- 신뢰 공식 eval 팩(데모 팩 거부);
- 후보/베이스라인 트리 바깥의 신뢰 빌드 래퍼;
- Ed25519 서명(HMAC/unsigned 불가).

**운영자 책임 — 코드가 강제하지 않음:**

- 고정 Stockfish를 빌드하는 신뢰 래퍼(예: 빌드 감옥 안에서 `make`를 감싸는
  `/wrapper.sh`) 제공;
- 베이스라인과 후보 빌드 사이의 동일한 컴파일러 플래그 보장;
- 후보가 화이트리스트된 탐색 변경만 적용된 고정 Stockfish임을 확인하는 `bench` /
  속도 정합성 검사.

파이프라인은 래퍼/스크립트가 산출하는 것을 빌드하고 대국시킨다. 컴파일러
플래그를 검사하지도, `bench` 정합성 검사를 실행하지도 않는다. 운영자가 통제하는
호스팅 경로(빌드 감옥 + 신뢰 래퍼 + 신뢰 팩 + Ed25519)를 통해 verify되기
전까지는 진단 결과로 취급하라.

## 준비도 점검 (섹션 H)

`ceb hosted readiness check`(`bench/ceb/hosted/readiness.py`)는 verified Track B
운영 준비 상태를 점검한다. 패키지 버전 >= 0.3.2, DB 스키마 마이그레이션, docker
가용성, engine jail 이미지, (Track B면) 빌드 감옥 이미지, 신뢰 공식 eval 팩,
데모 팩 거부, Ed25519 서명키 + 공개키 검증, smoke 비-verifiable,
official/final-production verifiable, final 게임 바닥선, 그리고 `--track B`이면
**빌드 래퍼가 트리 바깥에 있고 실행 가능한지**(`_build_wrapper_ok` →
`validate_build_wrapper` + `chmod +x` 확인)를 점검한다. JSON 보고서
(스키마 `ceb.hosted.readiness/v1`)와 사람용 요약을 내고, 준비되지 않았으면
0이 아닌 코드로 종료한다.

```bash
ceb hosted readiness check --db runs/hosted.sqlite \
  --eval-pack <trusted-pack> --public-key <ed25519.pub> --track B \
  --build-wrapper <trusted-wrapper> [--signing-key KEY] \
  [--official-pack-hash H] [--official-pack-registry FILE] \
  [--require-server] [--json]
```

## 테스트와 CI

`tests/test_track_b_official.py`는 **작은 가짜 소스 트리와 번들된 Python UCI
엔진을 제자리에 복사하는 데모 래퍼/빌드 스크립트**로 진단 파이프라인과 호스티드
통합을 처음부터 끝까지 검증한다 — 실제 Stockfish도 컴파일러도 관여하지 않는다.
토이 트리 테스트는 happy path(빌드, 채점, 구별되는 트리 해시 기록,
STAGED→승격된 `official_result.json` 작성), 금지 파일 거부(스캐너 중단), 빌드
스크립트 누락 중단, verified=True + 호스트 빌드 거부, 신뢰 팩/서명/래퍼 게이트,
그리고 `--dev-allow-unjailed`/`--dev-allow-unsigned`가 진단 등급을 만드는지를
다룬다. 비-docker 테스트 스위트는 현재 238 passed, 6 skipped다.

verified-in-jail 경로는 **Docker opt-in**이다: `CEB_DOCKER_TESTS=1`이고 docker와
`chess-en-bench-jail:0.4` 이미지가 준비된 경우에만 실행되며, 빌드 감옥 안 빌드 +
engine jail 안 후보 엔진 + 신뢰 팩 + Ed25519 서명으로 `verified-official` 결과가
나고 `verified_leaderboard(track="B")`에 오르는지를 확인한다. **실제 고정
Stockfish 빌드 래퍼는 운영자 단계**다 — 테스트는 토이 트리만 쓴다.

CI는 이 파이프라인을 실행하지 않는다. CI는 토이 Track B *라운드*
(`BenchRandom`을 쓰는 `ceb track-b round run`)만 실행한다. CI에는 Stockfish,
Docker, 클라우드 실행이 없다.
