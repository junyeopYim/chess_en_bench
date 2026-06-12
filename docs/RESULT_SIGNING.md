# 결과 서명 (Result Signing)

공식 결과가 어떻게 지문화(fingerprint)되고, 서명되고, 검증되는지를 다룬다.

공식 권장 알고리즘은 **Ed25519 비대칭 서명**이다. 운영자는 비공개 키로
서명하고, **누구나** 게시된 공개 키로 진정성을 독립적으로 검증할 수 있다. 레거시
대칭 **HMAC-SHA256**(공유 비밀 `CEB_SIGNING_KEY`로 키 지정)은 운영자 내부 진단
용도로만 유지된다. 두 알고리즘은 서명 블록의 `algorithm` 필드로 명시적으로
구분되며 서로 혼동되지 않는다(공개키 검증기는 HMAC 결과를 받아들이지 않고, 그
반대도 마찬가지다).

**공개 공식(verified) 결과는 반드시 Ed25519로 서명되어야 한다.** HMAC 결과는
공개 공식 verified가 **결코** 될 수 없으며 레거시/진단으로만 남는다. 검증 가능
프로필이 Ed25519 키 없이 돌면 평가 자체가 거부되거나(아래 "verified의 Ed25519
필수 규칙"), `--dev-allow-unsigned`로 강제 다운그레이드된 진단 결과
(verified=false)만 나온다.

구현:
- 메타데이터: `bench/ceb/hosted/metadata.py`
- 서명/키 생성/검증: `bench/ceb/hosted/signing.py`
- 검증 판정: `bench/ceb/hosted/verifier.py`
- 결과 생성기(verified의 Ed25519 강제): `bench/ceb/hosted/official_eval.py`
  (`run_official_eval`, Track A), `bench/ceb/hosted/track_b_eval.py`
  (`run_hosted_track_b`, Track B)

결과 파일은 스키마 `ceb.hosted.official_result/v2`(레거시 `/v1`도 검증 가능)를
사용하며 공개 아티팩트 `official_result.json`으로 기록된다. 이는 `metadata`
블록과 `signature` 블록을 담는다.

## 알고리즘 선택 (`sign_official_result`)

`sign_official_result(result, private_key_path=...)`는 구성된 가장 강력한
알고리즘으로 서명한다:

1. Ed25519 비공개 키 경로가 잡히면(`private_key_path=` 인자 → 즉 워커의
   `--signing-key`, 없으면 `CEB_SIGNING_PRIVATE_KEY`) → **Ed25519**.
2. 아니고 `CEB_SIGNING_KEY`(HMAC 비밀)가 설정되면 → **HMAC-SHA256**(레거시).
3. 둘 다 없으면 → **서명되지 않음**(`unsigned`).

서명되지 않은 결과는 **결코 진정성을 주장하지 않으며**, 검증기는 이를 진정하지
않은 것으로 취급한다. "마법 같은 verified"는 없다.

## verified의 Ed25519 필수 규칙 (public_official_signing)

공개 공식 verified 결과는 반드시 Ed25519로 서명된다 — HMAC도 unsigned도 안 된다.
이는 생성과 검증 양쪽에서 강제된다.

**생성 측** (`official_eval.py`의 `run_official_eval`, `track_b_eval.py`의
`run_hosted_track_b`): 검증 가능 프로필이 verified가 되려면 평가 *전에* Ed25519
키가 있어야 한다. `ed25519_private_key_path(explicit_path=signing_key_path)`로
`--signing-key`(없으면 `CEB_SIGNING_PRIVATE_KEY`)를 확인하고:

- 키가 없으면 → 평가를 시작하지 않고 **거부**한다("requires an Ed25519 signing
  key (set `CEB_SIGNING_PRIVATE_KEY` or pass `--signing-key`); HMAC is not
  accepted ..."). HMAC만 구성된 환경도 verified가 될 수 없다.
- `--dev-allow-unsigned`가 있으면 → `verified=false`로 강제 다운그레이드하고
  등급을 `diagnostic-unsigned`로 매긴다(리더보드에 오르지 않음).

서명 직후 심층 방어로 한 번 더 확인한다: verified 결과의
`signature.algorithm != "ed25519"`이면 내부 오류로 보고 거부한다. (진단
CLI 경로인 `ceb track-b official run`은 호스트 빌드를 유지하므로 항상
`verified=false`이며 이 규칙에 닿지 않는다.)

**검증 측** (`verify_result_file`): 결과가 `verified`를 주장하는데 서명이
Ed25519가 아니면 판정 필드 `public_official_signing=false`가 되고 `authentic`은
거짓이 된다(`claims_verified`가 아닌 결과에는 이 게이트가 적용되지 않음).

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
입증), HMAC의 경우 `CEB_SIGNING_KEY`로 폴백한다.

공식 워커는 verified 결과의 마지막 단계로 자동 서명한다. 워커에 Ed25519 키를
주는 경로는 `ceb hosted worker run-once --signing-key <ed25519.pem>`(없으면
`CEB_SIGNING_PRIVATE_KEY`)이며, 이 키 없이는 검증 가능 프로필이 verified를 낼 수
없다("verified의 Ed25519 필수 규칙" 참조). `--dev-allow-unsigned`는 개발용
다운그레이드 플래그다.

## 검증 판정 (`verify_result_file`, 스키마 `ceb.hosted.verification/v1`)

- `result_schema` / `schema_ok` — 결과 스키마가 허용 목록
  (`ceb.hosted.official_result/v2`, `/v1`, `ceb.track_b.official_result/v1`)에 있는지.
- `claims_verified` — 결과 자체의 `verified` 플래그(증명이 아니라 주장).
- `signature_algorithm` — `ed25519` / `hmac-sha256` / `null`.
- `signature_ok` / `signature_detail` — 알고리즘별 검증 결과(`verify_any`가 라우팅).
- `signature_trust` — 무엇으로 검증했는가: `supplied-public-key`(대역 외 공개
  키로 검증), `embedded-self-described`(결과 자신의 임베드 키로만 검증 — 자기
  일관성일 뿐 진정성 아님), `operator-hmac-key`(HMAC), `none`(미서명/미상).
- `public_official_signing` — verified를 주장하는 결과가 Ed25519로 서명되었는가.
  HMAC/unsigned verified 결과는 여기서 `false`가 되어 `authentic`을 막는다.
  `verified`를 주장하지 않는 결과에는 항상 `true`.
- `metadata_missing_keys` — 없는 필수 메타데이터 키.
- **`authentic`** = `schema_ok AND signature_ok AND trusted AND
  public_official_signing AND (no metadata_missing_keys)`. 여기서 `trusted`는
  **신뢰된 키로 검증되었는지**다: Ed25519는 대역 외 공개 키를 제공해야 하고
  (임베드 키만으로는 `authentic=false`), HMAC은 운영자 비밀을 보유해야 한다.

`signature_ok=False`인 경우:
- **서명되지 않음**: 진정한 것으로 결코 오인되지 않는다;
- **변조 / 잘못된 키**: `"signature MISMATCH ..."`(Ed25519는 키 불일치 시 `key_id`
  불일치도 보고);
- **잘못된 알고리즘으로 검증 시도**: 예를 들어 HMAC 결과를 공개키 검증기에
  넣으면 `"... not Ed25519"`.

검증기 `authentic`은 **공급된 대역 외 공개 키**를 요구한다 — 임베드 키만으로
통과하면 `signature_trust="embedded-self-described"`이고 `authentic=false`다.
공격자가 자기 키로 위조 결과에 서명하고 그 공개 키를 임베드할 수 있기 때문이다.
진짜 판정을 보려면 운영자가 신뢰 채널로 게시한 공개 키를 `--public-key`로 준다.

## 메타데이터 블록

`build_metadata`가 조립하며 모든 필드는 항상 존재한다. 호스트에서 결정할 수
없는 필드는 생략되지 않고 명시적으로 `null`이다(예: git 트리가 아니면
`git_commit=null`, docker 미빌드면 이미지 digest=`null`). `benchmark_version`은
`ceb.__version__`(현재 `0.3.2`), `engine_jail_image_digest`는 감옥 이미지
`chess-en-bench-jail:0.4`를 가리킨다. null은 재현성 저하를 숨기지 않고 명시적
감사 신호로 드러낸다.

## 운영 노트

- **공개 키 배포는 운영자 책임이다.** 공개 키는 결과 번들이 아니라 신뢰된
  채널(웹사이트, 저장소 태그)로 게시한다.
- **비공개 키는 커밋하지 않는다.** `*.pem`은 gitignore되어 있다. 회전, 저장,
  배포는 운영자의 관심사다.
- **번들 내보내기**: `ceb hosted result export`는 공개 아티팩트와 검증 지침만
  담은 zip을 만든다(비공개 detail 없음). 검증자는 운영자 공개 키로 확인한다.
