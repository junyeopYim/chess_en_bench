# 핸드오프

## 목표
chess_en_bench v0.3.2 — 공개 공식 호스트형 벤치마크 준비. 정상/악의 운영 모두에서
우연히 `verified: true`가 생성될 수 없게 한다. verified는 깨끗한 스냅샷 + 신뢰된
공식 평가 팩 + 정적 스캔 + 엄격 게이트 + Docker 엔진 감옥 + (Track B)격리 빌드
감옥 + 공개 누출 스캔 + Ed25519 서명 + 원자적 소유권 펜싱 기록을 모두 만족할
때만 호스트형 워커가 생성한다.

## 현재 상태 (브랜치 v0.3.2-public-official-readiness)
v0.3.1의 모든 가드 위에 다음을 추가했다.

- (A) 신뢰된 공식 평가 팩 가드(`bench/ceb/hosted/eval_pack_trust.py`):
  `ceb.eval_pack.manifest/v1` + 비-데모 경로 + 선택적 해시 허용목록. 데모 팩은 절대
  verified 불가. 결과에 `eval_pack_id/hash/manifest_hash/trusted/track/season` 기록.
- (B) verified는 Ed25519 서명 필수. 키 없으면 거부(또는 `--dev-allow-unsigned`로
  diagnostic-unsigned). HMAC은 공개 공식 verified 불가. 검증기가 강제.
- (C) Track B 후보 빌드 격리(`build_jail.py` + `build_wrappers.py` +
  `infra/docker/track_b_build_jail.Dockerfile`): 신뢰된 운영자 래퍼가 Docker 빌드
  감옥에서 빌드. verified는 호스트 빌드 거부.
- (D) 공개 아티팩트 스테이징→누출 스캔→승격(`bench/ceb/storage/promotion.py`):
  스캔 통과 전에는 어떤 공개 아티팩트도 존재/제공되지 않음.
- (E) Track B 호스트형 제출 API(`POST .../track-b-submissions`, 관리자 전용).
- (F) 결과 번들은 선택된 검증 결과만(`--include-all-public`는 진단용).
- (G) 스트리밍 업로드(청크 단위 바이트 한도, 실패 시 임시 파일 삭제).
- (H) 공식 준비 점검 `ceb hosted readiness check`(JSON+요약, 미준비 시 비정상 종료).
- (I) 문서/CI 갱신.

## 테스트 결과
- `python -m pip install -e ".[dev,server,hosted]"` 성공.
- `pytest -q`: **238 passed, 6 skipped**(Docker 통합 opt-in).
- `CEB_DOCKER_TESTS=1`(jail:0.4 빌드 후): 검증 Track A e2e, 검증 Track B(빌드 감옥),
  C++-in-jail 게이트 등 opt-in 14개 통과. 검증 결과는 Ed25519 서명·공개키로
  authentic=true·신뢰 팩으로 확인.
- `ceb hosted readiness check`: 데모 팩에서 NOT READY(공식팩/Ed25519 FAIL), 공식
  설정에서 READY.

## 알려진 한계
- 검증 e2e(Track A/B, 빌드 감옥, C++-in-jail)는 opt-in Docker 테스트다(CI는 비-docker
  가드 + 호스트 g++ C++ 게이트로 커버).
- 호스트형 백엔드는 SQLite + 로컬 FS(단일 노드)다. 다중 노드 큐/객체 저장소·키 회전·
  공개키 배포 채널은 운영자 범위다. → 정직한 라벨: **공개 공식 단일 노드 호스트형 MVP**.
- 실제 고정 Stockfish 빌드 래퍼와 `bench`/속도 검사는 운영자가 제공한다.
- fastchess는 오라클 PGN 사후 검증이 없어 공식 검증 경로 밖이다.

## 다음 단계
- fastchess PGN→오라클 사후 검증(통과 시 공식 경로 편입).
- 다중 노드 큐/객체 저장소, 키 회전, 공개키 배포 채널 문서화.
- 실제 고정 Stockfish 트러스트 빌드 래퍼 + bench 정합성 자동화.
