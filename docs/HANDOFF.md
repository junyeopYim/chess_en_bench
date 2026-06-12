# 핸드오프

## 목표
chess_en_bench v0.3.1 — 공식 호스팅형 벤치마크 하드닝. 검증된 점수는 오직 공식
워커가, 깨끗한 스냅샷 + 비공개 평가 팩 + 정적 스캔 + 엄격 게이트 + Docker 엔진
감옥 + `official`/`final-production` 프로파일 + 공개 누출 스캔 + 서명을 모두
만족할 때만 생성한다. *우연한* verified는 불가능하다.

## 현재 상태 (브랜치 v0.3.1-official-hosted-hardening)
모든 P0와 대부분의 P1이 구현·테스트됨.

P0:
- (P0.1) verifiable 프로파일은 `engine_jail == docker`가 아니면 평가 전에 검증을
  거부. 워커 `--engine-jail` 기본값 docker. `--dev-allow-unjailed`는 강제로
  verified=false(diagnostic-unjailed).
- (P0.2/P0.3) 프로파일 `smoke`/`official`/`final-production`
  (`bench/ceb/hosted/profiles.py`). smoke는 절대 verified 아님·리더보드 제외.
  `final_production` 라운드 모드 = 2016게임/paired/movetime 1000ms. 결과·DB에
  `profile`·`verification_grade` 기록.
- (P0.4) 공유 선택자 `select_best_verified_result`: 리더보드/`result show`/
  official-result API가 동일 결과 선택(final-tier 우선).
- (P0.5) `claim_next_job`(BEGIN IMMEDIATE) 원자적 클레임 + lease 회수 +
  worker_id/attempt_count/public_detail + 가산 마이그레이션.
- (P0.6) Track B 호스팅형(Option A): 잡 `track_b_official_eval`,
  `ceb hosted submit-track-b`, 워커 분기, verified track B 리더보드.
- (P0.7) 감옥 이미지에 빌드 툴체인(`chess-en-bench-jail:0.4`); C++ 예제
  `examples/submissions/minimal_uci_engine_cpp`가 strict 게이트 통과.
- (P0.8) 공개 아티팩트 누출 스캐너(`bench/ceb/scan/leak_scan.py`); 누출 시 검증
  거부 + 비공개 leak 보고서(해시만).
- (P0.9) Ed25519 공개키 서명 + `keygen`/`sign-result`/`verify-result`; HMAC 레거시.
- (P0.10) 문서 갱신(README, 이 파일, HOSTED_*, SECURITY_MODEL, RESULT_SIGNING,
  LEADERBOARD_GOVERNANCE, TRACK_B_OFFICIAL_PIPELINE, RELEASE_NOTES).

P1: (P1.2) 안전 업로드 `safe_extract_archive` + `submit --archive` + 업로드 API.
(P1.3) `ceb hosted result export` 공개 번들. (P1.4) 에이전트 궤적 스키마.

## 테스트 결과
- `python -m pip install -e ".[dev,server,hosted]"` 성공.
- `pytest -q`: **214 passed, 5 skipped**(Docker 통합 opt-in).
- `CEB_DOCKER_TESTS=1`(jail 이미지 빌드 후): jail/Track B verified/C++-in-jail
  테스트 포함 23 passed. verified Track A 경로를 수동 검증: verified=true, Ed25519
  서명, 누출 스캔 통과, 공개 키로 authentic=true.

## 알려진 한계
- 검증된 Track B end-to-end(감옥 내 빌드+매치)와 C++-in-jail 게이트는 opt-in
  Docker 테스트다(CI는 비-docker 가드/진단 경로 + 호스트 g++ C++ 게이트로 커버).
- fastchess 어댑터는 아직 오라클 PGN 사후 검증이 없어 공식 검증 경로 밖이다(P1.1).
- 실제 고정 Stockfish 빌드 래퍼와 `bench`/속도 검사는 운영자 단계다.
- 호스팅형 백엔드는 SQLite + 로컬 FS(단일 노드)이며 관리자 토큰 외 인증은 없다.

## 다음 단계
- P1.1 fastchess PGN→오라클 사후 검증(통과해야 공식 경로 편입).
- 다중 노드 큐/객체 저장소, 키 회전, 공개 키 배포 채널 문서화.
