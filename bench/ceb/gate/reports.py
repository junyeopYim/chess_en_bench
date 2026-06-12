"""Gate report structures: JSON-serializable and human-readable."""

import json
import time

STATUS_PASS = "pass"
STATUS_FAIL = "fail"
STATUS_WARN = "warn"
STATUS_SKIP = "skip"


class CheckResult:
    __slots__ = ("check_id", "name", "status", "details", "duration_ms")

    def __init__(self, check_id, name, status, details="", duration_ms=0):
        self.check_id = check_id
        self.name = name
        self.status = status
        self.details = details
        self.duration_ms = duration_ms

    def to_dict(self):
        return {
            "id": self.check_id,
            "name": self.name,
            "status": self.status,
            "details": self.details,
            "duration_ms": round(self.duration_ms, 1),
        }


class GateReport:
    def __init__(self, track, workspace, strict=False):
        self.schema = "ceb.gate.report/v1"
        self.track = track
        self.workspace = str(workspace)
        self.strict = bool(strict)
        self.started_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        self.finished_at = None
        self.checks = []

    def add(self, check):
        self.checks.append(check)

    def finish(self):
        self.finished_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")

    @property
    def passed(self):
        required = [c for c in self.checks if c.status in (STATUS_PASS, STATUS_FAIL)]
        return bool(required) and all(c.status == STATUS_PASS for c in required)

    @property
    def warnings(self):
        return [c for c in self.checks if c.status == STATUS_WARN]

    def to_dict(self):
        return {
            "schema": self.schema,
            "track": self.track,
            "workspace": self.workspace,
            "strict": self.strict,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "passed": self.passed,
            "checks": [c.to_dict() for c in self.checks],
        }

    def to_json(self, indent=2):
        return json.dumps(self.to_dict(), indent=indent)

    def human_summary(self):
        icons = {STATUS_PASS: "PASS", STATUS_FAIL: "FAIL",
                 STATUS_WARN: "WARN", STATUS_SKIP: "SKIP"}
        mode = "strict" if self.strict else "public"
        lines = ["%s gate — track %s — %s" % (mode.capitalize(), self.track,
                                              self.workspace), ""]
        for c in self.checks:
            line = "  [%s] %-22s %s" % (icons[c.status], c.check_id, c.name)
            if c.details:
                detail = c.details if len(c.details) <= 120 else c.details[:117] + "..."
                line += " — " + detail
            lines.append(line)
        lines.append("")
        lines.append("Gate result: %s" % ("PASSED" if self.passed else "FAILED"))
        if self.warnings:
            lines.append("Warnings: %d (gate still passes; see details above)"
                         % len(self.warnings))
        return "\n".join(lines)
