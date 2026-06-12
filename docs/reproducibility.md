# 재현성(Reproducibility)

chess_en_bench 실행을 반복 가능하게 만드는 요소, 나중에 감사할 수 있도록 영속화되는
대상, 그리고 결정성(determinism)이 솔직히 어디서 끝나는지.

## 구현됨

### 게임별 시드

내부 매치 러너(`bench/ceb/match/internal_runner.py`)는 모든 게임에 시드를 부여한다.
`play_match(..., base_seed=N)`은 게임 `i`에 시드 `base_seed + i`를 주고,
`play_game`은 첫 수 이전에 그 시드를 **두** 엔진 모두에게 보낸다.

    setoption name Seed value <base_seed + i>

맥락별 시드 부여:

- 공식/quick 라운드(`bench/ceb/rounds/round_runner.py`)와 Track B 라운드
  (`bench/ceb/track_b/round_runner.py`): `base_seed = 1000 * round_number`. 같은
  라운드 번호를 다시 실행하면 동일한 시드를 재생한다.
- 게이트 미니 매치(`bench/ceb/gate/gate_runner.py`): `play_match`의 기본값,
  `base_seed = 1`.

벤치마크 상대(`python -m ceb.match.opponents <Name>`)는 `Seed` UCI 옵션을 구현하고
이로부터 자신의 `random.Random`을 재설정한다. `setoption`을 거부하는 후보 엔진도
허용된다. 색상은 결정적으로 교대된다(짝수 인덱스 게임에서 후보가 백). 무승부 판정은
규칙 기반(fifty-move rule, `max_plies` 상한)이며 판단 기반이 아니다.

### 결정적 오프닝

시작 포지션은 검증된 JSONL 스위트(`bench/ceb/match/openings.py`)에서 온다. 모든
오프닝의 모든 수는 로드 시점에 오라클로 점검되므로, 손상된 스위트는 조용히 포지션을
바꾸는 대신 `OpeningError`를 일으킨다. 선택은 순수 산술이며 무작위성이 없다.

- 라운드 모드는 해석된 스위트의 처음 `openings_limit`개 오프닝을 취한다(quick 2,
  공식 6 — `tracks/a_from_scratch/scoring.yaml`).
- 상대 `j`는 `rotate_suite(suite, pairs, j * pairs)`를 받는다 — 고정된 순환 윈도우
  이므로 라운드가 스위트 전체를 덮고 같은 상대는 항상 같은 오프닝을 본다.
- 게임은 쌍으로 진행된다. 연속된 두 게임이 하나의 오프닝을 색상만 바꿔 재사용하므로
  후보가 각 오프닝을 백과 흑 양쪽으로 두게 된다.

매치 보고서는 스위트(`"openings"`)와 각 게임의 `opening_id`를 기록하고, 라운드
보고서는 `"openings_used"`를 기록한다.

### 평가 팩은 평가 조건의 일부다

공식 라운드와 strict 게이트는 평가 팩을 해석한다(`bench/ceb/eval_pack.py`). 공개
데이터에 선택적 비공개 디렉터리(`--eval-pack`, 또는 공식/strict 실행에서는
`CEB_PRIVATE_EVAL_DIR`)가 더해진다. 팩의 FEN, perft, 오프닝 내용은 게이트 결과와
라운드 시작 포지션을 바꾸므로, **두 실행은 같은 팩 아래에서만 비교 가능하다**.
비공개 팩에 버전을 매겨라. 개정마다 안정적인 `manifest.json` `"name"`을 부여하면
라운드 보고서의 `"eval_pack"` 블록이 이름, 소스, 행 수를 기록하며, 이것이 점수가
무엇에 대해 측정되었는지 감사하는 방법이다.

### 고정된 Track B baseline

`tracks/b_stockfish_opt/stockfish.lock`은 Stockfish 18, 태그 `sf_18`, 커밋
`cb3d4ee`로 고정한다 — 움직이는 브랜치가 아니다. `scripts/setup_stockfish.sh`는 그
태그를 체크아웃하고 커밋이 불일치하면 단호히 실패한다. Track B 라운드
(`ceb track-b round run`)는 어떤 게임이든 시작하기 전에 diff 화이트리스트를 점검한
뒤, `Threads=1 Hash=16`을 두 엔진 모두에게 보내 쌍 오프닝·색상 교대 게임을 둔다.
두 바이너리에 동일한 컴파일러 플래그와 빌드 조건을 두는 것은 실제 평가에서 정책상
요구되며 — 문서화되어 있으나 코드로 강제되지는 않는다.

### 영속화되는 실행 메타데이터

평가가 생성하는 모든 것은 `runs/<run_id>/` 아래에 떨어진다.

- `state.json` (`ceb.run.state/v1`) — 게이트 상태/시도, 공식 라운드 예산, 점수가
  포함된 전체 라운드 궤적.
- `gate_report.json` (`ceb.gate.report/v1`) — 체크별 결과와 어떤 게이트 정책이
  실행됐는지 알려주는 `"strict"` 필드.
- `round_<N>/report.json` (`ceb.round.report/v1`) — 모드, `strict_gate`,
  `eval_pack`, `openings_used`, 상대별 합계, 결함, 점수.
- `round_<N>/match_vs_<Opponent>.json` (`ceb.match.report/v1`) — 모든 게임의 전체
  UCI 수 목록, 오프닝 id, 결과, 종료 사유, 최종 FEN.
- `round_<N>/feedback.json` (`ceb.round.feedback/v1`) — 에이전트에게 보여주는 정제된
  집계값(FEN, 수, 오프닝 id 없음).

수 목록, 오프닝 id, 시드(`base_seed + game_index`로 도출 가능)가 저장되므로, 어떤
게임이든 내부 오라클(`bench/ceb/chess/`)로 재생하고 재검증할 수 있다.

### verified 결과의 신뢰 메타데이터

호스티드 워커가 만드는 공개 공식 `verified` 결과의 `metadata` 블록은 기본
재현성 필드(`benchmark_version`, `git_commit`, 이미지 digest, `eval_pack_hash`,
`opponent_pool_hash`, `opening_suite_hash`, 하드웨어/소프트웨어 지문, `random_seed`
— `bench/ceb/hosted/metadata.py`의 `build_metadata`)에 더해 평가 팩의 신뢰 출처를
못박는다(`bench/ceb/hosted/official_eval.py`, `bench/ceb/track_b/official_pipeline.py`).

- `eval_pack_trusted` — 결과가 신뢰된 공식 팩으로 검증됐는지(`verified`이고 신뢰
  검증을 통과했을 때만 `true`).
- `eval_pack_manifest_hash` — 팩 `manifest.json`의 정규화 JSON에 대한 sha256
  (`bench/ceb/hosted/eval_pack_trust.py`의 `compute_manifest_hash`). 디렉터리 내용
  해시인 기존 `eval_pack_hash`와 별개로, 매니페스트 선언 자체를 고정한다.
- `eval_pack_track` / `eval_pack_season` — 매니페스트의 `track`(대문자 정규화)과
  `season`. 점수가 어떤 트랙·시즌 팩에 대해 측정됐는지 감사할 수 있다.
- `eval_pack_id`는 신뢰 검증을 통과하면 매니페스트의 `pack_id`로 채워진다.

신뢰 검증(`validate_official_eval_pack`)은 팩이 `manifest.json` 스키마
`"ceb.eval_pack.manifest/v1"`을 갖고, `official: true` / `visibility: "private"`이며,
요청 트랙과 일치하고, 저장소의 `examples/`·`tests/` 바깥(`--dev-allow-demo-pack`만
이 경로 점검을 우회)에 있을 것을 요구한다. 공개 공식 verified는 팩 내용
해시가 **고정(PIN)** 되어 있을 것을 추가로 요구한다 — 운영자 허용목록(env
`CEB_OFFICIAL_EVAL_PACK_HASHES`, CLI `--official-pack-hash`/`--official-pack-registry`)이
하나라도 있고 그 안에 팩 해시가 들어 있어야 한다. 허용목록이 비어 있으면(고정 안 됨)
평가를 시작하기도 전에 verified가 거부된다. `--dev-allow-unpinned-pack`은 결과를
`verified=false`, 등급 `diagnostic-unpinned-pack`으로 강등한다. 커밋된 데모 팩
`examples/eval_packs/tiny_private`은 공식 매니페스트가 없어 **결코** verified될 수
없으므로(smoke 프로파일은 여전히 데모 팩을 unverified로 쓴다), 데모 팩으로 만든
결과는 `eval_pack_trusted: false`다.

Track B verified 결과는 `metadata.track_b`에 격리 빌드와 신뢰 출처를 추가로 기록한다
(`bench/ceb/track_b/official_pipeline.py`, `bench/ceb/hosted/track_b_eval.py`). 엔진
jail·Ed25519 서명 위에 baseline·build wrapper·빌드 출력·bench까지 못박는다:

- baseline 신뢰(`bench/ceb/track_b/baseline_trust.py`의 `validate_track_b_baseline`):
  `baseline_trusted`, `baseline_trust_mode`, `baseline_tree_hash`,
  `stockfish_lock`. 신뢰 모드는 셋 중 하나다 — `stockfish-lock`(baseline 체크아웃의
  git HEAD가 `tracks/b_stockfish_opt/stockfish.lock`의 커밋과 일치), `hash`
  (`--track-b-baseline-hash` / `CEB_TRACK_B_BASELINE_HASHES` /
  `--track-b-baseline-registry` 허용목록에 트리 해시가 있음), `toy`
  (`--dev-allow-toy-baseline`은 `verified=false`, 등급
  `diagnostic-untrusted-baseline`). v0.3.5에서 `stockfish-lock` 모드는 HEAD 일치만으로는
  부족하다 — 워킹 트리가 깨끗하고(`git_worktree_clean`: `git status --porcelain`이 비어
  수정·미추적 파일 없음) 서브모듈도 깨끗해야(`git_submodules_clean`) 한다. dirty/미추적
  체크아웃은 `stockfish-lock`으로 신뢰되지 않고 `hash` 모드로 떨어진다(없으면 실패). 통과
  시 `worktree_clean: true`와 baseline 내용 해시(`baseline_tree_hash`)가 함께 기록된다.
  `.git`이 없는 스냅샷 baseline은 `hash` 모드(내용 해시 허용목록)로 여전히 신뢰된다.
  신뢰된 모드에서는 `stockfish_lock`에 release/tag/commit이 박힌다.
- build wrapper 해시 고정(`bench/ceb/hosted/build_wrappers.py`의
  `compute_wrapper_hash`/`resolve_wrapper_hashes`): `build_wrapper`,
  `build_wrapper_hash`, `build_wrapper_trusted`, `build_isolation`,
  `build_jail_image_digest`. verified Track B는 후보 트리 바깥의 신뢰된 운영자 래퍼
  파일 해시가 `--build-wrapper-hash` / `CEB_TRACK_B_BUILD_WRAPPER_HASHES` /
  `--build-wrapper-registry`로 고정되어 있을 것을 요구한다. 고정 안 되면
  `--dev-allow-unpinned-wrapper`로만 진행되며 `verified=false`, 등급
  `diagnostic-untrusted-wrapper`다.
- 빌드 출력 경화(`bench/ceb/track_b/build_jail.py`의 `validate_build_output`): jail
  빌드 후 엔진이 존재하고, 실행 가능하며, 일반 파일(심볼릭 링크 아님)이어야 하고,
  출력 트리 어디에도 심볼릭 링크가 없어야 하며, 총 크기 512 MiB 이하·파일 10000개
  이하여야 한다. 통과한 빌드 출력 트리 해시는 `build_output`(baseline/candidate
  각각의 출력 해시)에 기록된다.
- bench/속도 sanity(`bench/ceb/track_b/bench_sanity.py`의 `run_bench_sanity`):
  두 엔진 모두 `bench`를 돌려 엔진별 nodes/nps/output_hash와 `nps_ratio`를 `bench`에
  기록한다. NPS 비율 임계값(`--bench-min-nps-ratio`, 기본 0.3)은 두 엔진이 모두
  `bench`를 지원할 때만 강제되고(toy 엔진은 `supported=false`로 허용된다), jail 시
  후보는 bench도 jail 안에서 돈다. v0.3.5에서 verified Track B의 bench 정책은 더 엄격해졌다:
  verified 경로는 baseline과 후보 **모두** bench를 지원할 것을 요구하며, baseline이 NPS를
  보고하지 못하면(unsupported) verified Track B는 통과하지 않고 실패한다 — 예전의
  "지원 안 됨 = 조용히 통과"는 사라졌다. baseline은 bench를 돌리는데 후보가 못 돌리면
  역시 실패·강등이며 결코 verified가 되지 않는다. verified 경로에서 후보의 engine-jail
  bench 명령 구성이 실패하면 후보 bench는 거부되고(error) 호스트에서 대신 돌지 않는다
  (host fallback 없음; 내부적으로 `_run_bench(require_candidate_jail=...)`). verified
  실행이 bench를 지원하면서 NPS 임계값을 넘기지 못하면, `--dev-allow-no-bench`는 그
  실패를 통과시키지 않고 결과를 `verified=false`, 등급 `diagnostic-no-bench`
  (`bench/ceb/hosted/profiles.py`)로 강등한다 — 실패한 bench는 결코 리더보드에 오르지
  못한다. 플래그가 없으면 단호히 실패한다(결과 없음). 실제 공개 Track B는 bench를
  지원하는 고정된 Stockfish가 필요하다.
- verified 결과의 `metadata.track_b`는 bench 판정을 감사 가능하게 기록한다 —
  `bench_required`, `bench_supported`, `bench_passed`, `nps_ratio`, `min_nps_ratio`,
  그리고 `bench_policy` 객체(`supported_required_for_verified`,
  `enforced_when_baseline_supports_bench`, `override_downgrades_to_diagnostic`)에 더해
  전체 bench 리포트가 들어간다.

verified는 `build_isolation == "jail"`만 허용하며 host 빌드 경로는 진단 전용
(`verified=false`, `build_script`만 채워진다)이다. 일반화하면, 모든 `--dev-*` 플래그는
verifiable 실행을 실패시키거나 진단(unverified) 등급을 강제할 뿐, verified를 유지하는
플래그는 하나도 없다. 마찬가지로 verifiable 프로파일은 정적 스캔/strict 게이트/빌드/매치
이전에 Ed25519 개인키를 해석·로드 검증하므로(`bench/ceb/hosted/signing.py`의
`require_ed25519_private_key`; `official_eval.py`, `track_b_eval.py`), 키가 없으면
강등(`--dev-allow-unsigned`)되거나 실패하고, 키가 손상됐으면 정제된 메시지와 함께 일찍
단호히 실패해 서명 실패로 스테이징된 공개 아티팩트가 남지 않는다. 검증된 키 경로는 서명
시점에 재사용된다. HMAC/unsigned는 진단 전용이다.

### 릴리스 매니페스트가 시즌 신뢰 앵커를 고정·공개한다

`ceb hosted release-manifest create --track --eval-pack --official-pack-hash
--public-key [--track-b-baseline-hash --build-wrapper-hash] --out`
(`bench/ceb/hosted/release_manifest.py`)은 한 시즌의 모든 공개 공식 신뢰 앵커를
못박는 **비밀 없는(secret-free)** 매니페스트(스키마 `ceb.release_manifest/v1`)를
낸다. 공개 리더보드가 이를 게시하면 누구든 어떤 시즌이 어떤 앵커를 썼는지 점검할 수
있다. 내용:

- `benchmark_version`, `git_commit`, `track`, `season`.
- `official_eval_pack_id` / `official_eval_pack_hash` / `official_eval_pack_manifest_hash`
  — 고정된 공식 팩 해시가 반드시 있어야 하며(없으면 거부), 팩은 신뢰 검증을 통과해야
  한다.
- `operator_public_key_fingerprint` — 운영자 공개키의 **지문만**(키 자체는 절대 넣지
  않는다). `--public-key`가 필수다.
- `engine_jail_image`(`chess-en-bench-jail:0.4`) + `engine_jail_image_digest`.
- Track B는 `track_b_baseline_hash`, `track_b_build_wrapper_hash`,
  `build_jail_image_digest`를 추가로 박으며 `--track-b-baseline-hash`와
  `--build-wrapper-hash`가 정확히 하나씩 필수다(둘 이상이면 모호하다며 거부). v0.3.5는
  `track_b_baseline_trust_mode`(`"hash"` — 매니페스트는 가장 강한 내용 해시 모드로
  baseline을 고정한다)와 `bench_policy`(`min_nps_ratio`,
  `enforced_when_baseline_supports_bench`, `override_downgrades_to_diagnostic`)를
  함께 박는다.
- `leaderboard_policy`, `known_limitations`.

매니페스트는 비밀이 없도록 설계된다 — 개인키도, 비공개 eval 팩 경로도, 숨은 FEN·오프닝
id도, 비공개 아티팩트 경로도 들어가지 않는다.

v0.3.5부터 매니페스트는 **서명·검증 가능**하다(Ed25519). `release-manifest create`에
`--private-key op.pem`(또는 `CEB_SIGNING_PRIVATE_KEY`)을 주면 즉시 서명되고, 없으면
읽을 수는 있으나 서명되지 않은 채로 기록된다. 사후 서명은 `ceb hosted release-manifest
sign --manifest release.json --private-key op.pem`, 검증은 `ceb hosted release-manifest
verify --manifest release.json --public-key op.pub.pem`이다. 서명 블록은 공식 결과와
동일한 방식으로 서명 블록을 제외한 정규화 매니페스트를 덮는다. 검증이 `authentic: true`가
되는 것은 **대역 외(out-of-band) 공개키**에 대해 검증할 때뿐이다 — 서명되지 않은
매니페스트는 읽을 수는 있어도 결코 authentic이 아니며, 임베드된 키로 검증하는 것은
내부 일관성만 증명할 뿐 진위는 증명하지 못한다. 공개 배포용 매니페스트는 반드시
서명되어야 한다. 이 서명된 매니페스트는 재현성·감사 앵커로서 결과 번들에도 함께 들어간다.

### 공개 아티팩트는 누출 스캔 후에만 공개된다

공개 공식 평가는 공개 아티팩트를 절대 직접 공개로 쓰지 않는다
(`bench/ceb/storage/promotion.py`). `official_result.json`, `feedback.json` 같은
공개 대상 아티팩트는 먼저 **스테이징** 상태로 기록된다 — 파일은 디스크에 있지만
매니페스트 항목은 `visibility: private` + `staged_public: true` 마커라 무엇도
서빙되지 않는다. 누출 스캐너(`scan_public_artifacts(..., staged=True)`)가 스테이징된
집합 전체를 재귀적으로 훑고, 통과한 경우에만 `promote_public_artifacts`가 이를
원자적으로 `visibility: public`으로 승격한다. 누출이 잡히면 아무것도 승격되지 않고
잡 시도에 대한 공개 매니페스트 항목이 존재하지 않으므로(워커는 `visibility=public`만
등록한다) 공개되는 것이 없다. Track A(`official_eval.py`)와 Track
B(`official_pipeline.py`)가 모두 이 스테이징→스캔→승격을 거친다.

### 공개 API가 릴리스 매니페스트와 준비 상태를 비밀 없이 서빙한다

호스티드 API(`bench/ceb/api/main.py`)는 비밀 없는 공개 GET 두 개를 노출한다. 새
`GET /api/hosted/release-manifest`는 `CEB_RELEASE_MANIFEST` 경로의 매니페스트를
서빙한다(설정 안 됐으면 503, 파일 없으면 404). 이 공개 GET에는 관리자 토큰이 필요
없으며, 매니페스트는 구성상 비밀이 없다. 기존 `GET /api/hosted/readiness/public`도
그대로 비밀 없는 준비 메타데이터(버전, 정책, 프로파일 verifiability)를 낸다. 관리자
POST 엔드포인트는 상수 시간 토큰 비교(`hmac.compare_digest`)로 계속 보호된다.

### 준비 선언 게이트가 단일 공개 공식 판정 지점이다

`ceb hosted readiness declare`(또는 `ceb hosted readiness check
--strict-public-official`)이 통과할 때만(`bench/ceb/hosted/readiness.py`, 스키마
`ceb.hosted.readiness/v2`) 이 저장소가 "Track A·Track B용 공개 공식 단일 노드 호스티드
벤치마크로 준비됨"이라고 선언된다. v0.3.5의 `readiness declare`는 **항상** strict 공개
공식 정책을 적용하며 `public_official_declaration == "ready"`일 때만 종료 코드 0을
낸다(`--json`은 JSON만 출력). 비-strict `readiness check`는 진단용으로 남는다 —
공식 선언 게이트는 오직 `readiness declare` 또는 `readiness check
--strict-public-official`뿐이다. 단일 노드(SQLite + 로컬 FS)라는 점은 솔직하게
유지되며, 분산 프로덕션 SaaS가 아니다. 버전 하한은 0.3.5이며, 리포트는
`public_official_declaration`(`"ready"` | `"not-ready"`)과 `blocking_failures`
(실패한 필수 체크 목록)를 담는다. `readiness declare`는 최상위에
`declaration_certificate` 객체(스키마 `ceb.hosted.declaration_certificate/v1`)를
추가하며, 여기에 `benchmark_version`, `track`, `ready`, `public_official_declaration`,
`release_manifest_hash`, `operator_public_key_fingerprint`, `official_eval_pack_hash`,
`track_b_baseline_hash`, `build_wrapper_hash`, `timestamp`, `known_limitations`가 담겨
재현성·감사 앵커가 된다. `--track BOTH`는 Track A 팩 체크와 모든 Track B 체크를 함께
돌린다. CLI `--json` 플래그는 JSON만 출력한다(깨끗한 기계 출력).

- strict Track A는 다음을 필수로 본다 — 버전/DB/docker/엔진 jail
  이미지/신뢰+고정된 팩/데모 팩 거부/Ed25519 개인키/공개키/키쌍 일치/final-production
  게임 하한.
- strict Track B는 추가로 — build jail 이미지/빌드 래퍼(존재+실행 가능+트리 바깥+해시
  고정)/baseline 신뢰(내용 해시 고정 또는 깨끗한 stockfish-lock)/bench 정책(강제이며
  우회 불가: 실패한 bench나 `--dev-allow-no-bench`는 강등할 뿐 verified가 되지 않는다)/
  Track B API 엔드포인트 import 가능 여부. v0.3.5에서 strict Track B는 bench 능력을
  **증명**한다 — `--track-b-baseline-engine <bench 가능 엔진>`을 주면 readiness가 그
  엔진으로 bench를 돌리고, 새 BLOCKING 체크 `track_b_bench_capability`가 NPS 보고를
  확인한다. 없으면 strict Track B 선언이 BLOCK된다.

### 공개 결과 번들이 매니페스트와 키 지문을 담을 수 있다

`ceb hosted result export --release-manifest <path>
--public-key <pem> | --public-key-fingerprint <fp>`
(`bench/ceb/hosted/result_bundle.py`)은 선택된 최선 verified 결과의 공개 아티팩트만
담은 번들에, v0.3.4부터 릴리스 매니페스트(`release_manifest.json`)와 운영자 공개키
지문을 함께 넣을 수 있다. v0.3.5에서는 서명된 매니페스트가 번들에 들어가며,
`VERIFY.txt`에는 `ceb hosted release-manifest verify --manifest release_manifest.json
--public-key <operator.pem>`으로 대역 외(out-of-band) 공개키에 대해 검증하라는 안내가
포함된다. 번들은 여전히 선택되지 않은 smoke/진단 결과와 모든 비공개 아티팩트(스캔/누출
리포트, 매치 로그)를 제외하며, 개인키나 숨은 팩 데이터는 결코 넣지 않는다.

### 설정 주도 파라미터

게이트와 라운드 파라미터는 버전 관리되는 파일에 있다.
`tracks/a_from_scratch/public/gate_config.yaml`,
`tracks/a_from_scratch/scoring.yaml`(라운드 모드, 오프닝 한도, 상대 및 앵커 레이팅,
페널티), `tracks/a_from_scratch/track.yaml`(공식 라운드 예산). 동일한 설정에 동일한
시드와 팩을 더하면 동일한 평가 조건이 된다.

### 버전 교차 점검으로서의 CI

`.github/workflows/ci.yml`은 전체 파이프라인을 실행한다 — 테스트, doctor, 공개 및
strict 게이트, 준비된 워크스페이스 quick 라운드(`runs/ci_smoke/round_1/report.json`
존재 단언), 두 모드의 리더보드 — Python 3.10/3.11/3.12에서 매 push와 PR마다 실행되어
평가 파이프라인이 지원 인터프리터 전반에서 지속적으로 점검된다. CI는 Stockfish도
Docker도 사용하지 않는다.

## 동일한 quick 라운드 다시 실행하기

quick 라운드는 무료이므로(공식 예산을 소비하지 않음) 안정성 점검을 위해 반복할 수
있다.

    ceb workspace prepare --track A --run-id demo
    # put your engine in runs/demo/workspace, then:
    ceb round run --track A --workspace runs/demo/workspace --round 1 --quick
    cp runs/demo/round_1/match_vs_BenchRandom.json /tmp/first.json
    ceb round run --track A --workspace runs/demo/workspace --round 1 --quick
    diff /tmp/first.json runs/demo/round_1/match_vs_BenchRandom.json

실행 id `demo`는 `runs/demo/workspace` 레이아웃에서 추론된다(`default_run_id`).
`--run-id`로 재정의할 수 있다. 같은 라운드 번호는 같은 `base_seed`(1000), 같은 상대,
같은 오프닝, 같은 movetime을 뜻한다. 라운드 번호를 다시 실행하면 `round_<N>/`
아티팩트를 **덮어쓰고** `state.json`에 덧붙이므로 — 보고서를 먼저 복사하라. 동일한
수 목록은 아래 주의사항 범위 안에서만 기대하라(`elapsed_s`는 항상 다르다).

## 솔직한 주의사항

- **Movetime 타이밍은 벽시계(wall-clock)다.** 탐색 깊이가 경과 시간에 의존하는 엔진은
  머신 부하가 다르면 다른 수를 고를 수 있다.
- **깊이 기반 상대도 시간 제한을 받는다.** `BenchRandom`과 `BenchGreedyCapture`는
  시드가 주어지면 완전히 결정적이지만, 나머지는 마감 시한에 맞서 반복 심화
  (iterative deepening)를 사용하므로 부하가 걸린 머신은 같은 시드에서도 선택된 수를
  바꿀 수 있다. 활성화된 선택적 앵커 엔진(`UCI_Elo` 수준의 Stockfish)에도 같은 것이
  적용된다.
- **후보 엔진은 비결정적일 수 있다.** 제출물이 `Seed`를 따르도록 강제하는 것은 없다.
  스레드, 해시 테이블, 자체 타이밍 로직이 실행마다 달라질 수 있다.
- **타임아웃과 결함 경계는 `movetime + grace_ms` 근처에서 타이밍에 민감하다.**
- **환경 고정은 부분적이다.** `--sandbox docker`는 평가를
  `chess-en-bench-evaluator:0.2` 이미지(`python:3.12-slim` 베이스)에서 실행하여
  Python 런타임을 고정하지만 — 베이스 태그가 digest로 고정되어 있지 않아 다른 날
  재빌드하면 달라질 수 있고, 호스트 실행(기본값)은 머신에 있는 것을 그대로 사용한다.

## 러너

내부 Python 러너가 기본값이며 모든 매치와 테스트의 신뢰 기준이다. 대량 Track B
매치를 위한 선택적 `fastchess` 어댑터(`ceb track-b round run --runner fastchess`)가
제공되지만, 결함을 귀속시키지 않고 결과에 접어 넣으며 아직 오라클 PGN 사후 검증이
없으므로 내부 러너가 권위 있는 기준으로 남는다. `cutechess-cli` 어댑터는 구현되어
있지 않다.
