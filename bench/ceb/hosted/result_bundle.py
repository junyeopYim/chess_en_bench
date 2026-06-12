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


def export_result_bundle(conn, run_id, out_zip, db_path):
    """Write a public result bundle zip. Returns (Path, manifest dict)."""
    from ceb.hosted import db as hosted_db

    run = hosted_db.get_run(conn, run_id)
    if run is None:
        raise ResultBundleError("run %r not found" % run_id)
    rows = conn.execute(
        "SELECT * FROM artifacts WHERE run_id = ? AND visibility = 'public'",
        (run_id,)).fetchall()
    if not rows:
        raise ResultBundleError("run %r has no public artifacts to export"
                                % run_id)

    store = hosted_db.store_dir(db_path).resolve()
    best = hosted_db.select_best_verified_result(conn, run_id)

    out_zip = Path(out_zip)
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    files = []
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for row in rows:
            real = os.path.realpath(row["path"])
            # Defense in depth: never package anything outside the object store.
            if not real.startswith(str(store) + os.sep) or not os.path.isfile(real):
                continue
            arcname = Path(real).relative_to(store).as_posix()
            zf.write(real, arcname)
            files.append(arcname)
        manifest = {
            "schema": SCHEMA,
            "run_id": run_id,
            "track": run["track"],
            "verified": bool(best),
            "selected_result_id": best["id"] if best else None,
            "selected_mode": best["mode"] if best else None,
            "selected_score": best["score"] if best else None,
            "files": files,
            "note": "public artifacts only; verify with the operator's public key",
        }
        zf.writestr("bundle_manifest.json", json.dumps(manifest, indent=2) + "\n")
        zf.writestr("VERIFY.txt", _VERIFY_TXT)
    manifest["files"] = files + ["bundle_manifest.json", "VERIFY.txt"]
    return out_zip, manifest
