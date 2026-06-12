# 평가 팩(evaluation pack)

평가 팩은 평가가 소비하는 데이터다. 이 저장소에 함께 배포되는 **공개(public)**
부분과, 운영자가 평가 시점에 마운트하는 선택적 **비공개(private)** 부분으로
구성된다. 로더는 `bench/ceb/eval_pack.py`이며, 오프닝 검증은
`bench/ceb/match/openings.py`에 있다.

**실제 비공개 데이터는 이 저장소에 배포되지 않는다.** 트리에 존재하는 유일한
비공개 팩은 `examples/eval_packs/tiny_private/`에 있는 가짜 데모뿐이며, 로더와
테스트가 동작을 검증할 수 있도록 문서화된 형태를 제공하기 위해 존재한다. 실제
hidden FEN, perft 기댓값, 오프닝은 운영자가 관리하며 배포마다 마운트된다.

## 신뢰된 공식 팩(verified 전용, v0.3.2)

공개 공식 `verified: true` 결과는 **신뢰된 공식 팩**만 사용할 수 있다(데모 팩은
절대 불가). 신뢰 검증은 `bench/ceb/hosted/eval_pack_trust.py`의
`validate_official_eval_pack`이 수행한다. 공식 팩 디렉터리는 다음 매니페스트를
포함해야 한다:

```json
{
  "schema": "ceb.eval_pack.manifest/v1",
  "pack_id": "ceb-A-2026s1",
  "name": "Track A official pack 2026 season 1",
  "track": "A",
  "season": "2026-s1",
  "official": true,
  "visibility": "private",
  "openings_mode": "replace"
}
```

검증 규칙:

- `schema`가 `ceb.eval_pack.manifest/v1`이고 위 키가 모두 존재해야 한다.
- `official`은 `true`, `visibility`는 `"private"`, `track`은 `"A"`/`"B"`/`"both"`
  (평가 트랙과 일치해야 함).
- 팩은 저장소의 `examples/` 또는 `tests/` 같은 커밋/데모 경로 **밖**에 있어야 한다
  (개발용 `--dev-allow-demo-pack` 예외).
- 운영자가 허용목록을 제공하면 팩의 내용 해시(`hash_directory`의 `sha256:`)가
  일치해야 한다. 허용목록 출처: env `CEB_OFFICIAL_EVAL_PACK_HASHES`(콤마 구분),
  `--official-pack-hash`(반복/콤마), `--official-pack-registry`(JSON/텍스트 파일).

verified 결과 메타데이터에 기록되는 신뢰 필드: `eval_pack_id`, `eval_pack_hash`,
`eval_pack_manifest_hash`, `eval_pack_trusted: true`, `eval_pack_track`,
`eval_pack_season`. 팩 해시는 `ceb hosted readiness check --eval-pack <dir>`로
확인할 수 있다.

## 공개 팩

공개 팩은 Track A의 `public/` 디렉터리이며, `load_public_pack()`이 로드한다.

| File | Rows | Format |
|---|---|---|
| `tracks/a_from_scratch/public/fen_examples.jsonl` | bestmove-legality 포지션 | `{"id", "fen", "tags"}` |
| `tracks/a_from_scratch/public/perft_examples.jsonl` | perft 기댓값 | `{"id", "fen", "depth", "nodes"}` |
| `tracks/a_from_scratch/public/openings_public.jsonl` | 오프닝 스위트 | `{"id", "fen": "startpos"\|FEN, "moves": [UCI...], "tags": [...]}` |

그 결과로 만들어지는 `EvalPack`은 `source = "public"`을 가진다.

## 비공개 팩 디렉터리

비공개 팩은 다음 파일들 가운데 일부를 담은 **디렉터리**다(최소 하나는 필수).
각 행 형식은 공개 파일과 정확히 동일하다.

| File | Extends | Row format |
|---|---|---|
| `fen_hidden.jsonl` | 공개 FEN | `{"id", "fen", "tags"}` |
| `perft_hidden.jsonl` | 공개 perft | `{"id", "fen", "depth", "nodes"}` |
| `openings_hidden.jsonl` | 공개 오프닝(`openings_mode` 참조) | `{"id", "fen": "startpos"\|FEN, "moves": [UCI...], "tags": [...]}` |
| `manifest.json` | 선택 | `{"name": ..., "openings_mode": "extend"\|"replace"}` |

`manifest.json` 키(둘 다 선택):

- `name` — 아티팩트에 기록되는 팩 이름(기본값은 디렉터리 이름). 그 외의 키
  (예: `note`)는 무시된다.
- `openings_mode` — `"extend"`(기본값)는 hidden 오프닝을 공개 스위트 뒤에
  덧붙이고, `"replace"`는 hidden 오프닝만 사용한다. FEN과 perft 행은 **항상
  공개 집합을 확장(extend)**하며, `openings_mode`를 따르는 것은 오프닝뿐이다.

비공개 팩이 해석되면 `EvalPack.source`는 `"public+private"`가 된다.

### hidden 행의 id 부여

모든 행은 `id`를 갖도록 보장된다. 비공개 행이 id를 생략하면 로더가 다음과 같이
부여한다.

- `fen_hidden.jsonl`에서는 `hidden_fen_<line>`
- `perft_hidden.jsonl`에서는 `hidden_perft_<line>`
- `openings_hidden.jsonl`에서는 `opening_<line>`

hidden 행에는 내부적으로 태그(`hidden: true`)도 붙는다. 모든 행에 id가 있으므로
게이트 실패, 라운드 보고서, 피드백은 hidden 행을 id로 참조할 수 있고 hidden FEN
이나 수(move)를 인용할 필요가 전혀 없다.

### hidden-safe 로딩

비공개 파일은 `hidden=True`로 로드된다. FEN과 오프닝 수는 로드 시점에 검증되므로
(FEN은 `parse_fen`을 통해, 오프닝 수는 내부 move 오라클에 대해) 손상된 팩은 불법
포지션을 매치에 흘려보내는 대신 큰 소리로 실패한다. 오류 메시지는 누출이 없도록
유지된다. hidden 검증 오류는 **파일 basename + 행 id + "content withheld"**를
인용할 뿐 FEN, 수, 전체 경로는 절대 노출하지 않는다. 전체 상세는 운영자 로그용으로
예외의 `private_message`에만 보관된다(`bench/ceb/sanitize.py`).

## 팩 해석하기

`resolve_eval_pack(root, private_dir=None, allow_env=False)`는 항상 공개 팩을
로드한 뒤, 비공개 팩이 해석되면 이를 병합한다. 비공개 디렉터리를 공급하는 방법은
두 가지다.

1. **`--eval-pack <dir>`** — 명시적 플래그로, 이를 허용하는 모든 곳에서 적용된다.
   `ceb gate run`, `ceb round run`, `ceb track-b round run`,
   `ceb track-b official run`, `ceb hosted worker run-once`.
2. **`CEB_PRIVATE_EVAL_DIR`** — 환경 변수 폴백으로, 옵트인한 평가(`allow_env=True`)
   에서**만** 소비된다. 즉 strict Track A 게이트(`ceb gate run --strict`), 공식
   Track A 라운드, **모든** Track B 라운드(`bench/ceb/track_b/round_runner.py`가
   `allow_env=True`를 전달)이다. 일반 공개 게이트와 Track A quick 라운드는
   `allow_env=False`를 전달하므로 환경 변수를 절대 읽지 않는다.

비공개 디렉터리를 암묵적으로 읽는 곳은 없다. 관례적인 마운트 지점
(`tracks/a_from_scratch/private/`, `tracks/b_stockfish_opt/private/`)은 비어 있는
플레이스홀더다. 배포 시 플래그나 환경 변수를 운영자가 관리하는 디렉터리로
가리켜야 한다.

```bash
# Strict Track A gate with a private pack
ceb gate run --track A --workspace <ws> --strict --eval-pack <private-dir>

# Official Track A round with a private pack
ceb round run --track A --workspace <ws> --round 1 --eval-pack <private-dir>

# Hosted worker (private pack is REQUIRED to produce a verified result)
ceb hosted worker run-once --db runs/hosted.sqlite \
    --eval-pack <private-dir> --engine-jail docker
```

## 엔진 감옥(engine jail)과의 결합

hidden 팩은 `--engine-jail docker`와 안전하게 결합된다. **평가기(evaluator)는
호스트에 머물며** 그곳에서 팩을 읽는다. 감옥에 갇힌 엔진은 자기 stdin으로 개별
`position fen ...` UCI 라인만 받을 뿐이다. 팩 디렉터리는 감옥 컨테이너에 **절대
마운트되지 않는다** — 감옥은 제출물 워크스페이스만 읽기 전용으로 `/submission`에
마운트한다(`bench/ceb/jail/docker_engine.py`).

이러한 분리 덕분에 `--eval-pack`는 **`--engine-jail docker`와 함께** 동작한다.
이는 레거시 `--sandbox docker` 모드(harness-in-container)와 다른데, 그 모드는
여전히 `--eval-pack`를 **거부**한다. 해당 모드는 팩을 컨테이너 내부에 마운트해야
하므로 `ceb round run --sandbox docker --eval-pack ...`는 `--engine-jail docker`
또는 `--sandbox none`을 가리키는 메시지와 함께 중단된다. 공식 호스트 평가는
`--sandbox`가 아니라 `--engine-jail docker`를 사용한다.

## 팩 버전 관리: eval_pack_hash

공식 결과(official-result) 메타데이터는 사용한 팩을 기록하여 결과를 재현 가능하고
변조에 강하게 만든다(`bench/ceb/hosted/metadata.py`).

- `eval_pack_id` — 팩 이름(`manifest.json` 또는 디렉터리 이름에서).
- `eval_pack_hash` — 팩 디렉터리의 상대 경로와 파일 내용에 대한 결정적 `sha256:`
  값(`hash_directory`), 또는 비공개 팩을 사용하지 않은 경우 `null`.

팩 디렉터리를 버전 관리되는 콘텐츠로 취급하라. 어떤 행이든 바꾸면 해시가 바뀌므로,
두 실행은 `eval_pack_hash`가 일치할 때만 비교 가능하다.

## tiny_private 데모 팩

`examples/eval_packs/tiny_private/`는 정확한 레이아웃을 보여주며 테스트 스위트가
이를 사용한다(`tests/test_eval_pack.py`, 그리고 `tests/test_hosted.py`,
`tests/test_engine_jail.py` 등에서 대역 비공개 팩으로). 이것은 **가짜 시연
데이터이며 실제 hidden 팩이 아니다**.

```
examples/eval_packs/tiny_private/
  manifest.json          {"name": "tiny_private_example", "openings_mode": "extend", ...}
  fen_hidden.jsonl       2 endgame positions
  perft_hidden.jsonl     2 perft expectations
  openings_hidden.jsonl  2 opening lines
```

실제 운영자 팩을 가리키기 전에 로더와 CLI 플래그를 dry-run으로 점검하는 데
사용하라.

```bash
ceb round run --track A --workspace <ws> --round 1 \
    --eval-pack examples/eval_packs/tiny_private
```
