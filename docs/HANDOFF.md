# 핸드오프

## 목표
chess_en_bench v0.3.4 — 최종 공개 공식 감사 하드닝. 공개 공식 선언 직전의 잔여
모호성을 제거한다. 메인테이너는 운영자가 실제 공식 비공개 eval 팩·Ed25519 키·Docker
이미지·핀된 Track B 베이스라인/래퍼 해시를 공급하고
`ceb hosted readiness check --strict-public-official`가 통과할 때, 저장소를 "Track A·B
공개 공식 단일 노드 호스트형 벤치마크 준비 완료"로 선언할 수 있다. 분산 프로덕션
SaaS는 아니다(SQLite + 로컬 FS 단일 노드).

## 현재 상태 (브랜치 v0.3.4-final-public-official-audit)
v0.3.3 위에 감사 항목 1~7을 추가했다.

- (1) bench 실패 시 `--dev-allow-no-bench`는 verified를 유지하지 못하고
  `diagnostic-no-bench`로 강등(리더보드 제외).
- (2) `stockfish-lock` 베이스라인은 git HEAD 일치 + 작업 트리·서브모듈 clean + 콘텐츠
  해시 기록을 요구(`baseline_trust.py`). dirty/untracked는 신뢰 불가.
- (3) `require_ed25519_private_key`로 스캔/게이트/빌드/매치 전에 키 로드 검증; 손상 키는
  조기 실패, 스테이징된 공개 아티팩트 없음.
- (4) readiness: 버전 `>= 0.3.4`, `public_official_declaration` +
  `blocking_failures`, `--track BOTH`, `--json`은 JSON만.
- (5) 릴리스 매니페스트에 `track_b_baseline_trust_mode`/`bench_policy` 추가(비밀 없음).
- (6) 공개 `GET /api/hosted/release-manifest`(`CEB_RELEASE_MANIFEST`), 관리자 토큰
  상수시간 비교.
- (7) `result export --release-manifest --public-key`로 매니페스트·공개키 지문 포함.

## 테스트 결과
- `pip install -e ".[dev,server,hosted]"` 성공.
- `pytest -q`: **289 passed, 6 skipped**(Docker 통합 opt-in).
- `CEB_DOCKER_TESTS=1`(jail:0.4): 검증 Track A/B e2e(핀된 팩/베이스라인/래퍼 + 빌드
  감옥 + bench) 포함 **84 passed**.
- CLI: `readiness check --strict-public-official --json`(declaration not-ready, 데모
  팩 거부), `release-manifest create`(비밀 없는 매니페스트, bench_policy 포함) 확인.

## 알려진 한계 (정직)
- 호스트형 백엔드는 SQLite + 로컬 FS **단일 노드** — 분산 프로덕션 SaaS 아님.
- 검증 e2e/빌드 감옥/bench는 opt-in Docker(CI는 비-docker 가드 + 호스트 g++ C++ 게이트
  + strict-readiness/release-manifest 스모크).
- bench NPS는 후보 자기보고 **sanity** 신호(진짜 보호는 diff 화이트리스트 + 스캔 +
  jail). 실 공개 Track B는 bench 지원 고정 Stockfish 베이스라인 필요.
- fastchess는 PGN 오라클 사후 검증 전까지 공식 경로 밖.
- 실제 hidden eval 팩·Ed25519 키·Stockfish 체크아웃·릴리스 매니페스트는 운영자
  자산이며 커밋하지 않는다.

## 다음 단계
- 다중 노드 큐/객체 저장소, 키 회전, 공개키·릴리스 매니페스트 배포 채널.
- 실 고정 Stockfish 트러스트 빌드 래퍼 + bench 정합성 자동화.
- fastchess PGN→오라클 사후 검증.
