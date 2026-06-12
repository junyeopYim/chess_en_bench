# 결과 서명 (Result Signing)

공식 결과가 v0.3에서 어떻게 지문화(fingerprint)되고, 서명되고, 검증되는지를
다룬다.

이것은 **MVP**다. 서명은 공유 비밀로 키가 지정된 **대칭 HMAC-SHA256**이다. 그
키 보유자만 결과를 검증할 수 있다. 이는 공개키 증명(attestation)이 **아니다** —
제3자가 독립적으로 진정성을 확인할 수 없다. 비대칭 서명은 향후 작업이다("한계"
참고).

구현:
- 메타데이터: `bench/ceb/hosted/metadata.py`
- 서명: `bench/ceb/hosted/signing.py`
- 검증: `bench/ceb/hosted/verifier.py`
- 결과 생성기: `bench/ceb/hosted/official_eval.py` (`run_official_eval`)

결과 파일은 스키마 `ceb.hosted.official_result/v1`을 사용하며 공개 아티팩트
`official_result.json`으로 기록된다. 이는 `metadata` 블록과 `signature`
블록을 담는다.

## 메타데이터 블록

`build_metadata`가 조립한다. 모든 필드는 항상 존재한다. 호스트에서 결정할 수
없는 필드는 생략되지 않고 명시적으로 `null`이다.

| 키 | 의미 | null인 경우 |
| --- | --- | --- |
| `benchmark_version` | `ceb.__version__` (현재 `0.3.0`). | 없음 |
| `git_commit` | 저장소 루트의 `git rev-parse HEAD`. | git 체크아웃이 아님 / git 사용 불가 |
| `evaluator_image_digest` | 평가기 이미지(기본 `chess-en-bench-evaluator:0.2`)의 Docker 이미지 id. | docker 없음 또는 이미지 미pull |
| `engine_jail_image_digest` | 엔진 감옥 이미지(`chess-en-bench-jail:0.3`)의 Docker 이미지 id. | docker 없음 또는 이미지 미빌드 |
| `eval_pack_id` | 해석된 eval 팩의 이름. | (공식 경로는 항상 설정함; 비공식 호출자는 `None`을 전달할 수 있음) |
| `eval_pack_hash` | eval 팩 디렉터리(상대 경로 + 내용)에 대한 `sha256:`. | `eval_pack_dir`가 전달되지 않음 |
| `opponent_pool_hash` | `bench/ceb/match/opponents.py`의 `sha256:`. | 없음 |
| `opening_suite_hash` | 오프닝 스위트의 정규(canonical) JSON에 대한 `sha256:`. | 오프닝 스위트가 전달되지 않음 |
| `hardware.cpu_model` | `/proc/cpuinfo` 또는 `platform.processor()`에서 가져온 CPU 모델. | 둘 다 해석되지 않음 |
| `hardware.cpu_cores` | 실행에 할당된 코어 수(엔진 감옥에서는 1). | 없음 |
| `hardware.memory_limit` | 메모리 상한 문자열, 예: `"1g (engine jail)"`. | 엔진 감옥에서 실행되지 않음 |
| `software.python` | Python 버전. | 없음 |
| `software.platform` | `platform.platform()`. | 없음 |
| `software.compiler` | `g++`/`clang++ --version`의 첫 줄. | PATH에 C++ 컴파일러 없음 |
| `software.fastchess` | PATH의 `fastchess` 경로. | fastchess 미설치 |
| `software.stockfish_baseline` | 고정 베이스라인 문자열 `"sf_18/cb3d4ee"`. | 없음 (상수) |
| `random_seed` | 사용된 시드(공식 경로에서는 `1000 * round_number`). | 호출자가 `None`을 전달할 수 있음 |
| `verified` | 공식 워커 경로에서만 `true`. | 없음 (항상 bool) |

`eval_pack_hash`, `git_commit`, 이미지 digest, `compiler`, `fastchess`가
`null`인 것은 정당한 감사 신호다. docker 이미지가 고정되지 않은 채 계산된
결과, 또는 git이 아닌 트리에서 나온 결과는 재현성이 저하된 것이며, null은 이를
숨기는 대신 명시적으로 드러낸다.

## 서명 블록

`sign_result(result, key=None)`은 `signature` 블록을 제자리에 부착한다. 키는
명시적으로 전달되지 않는 한 `CEB_SIGNING_KEY` 환경 변수에서 온다.

**서명됨** (키 있음):

```json
"signature": {
  "status": "signed",
  "algorithm": "hmac-sha256",
  "note": "symmetric HMAC; verifiable only by holders of the signing key",
  "value": "<hex digest>"
}
```

**서명되지 않음** (키 미설정):

```json
"signature": {
  "status": "unsigned",
  "algorithm": null,
  "note": "no CEB_SIGNING_KEY configured; this result has NO cryptographic authenticity"
}
```

서명되지 않은 블록은 **결코 진정성을 주장하지 않는다** — 그 노트가 그렇게
말하며, 검증기는 이를 진정하지 않은 것으로 취급한다(아래). 서명되지 않은
결과도 여전히 유효하고 유용한 결과다. 단지 암호학적 출처(provenance)가 없을
뿐이다.

### 정규 페이로드 (Canonical payload)

digest는 `canonical_payload(result)`에 대한 HMAC-SHA256이다:

```python
body = {k: v for k, v in result.items() if k != "signature"}
json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
```

`signature` 블록 자체는 **제외**되고, 키는 정렬되며, 구분자는 압축적이다 —
따라서 바이트는 dict 순서나 공백과 무관하게 안정적이다. 검증은 동일한 정규
바이트에 대해 다시 계산한다. 결과 본문에 대한 모든 변경(또는 다른 키로 서명)은
불일치를 낳는다.

## CLI

결과 파일을 제자리에서 서명:

```bash
CEB_SIGNING_KEY=... ceb hosted sign-result --result path/to/official_result.json
```

`CEB_SIGNING_KEY`가 없으면 `sign-result`는 서명되지 않은 블록을 기록하고,
서명되지 않은 결과에는 암호학적 진정성이 없다는 알림을 출력한다.

결과 파일을 검증(JSON 판정을 출력; 진정하면 종료 코드 `0`, 그렇지 않으면 `2`):

```bash
CEB_SIGNING_KEY=... ceb hosted verify-result --result path/to/official_result.json
```

공식 워커(`ceb hosted worker run-once`)는 검증된 결과를 생성하는 마지막
단계로 자동으로 서명한다.

## 검증 판정

`verify_result_file` (스키마 `ceb.hosted.verification/v1`)이 반환하는 것:

- `schema_ok` — 결과 스키마가 `ceb.hosted.official_result/v1`인지.
- `claims_verified` — 결과 자체의 `verified` 플래그(증명이 아니라 주장).
- `signature_ok` / `signature_detail` — `verify_result`에서.
- `metadata_present` — `metadata`가 dict인지.
- `metadata_missing_keys` — `metadata`에 없는 필수 키:
  `benchmark_version`, `git_commit`, `eval_pack_hash`, `opponent_pool_hash`,
  `opening_suite_hash`, `random_seed`, `verified`. (참고: 필수란 키가
  존재함을 의미한다. 명시적인 `null` 값도 여전히 존재하는 것으로 친다.)
- **`authentic`** — 최종 판단:

  ```
  authentic = schema_ok AND signature_ok AND (no metadata_missing_keys)
  ```

`verify_result`는 다음의 경우 `signature_ok=False`를 반환한다:
- **서명되지 않은** 결과: `"unsigned result (no cryptographic authenticity)"` —
  따라서 서명되지 않은 결과는 결코 진정한 것으로 오인될 수 없다;
- 검증 시점에 **키 없음**: `"no CEB_SIGNING_KEY configured; cannot verify"`;
- **변조 / 잘못된 키**: `"signature MISMATCH: result was modified or signed
  with a different key"` (`hmac.compare_digest`를 통한 상수 시간 비교).

## 한계 (MVP)

- **대칭 전용.** HMAC은 `CEB_SIGNING_KEY`를 보유한 누구에게나, 즉 벤치마크
  운영자에게 인증한다. 검증자와 서명자가 같은 비밀을 공유하므로, "검증할 수
  있음"과 "위조할 수 있음" 사이에 분리가 없다. 서명된 결과는 키가 없는
  제3자에게는 아무것도 증명하지 못한다.
- **공개키 증명 없음.** 비대칭 서명(운영자가 비공개 키로 서명하고, 누구나 게시된
  공개 키로 검증)은 **향후 작업**이다. 그때까지는 검증된 결과를 공개적으로 검증
  가능한 것이 아니라 운영자가 증명한 것으로 취급한다.
- **키 관리는 범위 밖이다.** 키는 환경 변수에서 읽힌다. 회전(rotation), 저장,
  배포는 운영자의 관심사다.
