"""FastAPI app: health, runs, leaderboard, artifacts, static dashboard.

Requires the 'server' extra:  pip install -e ".[server]"
Core gate/match/scoring never import this module.
"""

import json
import re

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse, HTMLResponse
    from fastapi.staticfiles import StaticFiles
except ImportError as exc:  # pragma: no cover - exercised only without extras
    raise ImportError(
        "FastAPI is not installed. Install server extras with:\n"
        "  pip install -e \".[server]\"") from exc

from ceb import __version__, paths
from ceb.scoring.track_a import compute_leaderboard

app = FastAPI(title="chess_en_bench", version=__version__)

_ARTIFACT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@app.get("/health")
def health():
    return {"status": "ok", "service": "chess_en_bench", "version": __version__}


@app.get("/api/runs")
def list_runs():
    runs = []
    runs_root = paths.runs_dir()
    for state_path in sorted(runs_root.glob("*/state.json")):
        try:
            runs.append(json.loads(state_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return {"runs": runs}


@app.get("/api/leaderboard")
def leaderboard(track: str = "A"):
    if track.upper() not in ("A", "B"):
        raise HTTPException(status_code=400, detail="track must be A or B")
    if track.upper() == "B":
        # Track B official evaluation is not part of v0.1; report honestly.
        return {"schema": "ceb.leaderboard/v1", "track": "B", "entries": [],
                "note": "Track B leaderboard requires the Stockfish evaluation "
                        "pipeline; see docs/track_b_stockfish_optimization.md"}
    return compute_leaderboard(paths.runs_dir(), track="A")


@app.get("/api/artifacts/{artifact_id}")
def get_artifact(artifact_id: str):
    """Resolve a flat artifact filename under artifacts/ (no path traversal)."""
    if not _ARTIFACT_ID_RE.match(artifact_id) or ".." in artifact_id:
        raise HTTPException(status_code=400, detail="bad artifact id")
    path = paths.artifacts_dir() / artifact_id
    if not path.is_file():
        raise HTTPException(status_code=404, detail="artifact not found")
    return FileResponse(path)


_static = paths.web_static_dir()
if _static.is_dir():
    app.mount("/", StaticFiles(directory=str(_static), html=True), name="static")
else:  # pragma: no cover - repo always ships web/static
    @app.get("/", response_class=HTMLResponse)
    def index_fallback():
        return "<h1>chess_en_bench</h1><p>web/static not found.</p>"
