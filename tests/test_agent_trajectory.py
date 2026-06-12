"""Tests for the optional agent-trajectory schema (P1.4)."""

import pytest

from ceb.agent_trajectory import SCHEMA, attach_trajectory, normalize_trajectory


def test_normalize_keeps_known_fields_only():
    block = normalize_trajectory({
        "model_id": "claude-opus-4-8", "agent_id": "harness-1",
        "gate_attempts": 5, "chain_of_thought": "SECRET", "unknown": 1,
    })
    assert block["schema"] == SCHEMA
    assert block["model_id"] == "claude-opus-4-8"
    assert block["gate_attempts"] == 5
    assert "chain_of_thought" not in block      # private CoT is never required
    assert "unknown" not in block


def test_attach_to_result():
    result = {"run_id": "r"}
    attach_trajectory(result, {"prompt_version": "v3",
                               "source_snapshot_hash": "sha256:abc"})
    assert result["agent_trajectory"]["prompt_version"] == "v3"
    assert result["agent_trajectory"]["source_snapshot_hash"] == "sha256:abc"


def test_normalize_rejects_non_object():
    with pytest.raises(ValueError):
        normalize_trajectory(["not", "a", "dict"])
