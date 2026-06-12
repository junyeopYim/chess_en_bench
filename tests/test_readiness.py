"""Tests for the strict public-official readiness gate (v0.3.3, req 2/10)."""

from pathlib import Path

import pytest

from ceb.hosted import db as hosted_db
from ceb.hosted.eval_pack_trust import compute_eval_pack_hash
from ceb.hosted.signing import generate_keypair
import ceb.hosted.readiness as rmod
import ceb.jail.docker_engine as de

from conftest import make_official_pack

REPO_ROOT = Path(__file__).resolve().parents[1]
TINY_PACK = REPO_ROOT / "examples" / "eval_packs" / "tiny_private"


def _checks(report):
    return {c["name"]: c for c in report["checks"]}


@pytest.fixture
def mock_docker(monkeypatch):
    monkeypatch.setattr(de, "docker_available", lambda: True)
    monkeypatch.setattr(rmod, "_image_present", lambda image: True)


def _keys(tmp_path):
    generate_keypair(tmp_path / "priv.pem", tmp_path / "pub.pem")
    return str(tmp_path / "priv.pem"), str(tmp_path / "pub.pem")


def test_strict_readiness_track_a_pass(tmp_path, official_pack, mock_docker):
    priv, pub = _keys(tmp_path)
    db = hosted_db.init_db(tmp_path / "h.sqlite")
    report = rmod.readiness_check(
        db_path=str(db), eval_pack_dir=str(official_pack), public_key_path=pub,
        signing_key_path=priv, track="A",
        official_pack_hashes=[compute_eval_pack_hash(official_pack)],
        strict_public_official=True)
    assert report["schema"] == "ceb.hosted.readiness/v2"
    failed = [c["name"] for c in report["checks"] if c["required"] and not c["ok"]]
    assert report["ready"] is True, failed
    assert _checks(report)["keypair_match"]["ok"] is True


def test_strict_readiness_fails_without_pin(tmp_path, official_pack, mock_docker):
    priv, pub = _keys(tmp_path)
    report = rmod.readiness_check(
        db_path=str(hosted_db.init_db(tmp_path / "h.sqlite")),
        eval_pack_dir=str(official_pack), public_key_path=pub,
        signing_key_path=priv, track="A", strict_public_official=True)
    assert report["ready"] is False
    pinned = _checks(report)["official_pack_pinned"]
    assert pinned["ok"] is False and pinned["required"] is True


def test_strict_readiness_fails_without_public_key(tmp_path, official_pack,
                                                   mock_docker):
    priv, _ = _keys(tmp_path)
    report = rmod.readiness_check(
        db_path=str(hosted_db.init_db(tmp_path / "h.sqlite")),
        eval_pack_dir=str(official_pack), signing_key_path=priv, track="A",
        official_pack_hashes=[compute_eval_pack_hash(official_pack)],
        strict_public_official=True)
    assert report["ready"] is False
    assert _checks(report)["public_key_verify_ready"]["required"] is True
    assert _checks(report)["public_key_verify_ready"]["ok"] is False


def test_strict_readiness_fails_mismatched_keypair(tmp_path, official_pack,
                                                   mock_docker):
    generate_keypair(tmp_path / "priv.pem", tmp_path / "pub.pem")
    generate_keypair(tmp_path / "other_priv.pem", tmp_path / "other_pub.pem")
    report = rmod.readiness_check(
        db_path=str(hosted_db.init_db(tmp_path / "h.sqlite")),
        eval_pack_dir=str(official_pack),
        public_key_path=str(tmp_path / "other_pub.pem"),
        signing_key_path=str(tmp_path / "priv.pem"), track="A",
        official_pack_hashes=[compute_eval_pack_hash(official_pack)],
        strict_public_official=True)
    assert report["ready"] is False
    assert _checks(report)["keypair_match"]["ok"] is False


def test_strict_readiness_fails_with_demo_pack(tmp_path, mock_docker):
    priv, pub = _keys(tmp_path)
    report = rmod.readiness_check(
        db_path=str(hosted_db.init_db(tmp_path / "h.sqlite")),
        eval_pack_dir=str(TINY_PACK), public_key_path=pub, signing_key_path=priv,
        track="A", strict_public_official=True)
    assert report["ready"] is False
    assert _checks(report)["official_eval_pack_trusted"]["ok"] is False
    assert _checks(report)["demo_pack_rejected"]["ok"] is True


def test_strict_readiness_track_b_requires_baseline_and_wrapper(
        tmp_path, official_pack, mock_docker):
    from ceb.hosted.build_wrappers import write_demo_wrapper
    priv, pub = _keys(tmp_path)
    wrapper = write_demo_wrapper(tmp_path / "wrapper.sh")
    # No baseline hash and no wrapper hash -> both required checks fail.
    report = rmod.readiness_check(
        db_path=str(hosted_db.init_db(tmp_path / "h.sqlite")),
        eval_pack_dir=str(official_pack), public_key_path=pub,
        signing_key_path=priv, track="B", build_wrapper=str(wrapper),
        official_pack_hashes=[compute_eval_pack_hash(official_pack)],
        strict_public_official=True, root=tmp_path)
    assert report["ready"] is False
    c = _checks(report)
    assert c["build_wrapper_pinned"]["ok"] is False
    assert c["track_b_baseline_trust"]["ok"] is False


def test_strict_readiness_track_b_pass(tmp_path, official_pack, mock_docker):
    from ceb.hosted.build_wrappers import write_demo_wrapper, compute_wrapper_hash
    priv, pub = _keys(tmp_path)
    wrapper = write_demo_wrapper(tmp_path / "wrapper.sh")
    report = rmod.readiness_check(
        db_path=str(hosted_db.init_db(tmp_path / "h.sqlite")),
        eval_pack_dir=str(official_pack), public_key_path=pub,
        signing_key_path=priv, track="B", build_wrapper=str(wrapper),
        official_pack_hashes=[compute_eval_pack_hash(official_pack)],
        build_wrapper_hashes=[compute_wrapper_hash(wrapper)],
        track_b_baseline_hashes=["sha256:" + "0" * 64],
        strict_public_official=True, root=tmp_path)
    failed = [c["name"] for c in report["checks"] if c["required"] and not c["ok"]]
    assert report["ready"] is True, failed


def test_non_strict_readiness_pinning_is_warning(tmp_path, official_pack,
                                                 mock_docker):
    priv, pub = _keys(tmp_path)
    report = rmod.readiness_check(
        db_path=str(hosted_db.init_db(tmp_path / "h.sqlite")),
        eval_pack_dir=str(official_pack), public_key_path=pub,
        signing_key_path=priv, track="A", strict_public_official=False)
    # Unpinned is only a warning when not strict.
    assert _checks(report)["official_pack_pinned"]["required"] is False
    assert report["ready"] is True


def test_strict_readiness_validates_supplied_baseline(tmp_path, official_pack,
                                                      mock_docker):
    # Regression (review #6): when a baseline tree is supplied, readiness must
    # VALIDATE it against the allowlist, not trust a non-empty allowlist alone.
    from ceb.hosted.build_wrappers import write_demo_wrapper, compute_wrapper_hash
    priv, pub = _keys(tmp_path)
    base = tmp_path / "baseline"; base.mkdir(); (base / "f.cpp").write_text("x\n")
    wrapper = write_demo_wrapper(tmp_path / "wrapper.sh")
    # Allowlist a DIFFERENT hash than the supplied baseline -> not trusted.
    report = rmod.readiness_check(
        db_path=str(hosted_db.init_db(tmp_path / "h.sqlite")),
        eval_pack_dir=str(official_pack), public_key_path=pub, signing_key_path=priv,
        track="B", build_wrapper=str(wrapper), baseline_src=str(base),
        official_pack_hashes=[compute_eval_pack_hash(official_pack)],
        build_wrapper_hashes=[compute_wrapper_hash(wrapper)],
        track_b_baseline_hashes=["sha256:" + "9" * 64],
        strict_public_official=True, root=tmp_path)
    assert _checks(report)["track_b_baseline_trust"]["ok"] is False
    assert report["ready"] is False


def test_readiness_has_declaration_field(tmp_path, mock_docker):
    # Item 4: machine-readable declaration + blocking_failures.
    priv, pub = _keys(tmp_path)
    report = rmod.readiness_check(
        db_path=str(hosted_db.init_db(tmp_path / "h.sqlite")),
        eval_pack_dir=str(TINY_PACK), public_key_path=pub, signing_key_path=priv,
        track="A", strict_public_official=True)
    assert report["public_official_declaration"] == "not-ready"
    assert "official_eval_pack_trusted" in report["blocking_failures"]


def test_readiness_pass_declares_ready(tmp_path, official_pack, mock_docker):
    priv, pub = _keys(tmp_path)
    report = rmod.readiness_check(
        db_path=str(hosted_db.init_db(tmp_path / "h.sqlite")),
        eval_pack_dir=str(official_pack), public_key_path=pub, signing_key_path=priv,
        track="A", official_pack_hashes=[compute_eval_pack_hash(official_pack)],
        strict_public_official=True)
    assert report["public_official_declaration"] == "ready"
    assert report["blocking_failures"] == []


def test_non_strict_never_declares_public_official_ready(tmp_path, official_pack,
                                                         mock_docker):
    # Review #5: a non-strict pass is NOT a public-official declaration.
    priv, pub = _keys(tmp_path)
    report = rmod.readiness_check(
        db_path=str(hosted_db.init_db(tmp_path / "h.sqlite")),
        eval_pack_dir=str(official_pack), public_key_path=pub, signing_key_path=priv,
        track="A", strict_public_official=False)   # unpinned, non-strict
    assert report["ready"] is True
    assert report["public_official_declaration"] == "not-ready"


def test_strict_both_requires_both_tracks_pack(tmp_path, mock_docker):
    # Review #6: --track BOTH must validate the pack as BOTH, not Track A only.
    from ceb.hosted.build_wrappers import write_demo_wrapper, compute_wrapper_hash
    priv, pub = _keys(tmp_path)
    a_only = make_official_pack(tmp_path / "a_pack", manifest_overrides={"track": "A"})
    wrapper = write_demo_wrapper(tmp_path / "wrapper.sh")
    report = rmod.readiness_check(
        db_path=str(hosted_db.init_db(tmp_path / "h.sqlite")),
        eval_pack_dir=str(a_only), public_key_path=pub, signing_key_path=priv,
        track="BOTH", build_wrapper=str(wrapper),
        official_pack_hashes=[compute_eval_pack_hash(a_only)],
        build_wrapper_hashes=[compute_wrapper_hash(wrapper)],
        track_b_baseline_hashes=["sha256:" + "0" * 64],
        strict_public_official=True, root=tmp_path)
    assert _checks(report)["official_eval_pack_trusted"]["ok"] is False
    assert report["ready"] is False
