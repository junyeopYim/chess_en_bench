# Result Signing

How an official result is fingerprinted, signed, and verified in v0.3.

This is an **MVP**: signing is **symmetric HMAC-SHA256** keyed by a shared
secret. Only holders of that key can verify a result. It is **not** public-key
attestation — third parties cannot independently confirm authenticity.
Asymmetric signing is future work (see "Limitations").

Implementation:
- metadata: `bench/ceb/hosted/metadata.py`
- signing: `bench/ceb/hosted/signing.py`
- verification: `bench/ceb/hosted/verifier.py`
- result producer: `bench/ceb/hosted/official_eval.py` (`run_official_eval`)

A result file uses schema `ceb.hosted.official_result/v1` and is written as the
public artifact `official_result.json`. It carries a `metadata` block and a
`signature` block.

## Metadata block

Assembled by `build_metadata`. Every field is always present; fields that
cannot be determined on the host are explicit `null`, never omitted.

| Key | Meaning | Null when |
| --- | --- | --- |
| `benchmark_version` | `ceb.__version__` (currently `0.3.0`). | never |
| `git_commit` | `git rev-parse HEAD` of the repo root. | not a git checkout / git unavailable |
| `evaluator_image_digest` | Docker image id of the evaluator image (default `chess-en-bench-evaluator:0.2`). | docker missing or image not pulled |
| `engine_jail_image_digest` | Docker image id of the engine-jail image (`chess-en-bench-jail:0.3`). | docker missing or image not built |
| `eval_pack_id` | Name of the resolved eval pack. | (official path always sets it; a non-official caller could pass `None`) |
| `eval_pack_hash` | `sha256:` over the eval-pack directory (relative paths + contents). | no `eval_pack_dir` passed |
| `opponent_pool_hash` | `sha256:` of `bench/ceb/match/opponents.py`. | never |
| `opening_suite_hash` | `sha256:` over the canonical JSON of the opening suite. | no opening suite passed |
| `hardware.cpu_model` | CPU model from `/proc/cpuinfo` or `platform.processor()`. | neither resolves |
| `hardware.cpu_cores` | Cores allotted to the run (1 under the engine jail). | never |
| `hardware.memory_limit` | Memory cap string, e.g. `"1g (engine jail)"`. | not run under the engine jail |
| `software.python` | Python version. | never |
| `software.platform` | `platform.platform()`. | never |
| `software.compiler` | First line of `g++`/`clang++ --version`. | no C++ compiler on PATH |
| `software.fastchess` | Path to `fastchess` on PATH. | fastchess not installed |
| `software.stockfish_baseline` | Pinned baseline string `"sf_18/cb3d4ee"`. | never (constant) |
| `random_seed` | Seed used (`1000 * round_number` in the official path). | a caller may pass `None` |
| `verified` | `true` only for the official worker path. | never (always bool) |

`eval_pack_hash`, `git_commit`, the image digests, `compiler`, and `fastchess`
being `null` are legitimate audit signals: a result computed without docker
images pinned, or off a non-git tree, is reproducibility-degraded and the nulls
make that explicit rather than hiding it.

## Signature block

`sign_result(result, key=None)` attaches a `signature` block in place. The key
comes from the `CEB_SIGNING_KEY` environment variable unless one is passed
explicitly.

**Signed** (key present):

```json
"signature": {
  "status": "signed",
  "algorithm": "hmac-sha256",
  "note": "symmetric HMAC; verifiable only by holders of the signing key",
  "value": "<hex digest>"
}
```

**Unsigned** (no key configured):

```json
"signature": {
  "status": "unsigned",
  "algorithm": null,
  "note": "no CEB_SIGNING_KEY configured; this result has NO cryptographic authenticity"
}
```

The unsigned block **never claims authenticity** — its note says so, and the
verifier treats it as not authentic (below). An unsigned result is still a
valid, useful result; it simply has no cryptographic provenance.

### Canonical payload

The digest is HMAC-SHA256 over `canonical_payload(result)`:

```python
body = {k: v for k, v in result.items() if k != "signature"}
json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
```

The `signature` block itself is **excluded**, keys are sorted, and separators
are compact — so the bytes are stable regardless of dict ordering or
whitespace. Verification recomputes over the same canonical bytes; any change
to the result body (or signing with a different key) yields a mismatch.

## CLI

Sign a result file in place:

```bash
CEB_SIGNING_KEY=... ceb hosted sign-result --result path/to/official_result.json
```

With no `CEB_SIGNING_KEY`, `sign-result` writes the unsigned block and prints a
reminder that unsigned results have no cryptographic authenticity.

Verify a result file (prints a JSON verdict; exit `0` if authentic, `2`
otherwise):

```bash
CEB_SIGNING_KEY=... ceb hosted verify-result --result path/to/official_result.json
```

The official worker (`ceb hosted worker run-once`) signs automatically as the
final step of producing a verified result.

## Verification verdict

`verify_result_file` (schema `ceb.hosted.verification/v1`) returns:

- `schema_ok` — result schema is `ceb.hosted.official_result/v1`.
- `claims_verified` — the result's own `verified` flag (a claim, not proof).
- `signature_ok` / `signature_detail` — from `verify_result`.
- `metadata_present` — `metadata` is a dict.
- `metadata_missing_keys` — required keys absent from `metadata`:
  `benchmark_version`, `git_commit`, `eval_pack_hash`, `opponent_pool_hash`,
  `opening_suite_hash`, `random_seed`, `verified`. (Note: required means the
  key is present; an explicit `null` value still counts as present.)
- **`authentic`** — the bottom line:

  ```
  authentic = schema_ok AND signature_ok AND (no metadata_missing_keys)
  ```

`verify_result` returns `signature_ok=False` for:
- **unsigned** results: `"unsigned result (no cryptographic authenticity)"` —
  so an unsigned result can never be mistaken for authentic;
- **no key** at verify time: `"no CEB_SIGNING_KEY configured; cannot verify"`;
- **tamper / wrong key**: `"signature MISMATCH: result was modified or signed
  with a different key"` (constant-time compare via `hmac.compare_digest`).

## Limitations (MVP)

- **Symmetric only.** HMAC authenticates to anyone who holds `CEB_SIGNING_KEY`,
  i.e. the benchmark operator. Verifiers and signers share the same secret;
  there is no separation between "can verify" and "can forge". A signed result
  proves nothing to a third party who lacks the key.
- **No public-key attestation.** Asymmetric signing (operator signs with a
  private key, anyone verifies with the published public key) is **future
  work**. Until then, treat verified results as operator-attested, not
  publicly verifiable.
- **Key management is out of scope.** The key is read from an environment
  variable; rotation, storage, and distribution are operator concerns.
