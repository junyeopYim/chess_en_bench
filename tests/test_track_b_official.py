"""Tests for the Track B source-build official pipeline (P1.2), using tiny
fake source trees and a fake build script (no real Stockfish)."""

import json
from pathlib import Path

import pytest

from ceb.track_b.official_pipeline import (
    run_official_track_b, TrackBPipelineError)

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ENGINE_PY = (REPO_ROOT / "examples" / "submissions"
                     / "minimal_uci_engine_python" / "engine.py")

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
