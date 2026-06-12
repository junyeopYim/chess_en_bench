"""Public result-bundle export (P1.3).

`export_result_bundle` packages a run's PUBLIC artifacts (the signed
official_result.json with its metadata + signature, feedback.json,
report.public.json) into a single zip with verification instructions. Private
and admin artifacts are never included — the bundle is what a third party
needs to independently verify an official result, and nothing more.
"""

import json
import os
import zipfile
from pathlib import Path

from ceb.sanitize import SanitizedError

SCHEMA = "ceb.hosted.result_bundle/v1"

_VERIFY_TXT = """\
chess_en_bench — public result bundle
=====================================

This bundle contains the PUBLIC artifacts of a hosted official evaluation:
the signed official_result.json (with reproducibility metadata and a signature
block), the public feedback, and any public report. No private evaluation
detail is included.

To verify authenticity yourself:

  1. Obtain the operator's Ed25519 PUBLIC key out-of-band (not from this
     bundle — the embedded public key proves only internal consistency).
  2. Run:
       ceb hosted verify-result --result official_result.json \\
           --public-key <operator_public_key.pem>
     A genuine, unmodified result reports "authentic": true. Any edit to the
     result invalidates the signature.

A result with "verified": true was produced by the official hosted worker from
a clean snapshot, a private eval pack, the docker engine jail, a passing static
scan and strict gate, and a passing public-artifact leak scan. Locally produced
(self-reported) rounds are never verified and never appear here.
"""


class ResultBundleError(SanitizedError, ValueError):
    pass


def _job_attempt_dir(result_path):
    """The job-attempt directory (store/<run>/job_<id>_attempt_<n>) that owns a
    result, derived by walking up from its result file path."""
    p = Path(result_path)
    for ancestor in p.parents:
        if ancestor.name.startswith("job_"):
            return ancestor
    return p.parent


def export_result_bundle(conn, run_id, out_zip, db_path, *,
                         include_all_public=False, release_manifest_path=None,
                         public_key_fingerprint=None):
    """Write a public result bundle zip. Returns (Path, manifest dict).

    By default the bundle contains ONLY the public artifacts of the selected
    best verified result (the one the leaderboard/API serve) — never smoke or
    older non-selected results, and never any private artifact. Pass
    include_all_public=True for a diagnostic bundle of every public artifact
    (clearly marked non-official)."""
    from ceb.hosted import db as hosted_db

    run = hosted_db.get_run(conn, run_id)
    if run is None:
        raise ResultBundleError("run %r not found" % run_id)
    rows = conn.execute(
        "SELECT * FROM artifacts WHERE run_id = ? AND visibility = 'public'",
        (run_id,)).fetchall()

    store = hosted_db.store_dir(db_path).resolve()
    best = hosted_db.select_best_verified_result(conn, run_id)

    if include_all_public:
        if not rows:
            raise ResultBundleError("run %r has no public artifacts to export"
                                    % run_id)
        selected_dir = None
    else:
        if best is None:
            raise ResultBundleError(
                "run %r has no verified result to export; use "
                "--include-all-public for a diagnostic (non-official) bundle"
                % run_id)
        selected_dir = str(_job_attempt_dir(best["result_path"]).resolve())

    # Validate the release manifest BEFORE opening the zip (so a bad path/JSON
    # never leaves a partial bundle on disk).
    rel = None
    if release_manifest_path:
        if not os.path.isfile(release_manifest_path):
            raise ResultBundleError(
                "release manifest not found",
                "release manifest not found: %s" % release_manifest_path)
        try:
            with open(release_manifest_path, encoding="utf-8") as fh:
                rel = json.load(fh)
        except (OSError, ValueError) as exc:
            raise ResultBundleError(
                "release manifest is not valid JSON",
                "release manifest read error: %s" % exc)
        if not isinstance(rel, dict):
            raise ResultBundleError("release manifest must be a JSON object")

    out_zip = Path(out_zip)
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    files = []
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for row in rows:
            real = os.path.realpath(row["path"])
            # Defense in depth: never package anything outside the object store.
            if not real.startswith(str(store) + os.sep) or not os.path.isfile(real):
                continue
            # Selected-only: keep only artifacts under the selected result's
            # job-attempt directory.
            if selected_dir is not None and not real.startswith(selected_dir + os.sep):
                continue
            arcname = Path(real).relative_to(store).as_posix()
            zf.write(real, arcname)
            files.append(arcname)

        # Optionally include the operator's public release manifest (secret-free)
        # so a third party can match the result to its official season.
        manifest_included = False
        fingerprint = public_key_fingerprint
        if rel is not None:
            zf.writestr("release_manifest.json", json.dumps(rel, indent=2) + "\n")
            manifest_included = True
            fingerprint = fingerprint or rel.get("operator_public_key_fingerprint")

        manifest = {
            "schema": SCHEMA,
            "version": "v0.3.5",
            "run_id": run_id,
            "track": run["track"],
            "verified": bool(best),
            "official": bool(best) and not include_all_public,
            "selected_only": not include_all_public,
            "selected_result_id": best["id"] if best else None,
            "selected_mode": best["mode"] if best else None,
            "selected_grade": best["verification_grade"] if best else None,
            "selected_score": best["score"] if best else None,
            "release_manifest_included": manifest_included,
            "operator_public_key_fingerprint": fingerprint,
            "files": files,
            "note": "public artifacts only; verify with the operator's public key",
        }
        zf.writestr("bundle_manifest.json", json.dumps(manifest, indent=2) + "\n")
        verify_txt = _VERIFY_TXT
        if fingerprint:
            verify_txt += ("\nThe operator public key fingerprint for this "
                           "season is:\n  %s\nVerify the published public key "
                           "matches this fingerprint before trusting it.\n"
                           % fingerprint)
        if manifest_included:
            verify_txt += (
                "\nrelease_manifest.json pins this season's anchors (pack hash, "
                "key fingerprint, image digests). When the operator signs it, "
                "verify its authenticity with the OUT-OF-BAND public key:\n"
                "  ceb hosted release-manifest verify \\\n"
                "      --manifest release_manifest.json \\\n"
                "      --public-key <operator_public_key.pem>\n"
                "An unsigned manifest is readable but not authentic.\n")
        zf.writestr("VERIFY.txt", verify_txt)
    extra = ["bundle_manifest.json", "VERIFY.txt"]
    if manifest_included:
        extra.append("release_manifest.json")
    manifest["files"] = files + extra
    return out_zip, manifest
