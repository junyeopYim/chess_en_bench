"""Optional agent-trajectory schema (P1.4).

A lightweight, OPTIONAL record describing how an agent produced a submission,
for provenance and analysis. It never requires a private chain of thought —
only coarse, auditable metadata an agent or operator can attach to a result:

    model_id              model identifier (e.g. "claude-opus-4-8")
    agent_id              harness/agent identifier
    prompt_version        version of the task prompt used
    tool_budget           tool-call budget granted
    gate_attempts         number of public-gate attempts
    round_attempts        number of official rounds attempted
    command_log_hash      sha256 of the agent's command log (content withheld)
    source_snapshot_hash  tree hash of the submitted snapshot

All fields are optional; unknown fields are dropped. attach_trajectory records
a normalized block under result["agent_trajectory"].
"""

SCHEMA = "ceb.agent.trajectory/v1"

FIELDS = (
    "model_id", "agent_id", "prompt_version", "tool_budget",
    "gate_attempts", "round_attempts", "command_log_hash",
    "source_snapshot_hash",
)


def normalize_trajectory(payload):
    """Return a normalized trajectory dict (schema + known fields only)."""
    if not isinstance(payload, dict):
        raise ValueError("agent trajectory must be a JSON object")
    block = {"schema": SCHEMA}
    for field in FIELDS:
        if payload.get(field) is not None:
            block[field] = payload[field]
    return block


def attach_trajectory(result, payload):
    """Attach a normalized trajectory block to a result dict (in place)."""
    result["agent_trajectory"] = normalize_trajectory(payload)
    return result
