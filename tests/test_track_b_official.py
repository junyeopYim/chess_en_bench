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


# ----- Track B build isolation (C) --------------------------------------------

def test_validate_build_wrapper(tmp_path):
    from ceb.hosted.build_wrappers import (
        validate_build_wrapper, write_demo_wrapper, BuildWrapperError)

    cand = tmp_path / "cand"
    cand.mkdir()
    with pytest.raises(BuildWrapperError, match="trusted"):
        validate_build_wrapper(None)
    with pytest.raises(BuildWrapperError, match="not found"):
        validate_build_wrapper(tmp_path / "nope.sh")
    inside = write_demo_wrapper(cand / "build.sh")
    with pytest.raises(BuildWrapperError, match="OUTSIDE"):
        validate_build_wrapper(inside, candidate_src=cand)
    outside = write_demo_wrapper(tmp_path / "wrapper.sh")
    assert validate_build_wrapper(outside, candidate_src=cand) == outside.resolve()


def test_run_official_track_b_refuses_verified_host_build(tmp_path):
    # Defense: a verified Track B result must NOT come from a host build.
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _fake_tree(baseline, 1)
    _fake_tree(candidate, 2)
    with pytest.raises(TrackBPipelineError, match="build jail"):
        run_official_track_b(
            candidate_src=candidate, baseline_src=baseline, verified=True,
            build_isolation="host", run_id="x", runs_root=tmp_path / "runs",
            root=REPO_ROOT)


def test_run_official_track_b_validates_wrapper_outside_tree(tmp_path):
    # Defense in depth (regression): run_official_track_b itself rejects a build
    # wrapper that lives inside the candidate tree, not only the hosted entry.
    # The wrapper points at an existing whitelisted file (so the diff scan
    # passes) inside the candidate tree.
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _fake_tree(baseline, 1)
    _fake_tree(candidate, 2)
    inside = candidate / "src" / "search.cpp"   # exists, inside the tree
    with pytest.raises(TrackBPipelineError, match="wrapper"):
        run_official_track_b(
            candidate_src=candidate, baseline_src=baseline, verified=True,
            build_isolation="jail", build_wrapper=str(inside),
            eval_pack_dir=str(TINY_PACK), run_id="x",
            runs_root=tmp_path / "runs", root=REPO_ROOT)


def test_run_official_track_b_verified_requires_pack_for_leak_scan(tmp_path):
    # Regression: a verified result must not be promoted without a leak scan;
    # so verified requires an eval pack.
    from ceb.hosted.build_wrappers import write_demo_wrapper
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _fake_tree(baseline, 1)
    _fake_tree(candidate, 2)
    wrapper = write_demo_wrapper(tmp_path / "wrapper.sh")
    with pytest.raises(TrackBPipelineError, match="leak-scanned|eval pack"):
        run_official_track_b(
            candidate_src=candidate, baseline_src=baseline, verified=True,
            build_isolation="jail", build_wrapper=str(wrapper),
            eval_pack_dir=None, run_id="x", runs_root=tmp_path / "runs",
            root=REPO_ROOT)


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
    from ceb.hosted.build_wrappers import write_demo_wrapper
    from ceb.hosted.signing import generate_keypair
    from ceb.hosted.track_b_eval import track_b_score, TRACK_B_RESULT_MODE
    from conftest import make_official_pack

    from ceb.hosted.eval_pack_trust import compute_eval_pack_hash
    from ceb.hosted.build_wrappers import compute_wrapper_hash
    from ceb.hosted.metadata import hash_directory
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _fake_tree(baseline, 1)
    _fake_tree(candidate, 2)
    pack = make_official_pack(tmp_path / "offpack")          # trusted (A)
    wrapper = write_demo_wrapper(tmp_path / "wrapper.sh")    # outside trees (C)
    generate_keypair(tmp_path / "priv.pem", tmp_path / "pub.pem")  # Ed25519 (B)
    import os
    os.environ["CEB_SIGNING_PRIVATE_KEY"] = str(tmp_path / "priv.pem")
    try:
        report, result_path = run_hosted_track_b(
            run_id="tbrun", candidate_src=candidate, baseline_src=baseline,
            build_script="ceb_build.sh", engine_relpath="ceb_engine",
            eval_pack_dir=str(pack), out_dir=tmp_path / "out",
            engine_jail="docker", profile="official", build_wrapper=str(wrapper),
            official_pack_hashes=[compute_eval_pack_hash(pack)],          # pinned (1)
            track_b_baseline_hashes=[hash_directory(baseline)],          # trusted baseline (3)
            build_wrapper_hashes=[compute_wrapper_hash(wrapper)],        # pinned wrapper (4)
            games=2, movetime_ms=30, max_plies=20, root=REPO_ROOT)
    finally:
        os.environ.pop("CEB_SIGNING_PRIVATE_KEY", None)
    assert report["verified"] is True
    assert report["profile"] == "official"
    assert report["verification_grade"] == "verified-official"
    assert report["signature"]["algorithm"] == "ed25519"
    assert report["build_isolation"] == "jail"
    tb = report["metadata"]["track_b"]
    assert tb["baseline_trusted"] is True and tb["baseline_trust_mode"] == "hash"
    assert tb["build_wrapper_trusted"] is True
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


# ----- v0.3.3 trust anchors ---------------------------------------------------

def test_baseline_trust_hash_mode(tmp_path):
    from ceb.track_b.baseline_trust import validate_track_b_baseline
    from ceb.hosted.metadata import hash_directory
    base = tmp_path / "base"
    base.mkdir()
    (base / "f.cpp").write_text("int x;\n")
    rep = validate_track_b_baseline(base, root=REPO_ROOT,
                                    allowed_hashes=[hash_directory(base)])
    assert rep["baseline_trusted"] is True
    assert rep["baseline_trust_mode"] == "hash"


def test_baseline_trust_toy_and_untrusted(tmp_path):
    from ceb.track_b.baseline_trust import (
        validate_track_b_baseline, BaselineTrustError)
    base = tmp_path / "base"
    base.mkdir()
    (base / "f.cpp").write_text("int x;\n")
    toy = validate_track_b_baseline(base, root=REPO_ROOT, allow_toy=True)
    assert toy["baseline_trusted"] is False and toy["baseline_trust_mode"] == "toy"
    with pytest.raises(BaselineTrustError):
        validate_track_b_baseline(base, root=REPO_ROOT)


def test_baseline_trust_stockfish_lock_mode(tmp_path, monkeypatch):
    import subprocess
    import ceb.track_b.baseline_trust as bt
    base = tmp_path / "sf"
    base.mkdir()
    (base / "a.cpp").write_text("int x;\n")
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e"}
    import os
    e = {**os.environ, **env}
    subprocess.run(["git", "init", "-q", str(base)], check=True)
    subprocess.run(["git", "-C", str(base), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(base), "commit", "-q", "-m", "x"],
                   check=True, env=e)
    head = subprocess.run(["git", "-C", str(base), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    monkeypatch.setattr(bt, "load_lock", lambda root=None: {
        "commit": head[:7], "tag": "sf_18", "release": "Stockfish 18"})
    rep = bt.validate_track_b_baseline(base, root=REPO_ROOT, allow_toy=True)
    assert rep["baseline_trusted"] is True
    assert rep["baseline_trust_mode"] == "stockfish-lock"
    assert rep["stockfish_lock"]["tag"] == "sf_18"


def test_validate_build_output(tmp_path):
    import os
    from ceb.track_b.build_jail import validate_build_output, BuildJailError
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(BuildJailError, match="regular engine"):
        validate_build_output(out, "engine")
    (out / "engine").write_text("#!/bin/sh\n")
    (out / "engine").chmod(0o755)
    assert validate_build_output(out, "engine").name == "engine"
    os.symlink("/etc/passwd", out / "link")
    with pytest.raises(BuildJailError, match="symlink"):
        validate_build_output(out, "engine")
    os.remove(out / "link")
    with pytest.raises(BuildJailError, match="bytes"):
        validate_build_output(out, "engine", max_bytes=1)


def test_bench_sanity_unsupported(tmp_path):
    from ceb.track_b.bench_sanity import run_bench_sanity
    eng = tmp_path / "e.sh"
    eng.write_text("#!/bin/sh\nwhile read line; do :; done\n")
    eng.chmod(0o755)
    rep = run_bench_sanity([str(eng)], [str(eng)], timeout_s=5)
    assert rep["supported"] is False
    assert rep["passed"] is True          # unsupported is not a failure


def test_bench_sanity_nps_threshold(monkeypatch):
    from ceb.track_b import bench_sanity
    monkeypatch.setattr(bench_sanity, "run_bench", lambda cmd, **kw: {
        "supported": True, "nodes": 1000, "nps": int(cmd[0]),
        "output_hash": "sha256:x"})
    rep = bench_sanity.run_bench_sanity(["1000000"], ["100000"], min_nps_ratio=0.5)
    assert rep["supported"] is True
    assert rep["nps_ratio"] == 0.1
    assert rep["passed"] is False         # 0.1 < 0.5


def test_hosted_track_b_trust_gates(tmp_path, monkeypatch):
    # Exercise the verified Track B trust gates without docker by stubbing the
    # actual build+match (run_official_track_b).
    import os
    import ceb.hosted.track_b_eval as tbe
    from ceb.hosted.signing import generate_keypair
    from ceb.hosted.eval_pack_trust import compute_eval_pack_hash
    from ceb.hosted.build_wrappers import write_demo_wrapper, compute_wrapper_hash
    from ceb.hosted.metadata import hash_directory
    from conftest import make_official_pack

    captured = {}

    def fake_official(**kw):
        captured.clear()
        captured.update(kw)
        return {"verified": kw["verified"], "profile": kw["profile"],
                "verification_grade": kw["verification_grade"],
                "score": {"final_delta_elo": 0.0},
                "signature": {"algorithm": "ed25519" if kw["verified"] else None},
                "metadata": {"track_b": {}}}

    monkeypatch.setattr(tbe, "run_official_track_b", fake_official)
    base = tmp_path / "baseline"
    cand = tmp_path / "candidate"
    _fake_tree(base, 1)
    _fake_tree(cand, 2)
    pack = make_official_pack(tmp_path / "pack")
    wrapper = write_demo_wrapper(tmp_path / "wrapper.sh")
    generate_keypair(tmp_path / "priv.pem", tmp_path / "pub.pem")
    monkeypatch.setenv("CEB_SIGNING_PRIVATE_KEY", str(tmp_path / "priv.pem"))

    base_kwargs = dict(
        run_id="g", candidate_src=cand, baseline_src=base,
        build_script="ceb_build.sh", engine_relpath="ceb_engine",
        eval_pack_dir=str(pack), out_dir=tmp_path / "out", engine_jail="docker",
        profile="official", build_wrapper=str(wrapper), root=REPO_ROOT)
    pins = dict(official_pack_hashes=[compute_eval_pack_hash(pack)],
                track_b_baseline_hashes=[hash_directory(base)],
                build_wrapper_hashes=[compute_wrapper_hash(wrapper)])

    # All anchors pinned -> verified.
    tbe.run_hosted_track_b(**base_kwargs, **pins)
    assert captured["verified"] is True

    # Unpinned wrapper, no dev flag -> hard fail.
    no_wrap = dict(pins); no_wrap["build_wrapper_hashes"] = None
    with pytest.raises(tbe.TrackBPipelineError, match="build wrapper hash"):
        tbe.run_hosted_track_b(**base_kwargs, **no_wrap)

    # Unpinned wrapper + dev flag -> diagnostic-untrusted-wrapper.
    tbe.run_hosted_track_b(**base_kwargs, **no_wrap, allow_unpinned_wrapper=True)
    assert captured["verified"] is False
    assert captured["verification_grade"] == "diagnostic-untrusted-wrapper"

    # Untrusted baseline + dev flag -> diagnostic-untrusted-baseline.
    no_base = dict(pins); no_base["track_b_baseline_hashes"] = None
    tbe.run_hosted_track_b(**base_kwargs, **no_base, allow_toy_baseline=True)
    assert captured["verified"] is False
    assert captured["verification_grade"] == "diagnostic-untrusted-baseline"

    # Unpinned pack + dev flag -> diagnostic-unpinned-pack.
    no_pack = dict(pins); no_pack["official_pack_hashes"] = None
    tbe.run_hosted_track_b(**base_kwargs, **no_pack, allow_unpinned_pack=True)
    assert captured["verified"] is False
    assert captured["verification_grade"] == "diagnostic-unpinned-pack"


# ----- v0.3.3 security-review regressions -------------------------------------

def test_downgraded_run_without_wrapper_is_diagnostic_not_hard_fail(tmp_path,
                                                                     monkeypatch):
    # Regression (review #1): a run already downgraded by an earlier anchor and
    # with NO build wrapper must produce a diagnostic (host build), not fail.
    import ceb.hosted.track_b_eval as tbe
    from ceb.hosted.signing import generate_keypair
    from ceb.hosted.eval_pack_trust import compute_eval_pack_hash
    from conftest import make_official_pack

    captured = {}

    def fake_official(**kw):
        captured.clear(); captured.update(kw)
        return {"verified": kw["verified"], "profile": kw["profile"],
                "verification_grade": kw["verification_grade"],
                "score": {"final_delta_elo": 0.0},
                "signature": {"algorithm": None}, "metadata": {"track_b": {}}}

    monkeypatch.setattr(tbe, "run_official_track_b", fake_official)
    base = tmp_path / "baseline"; cand = tmp_path / "candidate"
    _fake_tree(base, 1); _fake_tree(cand, 2)
    pack = make_official_pack(tmp_path / "pack")
    generate_keypair(tmp_path / "priv.pem", tmp_path / "pub.pem")
    monkeypatch.setenv("CEB_SIGNING_PRIVATE_KEY", str(tmp_path / "priv.pem"))

    # toy baseline (downgrade) + NO wrapper at all.
    tbe.run_hosted_track_b(
        run_id="g", candidate_src=cand, baseline_src=base,
        build_script="ceb_build.sh", engine_relpath="ceb_engine",
        eval_pack_dir=str(pack), out_dir=tmp_path / "out", engine_jail="docker",
        profile="official", build_wrapper=None,
        official_pack_hashes=[compute_eval_pack_hash(pack)],
        allow_toy_baseline=True, root=REPO_ROOT)
    assert captured["verified"] is False
    assert captured["verification_grade"] == "diagnostic-untrusted-baseline"
    assert captured["build_isolation"] == "host"   # fell back, did not hard-fail


def test_baseline_lock_does_not_match_short_head_prefix(tmp_path, monkeypatch):
    # Regression (review #3): a short HEAD that is a prefix of the lock commit
    # must NOT be accepted as a stockfish-lock match.
    import subprocess, os
    import ceb.track_b.baseline_trust as bt
    base = tmp_path / "sf"; base.mkdir(); (base / "a.cpp").write_text("x\n")
    e = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e",
         "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e"}
    subprocess.run(["git", "init", "-q", str(base)], check=True)
    subprocess.run(["git", "-C", str(base), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(base), "commit", "-q", "-m", "x"], check=True, env=e)
    head = subprocess.run(["git", "-C", str(base), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    # Lock commit = head + extra chars (so head is a prefix of the lock commit).
    monkeypatch.setattr(bt, "load_lock", lambda root=None: {
        "commit": head + "abc", "tag": "sf", "release": "x"})
    with pytest.raises(bt.BaselineTrustError):
        bt.validate_track_b_baseline(base, root=REPO_ROOT)


def test_bench_candidate_suppressing_nps_fails(monkeypatch):
    # Regression (review #4): baseline supports bench, candidate suppresses its
    # NPS -> must fail, not silently pass.
    from ceb.track_b import bench_sanity
    monkeypatch.setattr(bench_sanity, "run_bench", lambda cmd, **kw:
                        {"supported": True, "nodes": 1, "nps": 1_000_000,
                         "output_hash": "sha256:x"} if cmd[0] == "base"
                        else {"supported": False, "nodes": None, "nps": None,
                              "output_hash": None})
    rep = bench_sanity.run_bench_sanity(["base"], ["cand"])
    assert rep["supported"] is True              # baseline is the reference
    assert rep["candidate_bench_missing"] is True
    assert rep["passed"] is False
