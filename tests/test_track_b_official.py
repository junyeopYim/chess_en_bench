"""Tests for the Track B source-build official pipeline and its hosted
integration (P0.6 / P1.2), using tiny fake source trees and a fake build
script (no real Stockfish). The verified-in-jail path is opt-in (docker)."""

import json
import os
import subprocess
from pathlib import Path

import pytest

from ceb.hosted.track_b_eval import run_hosted_track_b
from ceb.jail.docker_engine import JAIL_IMAGE
from ceb.track_b.official_pipeline import (
    run_official_track_b, TrackBPipelineError)

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ENGINE_PY = (REPO_ROOT / "examples" / "submissions"
                     / "minimal_uci_engine_python" / "engine.py")
TINY_PACK = REPO_ROOT / "examples" / "eval_packs" / "tiny_private"


def _jail_image_ready():
    import shutil
    if os.environ.get("CEB_DOCKER_TESTS") != "1" or not shutil.which("docker"):
        return False
    probe = subprocess.run(["docker", "image", "inspect", JAIL_IMAGE],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return probe.returncode == 0

# A build script that copies the bundled engine into place — stands in for
# `make -C src build` so the pipeline can be exercised without a compiler.
BUILD_SCRIPT = """#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
cat > ceb_engine <<'EOF'
#!/usr/bin/env bash
exec python3 "$(dirname "$0")/engine.py"
EOF
chmod +x ceb_engine
"""


def _fake_tree(root, search_value):
    root.mkdir(parents=True)
    (root / "src").mkdir()
    (root / "src" / "search.cpp").write_text("int margin = %d;\n" % search_value)
    (root / "ceb_build.sh").write_text(BUILD_SCRIPT)
    (root / "ceb_build.sh").chmod(0o755)
    (root / "engine.py").write_text(EXAMPLE_ENGINE_PY.read_text())


def test_official_pipeline_builds_and_scores(tmp_path):
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _fake_tree(baseline, 1)
    _fake_tree(candidate, 2)  # allowed change to src/search.cpp

    report = run_official_track_b(
        candidate_src=candidate, baseline_src=baseline,
        games=2, movetime_ms=30, max_plies=20, run_id="tb_official_test",
        runs_root=tmp_path / "runs", root=REPO_ROOT)

    assert report["schema"] == "ceb.track_b.official_result/v1"
    assert report["verified"] is False  # CLI/direct runs are diagnostic
    score = report["score"]
    assert score["games"] == 2
    assert score["delta_elo"] is not None
    lo, hi = score["delta_elo_ci95"]
    assert lo <= score["delta_elo"] <= hi
    metadata = report["metadata"]
    assert metadata["track_b"]["baseline_tree_hash"].startswith("sha256:")
    assert metadata["track_b"]["candidate_tree_hash"] != \
        metadata["track_b"]["baseline_tree_hash"]
    assert report["signature"]["status"] in ("signed", "unsigned")
    result_file = (tmp_path / "runs" / "tb_official_test"
                   / "track_b_official_1" / "official_result.json")
    assert result_file.is_file()


def test_official_pipeline_rejects_forbidden_change(tmp_path):
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _fake_tree(baseline, 1)
    _fake_tree(candidate, 1)
    # Touch a forbidden file: evaluate.cpp is out of the whitelist.
    (candidate / "src" / "evaluate.cpp").write_text("int eval = 9;\n")

    with pytest.raises(TrackBPipelineError, match="scanner"):
        run_official_track_b(
            candidate_src=candidate, baseline_src=baseline,
            games=2, movetime_ms=30, run_id="tb_reject",
            runs_root=tmp_path / "runs", root=REPO_ROOT)


def test_official_pipeline_reports_missing_build_script(tmp_path):
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _fake_tree(baseline, 1)
    _fake_tree(candidate, 2)
    (baseline / "ceb_build.sh").unlink()
    (candidate / "ceb_build.sh").unlink()
    with pytest.raises(TrackBPipelineError, match="build script"):
        run_official_track_b(
            candidate_src=candidate, baseline_src=baseline,
            games=2, movetime_ms=30, run_id="tb_nobuild",
            runs_root=tmp_path / "runs", root=REPO_ROOT)


# ----- hosted Track B (P0.6) --------------------------------------------------

def test_hosted_track_b_dev_unjailed_is_diagnostic(tmp_path):
    # Full toy pipeline (build + match) without docker via the dev escape
    # hatch: it runs end to end but is never verified.
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _fake_tree(baseline, 1)
    _fake_tree(candidate, 2)
    report, result_path = run_hosted_track_b(
        run_id="tb_hosted", candidate_src=candidate, baseline_src=baseline,
        build_script="ceb_build.sh", engine_relpath="ceb_engine",
        eval_pack_dir=None, out_dir=tmp_path / "out", engine_jail="none",
        profile="official", allow_unjailed=True, games=2, movetime_ms=30,
        max_plies=20, root=REPO_ROOT)
    assert report["verified"] is False
    assert report["verification_grade"] == "diagnostic-unjailed"
    assert report["score"]["delta_elo"] is not None
    assert result_path.is_file()


@pytest.mark.skipif(not _jail_image_ready(),
                    reason="set CEB_DOCKER_TESTS=1 with docker + jail image "
                           "built to run the verified Track B jail test")
def test_hosted_track_b_verified_in_jail(tmp_path):
    from ceb.hosted import db as hosted_db
    from ceb.hosted.track_b_eval import track_b_score, TRACK_B_RESULT_MODE

    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _fake_tree(baseline, 1)
    _fake_tree(candidate, 2)
    report, result_path = run_hosted_track_b(
        run_id="tbrun", candidate_src=candidate, baseline_src=baseline,
        build_script="ceb_build.sh", engine_relpath="ceb_engine",
        eval_pack_dir=str(TINY_PACK), out_dir=tmp_path / "out",
        engine_jail="docker", profile="official", games=2, movetime_ms=30,
        max_plies=20, root=REPO_ROOT)
    assert report["verified"] is True
    assert report["profile"] == "official"
    assert report["verification_grade"] == "verified-official"
    assert Path(result_path).is_file()

    db = hosted_db.init_db(tmp_path / "h.sqlite")
    conn = hosted_db.connect(db)
    try:
        hosted_db.create_run(conn, "tbrun", "B")
        hosted_db.add_result(
            conn, "tbrun", None, verified=True, mode=TRACK_B_RESULT_MODE,
            score=track_b_score(report), result_path=result_path,
            profile="official", verification_grade=report["verification_grade"],
            track="B")
        board = hosted_db.verified_leaderboard(conn, track="B")
    finally:
        conn.close()
    assert [e["run_id"] for e in board["entries"]] == ["tbrun"]
