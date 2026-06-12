# chess_en_bench

통제되고 재현 가능한 조건에서 **체스 엔진을 처음부터 만들거나**(Track A) **Stockfish의
탐색을 최적화하는**(Track B) LLM 코딩 에이전트를 위한 벤치마크 플랫폼이다.

**v0.3.2는 "공개 공식 단일 노드 호스트형 MVP"다.** 핵심은 *우연히* `verified`가 만들어질
수 없게 하는 것이다. 공개 공식 검증 결과는 오직 호스팅형 워커가 — 깨끗한 스냅샷, **신뢰되는
공식 평가 팩**(저장소에 커밋된 데모 팩이 아님), 정적 스캔 통과, 엄격 게이트 통과, Docker
**엔진 감옥(engine jail)**, (Track B) 신뢰되는 운영자 래퍼를 쓰는 **격리된 빌드 감옥(build
jail)**, **스테이징된** 공개 아티팩트에 대한 누출 스캔 통과, **Ed25519 서명**, 소유권으로
울타리 친 원자적 DB 기록을 모두 만족할 때만 — 생성한다. 신뢰할 수 없는 엔진은 자신의
워크스페이스만 보이는 감옥에 갇히며(저장소·상대·비공개 팩은 절대 보이지 않음), 신뢰되는
평가자는 호스트에 남는다. 평가 **프로파일**(`smoke`/`official`/`final-production`)이 결과가
검증될 자격이 있는지를 결정한다 — `smoke`는 **절대 검증되지 않으며** 공식 리더보드에 오르지
않는다. 공개 공식 검증 결과는 **반드시 Ed25519로 서명**되어야 하며(HMAC은 레거시/진단 전용),
누구나 운영자 공개 키로 검증한다. 공개 아티팩트는 먼저 **스테이징(private)** 으로 기록되고
누출 스캔을 통과해야만 **public**으로 승격되며, 결과는 **재현성 메타데이터**를 포함한다.
기본 백엔드는 단일 노드(SQLite + 로컬 객체 저장소)이지만 다중 워커에 안전한 원자적 잡
클레임을 갖춘다. 모든 v0.2/v0.3 명령은 변경 없이 그대로 동작한다.

## 빠른 시작

```bash
git clone https://github.com/junyeopYim/chess_en_bench.git
cd chess_en_bench
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev,server,hosted]"   # hosted extra adds Ed25519 signing (cryptography)

ceb doctor                       # environment diagnosis
pytest -q                        # 238 passed + 6 skipped (Docker tests opt-in: CEB_DOCKER_TESTS=1)
```

공개 공식 호스팅형 배포를 운영하기 전에 준비 상태를 확인한다(`ceb` 버전 >= 0.3.2, DB 스키마,
Docker + 감옥 이미지, **신뢰되는** 공식 평가 팩, 데모 팩 거부, Ed25519 서명/검증 키, 프로파일
정책, `final-production` 게임 바닥선, Track B 빌드 래퍼, 관리자 토큰 등을 점검):

```bash
ceb hosted readiness check --db runs/hosted.sqlite --eval-pack <official-pack> \
    --public-key op.pub.pem --track A    # 준비 안 되면 0이 아닌 종료 코드, --json으로 보고서
```

공개 게이트와 함께 번들된 예제 엔진에 대한 빠른 라운드를 실행한다:

```bash
ceb gate run  --track A --workspace examples/submissions/minimal_uci_engine_python
ceb gate run  --track A --workspace examples/submissions/minimal_uci_engine_python --strict
ceb round run --track A --workspace examples/submissions/minimal_uci_engine_python --round 1 --quick
ceb round run --track A --workspace examples/submissions/minimal_uci_engine_python --round 1 --final-eval
ceb scan workspace --track A --workspace examples/submissions/minimal_uci_engine_python
ceb leaderboard compute --track A --results runs                 # official + final, quick excluded
ceb leaderboard compute --track A --results runs --include-quick # diagnostic view
ceb server start --host 127.0.0.1 --port 8000   # dashboard at http://127.0.0.1:8000/
```

## 엔진 감옥(engine jail) — 신뢰할 수 없는 엔진의 격리

엔진 감옥은 **오직** 제출물의 UCI 엔진만 가둔다. 평가자는 호스트에서 신뢰된 상태로 남아
비공개 팩을 직접 읽는다. 감옥에 갇힌 엔진은 `/submission`에 **읽기 전용(read-only)** 으로
마운트된 자신의 워크스페이스 외에는 아무것도 보지 못한다 — `--network none`, 읽기 전용 루트
+ tmpfs `/tmp`, `--cpus 1 --memory 1g --pids-limit 128`,
`--security-opt no-new-privileges`, 비-root, stdio 전용 UCI. 저장소, 평가 팩, 상대
마운트는 없으며, 감옥 이미지는 의도적으로 `ceb` 패키지를 설치하지 **않으므로** 갇힌 엔진은
평가자 코드를 import할 수 없다. 감옥 이미지에는 빌드 툴체인(`gcc`/`g++`/`make`, `python3`,
`bash`)이 포함되어 **Python뿐 아니라 C/C++/네이티브** 제출물도 `build.sh`로 from scratch
빌드·실행할 수 있다(빌드 단계는 `/submission` 쓰기 가능, 엔진 실행은 읽기 전용, 항상
네트워크 없음). 호스팅형 Track A 언어 정책: 감옥 내 툴체인만으로 `/submission/engine`
실행 파일을 만드는 어떤 언어든 허용한다. 동작하는 C++ 예제는
`examples/submissions/minimal_uci_engine_cpp`(소스 전용)다. 비공개 팩은 안전하게 결합된다 —
포지션은 stdin의 `position fen ...` 줄로만 감옥에 도달하므로 `--eval-pack`은
`--engine-jail docker`와 **함께** 동작한다(레거시 `--sandbox docker`와 달리).

```bash
bash scripts/build_jail_image.sh                 # builds chess-en-bench-jail:0.4 (with toolchain)
ceb gate run  --track A --workspace <dir> --engine-jail docker
ceb gate run  --track A --workspace examples/submissions/minimal_uci_engine_cpp --strict --engine-jail docker
ceb round run --track A --workspace <dir> --round 1 --eval-pack <private-pack> --engine-jail docker
```

`--engine-jail`의 기본값은 `none`(호스트 실행, 신뢰/로컬 용도)이다. Docker가 없거나 이미지가
없으면 실행 가능한 조치를 안내하는 오류를 발생시킨다. 레거시 `--sandbox docker` 모드(전체
하니스를 컨테이너에서, 저장소를 마운트)는 여전히 사용 가능하지만 호스팅형 공식 경로는
**아니며**, 여전히 `--eval-pack`을 거부한다.

## 호스팅형 공식 평가

호스팅형 파이프라인은 검증된 결과를 위한 **권위 있는(authoritative)** 경로다. 공식
워커(worker)는 `verified: true`를 기록하는 유일한 코드다. 평가 **프로파일**이 결과가 검증될
자격을 결정한다: `smoke`(진단, 절대 미검증, 감옥 불필요), `official`, `final-production`
(리더보드가 선호). verifiable 프로파일은 정적 스캔 → **신뢰되는 공식 팩**에 대한 엄격 게이트
→ 팩 + **Docker 엔진 감옥**으로 라운드 → 공개 아티팩트를 **스테이징(private)** 으로 기록 →
스테이징된 표면에 대한 **공개 누출 스캔** → 메타데이터 + **Ed25519 서명** → 통과 시에만
아티팩트를 **public으로 원자적 승격** 순으로 실행된다. 평가 팩이 없거나, 팩이 신뢰되지
않거나(데모 팩 포함), 감옥이 docker가 아니거나, **Ed25519 키가 없거나**, 스캔/엄격 게이트가
실패하거나, 누출이 탐지되면 **검증을 거부한다**(평가 전에 실패). 워커의 `--engine-jail`
기본값은 `docker`이며, 다중 워커에 안전한 원자적 잡 클레임을 사용한다. 기본 저장소는 SQLite와
`<db>_store/` 객체 디렉터리다.

**신뢰되는 공식 평가 팩.** 검증된 결과는 `manifest.json`(스키마 `ceb.eval_pack.manifest/v1`,
`official: true`/`visibility: "private"`/`track`/`season`/`openings_mode` 등)을 갖추고
저장소의 `examples/`·`tests/` **밖에** 사는 팩을 요구한다. 운영자는 선택적으로 팩 콘텐츠
해시 허용 목록을 줄 수 있다(env `CEB_OFFICIAL_EVAL_PACK_HASHES`, `--official-pack-hash`,
`--official-pack-registry`); 허용 목록이 있으면 팩 해시가 일치해야 한다. 커밋된 데모 팩
`examples/eval_packs/tiny_private`에는 공식 매니페스트가 없어 **절대 검증되지 않는다**(`smoke`
프로파일에는 적합). 결과 메타데이터는 `eval_pack_id`/`eval_pack_hash`/
`eval_pack_manifest_hash`/`eval_pack_trusted`/`eval_pack_track`/`eval_pack_season`을 기록한다.

```bash
bash scripts/build_jail_image.sh                 # jail image, once

ceb hosted keygen --private-key op.pem --public-key op.pub.pem   # Ed25519 서명 키(필수)
export CEB_SIGNING_PRIVATE_KEY=op.pem            # 또는 worker에 --signing-key

ceb hosted init   --db runs/hosted.sqlite
ceb hosted submit --track A --workspace <dir> --run-id myrun --db runs/hosted.sqlite
# snapshots the workspace (symlinks rejected), tree-hashes it, enqueues a job
# 또는 업로드: ceb hosted submit --archive <ws.tar.gz> --run-id myrun --db runs/hosted.sqlite

ceb hosted worker run-once --db runs/hosted.sqlite \
    --eval-pack <official-pack> --profile official \
    --signing-key op.pem --official-pack-hash <sha256:...>   # --profile final-production for leaderboard-quality
ceb hosted result show  --run-id myrun --db runs/hosted.sqlite     # marks the selected best verified result
ceb hosted leaderboard  --track A --db runs/hosted.sqlite          # verified results only; smoke never appears
ceb hosted result export --run-id myrun --db runs/hosted.sqlite --out myrun.zip   # selected verified bundle
```

`ceb hosted result export`는 기본적으로 **선택된 최고 검증 결과**(`select_best_verified_result`)의
공개 아티팩트만 묶는다 — `official_result.json`, `feedback.json`, `report.public.json`,
`bundle_manifest.json`, `VERIFY.txt`. smoke·구버전·비선택 결과나 비공개 아티팩트(스캔/누출
보고서, 매치 로그, 게임 텍스트)는 절대 포함하지 않는다. 검증 결과가 없으면 기본 내보내기는
오류를 낸다. `--include-all-public`은 비공식임을 명시한 진단용 번들이다.

누구나 운영자 공개 키로 결과를 검증한다:
`ceb hosted verify-result --result <official_result.json> --public-key op.pub.pem`
(Ed25519 필수; **반드시 대역 외(out-of-band)로 받은 공개 키로 검증해야 `authentic: true`**다 —
결과에 박힌 키만으로는 `embedded-self-described`로 진정성을 주장하지 않는다. 키가 없으면 결과는
명시적으로 `unsigned`이다). 동일한 작업이 `/api/hosted/...` 아래 HTTP로 노출된다. 관리자 업로드
엔드포인트(`POST /api/hosted/runs/{run_id}/upload`)는 본문을 임시 파일로 **스트리밍**하며
읽는 동안 200 MiB 상한(`_MAX_UPLOAD_BYTES`)을 강제하고, 안전 추출이 심볼릭/하드 링크·절대
경로·traversal·비정규 파일을 거부한다 — 자체 본문 제한이 있는 리버스 프록시(예: nginx
`client_max_body_size`) 뒤에 배포한다. 관리자 POST/업로드 엔드포인트는 `CEB_ADMIN_TOKEN`으로
보호되고, 공개 GET 엔드포인트는 공개 아티팩트만 제공한다. 자세한 내용은
[docs/HOSTED_OPERATIONS.md](docs/HOSTED_OPERATIONS.md),
[docs/LEADERBOARD_GOVERNANCE.md](docs/LEADERBOARD_GOVERNANCE.md),
[docs/RESULT_SIGNING.md](docs/RESULT_SIGNING.md)를 참조한다.

## 두 개의 트랙

**Track A — 처음부터 만드는 엔진.** 평가 대상 에이전트는 공개 명세
([specs/uci_minimal.md](specs/uci_minimal.md)), 공개 정확성 게이트, 예제 FEN/perft 데이터
([tracks/a_from_scratch/public/](tracks/a_from_scratch/public/))를 받는다. 자체 완결적인
UCI 엔진을 생성해야 한다. 게이트는 **무제한** 실행할 수 있다. 평가는 세 가지 모드를 사용한다
— `quick`(무료, 진단용), `official_round`(예산 3단위 중 1단위 소비, 엄격 게이트),
`final_eval`(엄격 게이트, 예산 비용 없음, 리더보드 품질). 라운드는 엔진을 벤치마크 소유의
상대 사다리(BenchRandom … BenchAlphaBeta3)와 맞붙이고, Elo 방식 사다리 레이팅에서 결함
페널티를 뺀 값으로 채점한다. 자세한 내용은
[docs/track_a_from_scratch.md](docs/track_a_from_scratch.md)를 참조한다.

**Track B — Stockfish 탐색 최적화.** 에이전트는 diff 화이트리스트 하에서 **고정된(pinned)**
베이스라인(Stockfish 18, 태그 `sf_18`, 커밋 `cb3d4ee` — 움직이는 브랜치는 절대 아님)의 탐색
관련 파일만 편집하며, 후보-대-베이스라인 델타 Elo로 채점된다. `ceb track-b round run`은 바이너리
후보를 바이너리 베이스라인과 맞붙인다. `ceb track-b official run`은 소스 우선(source-first)
**진단** 경로다(호스트 빌드, **항상 `verified: false`**). 자세한 내용은
[docs/track_b_stockfish_optimization.md](docs/track_b_stockfish_optimization.md)와
[docs/TRACK_B_OFFICIAL_PIPELINE.md](docs/TRACK_B_OFFICIAL_PIPELINE.md)를 참조한다.

```bash
bash scripts/setup_stockfish.sh   # optional: fetch the pinned baseline (GPLv3, gitignored)
ceb track-b status
ceb scan track-b --baseline-src <tree> --candidate-src <tree>
ceb track-b round run --candidate-engine <path> --baseline-engine <path> \
    --baseline-src <tree> --candidate-src <tree>
ceb track-b official run --candidate-src <tree> [--baseline-src <tree>] \
    [--eval-pack <dir>] [--engine-jail docker]
```

`ceb track-b round run`과 `official run`은 **진단용**이다(`verified: false`). 검증된 Track B
결과는 호스팅형 경로로만 나온다: 관리자 `POST /api/hosted/runs/{run_id}/track-b-submissions`
(JSON `{candidate_src, baseline_src, build_script?, engine_relpath?}`)가 후보/베이스라인
트리를 스냅샷(심볼릭 링크/안전하지 않은 파일 거부)·해싱하고 `track_b_official_eval` 잡을
큐잉하면, 워커가 스캔 + diff 화이트리스트 + **격리된 빌드 감옥에서 빌드** + Docker 엔진 감옥
후보-대-베이스라인 매치 + 스테이징→누출 스캔→승격 + Ed25519 서명을 거쳐 검증된 델타 Elo
결과(`ceb.track_b.official_result/v1`)를 호스팅형 리더보드(track B)에 기록한다.

**Track B 빌드 격리.** 검증된 Track B는 후보 소유 빌드 스크립트를 호스트에서 절대 실행하지
않는다. 후보/베이스라인 트리 **밖에** 있는 **신뢰되는 운영자 빌드 래퍼**(워커에
`--build-wrapper`로 전달)가 **같은 래퍼로** 베이스라인과 후보를 Docker 빌드 감옥 안에서
빌드한다: 소스는 `/src`에 **읽기 전용** 마운트, 쓰기 가능한 `/out`, 래퍼는 `/wrapper.sh`에
읽기 전용, `--network none`, 읽기 전용 루트 + tmpfs, cpu/mem/pids 제한, 비-root, 저장소·평가
팩은 일절 마운트 없음. 래퍼 계약: `/wrapper.sh <source_ro> <out_writable> <engine_relpath>`.
빌드 감옥은 기본적으로 `chess-en-bench-jail:0.4`를 재사용하며(gcc/g++/make/bash/python3 포함),
`infra/docker/track_b_build_jail.Dockerfile`로 전용 이미지(`chess-en-bench-build-jail:0.4`)를
만들 수도 있다. 빌드된 후보 엔진은 매치를 위해 엔진 감옥에서 실행된다. 결과 메타데이터는
`build_isolation`(`"jail"`|`"host"`)을 기록하며, `run_official_track_b`는
`build_isolation="host"`로는 `verified=True`를 거부한다. 내부 Python 러너가 기본값이자
신뢰되는 기준이며, `--runner fastchess`는 선택적 대용량 백엔드다(공식 검증 경로 밖).

## 평가가 실행되는 방식

1. `ceb workspace prepare --track A --run-id myrun` — `runs/myrun/`을 생성한다.
   `runs/myrun/workspace`에 대한 `round run`은 run id를 자동으로 추론한다.
2. 에이전트가 반복한다: 엔진 편집 → `ceb gate run …` → JSON 보고서 읽기 → 반복. 게이트 시도는
   무료이며 무제한이다.
3. **로컬 진단 라운드:** `ceb round run --track A --workspace … --round 1`
   (무료 스모크 라운드는 `--quick`, 리더보드 품질 라운드는 `--final-eval`). 공식 등급
   라운드는 **엄격** 게이트(perft 필수)를 다시 실행하고, 오프닝 모음에서 게임을 시작하며,
   운영자가 마운트한 비공개 평가 팩(`--eval-pack` / `CEB_PRIVATE_EVAL_DIR`)을 소비할 수
   있다. 모든 로컬 라운드는 `verified: false`(자가 보고)다.
4. **호스팅형 공식 라운드:** `ceb hosted submit` 후 `ceb hosted worker run-once`(프로파일
   `official`/`final-production`, `--engine-jail docker`, **신뢰되는** 공식 팩, Ed25519
   `--signing-key`)가 유일한 `verified: true` 결과를 생성한다. 호스팅형 리더보드가 이를 순위
   매긴다(최고 final-tier, 없으면 최고 official-tier. `smoke`/`quick`은 절대 등장하지 않는다).

세부 사항: [docs/benchmark_protocol.md](docs/benchmark_protocol.md)와
[docs/agent_protocol.md](docs/agent_protocol.md).

## 저장소 구조

| 경로 | 내용 |
| --- | --- |
| `bench/ceb/` | Python 패키지: 체스 오라클, UCI 클라이언트, 게이트, 매치 러너, 오프닝, 평가 팩, 채점, 라운드, CLI |
| `bench/ceb/jail/` | 엔진 감옥: `engine_jail.py`(프런트엔드), `docker_engine.py`(Docker 백엔드) — 신뢰할 수 없는 엔진만 가둔다 |
| `bench/ceb/storage/` | 아티팩트 가시성 모델(`artifacts_manifest.json`; 공개는 기본 거부), `promotion.py`(스테이징→누출 스캔→public 승격) |
| `bench/ceb/scan/` | 정적 부정행위 방지 스캐너(`scan workspace`, `scan track-b`), 공개 아티팩트 누출 스캐너 |
| `bench/ceb/hosted/` | 호스팅형 파이프라인: SQLite db, 제출물, 공식 워커, 메타데이터, 서명, 검증자, `eval_pack_trust.py`(신뢰 팩), `build_wrappers.py`(신뢰 빌드 래퍼), `result_bundle.py`(선택-번들), `readiness.py`(준비 점검) |
| `bench/ceb/sanitize.py` | 비공개 안전 오류(`SanitizedError`, `sanitize_exception`) |
| `bench/ceb/match/fastchess_runner.py` | 선택적 fastchess 백엔드(내부 러너가 기본 기준) |
| `bench/ceb/track_b/official_pipeline.py` | Track B 소스 우선 파이프라인(스캔 → 빌드 → 쌍지어진 매치 → 서명된 결과; `build_isolation` jail/host) |
| `bench/ceb/track_b/build_jail.py` | 격리된 Track B 빌드 감옥(`build_in_jail`; 신뢰 래퍼로 baseline+candidate 빌드) |
| `bench/ceb/sandbox/` | 레거시 컨테이너 내 하니스 `--sandbox docker`(호환용; 호스팅형 경로 아님) |
| `tracks/` | 트랙 설정, 공개 데이터(`openings_public.jsonl` 포함), 프롬프트, 채점/페널티 표 |
| `specs/` | 규범적 계약(UCI 부분집합, perft 확장, 제출, 피드백, 금지 동작) |
| `docs/` | 프로토콜, 채점, 재현성, 서명, 평가 팩, 리더보드 거버넌스, 보안 문서 |
| `examples/submissions/` | 최소한으로 통과하는 엔진과 의도적으로 망가뜨린 엔진들 |
| `examples/eval_packs/tiny_private/` | 운영자 인터페이스를 보여주는 가짜 데모 비공개 팩 |
| `infra/docker/engine_jail.Dockerfile` | 엔진 감옥 이미지(`scripts/build_jail_image.sh`, 태그 `chess-en-bench-jail:0.4`) |
| `infra/docker/track_b_build_jail.Dockerfile` | Track B 빌드 감옥 전용 이미지(`scripts/build_track_b_build_image.sh`, 태그 `chess-en-bench-build-jail:0.4`) |
| `infra/docker/evaluator.Dockerfile` | 레거시 샌드박스 이미지(`scripts/build_evaluator_image.sh`) |
| `tests/` | pytest 스위트(정규 perft 카운트 포함); CI는 3.10–3.12에서 실행한다 |
| `runs/`, `artifacts/` | 로컬 출력물(gitignored) |

## 설계 노트

- **오라클**(`bench/ceb/chess/`)은 의존성이 없으며 정규 perft 카운트로 검증된다. 모든
  게임의 모든 수를 판정한다. v0.3은 3회 동형반복, 보수적 기물 부족(K vs K, K+B vs K,
  K+N vs K), 설정 가능한 하프무브 무승부 임계값을 추가한다.
- 제출된 엔진은 **신뢰할 수 없다**: argv 전용 스폰, 모든 읽기에 타임아웃, 출력 수신량 제한,
  프로세스 그룹 종료, 그리고 선택적 엔진 감옥. [docs/security.md](docs/security.md)를 참조한다.
- **검증됨 대 미검증:** 호스팅형 워커만, verifiable 프로파일(`official`/
  `final-production`) + Docker 엔진 감옥 + **신뢰되는 공식 팩** + **Ed25519 서명** + (Track B)
  격리된 빌드 감옥 + 스테이징된 공개 아티팩트 누출 스캔 통과 시에만 `verified: true`를
  기록한다. 검증 등급은 `verified-official`/`verified-final-production`이며, 다운그레이드
  진단 등급으로 `diagnostic-smoke`/`diagnostic-unjailed`/`diagnostic-unsigned`/
  `diagnostic-untrusted-pack`가 있다. 로컬 라운드, `smoke` 프로파일, 직접 실행한 Track B CLI
  실행은 자가 보고 진단이다. 검증자(`verify-result`)는 verified 결과가 Ed25519가 아니거나
  대역 외 공개 키 없이 검증되면 `authentic: false`로 표시한다.
- 기계가 읽을 수 있는 모든 것은 버전이 명시된 JSON 스키마를 사용한다
  (`ceb.gate.report/v1`, `ceb.round.report.public/v1`,
  `ceb.hosted.official_result/v2`, `ceb.hosted.leaderboard/v2`,
  `ceb.eval_pack.manifest/v1`, `ceb.eval_pack.trust/v1`,
  `ceb.hosted.readiness/v1`, `ceb.hosted.result_bundle/v1`,
  `ceb.scan.workspace/v1`, `ceb.scan.leak/v1`, …).
  [docs/overview.md](docs/overview.md)를 참조한다.

라이선스: MIT([LICENSE](LICENSE) 참조). Stockfish는 GPLv3이며 이 저장소와 함께
배포되지 **않는다**([NOTICE](NOTICE) 참조).
