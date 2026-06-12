# 핸드오프

## 목표
chess_en_bench v0.3: 호스티드 공식 벤치마크 준비 상태. 공식 점수는 깨끗한
스냅샷, 비공개 평가 팩, 격리된 엔진 감옥(engine jail), 재현 가능한 서명된
메타데이터, 통계적으로 의미 있는 평가로부터 호스티드 평가자 워커만이
생성한다. 신뢰할 수 없는 엔진은 평가자 내부나 숨겨진 데이터를 결코 읽을 수
없다.

## 현재 상태 (브랜치 v0.3-hosted-benchmark)
모든 P0와 P1 항목이 구현되고 테스트됨.

P0:
- 엔진 감옥(`bench/ceb/jail/`): `--engine-jail docker`는 엔진만 가둔다 —
  워크스페이스 전용 읽기 전용 마운트, repo/팩/상대 마운트 없음,
  network-none, 읽기 전용 루트, 리소스 제한, 비루트, 재귀 가드.
- 숨겨진 평가 팩 + jail이 안전하게 결합됨(팩은 호스트 측에서 읽으며 결코 마운트되지 않음).
- 산출물 가시성 모델(`bench/ceb/storage/`): 공개 `feedback.json` /
  `report.public.json`; 비공개 전체 리포트/로그; 디렉터리별 매니페스트.
- 숨김 안전 오류(`bench/ceb/sanitize.py`, `hidden=` 로더); CLI는 트레이스백/
  비밀을 출력하지 않음(운영자는 `CEB_DEBUG=1`).
- 호스티드 파이프라인(`bench/ceb/hosted/`, SQLite + 스토어): 스냅샷, 잡,
  공식 워커 = `verified: true`의 유일한 출처. 비공개 팩이 없거나 / 스캔 실패
  시 / strict 게이트 실패 시 검증을 거부한다.
- 재현성 메타데이터 + HMAC-SHA256 서명(`CEB_SIGNING_KEY`; 그 외에는 명시적
  `unsigned`).
- 평가 모드 quick / official_round / final_eval에 CI 필드 포함; 리더보드는
  final_eval을, 그 다음 공식 라운드를 선호하며 quick은 결코 선호하지 않음.
- 부정행위 방지 스캐너(`bench/ceb/scan/`): `ceb scan workspace|track-b`.
- 기본 거부 방식의 공개 산출물 제공과 `CEB_ADMIN_TOKEN`으로 게이트된 POST를
  갖춘 호스티드 API 엔드포인트.

P1:
- 선택적 fastchess 어댑터(`--runner fastchess`).
- Track B 소스 우선 파이프라인(`ceb track-b official run`).
- 무승부 판정: 3회 동형 반복, 불충분한 기물, 설정 가능한 하프무브 임계값.
- 라운드 설정에 연결된 Stockfish UCI_Elo 앵커(우아하게 건너뜀;
  호스티드의 경우 `anchors_required`).

## 테스트 결과
- `pytest -q`: 180 passed, 3 skipped (Docker 통합 — `CEB_DOCKER_TESTS=1`로
  옵트인; 이미지를 빌드해 로컬에서 검증: 15개 docker 테스트
  통과, jailed 게이트 + jailed 라운드 + 호스티드 워커 모두 정상).
- 수용 + 호스티드 스모크 + Track B 토이 명령: 모두 종료 코드 0.

## 알려진 한계
- 결과 서명은 대칭(HMAC)이다; 공개키 증명은 향후 작업이다.
- Track B 공식 파이프라인은 트리별 `ceb_build.sh`를 통해 빌드한다; 실제
  고정된 Stockfish 빌드 래퍼와 `bench`/속도 검사는 운영자가
  제공한다(docs/TRACK_B_OFFICIAL_PIPELINE.md에 문서화됨).
- fastchess 어댑터는 결함을 결과에 접어 넣으며(결함별 귀속 없음) 아직 오라클
  PGN 사후 검증이 없다.
- 호스티드 백엔드는 SQLite + 로컬 FS이다(단일 노드 MVP); 관리자 토큰을 넘는
  인증 없음, 업로드 전송 없음(제출물은 서버 로컬 경로).
- `--eval-pack`은 레거시 `--sandbox docker` 모드에서 의도적으로 지원되지
  않는다; 대신 `--engine-jail docker`를 사용한다.

## 다음 단계
- 비대칭(공개키) 결과 서명 + 공개된 검증 키.
- Track B 공식 파이프라인에서 실제 고정된 Stockfish 빌드 래퍼 + `bench`
  검사; Track B 잡을 위해 호스티드 워커에 연결.
- 호스티드 제출을 위한 업로드 전송 + 인증; 다중 워커 큐.
- fastchess PGN → 오라클 사후 검증.
