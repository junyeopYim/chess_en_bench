# 라이선스

이 저장소, Stockfish 베이스라인, 그리고 참가자 산출물이 어떻게 라이선스되는지
설명한다. 이것은 실용적 요약이며 법률 자문이 아니다; 권위 있는 원문은
저장소 루트의 `LICENSE`와 `NOTICE`이다.

## 이 저장소: MIT

이 저장소에서 작성된 모든 것은 MIT 라이선스이다 (`LICENSE` 참고,
저작권 2026 junyeopYim): 벤치마크 하니스(`bench/ceb/`), 내부
체스 오라클(`bench/ceb/chess/`), 벤치마크 상대
(`bench/ceb/match/opponents.py`), 게이트 및 채점 코드, CLI,
트랙 설정(`tracks/`), 스펙, 문서, 스크립트, 정적 웹 UI, 그리고
`examples/submissions/` 아래 예시 제출물.

위 모든 것을 통상적인 MIT 조건 하에 사용, 수정, 재배포할 수 있다
(저작권 고지와 라이선스 텍스트를 유지한다).

## Stockfish: GPLv3, 배포하지 않음

Track B는 Stockfish에 대한 패치를 평가하며, Stockfish는 GNU
General Public License v3로 라이선스된다. `NOTICE`에 명시된 대로:

- **Stockfish 소스는 이 저장소와 함께 배포되지 않는다.**
- `scripts/setup_stockfish.sh`는 고정된 릴리스(Stockfish 18, 태그
  `sf_18`, 커밋 `cb3d4ee`)를 공식 저장소에서 `third_party/stockfish`로
  가져오며, 이 경로는 gitignore된다.
- Stockfish 또는 그로부터 파생된 바이너리의 배포는 GPLv3를 준수해야 한다.

가져오기 단계를 참가자 머신에 두면 MIT 저장소가 GPLv3 코드를 결코 배포하지
않게 된다. Stockfish 소스를 `bench/`, `tracks/`, 또는 MIT 라이선스 하의 다른
어떤 곳에도 벤더링하지 않으며, `third_party/`를 커밋하지 않는다.

베이스라인을 설정하고 확인하려면:

    bash scripts/setup_stockfish.sh
    ceb track-b status

## Track B 산출물: GPLv3 코드에 대한 패치는 GPLv3

Track B 제출물은 Stockfish의 탐색 파일에 대한 diff이다(`ceb track-b
check-diff`가 강제하는 화이트리스트 내). 함의:

- **패치는 Stockfish의 2차적 저작물이다.** Track B 패치 — 또는 패치된
  Stockfish로 빌드한 바이너리 — 를 배포한다면 GPLv3가 적용된다: 이를 GPLv3로
  라이선스하고 대응 소스를 제공해야 한다.
- **로컬 평가는 영향을 받지 않는다.** 패치된 Stockfish를 자신의 머신에서
  빌드하고 벤치마크하되 배포하지 않으면 GPLv3 배포 의무가 발생하지 않는다.
- **점수와 리포트는 그저 데이터이다.** Delta-Elo 결과
  (`ceb.score.track_b/v1`), diff-check 출력, 실행 메타데이터는 MIT 하니스가
  생성하며 Stockfish 코드를 포함하지 않는다; 이들은 2차적 저작물이 아니며
  자유롭게 공유할 수 있다.

Track B 결과를 공개한다면 깔끔한 패턴은 이렇다: 패치는 GPLv3로 공유하고
(고정된 `sf_18` 베이스라인 위에 적용됨) JSON 리포트는 원하는 조건으로
공유한다.

## 제출된 엔진은 작성자의 라이선스를 유지한다

Track A 제출물은 참가자(또는 그 에이전트)가 작성한다. 게이트, 라운드,
리더보드를 통해 엔진을 실행한다고 해서 그것이 **다시 라이선스되지는 않는다**:

- 워크스페이스(`runs/<run_id>/workspace/`)에 두는 코드는 당신이 선택한 어떤
  라이선스로든 당신의 것으로 남는다. 벤치마크는 그에 대한 평가 출력만
  저장한다(리포트, 게임 무브텍스트, 상태).
- `examples/submissions/`의 예시 엔진은 이 저장소의 일부이며 나머지와
  마찬가지로 MIT이다.
- Track A 엔진이 제3자 코드(기존 엔진, GPL 무브 생성기, 사용 조건이 있는
  오프닝 데이터)를 포함한다면, 그 라이선스를 준수할 책임은 당신에게 있다 —
  하니스는 이를 검사하지 않는다.

## 빠른 참조

| 대상 | 라이선스 | 위치 |
|---|---|---|
| 하니스, 오라클, 상대, 문서, 예시 | MIT | `LICENSE` |
| Stockfish 베이스라인 (가져오며, 배포하지 않음) | GPLv3 | `NOTICE`, `third_party/stockfish` |
| Track B 패치 및 패치된 바이너리, 배포 시 | GPLv3 | Stockfish의 파생물 |
| Track B/A 리포트, 점수, 실행 메타데이터 | MIT가 생성한 데이터 | `runs/<run_id>/` |
| Track A 제출 엔진 | 작성자의 선택 | 참가자 워크스페이스 |
