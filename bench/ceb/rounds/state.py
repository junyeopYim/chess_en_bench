"""Per-run state persisted at runs/<run_id>/state.json.

Tracks gate status, official round budget, and the round trajectory.
Gate attempts are unlimited and never consume budget; only official
(non-quick) rounds do.
"""

import json
import time
from pathlib import Path


class RunState:
    SCHEMA = "ceb.run.state/v1"

    def __init__(self, run_id, track="A", workspace=None, budget_total=3):
        self.run_id = run_id
        self.track = track
        self.workspace = str(workspace) if workspace else None
        self.budget_total = budget_total
        self.budget_used = 0
        self.gate = {"passed": False, "at": None, "attempts": 0, "report_path": None}
        self.rounds = []  # [{round, mode, started_at, report_path, score}]

    # ----- persistence -------------------------------------------------------

    @classmethod
    def path_for(cls, runs_root, run_id):
        return Path(runs_root) / run_id / "state.json"

    @classmethod
    def load_or_create(cls, runs_root, run_id, track="A", workspace=None,
                       budget_total=3):
        path = cls.path_for(runs_root, run_id)
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            state = cls(data["run_id"], data.get("track", track),
                        data.get("workspace"), data.get("budget_total", budget_total))
            state.budget_used = data.get("budget_used", 0)
            state.gate = data.get("gate", state.gate)
            state.rounds = data.get("rounds", [])
            if workspace and not state.workspace:
                state.workspace = str(workspace)
            return state
        state = cls(run_id, track, workspace, budget_total)
        state.save(runs_root)
        return state

    def save(self, runs_root):
        path = self.path_for(runs_root, self.run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")
        return path

    def to_dict(self):
        return {
            "schema": self.SCHEMA,
            "run_id": self.run_id,
            "track": self.track,
            "workspace": self.workspace,
            "budget_total": self.budget_total,
            "budget_used": self.budget_used,
            "budget_remaining": self.budget_remaining,
            "gate": self.gate,
            "rounds": self.rounds,
        }

    # ----- transitions ---------------------------------------------------------

    @property
    def budget_remaining(self):
        return max(0, self.budget_total - self.budget_used)

    def record_gate(self, passed, report_path=None):
        self.gate["attempts"] = self.gate.get("attempts", 0) + 1
        self.gate["passed"] = bool(passed)
        self.gate["at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        if report_path:
            self.gate["report_path"] = str(report_path)

    def can_start_round(self, official):
        if not self.gate.get("passed"):
            return False, "gate has not passed; run `ceb gate run` first"
        if official and self.budget_remaining <= 0:
            return False, ("official round budget exhausted "
                           "(%d/%d used)" % (self.budget_used, self.budget_total))
        return True, ""

    def record_round(self, round_number, mode, report_path, score):
        # "official" is the legacy v0.2 name for official_round records.
        if mode in ("official", "official_round"):
            self.budget_used += 1
        self.rounds.append({
            "round": round_number,
            "mode": mode,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "report_path": str(report_path),
            "score": score,
        })

    def best_score(self):
        scores = [r["score"] for r in self.rounds if r.get("score") is not None]
        return max(scores) if scores else None
