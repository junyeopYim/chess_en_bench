# 결과 서명 (Result Signing)

공식 결과가 어떻게 지문화(fingerprint)되고, 서명되고, 검증되는지를 다룬다.

v0.3.1부터 공식 권장 알고리즘은 **Ed25519 비대칭 서명**이다. 운영자는 비공개
키로 서명하고, **누구나** 게시된 공개 키로 진정성을 독립적으로 검증할 수 있다.
레거시 대칭 **HMAC-SHA256**(공유 비밀 `CEB_SIGNING_KEY`로 키 지정)은 운영자
내부 용도로 유지된다. 두 알고리즘은 서명 블록의 `algorithm` 필드로 명시적으로
구분되며 서로 혼동되지 않는다(공개키 검증기는 HMAC 결과를 받아들이지 않고, 그
반대도 마찬가지다).

구현:
- 메타데이터: `bench/ceb/hosted/metadata.py`
- 서명/키 생성/검증: `bench/ceb/hosted/signing.py`
- 검증 판정: `bench/ceb/hosted/verifier.py`
- 결과 생성기: `bench/ceb/hosted/official_eval.py` (`run_official_eval`)

결과 파일은 스키마 `ceb.hosted.official_result/v2`(레거시 `/v1`도 검증 가능)를
사용하며 공개 아티팩트 `official_result.json`으로 기록된다. 이는 `metadata`
블록과 `signature` 블록을 담는다.

## 알고리즘 선택 (`sign_official_result`)

공식 워커는 구성된 가장 강력한 알고리즘으로 서명한다:

1. `CEB_SIGNING_PRIVATE_KEY`(Ed25519 비공개 키 PEM 경로)가 설정되면 → **Ed25519**.
2. 아니고 `CEB_SIGNING_KEY`(HMAC 비밀)가 설정되면 → **HMAC-SHA256**(레거시).
3. 둘 다 없으면 → **서명되지 않음**(`unsigned`).

서명되지 않은 결과는 **결코 진정성을 주장하지 않으며**, 검증기는 이를 진정하지
않은 것으로 취급한다. "마법 같은 verified"는 없다.

## Ed25519 (권장, 공개 검증)

### 키 생성

```bash
ceb hosted keygen --private-key operator_ed25519.pem --public-key operator_ed25519.pub.pem
```

`generate_keypair`는 PKCS8 PEM 비공개 키(`chmod 600`)와 SubjectPublicKeyInfo
PEM 공개 키를 쓰고, `key_id`(원시 공개 키의 sha256, `ed25519:` 접두사)를
반환한다. **비공개 키는 절대 커밋하지 않는다**(`*.pem`은 gitignore됨). 공개 키는
대역 외(out-of-band)로 게시한다.

### 서명 블록

```json
"signature": {
  "status": "signed",
  "algorithm": "ed25519",
  "note": "Ed25519; verifiable by anyone holding the operator public key",
  "key_id": "ed25519:<fingerprint>",
  "public_key_fingerprint": "ed25519:<fingerprint>",
  "public_key": "<base64 raw public key>",
  "value": "<base64 signature>"
}
```

서명 블록은 공개 키와 그 지문을 **임베드**하여 결과 파일이 자기 기술적이게
하지만, 제3자의 신뢰는 임베드된 사본이 아니라 **대역 외로 얻은 공개 키**로
검증하는 데서 온다. 신뢰된 공개 키가 제공되면 검증기는 임베드된 `key_id`가 그
키와 일치하는지도 확인한다(결과가 실제 서명자와 다른 서명자를 주장할 수 없게).

## HMAC-SHA256 (레거시, 운영자 내부)

`sign_result(result, key)`는 `CEB_SIGNING_KEY`(또는 명시 키)로 HMAC 블록을
부착한다.

```json
"signature": {
  "status": "signed",
  "algorithm": "hmac-sha256",
  "note": "symmetric HMAC; verifiable only by holders of the signing key",
  "value": "<hex digest>"
}
```

HMAC은 비밀 키 보유자(즉 운영자)에게만 인증하며 공개키 증명이 **아니다**. 새
배포는 Ed25519를 사용해야 한다.

### 정규 페이로드 (Canonical payload)

두 알고리즘 모두 `canonical_payload(result)`에 서명한다:

```python
body = {k: v for k, v in result.items() if k != "signature"}
json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
```

`signature` 블록은 제외되고, 키는 정렬되며, 구분자는 압축적이다 — 따라서
바이트는 dict 순서나 공백과 무관하게 안정적이다. 결과 본문에 대한 모든
변경(또는 다른 키로 서명)은 불일치를 낳는다.

## CLI

```bash
# 키 생성(한 번)
ceb hosted keygen --private-key priv.pem --public-key pub.pem

# 서명: --private-key(Ed25519), 또는 CEB_SIGNING_PRIVATE_KEY / CEB_SIGNING_KEY
ceb hosted sign-result --result official_result.json --private-key priv.pem

# 검증: 제3자는 공개 키를 제공한다(진정하면 종료 0, 아니면 2)
ceb hosted verify-result --result official_result.json --public-key pub.pem
```

`--public-key`가 없으면 검증기는 Ed25519의 경우 임베드된 공개 키(자기 일관성만
입증), HMAC의 경우 `CEB_SIGNING_KEY`로 폴백한다. 공식 워커는 검증된 결과를
생성하는 마지막 단계로 `sign_official_result`로 자동 서명한다.

## 검증 판정 (`verify_result_file`, 스키마 `ceb.hosted.verification/v1`)

- `result_schema` / `schema_ok` — 결과 스키마가 허용 목록
  (`ceb.hosted.official_result/v2`, `/v1`, `ceb.track_b.official_result/v1`)에 있는지.
- `claims_verified` — 결과 자체의 `verified` 플래그(증명이 아니라 주장).
- `signature_algorithm` — `ed25519` / `hmac-sha256` / `null`.
- `signature_ok` / `signature_detail` — 알고리즘별 검증 결과(`verify_any`가 라우팅).
- `metadata_missing_keys` — 없는 필수 메타데이터 키.
- **`authentic`** = `schema_ok AND signature_ok AND (no metadata_missing_keys)`.

`signature_ok=False`인 경우:
- **서명되지 않음**: 진정한 것으로 결코 오인되지 않는다;
- **변조 / 잘못된 키**: `"signature MISMATCH ..."`(Ed25519는 키 불일치 시 `key_id`
  불일치도 보고);
- **잘못된 알고리즘으로 검증 시도**: 예를 들어 HMAC 결과를 공개키 검증기에
  넣으면 `"... not Ed25519"`.

## 메타데이터 블록

`build_metadata`가 조립하며 모든 필드는 항상 존재한다. 호스트에서 결정할 수
없는 필드는 생략되지 않고 명시적으로 `null`이다(예: git 트리가 아니면
`git_commit=null`, docker 미빌드면 이미지 digest=`null`). `benchmark_version`은
`ceb.__version__`(현재 `0.3.1`), `engine_jail_image_digest`는 감옥 이미지
`chess-en-bench-jail:0.4`를 가리킨다. null은 재현성 저하를 숨기지 않고 명시적
감사 신호로 드러낸다.

## 운영 노트

- **공개 키 배포는 운영자 책임이다.** 공개 키는 결과 번들이 아니라 신뢰된
  채널(웹사이트, 저장소 태그)로 게시한다.
- **비공개 키는 커밋하지 않는다.** `*.pem`은 gitignore되어 있다. 회전, 저장,
  배포는 운영자의 관심사다.
- **번들 내보내기**: `ceb hosted result export`는 공개 아티팩트와 검증 지침만
  담은 zip을 만든다(비공개 detail 없음). 검증자는 운영자 공개 키로 확인한다.
