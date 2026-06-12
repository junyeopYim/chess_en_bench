# Track A 상대 풀

벤치마크는 Track A 후보가 채점되는 대상인 6개의 UCI 상대 풀을 보유한다.
이들은 `bench/ceb/match/opponents.py`에 구현되어 있으며(이 디렉터리는 문서만
담고 있다) **설계상 공개**이다: 에이전트는 소스를 읽고 원하는 만큼 자주 이들과
대국할 수 있다 — 게이트 시도와 quick 라운드는 무료이며, 공식 라운드만 예산을
소모한다.

어떤 상대든 독립 실행형 UCI 엔진으로 실행할 수 있다:

```bash
python -m ceb.match.opponents BenchRandom
```

내부 매치 러너는 `opponent_command(name)`을 통해 동일한 방식으로,
argv 전용(셸 없음)으로 이들을 실행한다.

## 풀

| 이름 | 명목 레이팅 | 전략 |
|---|---|---|
| `BenchRandom` | 400 | 균등 무작위 합법 무브. |
| `BenchGreedyCapture` | 600 | 사용 가능한 가장 높은 가치의 캡처를 잡는다(앙파상 포함); 그렇지 않으면 무작위 합법 무브. |
| `BenchMaterial1` | 800 | 깊이 1 네가맥스, 기물 전용 평가. |
| `BenchPST1` | 1000 | 깊이 1 네가맥스, 기물에 더해 중앙 가중 기물-칸 보너스와 폰 전진 보너스. |
| `BenchMiniMax2` | 1200 | 알파-베타 가지치기를 적용한 깊이 2 네가맥스, 기물 전용 평가. |
| `BenchAlphaBeta3` | 1400 | 기물 + 기물-칸 평가를 적용한 깊이 3 알파-베타. |

모든 상대는 하나의 UCI 셸을 공유하며 무브 선택에서만 차이가 난다. 깊이
기반인 것들은 깊이 상한까지 반복 심화를 사용하며 `go movetime` 예산의 약 80%
지점에 데드라인을 두고, 완료된 가장 깊은 반복으로 폴백한다; 동일한 점수의
루트 무브 간 동점은 무작위로 깬다.

레이팅은 측정된 Elo가 아니라 **명목** 앵커이다. 이들은
`../scoring.yaml`(`opponent_ratings`)에 있으며
`bench/ceb/scoring/track_a.py`의 `DEFAULT_OPPONENT_RATINGS`를 미러링한다.
상대별 Track A 성능은 `opponent_rating + delta_elo(score_rate)`이며,
사다리 점수는 상대 전체의 평균이다.

## 결정성

각 상대 프로세스는 고정된 기본 시드에서 시작하며

```
setoption name Seed value N
```

을 받아들이며, 그 후 주어진 포지션 시퀀스에 대해 무브 선택이 완전히
결정적이다. 내부 매치 러너(`bench/ceb/match/internal_runner.py`)는
게임마다 새로운 시드를 설정하므로(라운드는 `base_seed = 1000 * round_number`를
사용) 라운드는 재현 가능하다.

## UCI 표면

셸이 이해하는 것: `uci`, `isready`, `ucinewgame`,
`setoption name Seed value N`, `position startpos|fen ... [moves ...]`,
`go movetime N`(기본 1000 ms), `go perft D`(응답
`info string perft <nodes>`), 그리고 `quit`. 합법 무브가 없으면
`bestmove 0000`으로 답한다.

## 사용되는 곳

- 게이트 미니매치: `BenchRandom` 상대 2게임(`../public/gate_config.yaml`).
- quick 라운드: `BenchRandom` + `BenchMaterial1`, 각각 50 ms로 2게임.
- 공식 라운드: 6개 상대 전부, 각각 200 ms로 4게임.

라운드 기본값은 `bench/ceb/rounds/round_runner.py`에 있으며 `../scoring.yaml`의
`round_modes` 아래에서 재정의할 수 있다. 숨겨진 상대는 계획된
호스티드 배포 기능이며 `../private/` 아래에 마운트될 것이다; 이 저장소는
어떤 것도 배포하지 않는다.
