# 릴리스 노트(Release notes)

버전 번호는 패키지 버전이다(`pyproject.toml`, `bench/ceb/__init__.py`). 각 릴리스는
이전 CLI 명령이 계속 동작하도록 유지한다.

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
