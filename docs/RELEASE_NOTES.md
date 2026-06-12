# 릴리스 노트(Release notes)

버전 번호는 패키지 버전이다(`pyproject.toml`, `bench/ceb/__init__.py`). 각 릴리스는
이전 CLI 명령이 계속 동작하도록 유지한다.

## v0.3.5 — 검증 경로 강화와 공개 공식 선언 자동화

테마: verified Track B 경로에서 마지막 침묵 통과를 제거하고, 공개 공식 선언을 전용
명령 + 서명된 매니페스트 + 커밋 안전 체크리스트로 정식화한다. dev 플래그 강등은 한눈에
구분되도록 라벨링된다. "단일 노드(SQLite + 로컬 FS)"는 정직하게 유지한다. strict readiness는
이제 버전 `>= 0.3.5`를 요구한다. 비도커 `pytest -q`는 311 passed / 6 skipped,
Docker(`CEB_DOCKER_TESTS=1 pytest -q`)는 317 passed.

- **bench는 지원되어야 verified, 호스트 폴백 없음(항목 1)**: verified Track B는 신뢰된
  베이스라인과 후보 양쪽에서 bench/속도 sanity가 **지원(SUPPORTED)** 되어야 한다.
  베이스라인이 bench NPS를 보고하지 못하면(unsupported) verified Track B는 **실패**한다
  (옛 "unsupported = 침묵 통과"는 제거). `--dev-allow-no-bench`는 검증을 보존하지 않고
  **항상** `diagnostic-no-bench`(`verified:false`)로 강등한다. 베이스라인은 bench하나 후보가
  못하면 실패/강등하며 결코 verified가 되지 않는다. verified 경로에서 후보의 engine-jail
  bench 명령 구성이 실패하면 후보 bench는 **거부**되며 호스트에서 실행되지 않는다(호스트
  폴백 없음, 내부 `_run_bench(require_candidate_jail=...)`). 결과 `metadata["track_b"]`는
  `bench_required`/`bench_supported`/`bench_passed`/`nps_ratio`/`min_nps_ratio`와
  `bench_policy`(`supported_required_for_verified`/`enforced_when_baseline_supports_bench`/
  `override_downgrades_to_diagnostic`) 및 전체 bench 보고서를 기록한다. strict Track B
  readiness는 이제 bench 능력을 **증명**한다: `--track-b-baseline-engine <bench 가능 엔진>`을
  넘기면 readiness가 그 엔진에 bench를 실행하고 새 차단성 검사 `track_b_bench_capability`가
  NPS 보고를 확인한다. 없으면 strict Track B 선언은 **차단**된다(예제 `engine.py`는 이제
  `bench` 명령에 응답해 테스트/스모크의 bench 가능 토이로 동작).
- **전용 strict 선언 명령(항목 2)**: 새 `ceb hosted readiness declare`는 **항상** strict
  공개 공식 정책으로 동작하며 `public_official_declaration == "ready"`일 때만 0으로 종료한다
  (`--json`은 JSON만 출력). 최상위 `declaration_certificate`(스키마
  `ceb.hosted.declaration_certificate/v1`)를 추가하며 `benchmark_version`/`track`/`ready`/
  `public_official_declaration`/`release_manifest_hash`/`operator_public_key_fingerprint`/
  `official_eval_pack_hash`/`track_b_baseline_hash`/`build_wrapper_hash`/`timestamp`/
  `known_limitations`를 담는다. 비-strict `ceb hosted readiness check`는 진단용으로 남는다.
  공식 선언 게이트는 오직 `readiness declare` 또는 `readiness check
  --strict-public-official`이다. 플래그: `--db --eval-pack --public-key --signing-key
  --track {A|B|BOTH} --build-wrapper --official-pack-hash --official-pack-registry
  --build-wrapper-hash --build-wrapper-registry --track-b-baseline-hash
  --track-b-baseline-registry --baseline-src --track-b-baseline-engine --release-manifest
  --json`.
- **서명·검증 가능한 릴리스 매니페스트(항목 3, Ed25519)**: `ceb hosted release-manifest
  create ... [--private-key op.pem]`은 `--private-key` 또는 `CEB_SIGNING_PRIVATE_KEY`가
  주어지면 직접 서명한다(없으면 UNSIGNED이되 읽기 가능). `ceb hosted release-manifest sign
  --manifest release.json --private-key op.pem`과 `ceb hosted release-manifest verify
  --manifest release.json --public-key op.pub.pem`을 추가한다. 매니페스트는 Ed25519 서명
  블록을 갖는다(서명은 서명 블록을 제외한 정규 매니페스트를 덮으며, 공식 결과와 동일 방식).
  `authentic:true`는 **대역 외(out-of-band)** 공개키에 대해서만 성립한다 — 미서명 매니페스트는
  읽을 수 있어도 결코 authentic이 아니고, 임베드 키 검증은 자기일관성만 증명한다.
  `GET /api/hosted/release-manifest`는 `CEB_RELEASE_MANIFEST`의 (서명된) JSON을 제공한다.
  결과 번들은 서명된 매니페스트를 포함하며 `VERIFY.txt`는 `ceb hosted release-manifest verify
  --manifest release_manifest.json --public-key <operator.pem>`을 문서화한다.
- **공개 공식 릴리스 체크리스트 아티팩트(항목 4)**: `ceb hosted release-checklist create
  --track {A|B|BOTH} --readiness-report readiness.json --release-manifest release.json
  --out PUBLIC_OFFICIAL_CHECKLIST.md`. 커밋 안전 Markdown으로 해시/지문/정책만 담고
  비밀·비공개 경로는 없다. 벤치마크 버전, git 커밋, readiness 선언 상태, 릴리스 매니페스트
  해시, 공식 eval 팩 id/해시/시즌, 운영자 공개키 지문, Track B 베이스라인 신뢰 모드/해시,
  빌드 래퍼 해시, 엔진/빌드 감옥 이미지 다이제스트, 리더보드 정책, 알려진 한계, 정확한
  verify 명령, 그리고 "Do not declare official unless the readiness declaration is ready."
  문구를 포함한다. 보안 장벽이 아니라 거버넌스이며 새 모듈
  `bench/ceb/hosted/release_checklist.py`로 구현된다.
- **dev 강등 플래그는 verified와 혼동 불가(항목 5)**: 모든 진단 결과(임의의 dev 플래그 강등)는
  `verified:false`, `diagnostic-`로 시작하는 `verification_grade`, 평문 `diagnostic_reason`,
  `public_official_eligible:false`를 갖는다. 호스트형 리더보드는 여전히 이를 무시하고(verified
  전용), `ceb hosted result show`는 `*** DIAGNOSTIC — NOT PUBLIC OFFICIAL: <reason> ***`를
  출력하며, 번들 내보내기는 기본적으로 진단 결과를 거부하고(선택된 최고 verified 결과만 번들),
  `GET .../official-result`는 verified 결과만 반환한다. 대상 플래그: `--dev-allow-unjailed`,
  `--dev-allow-demo-pack`, `--dev-allow-unpinned-pack`, `--dev-allow-unsigned`,
  `--dev-allow-toy-baseline`, `--dev-allow-unpinned-wrapper`, `--dev-allow-no-bench`.
- **공개 공식 스모크 레시피(항목 6)**: `scripts/public_official_smoke.sh [A|BOTH]`는 임시
  디렉터리에 완전히 모킹된 공식 셋업(저장소 밖 공식 팩, Ed25519 키, Track B 베이스라인/후보
  트리, 트리 밖의 신뢰된 래퍼, bench 가능 베이스라인 엔진, 핀된 해시, 임시 DB, 서명된 릴리스
  매니페스트)을 만들고 `ceb hosted readiness declare`를 실행한다. Docker + 감옥 이미지가 있으면
  READY에 도달하고, 없으면 감옥 앵커에서 올바르게 차단하며 완전한 verified e2e에는 Docker가
  필요함을 알린다. 아티팩트를 커밋하지 않고 PASS/FAIL을 출력한다.
- **문서(항목 7)**: 릴리스 노트와 호스트형/Track B 문서를 위 변경에 맞춰 v0.3.5로 갱신한다.

## v0.3.4 — 최종 공개 공식 감사 하드닝

테마: 공개 공식 선언 직전의 잔여 모호성을 제거한다. 어떤 `--dev-*` 플래그도
`verified: true`를 남길 수 없고, 신뢰 앵커는 실제로 검증되며, readiness가 단일
선언 게이트가 된다. "단일 노드(SQLite + 로컬 FS)"는 정직하게 유지한다.

- **dev 플래그가 verified를 유지하지 못한다(항목 1)**: Track B bench 실패 시
  `--dev-allow-no-bench`는 더 이상 통과시키지 않고 `verified: false`,
  `verification_grade: diagnostic-no-bench`로 강등한다(리더보드 제외).
- **베이스라인 콘텐츠 무결성(항목 2)**: `stockfish-lock` 모드는 git HEAD가 lock과
  일치할 뿐 아니라 **작업 트리·서브모듈이 깨끗**해야 하며(`git_worktree_clean` /
  `git_submodules_clean`) 콘텐츠 해시를 기록한다. dirty/untracked는 신뢰되지 않는다.
- **Ed25519 키 사전 로드(항목 3)**: verifiable 프로파일은 스캔·게이트·빌드·매치
  **전에** `require_ed25519_private_key`로 키를 로드 검증한다. 손상된 키는 일찍
  실패하며, 서명 실패로 스테이징된 공개 아티팩트가 남지 않는다.
- **readiness 선언 게이트(항목 4)**: `ceb hosted readiness check
  --strict-public-official`이 버전 `>= 0.3.4`를 요구하고 기계가 읽는
  `public_official_declaration`(`ready`/`not-ready`)과 `blocking_failures`를
  보고하며 `--track BOTH`를 지원한다. `--json`은 JSON만 출력한다.
- **릴리스 매니페스트 앵커(항목 5)**: `track_b_baseline_trust_mode`, `bench_policy`,
  `official_eval_pack_manifest_hash`를 포함한다(비밀 없음, 공개키는 지문만).
- **공개 API(항목 6)**: 비밀 없는 `GET /api/hosted/release-manifest`
  (`CEB_RELEASE_MANIFEST` 경로 제공, 없으면 503). 관리자 POST는 상수시간 토큰 비교.
- **결과 번들(항목 7)**: `ceb hosted result export --release-manifest --public-key`로
  릴리스 매니페스트와 운영자 공개키 지문 + 검증 지침을 번들에 포함(여전히 선택된
  검증 결과만, 비밀 없음).

## v0.3.3 — 최종 공개 공식 하드닝 (단일 노드)

테마: 모든 공개 공식 신뢰 앵커를 **핀(pin)** 하고, 단일 명령
(`ceb hosted readiness check --strict-public-official`)이 통과할 때만 공개 공식
준비 완료로 선언한다. "단일 노드"는 정직하게 유지한다(SQLite + 로컬 FS).

- **eval 팩 해시 핀 필수(req 1)**: verified는 팩 내용 해시가 허용목록
  (`--official-pack-hash` / `CEB_OFFICIAL_EVAL_PACK_HASHES` /
  `--official-pack-registry`)에 핀되어야 한다. 핀 없으면 거부;
  `--dev-allow-unpinned-pack` → `diagnostic-unpinned-pack`(미검증).
- **공개키 검증 + 키쌍 일치(req 2)**: strict readiness는 Ed25519 비공개·공개 키가
  로드되고 **서로 일치**함을 요구하며 공개키 지문을 보고서에 담는다. authentic은
  여전히 대역 외 공개키를 요구한다(임베드 키는 자기일관성만).
- **Track B 베이스라인 신뢰(req 3, `bench/ceb/track_b/baseline_trust.py`)**: 모드
  `stockfish-lock`(HEAD가 stockfish.lock과 일치) / `hash`(허용목록) / `toy`
  (`--dev-allow-toy-baseline` → `diagnostic-untrusted-baseline`). 신뢰 정보는
  메타데이터에 기록.
- **빌드 래퍼 해시 핀(req 4)**: verified Track B는 래퍼 해시가 허용목록
  (`--build-wrapper-hash` / `CEB_TRACK_B_BUILD_WRAPPER_HASHES`)에 핀되어야 한다.
- **빌드 출력 하드닝(req 5)**: 빌드 후 엔진 존재·실행 가능·정규 파일 확인, 출력 트리
  심볼릭 링크 거부, 크기/파일 수 한도(512 MiB / 10000), 출력 트리 해시 기록.
- **Track B bench/속도 검사(req 6, `bench_sanity.py`)**: 베이스라인·후보 `bench`
  실행으로 노드 수/NPS/NPS 비율 기록; 양쪽이 bench를 지원할 때만 NPS 비율 임계값
  강제(`--bench-min-nps-ratio`, `--dev-allow-no-bench`).
- **스테이징 승격 강화(req 7)**: 누출 스캔 실패 시 트리 어디에도 공개 매니페스트
  항목이 남지 않음을 테스트로 증명.
- **API 정리(req 8)**: `GET /api/leaderboard?track=B`는 호스트형 DB가 있으면 verified
  Track B 리더보드로 위임; 비밀 없는 `GET /api/hosted/readiness/public` 추가.
- **릴리스 매니페스트(req 9, `release_manifest.py`)**:
  `ceb hosted release-manifest create`가 시즌의 모든 앵커(버전·git·팩 해시·공개키
  지문·이미지 다이제스트·Track B 베이스라인/래퍼 해시·리더보드 정책·한계)를 담은
  비밀 없는 `ceb.release_manifest/v1`을 출력.
- **최종 게이트(req 10)**: `--strict-public-official`이 위 앵커들을 차단성(FAIL)으로
  취급. 보고서는 `ceb.hosted.readiness/v2`.

## v0.3.2 — 공개 공식 호스트형 벤치마크 준비

테마: 정상 운영에서 우연히도 악의적으로도 공개 공식 `verified: true`를 만들 수 없게
한다. verified는 이제 — 깨끗한 스냅샷 + **신뢰된 공식 평가 팩** + 정적 스캔 + 엄격
게이트 + Docker 엔진 감옥 + (Track B는) **격리된 빌드 감옥** + 공개 아티팩트 누출 스캔 +
**Ed25519 서명** + 원자적 소유권 펜싱 기록 — 을 모두 만족할 때만 생성된다.

- **신뢰된 공식 평가 팩 가드**(A, `bench/ceb/hosted/eval_pack_trust.py`): verified는
  `ceb.eval_pack.manifest/v1` 매니페스트(`pack_id`/`track`/`season`/`official:true`/
  `visibility:private` 등)를 갖고 저장소 committed/demo 경로 밖에 있는 공식 팩을
  요구한다. 선택적 허용목록(env `CEB_OFFICIAL_EVAL_PACK_HASHES`, `--official-pack-hash`,
  `--official-pack-registry`)이 있으면 팩 해시가 일치해야 한다. 커밋된 데모 팩
  (`examples/eval_packs/tiny_private`)은 절대 verified를 만들 수 없다. 결과는
  `eval_pack_id`/`eval_pack_hash`/`eval_pack_manifest_hash`/`eval_pack_trusted`/
  `eval_pack_track`/`eval_pack_season`를 기록한다.
- **verified는 Ed25519 서명을 요구**(B): verifiable 프로파일은 Ed25519 키
  (`CEB_SIGNING_PRIVATE_KEY` 또는 `--signing-key`)가 없으면 거부한다. HMAC 서명 결과는
  공개 공식 verified가 될 수 없다(레거시 진단용으로만 유지). `--dev-allow-unsigned`는
  강제로 `verified:false`(diagnostic-unsigned). 검증기는 verified 결과가 Ed25519가
  아니면 `authentic:false`다.
- **Track B 후보 빌드 격리**(C, `bench/ceb/track_b/build_jail.py`,
  `bench/ceb/hosted/build_wrappers.py`): verified Track B는 후보 소유 빌드 스크립트를
  호스트에서 실행하지 않는다. **신뢰된 운영자 래퍼**(후보 트리 밖)가 Docker 빌드 감옥
  에서 베이스라인·후보를 동일하게 빌드한다(네트워크 없음, 소스 읽기 전용, 출력 쓰기
  가능, repo/팩 미마운트, 비루트). 진단 호스트 빌드 경로는 항상 `verified:false`다.
- **공개 아티팩트 스테이징→누출 스캔→승격**(D, `bench/ceb/storage/promotion.py`): 공개
  대상 아티팩트는 먼저 비공개로 스테이징되고, 누출 스캔 통과 후에만 공개로 승격된다.
  스캔 실패 시 어떤 아티팩트도 공개로 표시되지 않는다.
- **Track B 호스트형 제출 API**(E): 관리자 인증
  `POST /api/hosted/runs/{run_id}/track-b-submissions`.
- **결과 번들은 선택된 검증 결과만**(F): `ceb hosted result export`는 기본적으로
  `select_best_verified_result`의 공개 아티팩트만 담는다(`--include-all-public`는 진단용).
- **스트리밍 업로드**(G): 업로드 API가 본문을 청크로 디스크에 스트리밍하며 바이트 한도를
  강제하고 실패 시 임시 파일을 삭제한다.
- **공식 준비 점검**(H): `ceb hosted readiness check`가 버전/DB/Docker/감옥 이미지/공식
  팩 신뢰/Ed25519 키/프로파일 정책/final-production 게임 하한/Track B 빌드 래퍼/관리자
  토큰을 점검하고 JSON+요약을 출력하며 준비되지 않으면 0이 아닌 종료 코드를 낸다.

## v0.3.1 — 공식 호스트형 운영을 위한 하드닝

테마: v0.3의 호스트형 MVP를 공개 공식 벤치마크로 운영해도 정직하게 신뢰할 수 있게
강화한다. 핵심은 *우연히* verified가 만들어질 수 없게 하는 것이다.

- **명시적 평가 프로파일** (`bench/ceb/hosted/profiles.py`): `smoke` / `official` /
  `final-production`(레거시 `final-eval`). `smoke`(=`--quick-test-mode`)는 진단
  전용으로 **절대 verified가 아니며** 호스트형 리더보드에 오르지 않고 감옥 없이
  실행된다(CI 플러밍). `official` / `final-production`은 다른 모든 게이트가 통과할
  때만 verified가 된다. 결과 JSON과 DB 행에 `profile`과 `verification_grade`
  (`verified-official` / `verified-final-production` / `diagnostic-smoke` /
  `diagnostic-unjailed` 등)가 기록된다.
- **verified는 Docker 엔진 감옥을 요구한다**: verifiable 프로파일은 `engine_jail ==
  docker`가 아니면 평가 전에 검증을 거부한다. 호스트형 워커의 `--engine-jail` 기본값은
  이제 `docker`다. 개발 전용 `--dev-allow-unjailed`는 감옥 없이 실행하되 결과를 강제로
  `verified: false`(diagnostic-unjailed)로 만든다.
- **프로덕션 final eval 프로파일** (`final_production` 라운드 모드, `eval_profiles.yaml`):
  상대당 336게임 × 6상대 = 2016게임, paired openings, movetime 1000ms로 의미 있는
  신뢰구간을 만든다. CI는 이 기본값을 절대 실행하지 않는다(테스트는 tiny override).
  리더보드는 final-tier(final_production/final_eval)를 official 라운드보다 선호한다.
- **공유 결과 선택자** (`select_best_verified_result`): 리더보드 / `result show` /
  `GET .../official-result`가 동일한 정책(final-tier 우선, smoke 제외)으로 같은 결과를
  선택한다.
- **원자적 잡 클레임** (`claim_next_job`, `BEGIN IMMEDIATE`): 다중 워커가 같은 잡을
  중복 처리하지 않는다. `jobs`에 `worker_id`/`started_at`/`lease_expires_at`/
  `attempt_count`/`public_detail` 추가, lease 만료 회수, 데이터 손실 없는 가산
  마이그레이션.
- **Track B 호스트형 공식 경로**(Option A): 잡 종류 `track_b_official_eval`,
  `ceb hosted submit-track-b`, 워커 분기, verified Track B 델타 Elo 리더보드 항목.
  verified는 감옥/스캔/diff 화이트리스트/동일 빌드 스크립트/비공개 오프닝 팩/누출
  스캔/서명을 요구한다.
- **감옥 빌드 툴체인**(이미지 `chess-en-bench-jail:0.4`): `gcc/g++/make`를 포함해
  C/C++/네이티브 제출물이 감옥 안에서 빌드·실행된다(네트워크 없음). C++ 예제
  `examples/submissions/minimal_uci_engine_cpp`가 strict 게이트를 통과한다.
- **공개 아티팩트 누출 스캐너** (`bench/ceb/scan/leak_scan.py`): verified 결과 기록
  전에 공개 아티팩트를 비공개 팩의 비밀 토큰과 대조해, 누출 시 검증을 거부하고 잡을
  실패시키며 비공개 leak 보고서(비밀은 echo하지 않고 해시만)를 남긴다.
- **Ed25519 공개키 서명**: 운영자는 비공개 키로 서명하고 누구나 게시된 공개 키로
  검증한다. `ceb hosted keygen / sign-result --private-key / verify-result
  --public-key`. 레거시 HMAC은 운영자 내부 용도로 유지된다. `cryptography`가 `hosted`
  extra에 추가됨. (docs/RESULT_SIGNING.md)
- **안전 업로드 전송**(`safe_extract_archive`): `.tar.gz`/`.tar`/`.zip` 업로드에서
  심링크·절대 경로·경로 탐색·비정규·과대 파일을 거부한다. `ceb hosted submit
  --archive`, 관리자 인증 `POST /api/hosted/runs/{id}/upload`.
- **결과 번들 내보내기**: `ceb hosted result export`는 공개 아티팩트와 검증 지침만 담은
  zip을 만든다(비공개 detail 없음).
- **에이전트 궤적 스키마**(선택): `ceb.agent.trajectory/v1` — 비공개 사고 과정을
  요구하지 않는 출처 메타데이터.
- 스키마 버전 상향: 결과 `ceb.hosted.official_result/v2`, 리더보드
  `ceb.hosted.leaderboard/v2`(검증기는 `v1`도 수용).

## v0.3.0 — 호스트형 공식 벤치마크 준비

테마: 엔진은 평가기 내부나 hidden 데이터를 절대 읽어서는 안 된다. 공식 점수는 깨끗한
스냅샷, 비공개 평가 팩, 고정 이미지, 재현 가능한 메타데이터, 의미 있는 평가 위에서
호스트형 평가기 워커로부터만 나온다.

- **엔진 감옥(engine jail)** (`--engine-jail docker`): 신뢰할 수 없는 엔진만 격리한다
  — 워크스페이스는 `/submission`에 읽기 전용 마운트, 저장소 / 평가 팩 / 상대
  마운트 없음, `--network none`, 읽기 전용 루트 + tmpfs, CPU/메모리/pids 제한,
  비루트, `no-new-privileges`. 평가기는 호스트에서 신뢰된 채로 머문다. 레거시
  `--sandbox docker`(harness-in-container)는 호환성을 위해 남는다.
- **hidden 평가 팩 + 감옥의 결합**: 비공개 팩은 평가기가 호스트 측에서 읽으며 감옥에
  절대 마운트되지 않는다. 포지션은 `position fen ...` UCI 라인으로만 엔진에 도달한다.
- **아티팩트 가시성 모델**: 모든 아티팩트 디렉터리는 매니페스트를 담는다.
  `feedback.json`과 `report.public.json`은 공개이며 정제되고, 전체 보고서 / 매치 로그
  / 게임 텍스트는 비공개다. 누출 스캐너 테스트는 공개 아티팩트에 hidden FEN, 오프닝
  id, 행 id, 수 시퀀스, 호스트 경로가 나타나지 않음을 단언한다.
- **hidden-safe 오류**: `SanitizedError`는 공개/비공개 메시지를 담는다. 평가 팩과
  오프닝 로더는 `hidden=True`를 받는다. CLI는 에이전트용 출력에 트레이스백이나 hidden
  콘텐츠를 절대 출력하지 않는다(운영자용은 `CEB_DEBUG=1`).
- **호스트형 파이프라인** (`ceb hosted ...`, SQLite + 로컬 스토어): 제출물은 스냅샷
  되고(심링크는 거부) 해시된다. 공식 워커는 `verified: true` 결과의 유일한 생산자다.
  비공개 평가 팩이 없거나, 정적 스캔이 실패하거나, strict 게이트가 실패하면 검증을
  거부한다.
- **재현성 메타데이터 + 서명**: 모든 공식 결과는 벤치마크 버전, git 커밋, 이미지
  digest, 평가 팩 / 상대 풀 / 오프닝 스위트 해시, 하드웨어/소프트웨어, 시드를 담는다.
  `CEB_SIGNING_KEY`로 키가 지정되는 HMAC-SHA256 서명(대칭 — 그렇게 문서화됨). 키가
  없으면 명시적으로 `unsigned`이며, 결코 거짓 진위 주장을 하지 않는다.
- **평가 모드**: `quick`(무료, 진단용, 비-strict), `official_round`(예산 차감, strict
  게이트), `final_eval`(리더보드 품질, strict, 예산 비용 없음). 점수는 전체 점수율,
  풀 대비 델타 Elo와 95% CI, 상대별 분해, 결함 카운트, 오프닝 커버리지를 담는다.
  리더보드는 최고 final eval을, 없으면 최고 공식 라운드를 사용하며 결코 quick을 쓰지
  않는다.
- **부정행위 방지 스캐너** (`ceb scan workspace`, `ceb scan track-b`): 외부 체스
  라이브러리/엔진, 네트워크/프로세스 사용, harness 핑거프린팅, 과대/바이너리/북/
  테이블베이스 파일, 심링크 탈출의 정적 탐지. Track B는 diff 화이트리스트 + 콘텐츠
  규칙을 추가한다.
- **호스트형 API**: `/api/hosted/...` 실행, 제출물, 작업, 피드백, 공식 결과,
  검증 전용 리더보드, 공개 아티팩트 리졸버(기본 거부, 경로 순회 안전). admin POST
  엔드포인트는 `CEB_ADMIN_TOKEN`으로 게이트된다.
- **Track B**: 자동화된 `ceb track-b round run`과 소스 우선
  `ceb track-b official run`(스캔 → 같은 스크립트로 baseline + 후보 빌드 → 쌍 매치 →
  서명된 델타 Elo 보고서). 선택적 `fastchess` 어댑터(`--runner fastchess`).
- **무승부 판정**: 삼중 반복, 불충분한 기물(K vs K, K+B vs K, K+N vs K), 설정 가능한
  halfmove 임계값.
- **CI**: Python 3.10–3.12 전반에 스캔, 호스트형 SQLite 스모크, Track B 토이 라운드를
  추가한다. Stockfish/Docker/클라우드 의존성 없음.

## v0.2.0 — 신뢰할 수 있는 로컬 벤치마크

- strict 게이트(`--strict`, perft 필수). 공식 라운드가 이를 사용한다.
- 오프닝 스위트(`openings_public.jsonl`), 상대 전반에 순환되며 색상이 쌍을 이룸.
- 공식 리더보드는 quick 라운드를 제외한다(`--include-quick` 진단용).
- `runs/<id>/workspace`의 실행 id 추론.
- 레거시 `--sandbox docker`(harness-in-container)와 hidden 평가 팩 인터페이스.
- 자동화된 Track B 후보-대-baseline 러너와 diff 화이트리스트 체커. GitHub Actions CI.

## v0.1.0 — 로컬 MVP

- 의존성 없는 체스 오라클(표준 perft 카운트에 대해 검증됨), UCI 클라이언트, 공개
  게이트, 여섯 벤치마크 상대, 내부 매치 러너, Elo/사다리/델타 Elo 채점, 라운드 +
  예산, FastAPI 대시보드, Track B 고정 + 스캐폴드.
