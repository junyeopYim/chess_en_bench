# 리더보드 거버넌스

리더보드에 무엇이 나타나는지, 어떻게 순위가 매겨지는지, 얼마나 신뢰할 수
있는지.

**두 개의** 리더보드가 있다. 둘은 한 가지 결정적 속성에서 다르다:
항목이 **검증**되었는지 여부.

| | 검증됨(호스티드) | 자가 보고(로컬) |
| --- | --- | --- |
| 코드 | `verified_leaderboard`, `bench/ceb/hosted/db.py` | `compute_leaderboard`, `bench/ceb/scoring/track_a.py` |
| 항목 출처 | 호스티드 SQLite DB의 `results` 행 | `<results>/*/state.json` 스캔 (기본 `runs/`) |
| `verified` 플래그 | `True` (워커가 발행한 것만) | 항상 `False` |
| CLI | `ceb hosted leaderboard --db --track` | `ceb leaderboard compute --track --results` |
| API | `GET /api/hosted/leaderboard?track=A` | `GET /api/leaderboard?track=A` |

`GET /api/leaderboard?track=B`는 미검증 로컬 보드 경로이지만 호스티드 DB가 있으면
검증된 호스티드 Track B 보드(`verified_leaderboard(conn, track="B")`)로 **위임**하고
(`note`로 `GET /api/hosted/leaderboard?track=B`를 안내), 호스티드 DB가 없으면 빈
항목과 함께 그 경로를 가리킨다(`bench/ceb/api/main.py`). 비밀 없는
`GET /api/hosted/readiness/public`(스키마 `ceb.hosted.readiness.public/v1`)는 버전,
프로파일 verifiable 여부, 리더보드 정책만 노출한다 — 운영자 앵커(팩·키·이미지)는
`ceb hosted readiness check --strict-public-official` CLI에서만 점검한다. 관리자
POST/업로드 엔드포인트는 `CEB_ADMIN_TOKEN`이 설정되지 않으면 503으로 유지된다.

## 검증됨 대 미검증

**호스티드 공식 워커만 `verified:true`를 발행한다.** 결과는
`ceb hosted worker run-once`를 통해 `run_official_eval`
(`bench/ceb/hosted/official_eval.py`)이 **verifiable 프로파일**(`official` /
`final-production`)로 산출하고 모든 게이트가 통과한 경우에만 검증된다. 그 경로는:

1. 비공개 eval 팩 필수(없으면 거부),
2. **엔진 감옥 가드**: verifiable 프로파일은 `engine_jail == docker`가 아니면
   평가 전에 검증을 거부한다(P0.1),
3. **신뢰 + 핀 고정 공식 eval 팩 가드 (A, req1)**: 검증된 결과는 운영자 OFFICIAL
   팩을 요구한다(`bench/ceb/hosted/eval_pack_trust.py`,
   `validate_official_eval_pack`). 팩에는 `manifest.json`(스키마
   `ceb.eval_pack.manifest/v1`, 키 `pack_id` / `name` / `track` / `season` /
   `official: true` / `visibility: "private"` / `openings_mode`)이 있어야 하고,
   리포의 `examples/` · `tests/` **밖**에 살아야 한다(`--dev-allow-demo-pack`만이 이
   경로 검사를 우회). 나아가 공식 검증은 팩 콘텐츠 해시가 운영자 허용목록에 **핀
   고정**되어 있어야 한다(env `CEB_OFFICIAL_EVAL_PACK_HASHES`, CLI
   `--official-pack-hash`, `--official-pack-registry` 중 하나로 공급;
   `official_eval.py` / `track_b_eval.py`가 강제). 허용목록이 **전혀 없으면** 검증은
   평가 전에 **실패**하며, `--dev-allow-unpinned-pack`만이 결과를 강제로
   `verified: false`(grade `diagnostic-unpinned-pack`)로 강등시킨다. `smoke`는
   여전히 데모 팩을 미검증으로 사용한다,
4. **Ed25519 서명 가드 (B)**: 검증된 결과는 Ed25519 비공개 키
   (env `CEB_SIGNING_PRIVATE_KEY` 또는 `--signing-key`)를 요구한다. 키가 없으면
   평가 전에 검증을 거부하며, `--dev-allow-unsigned`는 결과를 강제로
   `verified: false`(grade `diagnostic-unsigned`)로 만든다. HMAC은 공식 검증에
   받아들여지지 않는다,
5. 스냅샷의 정적 부정 방지(anti-cheating) 스캔,
6. **비공개** 신뢰 팩 + Docker 엔진 감옥으로 엄격 게이트 + 매치
   (`official_round` / `final_production` / 레거시 `final_eval`),
7. **스테이징(D)**: 공개용 아티팩트는 먼저 STAGED(비공개)로 기록되어 누구에게도
   제공되지 않는다,
8. **공개 아티팩트 누출 스캔**: STAGED 집합을 재귀적으로 스캔(누출 시 검증 거부 —
   공개 항목이 전혀 등록되지 않음),
9. 재현성 메타데이터 + Ed25519 서명,
10. 통과 시에만 스테이징 아티팩트를 공개로 **승격(D)**,
11. DB에 `verified=1`로 기록된 결과(`profile`, `verification_grade` 포함;
    소유권 펜싱 `record_result_if_owned`, `bench/ceb/hosted/db.py`).

비공개 eval 팩이 없거나, **신뢰 공식 팩이 아니거나**, 감옥이 docker가 아니거나
(개발 플래그 없이), **Ed25519 키가 없거나**, 스캔이 실패하거나, 엄격 게이트가
실패하거나, 누출이 탐지되면 워커는 **검증을 거부한다** — 검증된 결과가 기록되지
않는다. 검증된 결과는 신뢰 팩 출처를 메타데이터에 남긴다: `eval_pack_id`,
`eval_pack_hash`, `eval_pack_manifest_hash`, `eval_pack_trusted: true`,
`eval_pack_track`, `eval_pack_season`.

**Track B 빌드 격리 (C).** 검증된 Track B는 후보 소유 빌드 스크립트를 호스트에서
실행하지 않는다(`bench/ceb/track_b/build_jail.py`,
`bench/ceb/hosted/build_wrappers.py`). 후보/베이스라인 트리 **밖**에 있는 신뢰
운영자 빌드 래퍼를 워커에 `--build-wrapper`로 넘기면, 그 래퍼가 Docker 빌드 감옥
안에서 베이스라인과 후보를 **동일하게** 빌드한다(소스 `/src`에 읽기 전용 마운트,
쓰기 가능 `/out`, `--network none`, 읽기 전용 루트 + tmpfs, cpu/mem/pids 한도,
비루트; 리포·eval 팩은 마운트하지 않음). 빌드 감옥 이미지는 기본으로
`chess-en-bench-jail:0.4`를 재사용한다(`chess-en-bench-build-jail:0.4`를 따로 빌드
가능). 진단 CLI 경로 `ceb track-b official run`은 호스트 빌드를 유지하므로
**항상 `verified=false`**이고, `run_official_track_b`는 `build_isolation="host"`로
`verified=True`를 거부한다. 결과 메타데이터는 `build_isolation`(`"jail"` /
`"host"`)을 기록한다.

검증된 Track B는 세 가지 추가 신뢰 앵커도 통과해야 한다(없으면 dev 플래그가
`verified=false` 진단으로 강등):

- **베이스라인 신뢰 (req3)**: `validate_track_b_baseline`
  (`bench/ceb/track_b/baseline_trust.py`)이 베이스라인을 stockfish-lock, hash
  (`--track-b-baseline-hash` / `CEB_TRACK_B_BASELINE_HASHES` /
  `--track-b-baseline-registry`), 또는 toy(`--dev-allow-toy-baseline`,
  `verified=false` grade `diagnostic-untrusted-baseline`)로 검증한다. stockfish-lock
  모드는 git HEAD가 `tracks/b_stockfish_opt/stockfish.lock` 커밋과 일치하는 것만으로는
  부족하고, **클린 워킹 트리**(`git status --porcelain`이 빔, `git_worktree_clean`)와
  **클린 서브모듈**(`git_submodules_clean`)까지 요구하며 콘텐츠 해시를
  `baseline_tree_hash`로 기록한다. 더럽거나 추적되지 않은 체크아웃은 stockfish-lock으로
  신뢰되지 않고 hash 모드로 떨어지거나 실패한다. hash 모드(허용목록 콘텐츠 해시)는
  `.git`이 없는 스냅샷 베이스라인에도 동작한다. 메타데이터 `track_b`에
  `baseline_trusted` / `baseline_trust_mode` / `baseline_tree_hash` / `stockfish_lock`을
  기록한다.
- **빌드 래퍼 해시 핀 (req4)**: 래퍼 파일 해시가 허용목록(`--build-wrapper-hash` /
  `CEB_TRACK_B_BUILD_WRAPPER_HASHES` / `--build-wrapper-registry`)에 핀 고정되어야
  한다(`bench/ceb/hosted/build_wrappers.py`); 아니면 `--dev-allow-unpinned-wrapper`로
  `verified=false` grade `diagnostic-untrusted-wrapper`. 메타데이터 `track_b`에
  `build_wrapper_hash` / `build_wrapper_trusted` / `build_isolation` /
  `build_jail_image_digest`를 기록한다.
- **벤치/속도 정합성 (req6)**: 두 엔진이 bench를 실행하고 엔진별 nodes/nps/output_hash와
  `nps_ratio`를 보고한다(`bench/ceb/track_b/bench_sanity.py`). NPS 비율 임계값
  (`--bench-min-nps-ratio`, 기본 0.3)은 두 엔진 모두 bench를 지원할 때만 강제된다
  (toy 엔진은 `supported=false`로 허용). 이 정책은 **우회 불가능하다**: bench를
  지원하는 베이스라인에서 검증된 실행이 NPS 임계를 통과하지 못하면 플래그 없이는
  하드 실패(결과 없음)이고, `--dev-allow-no-bench`를 줘도 verified를 보존하지 않고
  `verified=false`, `verification_grade=diagnostic-no-bench`로 **강등**되어
  (`bench/ceb/track_b/official_pipeline.py`, `GRADE_DIAGNOSTIC_NO_BENCH`) 검증된
  리더보드에는 결코 오르지 않는다.

**어떤 `--dev-*` 플래그도 verified를 유지하지 못한다.** v0.3.4 감사로 마지막
모호성이 제거되었다: 모든 개발 플래그는 검증 가능한 실행을 **실패**시키거나
결과를 **진단(미검증) grade로 강등**시킨다 — 그 사이는 없다. `--dev-allow-unjailed`→
`diagnostic-unjailed`, `--dev-allow-unsigned`→`diagnostic-unsigned`,
`--dev-allow-unpinned-pack`→`diagnostic-unpinned-pack`,
`--dev-allow-toy-baseline`→`diagnostic-untrusted-baseline`,
`--dev-allow-unpinned-wrapper`→`diagnostic-untrusted-wrapper`,
`--dev-allow-no-bench`→`diagnostic-no-bench`. 이 진단 grade들은
(`bench/ceb/hosted/profiles.py`) **결코 검증된 리더보드에 도달하지 않는다**.

**`smoke` 프로파일(=`--quick-test-mode`)은 결코 verified가 아니다.** 프로파일이
verifiable이 아니므로 어떤 플래그를 줘도 verified 결과를 만들 수 없다("마법 같은
verified"는 없다). 커밋된 데모 팩 `examples/eval_packs/tiny_private`은 공식
manifest가 없어 **결코 검증될 수 없다**(smoke 프로파일용으로는 무방). HMAC·미서명
결과도 결코 공개 공식 검증을 받을 수 없다(레거시/진단으로 남는다).

**로컬 순위는 결코 검증되지 않는다.** `compute_leaderboard`는 로컬
`ceb round run` 호출이 작성한 `state.json` 파일을 스캔하고 모든 항목에
`verified: false`를 찍는다. 이것들은 명령을 실행한 누군가에 의해 자가
보고된 것이며, 하니스는 그것을 증명하지 않는다. 로컬 보드의 페이로드는 이를
명시하기 위해 `verified_only: false`로 설정한다.

## 선택 규칙

두 보드 모두 **실행당 하나의 항목**을, 최고 점수 순으로 순위 매기며, 동일한
우선순위를 사용한다(검증된 보드는 공유 선택자 `select_best_verified_result`를
사용해 리더보드 / `result show` / `official-result` API가 항상 같은 결과를
고르게 한다 — P0.4):

1. 존재한다면 **최고 final-tier** 결과(`final_production` / `final_eval`,
   Track B는 `track_b_official`), 없으면
2. **최고 official-tier** 결과(`official_round` / 레거시 `official`), 없으면
3. **없음** — 그 실행은 순위에 오르지 않는다.

**quick / smoke는 순위에 절대 집계되지 않는다.** 호스티드 워커는 smoke 결과를
검증으로 표시하지 않으므로 검증된 보드에 도달할 수 없다. 로컬 보드에서 quick은
`--include-quick`이 설정되지 않는 한 제외되며, 이 옵션은 **진단** 뷰이고 결코
공식 순위가 아니다 — 그 페이로드도 여전히 `verified_only: false`를 보고한다.

**레거시 "official"이 집계된다.** v0.3 이전 모드 이름 `official`은 공식
라운드로 취급된다: `OFFICIAL_MODES = {"official", "official_round"}`
(`track_a.py`), 그리고 호스티드 쿼리는 `mode in ("official_round",
"official")`과 일치시킨다. `mode` 필드 없이 기록된 로컬 라운드는 기본적으로
`official`이 된다.

eval 모드는 `bench/ceb/rounds/round_runner.py`와
`tracks/a_from_scratch/scoring.yaml`에 정의된다:

| 모드 | 예산 | 게이트 | 상대당 게임 | 오프닝 |
| --- | --- | --- | --- | --- |
| `quick` | free | non-strict | 2 | 2 |
| `official_round` | 1 of 3 units | strict | 4 | 6 |
| `final_eval` | none | strict | 8 | 8 |
| `final_production` | none | strict | 336 (2016 총) | 24 |

프로파일↔모드 매핑은 `bench/ceb/hosted/profiles.py`와
`tracks/a_from_scratch/eval_profiles.yaml`에 있다: `smoke`→`official_round`(tiny,
미검증), `official`→`official_round`, `final-production`→`final_production`. Track B
verified 결과는 `track_b_official` 모드로 final-tier에 들어간다.

## 결과를 등재 가능하게 만드는 것

**검증된 보드**의 경우 항목은 `verified=1`, null이 아닌 `score`, 모드
`final_eval`, `official_round`, 또는 레거시 `official`을 가진 DB `results`
행이어야 한다. 워커만 그런 행을 작성한다.

**로컬 보드**의 경우 항목은 `track`이 일치하는 읽을 수 있는 `state.json`에서
와야 하며, 등재 가능한 모드에서 null이 아닌 `score`를 가진 라운드를 적어도
하나 포함해야 한다. 읽을 수 없거나 비JSON인 상태 파일은 조용히 건너뛴다. 각
항목은 또한 맥락을 위해 `gate_passed`, `rounds_played`,
`official_rounds_played`를 보고한다.

## 무결성 주의 사항

- **자가 보고된 실행은 권위가 없다.** `compute_leaderboard` 출력
  (CLI `ceb leaderboard compute`, API `/api/leaderboard`)은 편의/진단
  뷰다. 항목은 러너가 통제하는 로컬 상태에서 계산되며, 스캔도, 비공개 팩
  강제도, 서명도 없다. 이것들을 공식 순위로 취급하지 않는다.
- **검증된 결과는 공개키로 검증 가능하다.** 검증된 보드는 워커가 산출한
  결과를 반영하며, 운영자의 **Ed25519 비공개 키**로 서명된다(검증된 결과는 반드시
  Ed25519). 검증기(`bench/ceb/hosted/verifier.py`, `verify_result_file`)는
  `authentic`을 **외부에서 별도로 공급된 공개 키**로 서명을 확인했을 때만 참으로
  본다(`signature_trust: "supplied-public-key"`). 결과에 박혀 있는 **임베디드
  공개 키만으로는 진정하지 않다**(`embedded-self-described`, `authentic: false`) —
  공격자가 자기 키로 위조 결과를 서명해 박을 수 있기 때문이다. 검증된 결과가
  Ed25519가 아니면 `public_official_signing: false`로 `authentic`을 무효화한다
  (HMAC·미서명은 결코 공개 공식 진정성을 얻지 못한다). 누구나 게시된 운영자 공개
  키로 `ceb hosted verify-result --public-key`로 독립 확인할 수 있다
  (`docs/RESULT_SIGNING.md` 참조).
- **readiness 선언이 단일 게이트다 (req10).** 리포가 Track A·B의 "공개 공식 단일
  노드 호스티드 벤치마크 준비 완료"인지는 오직 `ceb hosted readiness check
  --strict-public-official` 통과로만 선언한다(`bench/ceb/hosted/readiness.py`, 스키마
  `ceb.hosted.readiness/v2`, 버전 하한 0.3.4). 보고서는
  `public_official_declaration`(`"ready"`/`"not-ready"`)과 실패한 필수 체크 목록
  `blocking_failures`를 담는다. `--track BOTH`는 Track A 팩 체크와 모든 Track B
  체크를 함께 돌리고, CLI `--json`은 깔끔한 기계 출력을 위해 **JSON만** 찍는다.
  엄격 Track A는 버전/db/docker/엔진 감옥 이미지/신뢰+핀 고정 팩/데모 팩 거부/Ed25519
  키/공개 키/키페어 일치/final-production 게임 하한을, 엄격 Track B는 추가로 빌드 감옥
  이미지/빌드 래퍼(존재+실행 가능+트리 밖+해시 핀)/베이스라인 신뢰(콘텐츠 해시 핀 또는
  클린 stockfish-lock)/벤치 정책(우회 불가능: 실패하거나 `--dev-allow-no-bench`면
  강등, 결코 verified 아님)/Track B API 엔드포인트 임포트 가능을 BLOCKING으로 요구한다.
- **운영자 공개키 지문과 배포 경로를 게시한다 (req2).** 공개 리더보드는 운영자
  **공개키 지문**(`operator_public_key_fingerprint`)과 그 키의 배포 경로를 게시해,
  검증자가 별도로 공급할 공개 키의 출처를 알 수 있게 한다. 이 지문은 비밀 없는 릴리스
  매니페스트(`ceb hosted release-manifest create`, 스키마 `ceb.release_manifest/v1`,
  `bench/ceb/hosted/release_manifest.py`)에 실리며, **키 자체는 결코 게시하지 않는다**.
  `--strict-public-official` 엄격 readiness는 로드 가능한 Ed25519 비공개 키, 로드
  가능한 공개 키, 그리고 둘의 **키페어 일치**(비공개 키의 `public_key()` 지문이 공급된
  공개 키 지문과 동일)를 모두 BLOCKING 요구로 강제하며, 보고서에 공개키 지문을 담는다
  (체크 `ed25519_signing_key` / `public_key_verify_ready` / `keypair_match`).
- **릴리스 매니페스트가 시즌의 신뢰 앵커를 핀 고정한다 (req9).** 매니페스트는 핀 고정
  공식 팩 해시(`official_eval_pack_manifest_hash`)와 공개키 지문, 엔진/빌드 감옥 이미지
  다이제스트를 싣고, Track B에서는 정확히 하나의 베이스라인·래퍼 해시(모호하면 에러)와
  함께 `track_b_baseline_trust_mode`(`"hash"`) 및 `bench_policy`(`min_nps_ratio`,
  `enforced_when_baseline_supports_bench`, `override_downgrades_to_diagnostic`)를 더한다.
  **비밀이 없다**: 비공개 키도, 비공개 eval 팩 경로도, 숨은 FEN/오프닝 id도, 비공개
  아티팩트 경로도 없다. 핀 고정 팩 해시와 공개 키가 반드시 있어야 한다.
- **제3자가 매니페스트로 시즌을 확인한다.** 공개 GET
  `/api/hosted/release-manifest`(`bench/ceb/api/main.py`)는 `CEB_RELEASE_MANIFEST`의
  매니페스트를 관리자 토큰 없이 제공한다(미설정 503, 누락 404; 구조적으로 비밀 없음).
  `GET /api/hosted/readiness/public`도 유지된다. 관리자 POST 엔드포인트는
  상수 시간 토큰 비교(`hmac.compare_digest`)로 보호된다. 공개 결과 번들(`ceb hosted
  result export --release-manifest <path> --public-key <pem> | --public-key-fingerprint
  <fp>`, `bench/ceb/hosted/result_bundle.py`)은 선택된 검증 결과의 공개 아티팩트에
  `release_manifest.json`과 공개키 지문을 함께 담고, `VERIFY.txt`에 별도 공급한 공개
  키/매니페스트 지문으로 대조하는 절차를 적는다. 번들은 비선택 smoke/진단과 모든 비공개
  아티팩트(스캔·누출 리포트, 매치 로그), 비공개 키, 숨은 팩 데이터를 결코 포함하지 않는다.
- **검증된 결과 전용이 공개용 기본값이다.** `ceb hosted leaderboard`와
  `GET /api/hosted/leaderboard`는 검증된 항목만 반환한다. 미검증 로컬
  보드는 순위 발행이 아니라 자가 점검을 위해 존재한다. 단일 노드(SQLite + 로컬 FS)는
  분산 프로덕션 SaaS가 아니라 정직한 단일 노드 호스티드 백엔드로 유지된다.
