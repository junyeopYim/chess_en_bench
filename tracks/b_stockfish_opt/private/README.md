# Track B — 비공개 평가 데이터 (마운트 지점)

**이 저장소에는 어떤 숨겨진 데이터도 배포되지 않는다.** 이 디렉터리는 이
README를 제외하면 의도적으로 비어 있으며 관례적인 마운트 지점을 git에
유지하기 위해 존재한다. 어떤 코드도 이 경로를 직접 읽지 않는다; 숨겨진
데이터는 운영자가 eval-pack 로더를 디렉터리로 가리킬 때만 소비된다.

로더는 실재한다: Track B 숨겨진 오프닝은 Track A와 동일한 eval-pack
로더(`bench/ceb/eval_pack.py`)를 통해 해결된다. 전체 eval-pack 인터페이스 —
팩 파일, 숨겨진 행 id 부여, 숨김 안전 로딩, jail 결합 보장,
`eval_pack_hash` 버전 관리 — 는
**[`docs/EVAL_PACKS.md`](../../../docs/EVAL_PACKS.md)**에 한 번 문서화된다. 아래
노트는 Track B 고유 사항이다.

## 숨겨진 Track B 데이터가 로드되는 방식

운영자는 `ceb track-b round run ... --eval-pack <dir>`을 전달하거나(이는
`ceb track-b official run`도 받아들임) `CEB_PRIVATE_EVAL_DIR=<dir>`을
설정한다. Track B 라운드는 공식 평가로 간주되므로 환경 변수는 항상
존중된다(`bench/ceb/track_b/round_runner.py`가 `allow_env=True`로 팩을
해결함). Track B에는 숨겨진 오프닝만 중요하다:

- `openings_hidden.jsonl` — 숨겨진 오프닝,
  `tracks/a_from_scratch/public/openings_public.jsonl`과 동일한 JSONL 행 형식:
  `{"id", "fen": "startpos"|FEN, "moves": [UCI...], "tags": [...]}`. 모든 무브는
  로드 시점에 오라클 검증되며; id가 없는 행에는 id가 부여된다.
- `manifest.json` — 선택적 `{"name": ..., "openings_mode":
  "extend"|"replace"}`(기본 `extend`).

`extend` 모드에서는 숨겨진 오프닝이 공개 모음에 추가된다; 숨겨진 오프닝만
플레이하려면 `"openings_mode": "replace"`를 사용한다. 비공개 팩이 없으면
라운드는 Track B 공개 quick 모음
(`../public/quick_openings.jsonl`)을 사용한다.

공식 매치 파라미터(게임 수, movetime)는 `ceb track-b round run`의
**CLI 플래그**(`--games`, `--movetime`)이며, 숨겨진 설정 파일이 아니다;
이 디렉터리의 어떤 것도 이를 설정하지 않는다. 숨겨진 FEN/오프닝은 결코
에이전트에 도달하지 않는다: `feedback.json`은 집계만 담고, 전체 상세는
운영자 산출물(`report.json`, `match.json`, `games.txt`)에 머문다.

`examples/eval_packs/tiny_private/`는 정확한 형태를 보여주는 가짜 데모
팩이다(테스트가 사용함).

## 모든 숨겨진 평가가 따라야 하는 인터페이스

- 베이스라인은 `../stockfish.lock`의 정확한 고정 참조이다(Stockfish 18,
  태그 `sf_18`, 커밋 `cb3d4ee`); 다른 방식으로 빌드하면 비교가 무효화된다.
  두 엔진 모두 동일한 컴파일러 플래그로 빌드되어야 한다.
- 후보 트리는 먼저 diff 화이트리스트를 통과해야 한다; `ceb track-b round
  run --baseline-src ... --candidate-src ...`가 검사 자체를 실행하고 위반 시
  어떤 게임도 시작하기 전에 중단한다. `../allowed_paths.txt`에 매칭되는
  파일만 달라질 수 있으며; `../forbidden_paths.txt`에 매칭되는 것은 항상
  실패한다.
- 결과는 임베드된 `ceb.score.track_b/v1` 점수와 함께
  `ceb.track_b.round.report/v1`로 보고된다: W/D/L, 클램프된 득점률,
  `delta_elo_ci95`와 함께 `delta_elo`, 결함 패널티, 그리고 `final_delta_elo`.

## 상태

| 조각 | 상태 |
|---|---|
| 숨겨진 오프닝을 위한 eval-pack 로더(`--eval-pack` / `CEB_PRIVATE_EVAL_DIR`) | 구현됨 |
| 자동화된 후보 대 베이스라인 라운드(`ceb track-b round run`) | 구현됨 |
| 숨겨진 오프닝 팩 내용 | 운영자 제공; 어떤 것도 배포되지 않음 |
| 이 디렉터리를 코드가 직접 읽음 | 아니오 — 관례적 마운트 지점일 뿐 |
