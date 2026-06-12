# 핸드오프

## 목표
chess_en_bench v0.3.5 — 공개 공식 선언 마무리. v0.3.4의 잔여 모호성을 제거한다.
저장소 코드는 Track A·B 공개 공식 단일 노드 호스트형 벤치마크로 **코드 준비 완료**다.
실제 배포는 운영자가 진짜 hidden eval 팩·Ed25519 키·Docker 감옥 이미지·핀된 Track B
베이스라인/래퍼·릴리스 매니페스트를 공급하고 `ceb hosted readiness declare --track BOTH`
(또는 `readiness check --strict-public-official --track BOTH`)가 통과할 때만 공식으로
선언할 수 있다. 분산 프로덕션 SaaS는 아니다(SQLite + 로컬 FS 단일 노드).

## 현재 상태 (브랜치 v0.3.5-public-official-declaration-finalization)
v0.3.4 위에 선언 마감 블로커 7개를 닫았다.

- (1) 검증 Track B는 bench **지원**을 요구한다 — 베이스라인이 bench NPS를 보고하지
  않으면 verified 실패(미지원=통과 폐기). 후보 감옥 명령 실패 시 호스트 bench 폴백 제거.
  메타데이터에 `bench_required/supported/passed/nps_ratio/min_nps_ratio/bench_policy`.
  strict readiness는 `--track-b-baseline-engine`으로 bench 역량을 증명해야 통과
  (`track_b_bench_capability`).
- (2) 전용 선언 게이트 `ceb hosted readiness declare`(항상 strict, `--json` JSON 전용,
  `declaration_certificate` 포함, ready일 때만 exit 0).
- (3) 릴리스 매니페스트 Ed25519 서명/검증(`release-manifest create --private-key`/`sign`/
  `verify`); authentic은 out-of-band 공개키로만. 결과 번들이 서명 매니페스트를 동봉.
- (4) 커밋 안전한 `ceb hosted release-checklist create`(해시·지문·정책만).
- (5) 모든 dev 플래그 진단 결과에 `verified:false` + `diagnostic-*` + `diagnostic_reason` +
  `public_official_eligible:false`. `result show`가 "DIAGNOSTIC — NOT PUBLIC OFFICIAL" 표시.
- (6) `scripts/public_official_smoke.sh`: 모킹된 공식 자산으로 strict 선언 스모크
  (Docker 있으면 READY, 없으면 감옥 앵커에서 정확히 차단).
- (7) 문서 정밀화 + 테스트 수 갱신.

## 테스트 결과
- `pip install -e ".[dev,server,hosted]"` 성공.
- `pytest -q`: **311 passed, 6 skipped**(Docker 통합 opt-in).
- `CEB_DOCKER_TESTS=1 pytest -q`(jail:0.4 빌드됨): **317 passed**(검증 Track A/B e2e + 빌드
  감옥 + bench 포함).
- `bash scripts/public_official_smoke.sh BOTH`: 6/6 PASS(Docker 경로 READY).

## 알려진 한계 (정직)
- 호스트형 백엔드는 SQLite + 로컬 FS **단일 노드** — 분산 프로덕션 SaaS 아님.
- 검증 e2e/빌드 감옥/bench는 opt-in Docker. 비-Docker 실행은 진단 전용.
- bench NPS는 후보 자기보고 **sanity** 신호(진짜 보호는 diff 화이트리스트 + 스캔 + jail).
  실 공개 Track B는 bench 지원 고정 Stockfish 베이스라인 + 신뢰·핀된 빌드 래퍼 필요.
- fastchess는 PGN 오라클 사후 검증 전까지 공식 경로 밖.
- 실제 hidden eval 팩·Ed25519 키·Stockfish 체크아웃·릴리스 매니페스트는 운영자 자산이며
  커밋하지 않는다.

## 다음 단계
- 다중 노드 큐/객체 저장소, 키 회전, 공개키·릴리스 매니페스트 배포 채널.
- 실 고정 Stockfish 트러스트 빌드 래퍼 + bench 정합성 자동화.
- fastchess PGN→오라클 사후 검증.
