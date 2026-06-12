# Track B — 소스 우선 공식 파이프라인

이것은 Track B 후보 *소스 트리*를 채점되고 서명된 델타 Elo 결과로 바꾸는
소스 빌드 경로다. 실행 파일만 다루는 `ceb track-b round run`(이미 빌드한 두 엔진을
대국시킴)과 나란히 존재한다. 트랙 규칙, diff 화이트리스트, 고정 베이스라인, 델타
Elo 채점은 `docs/track_b_stockfish_optimization.md`를 참고하라.

명령: `ceb track-b official run`
(`bench/ceb/track_b/official_pipeline.py`, `run_official_track_b`).

## 명령

```bash
ceb track-b official run \
  --candidate-src /path/to/candidate \
  [--baseline-src third_party/stockfish] \
  [--eval-pack DIR] \
  [--engine-jail none|docker] \
  [--build-script ceb_build.sh] \
  [--engine-relpath ceb_engine] \
  [--games 8] [--movetime 100] [--max-plies 300] \
  [--run-id track_b_official] [--runs-dir DIR]
```

- `--candidate-src`는 필수다.
- `--baseline-src`의 기본값은 `third_party/stockfish`다. 그 디렉터리가 없고
  `--baseline-src`도 주어지지 않으면 파이프라인은 `scripts/setup_stockfish.sh`와
  고정 태그(`sf_18`)를 가리키는 메시지와 함께 중단한다.
- `--build-script`(기본 `ceb_build.sh`)와 `--engine-relpath`(기본 `ceb_engine`)는
  각 트리가 제공하는 빌드 래퍼와 그것이 산출하는 엔진의 이름을 지정한다.
  베이스라인과 후보는 **동일한** 빌드 스크립트와 엔진 relpath로 빌드된다.
- `--engine-jail docker`는 후보 엔진만 가둔다(아래 참고).
- 모든 중단(스캔 실패, 빌드 스크립트 누락, 빌드 실패, handshake 실패)에서 종료
  코드 2이며, 위생 처리된 한 줄 메시지가 함께 나온다.

## 무엇이, 어떤 순서로 실행되는가

`run_official_track_b`는 엄격히 다음 순서로 실행한다:

1. **베이스라인 트리 해소.** `--baseline-src`, 또는 고정된 `sf_18` / `cb3d4ee`
   상태의 `third_party/stockfish`. (고정값은 `tracks/b_stockfish_opt/stockfish.lock`에
   있다. 파이프라인은 커밋 해시를 재검증하지 않는다 — 그것은
   `scripts/setup_stockfish.sh` / `ceb track-b status`의 일이다.)
2. `scan_track_b`(`bench/ceb/scan/track_b_scan.py`)로 베이스라인 대비 후보를
   **스캔**: diff 화이트리스트 및 콘텐츠 규칙(바이너리/NNUE/북/테이블베이스
   페이로드, 하네스 핑거프린팅, 변경된 소스의 네트워크/프로세스 syscall, 심볼릭
   링크). `fail` 발견 또는 화이트리스트 위반이 있으면 **무엇도 빌드하기 전에**
   중단한다.
3. **베이스라인 빌드**, 그 다음 **후보 빌드**. 각각 트리를 작업 디렉터리로 하여
   `bash <build-script>`를 실행한다(빌드 타임아웃 1800초). 0이 아닌 종료, 스크립트
   누락, 또는 `<engine-relpath>`를 산출하지 못하는 빌드는 중단을 일으킨다. 산출된
   엔진은 실행 가능하게 만들어진다(`chmod +x`).
4. `run_track_b_round`(internal 러너 — 신뢰된 레퍼런스)를 통해 **후보-대-베이스라인
   쌍 매치 진행**. 이는 Track B 라운드 흐름을 재사용한다: UCI handshake, 쌍 색-교대
   오프닝, 양쪽 엔진에 `Threads=1` / `Hash=16`, 델타 Elo 채점.
5. **메타데이터 조립**(`build_metadata`)과 `track_b` 블록 추가:
   `baseline_tree_hash`와 `candidate_tree_hash`(`hash_directory`를 통해 각 트리의
   상대 경로 + 내용에 대한 sha256), 그리고 `build_script`.
6. 결과 **서명**(`sign_result`)과 산출물 작성.

## 출력

스키마 `ceb.track_b.official_result/v1`의 단일 결과 dict이며 다음을 포함한다:
`run_id`, `track`, `round`, `finished_at`, `engine_jail`, `scan.passed`, `score`
(`ceb.score.track_b/v1`: W/D/L, 결함, `delta_elo`, `delta_elo_ci95`, 페널티,
`final_delta_elo`), `feedback`, `metadata`(`track_b` 트리 해시와
`software.stockfish_baseline = "sf_18/cb3d4ee"` 포함), `verified`, 그리고
`signature` 블록.

`runs/<run-id>/track_b_official_<round>/` 아래의 산출물:

- `official_result.json` — 공개(위의 결과).
- `scan_report.json` — 비공개(전체 스캔 발견 사항).

서명은 `CEB_SIGNING_KEY`를 키로 하는 대칭 HMAC-SHA256이다. 키가 없으면
`signature.status`는 `unsigned`이며 "NO cryptographic authenticity" 메모가
붙는다 — `docs/reproducibility.md`를 참고하라. 대칭 HMAC은 같은 키를 가진
당사자에게만 인증되며, 공개키 증명(attestation)이 아니다.

## 후보용 engine jail

`--engine-jail docker`는 `run_track_b_round`로 전달되며, 이는 **후보** 엔진을
Docker 감옥(engine jail, `bench/ceb/jail/`, `scripts/build_jail_image.sh`로
빌드된 이미지 `chess-en-bench-jail:0.3`)에 가둔다. 베이스라인 빌드는 운영자가
제공하며 호스트에서 신뢰된 상태로 실행된다. 후보는 자신의 워크스페이스 디렉터리
안의 단일 실행 파일이어야 하며, 그렇지 않으면 감옥 요청이 거부된다. Docker가
없거나 이미지가 없으면 실행 가능한 `EngineJailError`가 발생한다. `--engine-jail
none`(기본)이면 두 엔진 모두 호스트에서 실행된다.

## verified vs 진단 — 코드가 강제하는 것, 운영자가 해야 하는 것

`ceb track-b official run`은 항상 **`verified: false`**를 작성한다: CLI가
`run_official_track_b(..., verified=False)`를 호출한다. `verified=True`는
호스팅된 공식 워커(hosted official worker)를 위해 예약되어 있다. 직접 CLI 실행은
진단용이다.

**코드가 강제하는 것:**

- 어떤 빌드도 하기 전에 스캔이 통과해야 한다;
- 베이스라인과 후보는 *동일한* 빌드 스크립트와 엔진 relpath로 빌드된다;
- 빌드 실패 / 엔진 누락은 중단을 일으킨다;
- 두 트리의 트리 해시가 메타데이터에 기록된다;
- UCI 옵션(`Threads=1`, `Hash=16`)이 라운드 러너에 의해 양쪽 엔진에 전송된다.

**운영자 책임 — 코드가 강제하지 않음:**

- 두 트리에 대한 실제 고정 Stockfish 빌드 래퍼(예: `make -C src build`를 감싸는
  `ceb_build.sh`) 제공;
- 베이스라인과 후보 빌드 사이의 동일한 컴파일러 플래그 보장;
- 후보가 화이트리스트된 탐색 변경만 적용된 고정 Stockfish임을 확인하는 `bench` /
  속도 정합성 검사.

파이프라인은 빌드 스크립트가 산출하는 것을 빌드하고 대국시킨다. 컴파일러 플래그를
검사하지도, `bench` 정합성 검사를 실행하지도 않는다. 운영자가 통제하는 호스팅
경로를 통해 재현되기 전까지는 CLI 결과를 진단용으로 취급하라.

## 테스트와 CI

`tests/test_track_b_official.py`는 **작은 가짜 소스 트리와 번들된 Python UCI
엔진을 제자리에 복사하는 가짜 빌드 스크립트**로 파이프라인을 처음부터 끝까지
검증한다 — 실제 Stockfish도 컴파일러도 관여하지 않는다. 테스트는 happy path
(빌드, 채점, 구별되는 트리 해시 기록, `official_result.json` 작성), 금지 파일 거부
(스캐너 중단), 빌드 스크립트 누락 중단을 다룬다. CI는 이 파이프라인을 실행하지
않는다. CI는 토이 Track B *라운드*(`BenchRandom`을 쓰는 `ceb track-b round run`)만
실행한다. CI에는 Stockfish, Docker, 클라우드 실행이 없다.
