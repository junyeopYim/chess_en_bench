# 핸드오프

## 목표
chess_en_bench v0.3.3 — 최종 공개 공식 하드닝. 모든 공개 공식 신뢰 앵커를 핀하고,
`ceb hosted readiness check --strict-public-official`이 통과할 때만 "Track A·B 공개
공식 단일 노드 호스트형 준비 완료"로 선언한다. verified는 호스트형 워커가, 깨끗한
스냅샷 + **핀된 신뢰 공식 팩** + 정적 스캔 + 엄격 게이트 + Docker 엔진 감옥 +
(Track B)**신뢰 베이스라인** + **핀된 빌드 래퍼** + 격리 빌드 감옥 + 빌드 출력 검증 +
bench 검사 + 공개 누출 스캔 + Ed25519 서명 + 원자적 펜싱 기록을 모두 만족할 때만
생성한다.

## 현재 상태 (브랜치 v0.3.3-final-public-official-hardening)
v0.3.2 위에 10개 요구사항을 추가했다.

- (1) eval 팩 해시 핀 필수(`--official-pack-hash` 등). 핀 없으면 거부/
  `--dev-allow-unpinned-pack`→diagnostic-unpinned-pack.
- (2) strict readiness: Ed25519 비공개·공개 키 로드 + 키쌍 일치 + 지문 보고.
- (3) Track B 베이스라인 신뢰(`baseline_trust.py`): stockfish-lock / hash / toy.
- (4) 빌드 래퍼 해시 핀(`--build-wrapper-hash`).
- (5) 빌드 출력 검증(`build_jail.validate_build_output`): 심볼릭/크기/개수/엔진.
- (6) bench/속도 검사(`bench_sanity.py`): NPS 비율, 지원 시에만 임계값 강제.
- (7) 스테이징 승격: 누출 실패 시 공개 항목 0개 증명.
- (8) API: `/api/leaderboard?track=B` 위임 + `/api/hosted/readiness/public`.
- (9) 릴리스 매니페스트(`release_manifest.py`, `ceb hosted release-manifest create`).
- (10) `--strict-public-official` 최종 게이트, 보고서 `ceb.hosted.readiness/v2`.

새 워커/CLI 플래그: `--official-pack-hash`/`--official-pack-registry`/
`--build-wrapper-hash`/`--build-wrapper-registry`/`--track-b-baseline-hash`/
`--track-b-baseline-registry`/`--bench-min-nps-ratio` + dev 플래그
(`--dev-allow-unpinned-pack`/`--dev-allow-toy-baseline`/
`--dev-allow-unpinned-wrapper`/`--dev-allow-no-bench`).

## 테스트 결과
- `pip install -e ".[dev,server,hosted]"` 성공.
- `pytest -q`: **265 passed, 6 skipped**(Docker 통합 opt-in).
- `CEB_DOCKER_TESTS=1`(jail:0.4): 검증 Track A/B e2e(핀된 팩/베이스라인/래퍼 + 빌드
  감옥 + bench) 포함 **69 passed**.
- CLI: `readiness check --strict-public-official`(완전 핀 → READY, 미핀 → NOT READY),
  `release-manifest create`(비밀 없는 매니페스트) 모두 의도대로.

## 알려진 한계 (정직하게)
- 호스트형 백엔드는 SQLite + 로컬 FS **단일 노드**다. 분산 프로덕션 서비스가 아니다.
- 검증 e2e와 빌드 감옥/bench는 opt-in Docker 테스트다(CI는 비-docker 가드 + 호스트
  g++ C++ 게이트 + strict-readiness/release-manifest CLI 스모크).
- 실제 고정 Stockfish 빌드 래퍼와 실 bench/속도 기준은 운영자가 제공한다(토이 엔진은
  bench 미지원 → NPS 강제 없음).
- fastchess는 PGN 오라클 사후 검증 전까지 공식 검증 경로 밖이다.
- 실제 hidden eval 팩·키·릴리스 매니페스트는 운영자 산출물이며 커밋하지 않는다.

## 다음 단계
- 다중 노드 큐/객체 저장소, 키 회전, 공개키·릴리스 매니페스트 배포 채널.
- 실 고정 Stockfish 트러스트 빌드 래퍼 + bench 정합성 자동화.
- fastchess PGN→오라클 사후 검증.
