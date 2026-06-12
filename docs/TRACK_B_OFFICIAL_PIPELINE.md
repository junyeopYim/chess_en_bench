# Track B — 소스 우선 공식 파이프라인

이것은 Track B 후보 *소스 트리*를 채점되고 서명된 델타 Elo 결과로 바꾸는
소스 빌드 경로다. 실행 파일만 다루는 `ceb track-b round run`(이미 빌드한 두 엔진을
대국시킴)과 나란히 존재한다. 트랙 규칙, diff 화이트리스트, 고정 베이스라인, 델타
Elo 채점은 `docs/track_b_stockfish_optimization.md`를 참고하라.

두 가지 진입점이 있고, 이 둘을 혼동해서는 안 된다:

- **진단 CLI**: `ceb track-b official run`
  (`bench/ceb/track_b/official_pipeline.py`, `run_official_track_b`). 항상
  `verified: false`를 작성한다. 직접 실행은 자가보고/진단용이며 결코 verified가
  아니고 리더보드에 오르지 않는다.
- **호스티드 verified 경로**: `ceb hosted submit-track-b` → 호스티드 워커
  (`ceb hosted worker run-once`) → `run_hosted_track_b`
  (`bench/ceb/hosted/track_b_eval.py`). 모든 verified 게이트를 만족할 때만
  `verified: true`를 생성하며, 이것만이 호스티드 리더보드(`track="B"`)에 오른다.

아래에서 두 경로를 차례로 설명한다.

## 진단 CLI: `ceb track-b official run`

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

`ceb track-b official run`은 CLI에서 `run_official_track_b(..., verified=False)`를
호출하므로 항상 **`verified: false`**를 작성한다. `verified=True`는 호스티드
공식 워커를 위해 예약되어 있다.

### 무엇이, 어떤 순서로 실행되는가

`run_official_track_b`는 엄격히 다음 순서로 실행한다:

1. **베이스라인 트리 해소.** `--baseline-src`, 또는 고정된 `sf_18` / `cb3d4ee`
   상태의 `third_party/stockfish`. (고정값은 `tracks/b_stockfish_opt/stockfish.lock`에
   있다. 파이프라인은 커밋 해시를 재검증하지 않는다 — 그것은
   `scripts/setup_stockfish.sh` / `ceb track-b status`의 일이다.)
2. `scan_track_b`(`bench/ceb/scan/track_b_scan.py`)로 베이스라인 대비 후보를
   **스캔**: diff 화이트리스트(`allowed_paths.txt` / `forbidden_paths.txt`) 및
   콘텐츠 규칙(바이너리/NNUE/북/테이블베이스 페이로드, 하네스 핑거프린팅, 변경된
   소스에 도입된 네트워크/프로세스 syscall, 심볼릭 링크). `fail` 발견 또는
   화이트리스트 위반이 있으면 **무엇도 빌드하기 전에** 중단한다.
3. **베이스라인 빌드**, 그 다음 **후보 빌드**. 각각 트리를 작업 디렉터리로 하여
   `bash <build-script>`를 실행한다(빌드 타임아웃 1800초). 0이 아닌 종료, 스크립트
   누락, 또는 `<engine-relpath>`를 산출하지 못하는 빌드는 중단을 일으킨다. 산출된
   엔진은 실행 가능하게 만들어진다(`chmod +x`).
4. `run_track_b_round`(internal 러너 — 신뢰된 레퍼런스)를 통해 **후보-대-베이스라인
   쌍 매치 진행**. 이는 Track B 라운드 흐름을 재사용한다: UCI handshake, 쌍 색-교대
   오프닝, 양쪽 엔진에 `Threads=1` / `Hash=16`, 델타 Elo 채점.
5. **메타데이터 조립**(`build_metadata`)과 `track_b` 블록 추가:
   `baseline_tree_hash`와 `candidate_tree_hash`(`hash_directory`를 통해 각 트리의
   상대 경로 + 내용에 대한 sha256), 그리고 `build_script`.
6. 결과 **서명**(`sign_official_result`)과 산출물 작성.
7. eval 팩이 주어진 경우 **공개 아티팩트 누출 스캔**(P0.8, `scan_public_artifacts`)을
   실행한다. 누출이 발견되면 중단한다(아래 참고).

### 출력

스키마 `ceb.track_b.official_result/v1`의 단일 결과 dict이며 다음을 포함한다:
`run_id`, `track`, `round`, `finished_at`, `engine_jail`, `scan.passed`, `score`
(`ceb.score.track_b/v1`: W/D/L, 결함, `delta_elo`, `delta_elo_ci95`, 페널티,
`final_delta_elo`), `feedback`, `metadata`(`track_b` 트리 해시와
`software.stockfish_baseline = "sf_18/cb3d4ee"` 포함), `verified`, 그리고
`signature` 블록. 호스티드 경로에서는 `profile`과 `verification_grade`도 추가된다.

`runs/<run-id>/track_b_official_<round>/` 아래의 산출물:

- `official_result.json` — 공개(위의 결과).
- `scan_report.json` — 비공개(전체 스캔 발견 사항).
- `leak_scan.json` — 비공개(eval 팩이 주어졌을 때, 비밀을 직접 echo하지 않고
  해시만 기록).

서명은 `sign_official_result`가 Ed25519 > HMAC > unsigned 순으로 선택한다.
`CEB_SIGNING_PRIVATE_KEY`가 설정되면 공개키(Ed25519) 서명을, 아니면
`CEB_SIGNING_KEY`로 대칭 HMAC-SHA256을, 둘 다 없으면 `signature.status`가
`unsigned`(암호학적 진위 없음)가 된다. 대칭 HMAC은 같은 키를 가진 당사자에게만
인증되며 공개키 증명(attestation)이 아니다 — 자세한 내용은
`docs/RESULT_SIGNING.md`를 참고하라.

### 후보용 engine jail

`--engine-jail docker`는 `run_track_b_round`로 전달되며, 이는 **후보** 엔진을
Docker 감옥(engine jail, `bench/ceb/jail/`, `scripts/build_jail_image.sh`로
빌드된 이미지 `chess-en-bench-jail:0.4`)에 가둔다. 베이스라인 빌드는 운영자가
제공하며 호스트에서 신뢰된 상태로 실행된다. 후보는 자신의 워크스페이스 디렉터리
안의 단일 실행 파일이어야 하며, 그렇지 않으면 감옥 요청이 거부된다. Docker가
없거나 이미지가 없으면 실행 가능한 `EngineJailError`가 발생한다. `--engine-jail
none`(기본)이면 두 엔진 모두 호스트에서 실행된다.

이 감옥은 평가 시 **엔진 실행**을 가두는 공식 경로다. 전체 하니스를 컨테이너에
넣는 레거시 `--sandbox docker`(개발/호환 경로)와는 다르며 공식 경로가 아니다.

## 호스티드 verified 경로 (P0.6)

호스티드 워커만이 verified Track B 결과를 생성할 수 있다. 후보를 제출하고
워커가 처리한다:

```bash
ceb hosted submit-track-b \
  --candidate-src /path/to/candidate \
  --baseline-src /path/to/baseline \
  --run-id <id> --db runs/hosted.sqlite \
  [--build-script ceb_build.sh] [--engine-relpath ceb_engine]

ceb hosted worker run-once --db runs/hosted.sqlite \
  --eval-pack <private-pack> --engine-jail docker
```

- `cmd_hosted_submit_track_b`는 후보/베이스라인 트리를 스냅샷하고
  (`snapshot_workspace`, 해시 포함) `track_b_submissions` 테이블에 행을 기록한 뒤
  (candidate/baseline 스냅샷+해시, `build_script`, `engine_relpath`) 잡 종류
  `track_b_official_eval`(`JOB_KIND_TRACK_B`)을 큐에 넣는다.
- 워커(`bench/ceb/hosted/worker.py`)는 잡을 원자적으로 클레임하고 잡 종류로
  분기한다. Track B 잡이면 `latest_track_b_submission`을 읽어
  `run_hosted_track_b`(`bench/ceb/hosted/track_b_eval.py`)를 호출하고, 결과를
  `mode=track_b_official`(`TRACK_B_OFFICIAL_MODE`), 점수는 최종 델타 Elo
  (`track_b_score`: `final_delta_elo`), `track="B"`로 DB에 기록한다.

### verified 요건

`run_hosted_track_b`는 다음을 모두 만족할 때만 `verified=true`를 만든다:

- **verifiable 프로파일**(official / final-production). smoke는 진단 전용이라
  verifiable이 아니며 결코 verified가 되지 않는다.
- **후보 엔진 Docker 감옥**(P0.1): verifiable 프로파일은 `engine_jail == "docker"`
  여야 한다. 아니면 평가 전에 거부한다(`TrackBPipelineError`).
  `--dev-allow-unjailed`(개발 전용)는 감옥 없이 실행하되 결과를 강제로
  `verified=false`(`diagnostic-unjailed`)로 만들어 리더보드에 절대 오르지 않게 한다.
- **비공개/공식 오프닝 팩**: verified는 `--eval-pack`이 필수다. 공개 오프닝만으로는
  verify를 거부한다.
- **소스 우선 게이트**: diff 화이트리스트 + 콘텐츠 스캔 통과, 그리고 베이스라인과
  후보가 *동일한* 빌드 스크립트로 빌드됨(위 진단 CLI와 동일한
  `run_official_track_b` 본문을 공유).
- **공개 아티팩트 누출 스캔 통과**(P0.8). 누출 시 verify 거부 + 잡 failed.
- **서명**(Ed25519 > HMAC > unsigned).

워커 CLI의 `--engine-jail` 기본값은 `docker`다. smoke 프로파일은 verifiable이
아니므로 flag와 무관하게 감옥 없이 실행된다.

### 프로파일과 매치 크기

프로파일은 `bench/ceb/hosted/profiles.py`에 정의된다. `run_hosted_track_b`는
`_MATCH_SIZE`로 프로파일 티어별 매치 크기를 정한다:

- `smoke` — 진단(`diagnostic-smoke`), verifiable=false, 리더보드 제외. CI/플러밍용
  tiny 매치(games=2, movetime=30ms)로 감옥 없이 실행.
- `official` — verifiable(`verified-official`). official 티어 매치(games=200,
  movetime=200ms).
- `final-production` — verifiable(`verified-final-production`). 프로덕션 규모 매치
  (games=1000, movetime=1000ms). 리더보드는 final 티어를 official보다 선호한다.

`verification_grade`는 결과 JSON과 DB 행에 저장된다: `verified-official` /
`verified-final-production` / `diagnostic-smoke` / `diagnostic-unjailed`.

리더보드 / `ceb hosted result show` / 공식 결과 API는 공유 선택자
`select_best_verified_result`(`bench/ceb/hosted/db.py`)를 통해 run별 단일 best
verified 결과를 고르므로 항상 일치한다. smoke는 verified가 아니므로 절대 선택되지
않는다. `verified_leaderboard(conn, track="B")`가 Track B 리더보드를 제공한다.

## verified vs 진단 — 코드가 강제하는 것, 운영자가 해야 하는 것

**코드가 강제하는 것** (두 경로 공통):

- 어떤 빌드도 하기 전에 스캔이 통과해야 한다;
- 베이스라인과 후보는 *동일한* 빌드 스크립트와 엔진 relpath로 빌드된다;
- 빌드 실패 / 엔진 누락은 중단을 일으킨다;
- 두 트리의 트리 해시가 메타데이터에 기록된다;
- UCI 옵션(`Threads=1`, `Hash=16`)이 라운드 러너에 의해 양쪽 엔진에 전송된다;
- (호스티드 verified) 감옥 = docker, 비공개 팩, 누출 스캔, 서명이 강제된다.

**운영자 책임 — 코드가 강제하지 않음:**

- 두 트리에 대한 실제 고정 Stockfish 빌드 래퍼(예: `make -C src build`를 감싸는
  `ceb_build.sh`) 제공;
- 베이스라인과 후보 빌드 사이의 동일한 컴파일러 플래그 보장;
- 후보가 화이트리스트된 탐색 변경만 적용된 고정 Stockfish임을 확인하는 `bench` /
  속도 정합성 검사.

파이프라인은 빌드 스크립트가 산출하는 것을 빌드하고 대국시킨다. 컴파일러 플래그를
검사하지도, `bench` 정합성 검사를 실행하지도 않는다. 운영자가 통제하는 호스팅
경로를 통해 재현되기 전까지는 CLI 결과를 진단용으로 취급하라.

## 테스트와 CI

`tests/test_track_b_official.py`는 **작은 가짜 소스 트리와 번들된 Python UCI
엔진을 제자리에 복사하는 가짜 빌드 스크립트**로 진단 파이프라인과 호스티드 통합을
처음부터 끝까지 검증한다 — 실제 Stockfish도 컴파일러도 관여하지 않는다. 토이 트리
테스트는 happy path(빌드, 채점, 구별되는 트리 해시 기록, `official_result.json`
작성), 금지 파일 거부(스캐너 중단), 빌드 스크립트 누락 중단, 그리고
`--dev-allow-unjailed`가 `diagnostic-unjailed`를 만드는지를 다룬다.

verified-in-jail 경로(`test_hosted_track_b_verified_in_jail`)는 **Docker opt-in**
이다: `CEB_DOCKER_TESTS=1`이고 docker와 `chess-en-bench-jail:0.4` 이미지가
준비된 경우에만 실행되며(`_jail_image_ready`), 감옥 안 후보 엔진 + 비공개 팩으로
`verified-official` 결과가 나고 `verified_leaderboard(track="B")`에 오르는지를
확인한다. **실제 고정 Stockfish 빌드 래퍼는 운영자 단계**다 — 테스트는 토이
트리만 쓴다.

CI는 이 파이프라인을 실행하지 않는다. CI는 토이 Track B *라운드*(`BenchRandom`을
쓰는 `ceb track-b round run`)만 실행한다. CI에는 Stockfish, Docker, 클라우드
실행이 없다.
