"""ceb — chess_en_bench command-line interface.

    ceb doctor
    ceb workspace prepare --track A --run-id demo
    ceb gate run --track A --workspace <dir> [--strict] [--sandbox docker]
    ceb round run --track A --workspace <dir> --round 1 [--quick] [--sandbox docker]
    ceb leaderboard compute --track A --results runs [--include-quick]
    ceb server start --host 127.0.0.1 --port 8000
    ceb track-b status
    ceb track-b check-diff --baseline <dir> --candidate <dir>
    ceb track-b round run --candidate-engine <path> --baseline-engine <path>

Also runnable as `python -m ceb.cli`.
"""

import argparse
import importlib.util
import json
import platform
import shutil
import sys
from pathlib import Path

from ceb import __version__


def _print(msg=""):
    sys.stdout.write(str(msg) + "\n")


# ----- doctor -----------------------------------------------------------------

def cmd_doctor(args):
    from ceb import paths

    _print("chess_en_bench doctor (v%s)" % __version__)
    _print("  python      : %s (%s)" % (platform.python_version(), sys.executable))
    _print("  platform    : %s" % platform.platform())

    try:
        root = paths.find_repo_root()
        _print("  repo root   : %s" % root)
        for track in ("a_from_scratch", "b_stockfish_opt"):
            present = (root / "tracks" / track).is_dir()
            _print("  track %-13s: %s" % (track, "ok" if present else "MISSING"))
    except FileNotFoundError as exc:
        _print("  repo root   : NOT FOUND (%s)" % exc)

    _print("  optional python deps:")
    for mod, why in (("fastapi", "API server"), ("uvicorn", "API server"),
                     ("pytest", "tests")):
        found = importlib.util.find_spec(mod) is not None
        hint = "" if found else '  -> pip install -e ".[dev,server]"'
        _print("    %-9s: %s (%s)%s" % (mod, "ok" if found else "missing", why, hint))

    _print("  optional external tools:")
    for tool, why in (("stockfish", "Track B baseline engine"),
                      ("fastchess", "external match runner (optional)"),
                      ("cutechess-cli", "external match runner (optional)"),
                      ("docker", "sandboxing (recommended)"),
                      ("git", "version control")):
        path = shutil.which(tool)
        _print("    %-13s: %s (%s)" % (tool, path or "missing", why))
    _print("")
    _print("Core gate/match/scoring need only the Python standard library.")
    _print("Missing optional tools degrade gracefully; see `ceb track-b status`.")
    return 0


# ----- workspace ----------------------------------------------------------------

_WORKSPACE_README = """\
# {run_id} — Track {track} workspace

Put your submission here (see specs/submission_contract.md):
  workspace/engine      executable UCI engine (or build.sh that creates it)
  workspace/build.sh    optional build script, run by the gate

Iterate freely against the public gate (unlimited attempts):
  ceb gate run --track {track} --workspace {workspace}

When the gate passes, spend an official round (budget is limited):
  ceb round run --track {track} --workspace {workspace} --round 1
"""


def cmd_workspace_prepare(args):
    from ceb import paths
    from ceb.rounds.state import RunState

    root = paths.find_repo_root()
    runs_root = Path(args.runs_dir) if args.runs_dir else paths.runs_dir(root)
    run_dir = runs_root / args.run_id
    workspace = run_dir / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    track_dir = paths.track_dir(args.track, root)
    prompt_src = track_dir / "prompt.md"
    if prompt_src.is_file():
        (run_dir / "instructions.md").write_text(
            prompt_src.read_text(encoding="utf-8"), encoding="utf-8")
    (workspace / "README.md").write_text(
        _WORKSPACE_README.format(run_id=args.run_id, track=args.track.upper(),
                                 workspace=workspace),
        encoding="utf-8")

    RunState.load_or_create(runs_root, args.run_id, track=args.track.upper(),
                            workspace=workspace)
    _print("prepared run %r" % args.run_id)
    _print("  workspace    : %s" % workspace)
    _print("  instructions : %s" % (run_dir / "instructions.md"))
    _print("  public data  : %s" % (track_dir / "public"))
    _print("  state        : %s" % RunState.path_for(runs_root, args.run_id))
    return 0


# ----- gate ---------------------------------------------------------------------

def cmd_gate_run(args):
    from ceb import paths
    from ceb.eval_pack import resolve_eval_pack, EvalPackError
    from ceb.gate.gate_runner import run_gate, save_gate_report

    root = paths.find_repo_root()
    if args.sandbox == "docker":
        from ceb.sandbox import run_gate_in_docker, SandboxError
        try:
            return run_gate_in_docker(root, args.workspace, track=args.track,
                                      strict=args.strict,
                                      no_match=args.no_match)
        except SandboxError as exc:
            _print("sandbox error: %s" % exc)
            return 2
    try:
        # Hidden eval packs apply only to strict checks unless requested.
        pack = resolve_eval_pack(root, private_dir=args.eval_pack,
                                 allow_env=args.strict)
    except EvalPackError as exc:
        _print("eval pack error: %s" % exc)
        return 2
    report = run_gate(args.workspace, track=args.track, root=root,
                      quick_match=not args.no_match, strict=args.strict,
                      eval_pack=pack, engine_jail=args.engine_jail)
    out_path = save_gate_report(report, args.json_out, root=root)
    _print(report.human_summary())
    _print("")
    _print("JSON report: %s" % out_path)
    return 0 if report.passed else 2


# ----- round --------------------------------------------------------------------

def cmd_round_run(args):
    from ceb.eval_pack import EvalPackError
    from ceb.rounds.feedback import feedback_to_text
    from ceb.rounds.round_runner import run_round, RoundError

    if args.sandbox == "docker":
        from ceb import paths
        from ceb.sandbox import run_round_in_docker, SandboxError
        if args.eval_pack:
            _print("--eval-pack is not supported with the legacy "
                   "--sandbox docker mode; use --engine-jail docker "
                   "(the evaluator reads the pack host-side and never mounts "
                   "it into the engine), or run with --sandbox none")
            return 2
        try:
            return run_round_in_docker(
                paths.find_repo_root(), args.workspace,
                round_number=args.round, track=args.track, quick=args.quick,
                run_id=args.run_id)
        except SandboxError as exc:
            _print("sandbox error: %s" % exc)
            return 2
    mode = None
    if args.final_eval:
        mode = "final_eval"
    try:
        report, feedback, state = run_round(
            args.workspace, args.round, quick=args.quick, mode=mode,
            run_id=args.run_id, track=args.track, runs_root=args.runs_dir,
            eval_pack_dir=args.eval_pack, engine_jail=args.engine_jail,
            progress=lambda msg: _print("  " + msg))
    except (RoundError, EvalPackError) as exc:
        _print("round aborted: %s" % exc)
        return 2
    _print("")
    _print(feedback_to_text(feedback))
    _print("")
    _print("report.json  : runs/%s/round_%d/report.json"
           % (report["run_id"], report["round"]))
    _print("official budget: %d used / %d total (quick rounds are free)"
           % (state.budget_used, state.budget_total))
    return 0


# ----- leaderboard ----------------------------------------------------------------

def cmd_leaderboard_compute(args):
    from ceb.scoring.track_a import compute_leaderboard

    board = compute_leaderboard(args.results, track=args.track,
                                include_quick=args.include_quick)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(board, indent=2) + "\n",
                                       encoding="utf-8")
        _print("leaderboard JSON written to %s" % args.json_out)
    _print("Leaderboard — track %s" % board["track"])
    if args.include_quick:
        _print("  (diagnostic view: quick rounds INCLUDED — not an official ranking)")
    else:
        _print("  (official rounds only; --include-quick shows diagnostic quick rounds)")
    if not board["entries"]:
        _print("  (no scored runs under %s)" % args.results)
        return 0
    _print("  %-4s %-28s %-10s %s" % ("#", "run", "score", "best round"))
    for i, e in enumerate(board["entries"], 1):
        best = e["best_round"]
        best_str = ("round %s (%s)" % (best["round"], best["mode"])) if best else "-"
        _print("  %-4d %-28s %-10s %s"
               % (i, e["run_id"], e["score"] if e["score"] is not None else "-",
                  best_str))
    return 0


# ----- server ---------------------------------------------------------------------

def cmd_server_start(args):
    try:
        import uvicorn
        from ceb.api.main import app  # noqa: F401 - import validates extras
    except ImportError:
        _print("The API server needs the 'server' extras. Install them with:")
        _print("  python3 -m venv .venv")
        _print("  . .venv/bin/activate")
        _print('  pip install -e ".[server]"')
        return 2
    _print("serving chess_en_bench dashboard at http://%s:%d/" % (args.host, args.port))
    uvicorn.run("ceb.api.main:app", host=args.host, port=args.port,
                log_level="info")
    return 0


# ----- track-b ---------------------------------------------------------------------

def cmd_track_b_status(args):
    from ceb.track_b.stockfish import stockfish_status

    status = stockfish_status()
    lock = status["lock"]
    _print("Track B baseline status")
    _print("  pinned release : %s (tag %s, commit %s)"
           % (lock.get("release"), lock.get("tag"), lock.get("commit")))
    _print("  sources        : %s (%s)"
           % (status["stockfish_dir"],
              "present" if status["present"] else "absent"))
    if status["head_commit"]:
        _print("  HEAD commit    : %s (matches lock: %s)"
               % (status["head_commit"][:12], status["commit_matches_lock"]))
    for action in status["actions"]:
        _print("  -> %s" % action)
    return 0


def _engine_command(spec):
    """Resolve an engine spec: a benchmark opponent name or an executable path."""
    from ceb.match.opponents import STRATEGIES, opponent_command

    if spec in STRATEGIES:
        return opponent_command(spec)
    path = Path(spec).resolve()
    if not path.is_file():
        raise FileNotFoundError("engine not found: %s (pass an executable "
                                "path or one of: %s)"
                                % (spec, ", ".join(STRATEGIES)))
    return [str(path)]


def cmd_track_b_round_run(args):
    from ceb.track_b.round_runner import run_track_b_round, TrackBRoundError

    try:
        candidate_cmd = _engine_command(args.candidate_engine)
        baseline_cmd = _engine_command(args.baseline_engine)
        report, feedback = run_track_b_round(
            candidate_cmd, baseline_cmd,
            round_number=args.round, run_id=args.run_id, games=args.games,
            movetime_ms=args.movetime, max_plies=args.max_plies,
            baseline_src=args.baseline_src, candidate_src=args.candidate_src,
            eval_pack_dir=args.eval_pack, runs_root=args.runs_dir,
            openings_limit=args.openings_limit, engine_jail=args.engine_jail,
            runner=args.runner,
            progress=lambda msg: _print("  " + msg))
    except (TrackBRoundError, FileNotFoundError) as exc:
        _print("track B round aborted: %s" % exc)
        return 2
    _print("")
    _print("Track B round %d — candidate vs baseline" % report["round"])
    totals = report["totals"]
    _print("  W%d D%d L%d over %d games" % (totals["wins"], totals["draws"],
                                            totals["losses"], feedback["games"]))
    _print("  delta Elo: %s  (95%% CI %s)  final after penalties: %s"
           % (feedback["delta_elo"], feedback["delta_elo_ci95"],
              feedback["final_delta_elo"]))
    _print("  report: runs/%s/track_b_round_%d/report.json"
           % (report["run_id"], report["round"]))
    return 0


def cmd_track_b_official_run(args):
    from ceb.track_b.official_pipeline import (
        run_official_track_b, TrackBPipelineError)
    from ceb.track_b.round_runner import TrackBRoundError

    try:
        report = run_official_track_b(
            candidate_src=args.candidate_src, baseline_src=args.baseline_src,
            eval_pack_dir=args.eval_pack, engine_jail=args.engine_jail,
            build_script=args.build_script, engine_relpath=args.engine_relpath,
            games=args.games, movetime_ms=args.movetime,
            max_plies=args.max_plies, run_id=args.run_id,
            runs_root=args.runs_dir, verified=False,
            progress=lambda msg: _print("  " + msg))
    except (TrackBPipelineError, TrackBRoundError) as exc:
        _print("track B official pipeline aborted: %s" % exc)
        return 2
    score = report["score"]
    _print("")
    _print("Track B official pipeline — run %s" % report["run_id"])
    _print("  delta Elo: %s  (95%% CI %s)" % (score["delta_elo"],
                                              score["delta_elo_ci95"]))
    _print("  verified : %s (CLI runs are diagnostic; hosted worker "
           "verification is the official path)" % report["verified"])
    return 0


def cmd_track_b_check_diff(args):
    from ceb import paths
    from ceb.track_b.diff_policy import check_diff, load_patterns

    track_dir = paths.track_dir("B")
    allowed = load_patterns(args.allowed or track_dir / "allowed_paths.txt")
    forbidden = load_patterns(args.forbidden or track_dir / "forbidden_paths.txt")
    report = check_diff(args.baseline, args.candidate, allowed, forbidden)
    _print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 2


# ----- scan ---------------------------------------------------------------------

def cmd_scan_workspace(args):
    from ceb.scan import scan_workspace

    if str(args.track).upper() not in ("A", "A_FROM_SCRATCH"):
        _print("scan workspace currently supports track A only")
        return 2
    report = scan_workspace(args.workspace)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2) + "\n",
                                       encoding="utf-8")
    _print("Static scan — %s" % report["workspace"])
    for finding in report["findings"]:
        _print("  [%s] %-24s %s — %s" % (finding["severity"].upper(),
                                         finding["rule"], finding["path"],
                                         finding["detail"]))
    if not report["findings"]:
        _print("  no findings")
    _print("Scan result: %s (%d fail, %d warn)"
           % ("PASSED" if report["passed"] else "FAILED",
              report["fail_count"], report["warn_count"]))
    return 0 if report["passed"] else 2


def cmd_scan_track_b(args):
    from ceb.scan import scan_track_b

    report = scan_track_b(args.baseline_src, args.candidate_src)
    _print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 2


# ----- hosted -------------------------------------------------------------------

def cmd_hosted_init(args):
    from ceb.hosted import db as hosted_db

    path = hosted_db.init_db(args.db)
    _print("hosted database initialized: %s" % path)
    _print("artifact store: %s" % hosted_db.store_dir(path))
    return 0


def cmd_hosted_submit(args):
    from ceb.hosted import db as hosted_db
    from ceb.hosted.submissions import snapshot_workspace, SubmissionError

    if str(args.track).upper() != "A":
        _print("hosted submissions currently support track A only")
        return 2
    if bool(args.workspace) == bool(args.archive):
        _print("pass exactly one of --workspace <dir> or --archive <file>")
        return 2
    conn = hosted_db.connect(args.db)
    try:
        if hosted_db.get_run(conn, args.run_id) is None:
            hosted_db.create_run(conn, args.run_id, args.track)
        store = hosted_db.store_dir(args.db)
        import uuid as _uuid
        stamp = "%d_%s" % (int(__import__("time").time()), _uuid.uuid4().hex[:8])
        workspace = args.workspace
        if args.archive:
            from ceb.hosted.upload import safe_extract_archive, UploadError
            extract_dest = (store / args.run_id / "uploads"
                            / ("upload_%s" % stamp))
            try:
                workspace = safe_extract_archive(args.archive, extract_dest)
            except UploadError as exc:
                _print("upload rejected: %s" % exc.public_message)
                return 2
        dest = store / args.run_id / "snapshots" / ("submission_%s" % stamp)
        try:
            snapshot, tree_hash = snapshot_workspace(workspace, dest)
        except SubmissionError as exc:
            _print("submission rejected: %s" % exc.public_message)
            return 2
        submission_id = hosted_db.add_submission(conn, args.run_id, snapshot,
                                                 tree_hash)
        job_id = hosted_db.enqueue_job(conn, args.run_id, "official_eval")
    finally:
        conn.close()
    _print("submitted run %r" % args.run_id)
    _print("  snapshot   : %s" % snapshot)
    _print("  tree hash  : %s" % tree_hash)
    _print("  submission : #%d" % submission_id)
    _print("  job queued : #%d (official_eval)" % job_id)
    _print("next: ceb hosted worker run-once --db %s --eval-pack <private-pack>"
           % args.db)
    return 0


def cmd_hosted_worker_run_once(args):
    from ceb.hosted.worker import run_once

    # Resolve the evaluation profile. Legacy flags win for backward
    # compatibility: --quick-test-mode -> smoke, --final-eval -> final-eval.
    if args.quick_test_mode:
        profile = "smoke"
    elif args.final_eval:
        profile = "final-eval"
    else:
        profile = args.profile

    status = run_once(
        args.db, eval_pack_dir=args.eval_pack, engine_jail=args.engine_jail,
        profile=profile, allow_unjailed=args.dev_allow_unjailed,
        official_pack_hashes=args.official_pack_hash,
        official_pack_registry=args.official_pack_registry,
        allow_demo_pack=args.dev_allow_demo_pack,
        allow_unpinned_pack=args.dev_allow_unpinned_pack,
        signing_key_path=args.signing_key,
        allow_unsigned=args.dev_allow_unsigned,
        build_wrapper=args.build_wrapper,
        build_wrapper_hashes=args.build_wrapper_hash,
        build_wrapper_registry=args.build_wrapper_registry,
        allow_unpinned_wrapper=args.dev_allow_unpinned_wrapper,
        track_b_baseline_hashes=args.track_b_baseline_hash,
        track_b_baseline_registry=args.track_b_baseline_registry,
        allow_toy_baseline=args.dev_allow_toy_baseline,
        bench_min_nps_ratio=args.bench_min_nps_ratio,
        allow_no_bench=args.dev_allow_no_bench,
        worker_id=args.worker_id, lease_seconds=args.lease_seconds,
        progress=lambda msg: _print("  " + msg))
    _print(json.dumps(status, indent=2))
    return 0 if status["status"] in ("done", "idle") else 2


def cmd_hosted_submit_track_b(args):
    from ceb.hosted import db as hosted_db
    from ceb.hosted.submissions import snapshot_workspace, SubmissionError

    conn = hosted_db.connect(args.db)
    try:
        if hosted_db.get_run(conn, args.run_id) is None:
            hosted_db.create_run(conn, args.run_id, "B")
        store = hosted_db.store_dir(args.db)
        import uuid as _uuid
        stamp = "%d_%s" % (int(__import__("time").time()), _uuid.uuid4().hex[:8])
        cand_dest = store / args.run_id / "snapshots" / ("candidate_%s" % stamp)
        base_dest = store / args.run_id / "snapshots" / ("baseline_%s" % stamp)
        try:
            cand_snap, cand_hash = snapshot_workspace(args.candidate_src, cand_dest)
            base_snap, base_hash = snapshot_workspace(args.baseline_src, base_dest)
        except SubmissionError as exc:
            _print("submission rejected: %s" % exc.public_message)
            return 2
        sub_id = hosted_db.add_track_b_submission(
            conn, args.run_id, candidate_snapshot=cand_snap,
            baseline_snapshot=base_snap, candidate_hash=cand_hash,
            baseline_hash=base_hash, build_script=args.build_script,
            engine_relpath=args.engine_relpath)
        job_id = hosted_db.enqueue_job(conn, args.run_id, "track_b_official_eval")
    finally:
        conn.close()
    _print("submitted Track B run %r" % args.run_id)
    _print("  candidate  : %s (%s)" % (cand_snap, cand_hash))
    _print("  baseline   : %s (%s)" % (base_snap, base_hash))
    _print("  submission : #%d" % sub_id)
    _print("  job queued : #%d (track_b_official_eval)" % job_id)
    _print("next: ceb hosted worker run-once --db %s --eval-pack <pack> "
           "--engine-jail docker" % args.db)
    return 0


def cmd_hosted_readiness_check(args):
    from ceb.hosted.readiness import readiness_check

    report = readiness_check(
        db_path=args.db, eval_pack_dir=args.eval_pack,
        public_key_path=args.public_key, track=args.track,
        build_wrapper=args.build_wrapper, signing_key_path=args.signing_key,
        official_pack_hashes=args.official_pack_hash,
        official_pack_registry=args.official_pack_registry,
        build_wrapper_hashes=args.build_wrapper_hash,
        build_wrapper_registry=args.build_wrapper_registry,
        track_b_baseline_hashes=args.track_b_baseline_hash,
        track_b_baseline_registry=args.track_b_baseline_registry,
        baseline_src=args.baseline_src,
        require_server=args.require_server,
        strict_public_official=args.strict_public_official)
    if args.json:
        # JSON only, so the output is cleanly machine-parseable.
        _print(json.dumps(report, indent=2))
        return 0 if report["ready"] else 2
    _print("Official readiness — track %s: %s"
           % (report["track"], "READY" if report["ready"] else "NOT READY"))
    for c in report["checks"]:
        mark = "ok  " if c["ok"] else ("FAIL" if c["required"] else "warn")
        _print("  [%s] %-30s %s" % (mark, c["name"], c["detail"]))
    if report["blocking_failures"]:
        _print("blocking failures: %s" % ", ".join(report["blocking_failures"]))
    return 0 if report["ready"] else 2


def cmd_hosted_release_manifest_create(args):
    from ceb.hosted.release_manifest import (
        build_release_manifest, ReleaseManifestError)

    try:
        manifest = build_release_manifest(
            track=args.track, eval_pack_dir=args.eval_pack,
            public_key_path=args.public_key,
            benchmark_version=args.benchmark_version, season=args.season,
            official_pack_hashes=args.official_pack_hash,
            official_pack_registry=args.official_pack_registry,
            track_b_baseline_hashes=args.track_b_baseline_hash,
            track_b_baseline_registry=args.track_b_baseline_registry,
            build_wrapper_hashes=args.build_wrapper_hash,
            build_wrapper_registry=args.build_wrapper_registry,
            leaderboard_policy=args.leaderboard_policy)
    except ReleaseManifestError as exc:
        _print("release manifest failed: %s" % exc)
        return 2
    text = json.dumps(manifest, indent=2) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        _print("wrote release manifest: %s" % args.out)
        _print("  pack hash : %s" % manifest["official_eval_pack_hash"])
        _print("  key id    : %s" % manifest["operator_public_key_fingerprint"])
    else:
        _print(text)
    return 0


def cmd_hosted_keygen(args):
    from ceb.hosted.signing import generate_keypair, SigningError

    try:
        key_id = generate_keypair(args.private_key, args.public_key)
    except SigningError as exc:
        _print("keygen failed: %s" % exc)
        return 2
    _print("generated Ed25519 keypair")
    _print("  private key : %s (keep secret; never commit)" % args.private_key)
    _print("  public key  : %s (publish for verification)" % args.public_key)
    _print("  key_id      : %s" % key_id)
    _print("sign results with: ceb hosted sign-result --result <f> "
           "--private-key %s" % args.private_key)
    return 0


def cmd_hosted_result_export(args):
    from ceb.hosted import db as hosted_db
    from ceb.hosted.result_bundle import export_result_bundle, ResultBundleError

    conn = hosted_db.connect(args.db)
    try:
        fingerprint = args.public_key_fingerprint
        if args.public_key and not fingerprint:
            from ceb.hosted.signing import (
                load_public_key, public_key_fingerprint, SigningError)
            try:
                fingerprint = public_key_fingerprint(load_public_key(args.public_key))
            except SigningError as exc:
                _print("could not load public key: %s" % exc)
                return 2
        try:
            out_path, manifest = export_result_bundle(
                conn, args.run_id, args.out, db_path=args.db,
                include_all_public=args.include_all_public,
                release_manifest_path=args.release_manifest,
                public_key_fingerprint=fingerprint)
        except ResultBundleError as exc:
            _print("export failed: %s" % exc)
            return 2
    finally:
        conn.close()
    _print("exported public result bundle for run %r" % args.run_id)
    _print("  bundle   : %s" % out_path)
    _print("  selected : result #%s (%s)" % (manifest.get("selected_result_id"),
                                             manifest.get("selected_mode")))
    _print("  files    : %s" % ", ".join(manifest["files"]))
    if manifest.get("selected_only"):
        _print("  (selected best verified result only; public artifacts; no "
               "private/admin detail)")
    else:
        _print("  (DIAGNOSTIC: all public artifacts; NOT an official bundle)")
    return 0


def cmd_hosted_result_show(args):
    from ceb.hosted import db as hosted_db
    from ceb.hosted.official_eval import load_result

    conn = hosted_db.connect(args.db)
    try:
        results = hosted_db.results_for_run(conn, args.run_id)
        best = hosted_db.select_best_verified_result(conn, args.run_id)
    finally:
        conn.close()
    if not results:
        _print("no results for run %r" % args.run_id)
        return 2
    best_id = best["id"] if best else None
    for row in results:
        marker = "  <- selected (best verified)" if row["id"] == best_id else ""
        _print("result #%d  mode=%s  profile=%s  grade=%s  verified=%s  "
               "score=%s%s"
               % (row["id"], row["mode"], row.get("profile"),
                  row.get("verification_grade"), bool(row["verified"]),
                  row["score"], marker))
        try:
            result = load_result(row["result_path"])
        except (OSError, ValueError):
            _print("  (result file unavailable)")
            continue
        sig = result.get("signature", {})
        _print("  signature : %s (%s)" % (sig.get("status"), sig.get("algorithm")))
        metadata = result.get("metadata", {})
        _print("  eval pack : %s (%s)" % (metadata.get("eval_pack_id"),
                                          metadata.get("eval_pack_hash")))
        _print("  file      : %s" % row["result_path"])
    if best is None:
        _print("selected for leaderboard: none (no verified result)")
    return 0


def cmd_hosted_leaderboard(args):
    from ceb.hosted import db as hosted_db

    conn = hosted_db.connect(args.db)
    try:
        board = hosted_db.verified_leaderboard(conn, track=args.track)
    finally:
        conn.close()
    _print("Hosted leaderboard — track %s (verified results only)"
           % board["track"])
    if not board["entries"]:
        _print("  (no verified results)")
        return 0
    _print("  %-4s %-24s %-10s %-16s %s"
           % ("#", "run", "score", "mode", "grade"))
    for i, entry in enumerate(board["entries"], 1):
        _print("  %-4d %-24s %-10s %-16s %s"
               % (i, entry["run_id"], entry["score"], entry["mode"],
                  entry.get("verification_grade") or "-"))
    return 0


def cmd_hosted_sign_result(args):
    from ceb.hosted.official_eval import load_result
    from ceb.hosted.signing import (
        sign_official_result, sign_result_ed25519, load_private_key,
        SigningError)

    result = load_result(args.result)
    try:
        if args.private_key:
            sign_result_ed25519(result, load_private_key(args.private_key))
        else:
            # Ed25519 if CEB_SIGNING_PRIVATE_KEY is set, else HMAC, else unsigned.
            sign_official_result(result)
    except SigningError as exc:
        _print("signing failed: %s" % exc)
        return 2
    Path(args.result).write_text(json.dumps(result, indent=2) + "\n",
                                 encoding="utf-8")
    sig = result["signature"]
    _print("result %s: %s (%s)" % (args.result, sig["status"],
                                   sig.get("algorithm")))
    if sig["status"] == "unsigned":
        _print("  (pass --private-key <ed25519.pem>, or set "
               "CEB_SIGNING_PRIVATE_KEY / CEB_SIGNING_KEY; unsigned results "
               "have no cryptographic authenticity)")
    return 0


def cmd_hosted_verify_result(args):
    from ceb.hosted.verifier import verify_result_file
    from ceb.hosted.signing import load_public_key, SigningError

    public_key = None
    if args.public_key:
        try:
            public_key = load_public_key(args.public_key)
        except SigningError as exc:
            _print("could not load public key: %s" % exc)
            return 2
    verdict = verify_result_file(args.result, public_key=public_key)
    _print(json.dumps(verdict, indent=2))
    if not verdict["authentic"] and \
            verdict.get("signature_trust") == "embedded-self-described":
        _print("  (signature checks out against the result's OWN embedded key "
               "only — this proves internal consistency, not authenticity. "
               "Pass --public-key <operator.pem> obtained out-of-band for a "
               "real verdict.)")
    return 0 if verdict["authentic"] else 2


# ----- parser ----------------------------------------------------------------------

def build_parser():
    from ceb.hosted.profiles import PROFILE_CHOICES

    parser = argparse.ArgumentParser(
        prog="ceb",
        description="chess_en_bench: benchmark for LLM agents that build or "
                    "optimize chess engines")
    parser.add_argument("--version", action="version",
                        version="chess_en_bench %s" % __version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("doctor", help="diagnose environment and dependencies")
    p.set_defaults(func=cmd_doctor)

    ws = sub.add_parser("workspace", help="manage run workspaces")
    ws_sub = ws.add_subparsers(dest="subcommand", required=True)
    p = ws_sub.add_parser("prepare", help="create a run workspace skeleton")
    p.add_argument("--track", default="A")
    p.add_argument("--run-id", required=True)
    p.add_argument("--runs-dir", default=None, help="override runs/ root (tests)")
    p.set_defaults(func=cmd_workspace_prepare)

    gate = sub.add_parser("gate", help="public correctness gate")
    gate_sub = gate.add_subparsers(dest="subcommand", required=True)
    p = gate_sub.add_parser("run", help="run the gate on a workspace")
    p.add_argument("--track", default="A")
    p.add_argument("--workspace", required=True)
    p.add_argument("--json-out", default=None)
    p.add_argument("--no-match", action="store_true",
                   help="skip the mini match smoke check")
    p.add_argument("--strict", action="store_true",
                   help="official-round policy: 'go perft' is mandatory")
    p.add_argument("--sandbox", choices=["none", "docker"], default="none",
                   help="run inside the Docker evaluator sandbox "
                        "(recommended for untrusted submissions)")
    p.add_argument("--eval-pack", default=None,
                   help="private eval pack directory (operator only)")
    p.add_argument("--engine-jail", choices=["none", "docker"], default="none",
                   help="confine the untrusted engine (official hosted "
                        "policy: docker)")
    p.set_defaults(func=cmd_gate_run)

    rnd = sub.add_parser("round", help="official/quick evaluation rounds")
    rnd_sub = rnd.add_subparsers(dest="subcommand", required=True)
    p = rnd_sub.add_parser("run", help="run one round (gate must pass)")
    p.add_argument("--track", default="A")
    p.add_argument("--workspace", required=True)
    p.add_argument("--round", type=int, required=True)
    p.add_argument("--quick", action="store_true",
                   help="reduced match set; does not consume official budget")
    p.add_argument("--run-id", default=None)
    p.add_argument("--runs-dir", default=None, help="override runs/ root (tests)")
    p.add_argument("--sandbox", choices=["none", "docker"], default="none",
                   help="legacy harness-in-container mode; official hosted "
                        "evaluation uses --engine-jail docker instead")
    p.add_argument("--engine-jail", choices=["none", "docker"], default="none",
                   help="confine the untrusted engine (combines with "
                        "--eval-pack: the pack is never mounted)")
    p.add_argument("--final-eval", action="store_true",
                   help="run a final_eval (leaderboard-quality; strict gate; "
                        "no round-budget cost)")
    p.add_argument("--eval-pack", default=None,
                   help="private eval pack directory (operator only)")
    p.set_defaults(func=cmd_round_run)

    lb = sub.add_parser("leaderboard", help="aggregate run scores")
    lb_sub = lb.add_subparsers(dest="subcommand", required=True)
    p = lb_sub.add_parser("compute", help="rank runs by best valid round")
    p.add_argument("--track", default="A")
    p.add_argument("--results", default="runs", help="runs directory to scan")
    p.add_argument("--json-out", default=None)
    p.add_argument("--include-quick", action="store_true",
                   help="diagnostic only: also rank quick rounds")
    p.set_defaults(func=cmd_leaderboard_compute)

    srv = sub.add_parser("server", help="API server + dashboard")
    srv_sub = srv.add_subparsers(dest="subcommand", required=True)
    p = srv_sub.add_parser("start", help="start the FastAPI server")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=cmd_server_start)

    tb = sub.add_parser("track-b", help="Stockfish optimization track tools")
    tb_sub = tb.add_subparsers(dest="subcommand", required=True)
    p = tb_sub.add_parser("status", help="pinned baseline / setup status")
    p.set_defaults(func=cmd_track_b_status)
    p = tb_sub.add_parser("check-diff", help="diff whitelist check")
    p.add_argument("--baseline", required=True)
    p.add_argument("--candidate", required=True)
    p.add_argument("--allowed", default=None)
    p.add_argument("--forbidden", default=None)
    p.set_defaults(func=cmd_track_b_check_diff)

    tb_round = tb_sub.add_parser("round", help="candidate-vs-baseline rounds")
    tb_round_sub = tb_round.add_subparsers(dest="subsubcommand", required=True)
    p = tb_round_sub.add_parser(
        "run", help="play candidate vs baseline and score delta Elo")
    p.add_argument("--candidate-engine", required=True,
                   help="executable path or a benchmark opponent name")
    p.add_argument("--baseline-engine", required=True,
                   help="executable path or a benchmark opponent name")
    p.add_argument("--baseline-src", default=None,
                   help="baseline source tree for the diff whitelist check")
    p.add_argument("--candidate-src", default=None,
                   help="candidate source tree for the diff whitelist check")
    p.add_argument("--round", type=int, default=1)
    p.add_argument("--run-id", default="track_b_local")
    p.add_argument("--games", type=int, default=8)
    p.add_argument("--movetime", type=int, default=100)
    p.add_argument("--max-plies", type=int, default=300)
    p.add_argument("--openings-limit", type=int, default=None)
    p.add_argument("--eval-pack", default=None)
    p.add_argument("--runs-dir", default=None, help="override runs/ root (tests)")
    p.add_argument("--engine-jail", choices=["none", "docker"], default="none",
                   help="confine the untrusted candidate engine")
    p.add_argument("--runner", choices=["internal", "fastchess"],
                   default="internal",
                   help="match backend (fastchess is optional, high-volume)")
    p.set_defaults(func=cmd_track_b_round_run)

    tb_official = tb_sub.add_parser("official",
                                    help="source-first official pipeline")
    tb_official_sub = tb_official.add_subparsers(dest="subsubcommand",
                                                 required=True)
    p = tb_official_sub.add_parser(
        "run", help="scan + build + evaluate a candidate source tree")
    p.add_argument("--candidate-src", required=True)
    p.add_argument("--baseline-src", default=None,
                   help="baseline tree (default: third_party/stockfish)")
    p.add_argument("--eval-pack", default=None)
    p.add_argument("--engine-jail", choices=["none", "docker"], default="none")
    p.add_argument("--build-script", default="ceb_build.sh")
    p.add_argument("--engine-relpath", default="ceb_engine")
    p.add_argument("--games", type=int, default=8)
    p.add_argument("--movetime", type=int, default=100)
    p.add_argument("--max-plies", type=int, default=300)
    p.add_argument("--run-id", default="track_b_official")
    p.add_argument("--runs-dir", default=None)
    p.set_defaults(func=cmd_track_b_official_run)

    scan = sub.add_parser("scan", help="anti-cheating scanners")
    scan_sub = scan.add_subparsers(dest="subcommand", required=True)
    p = scan_sub.add_parser("workspace", help="static scan of a submission")
    p.add_argument("--track", default="A")
    p.add_argument("--workspace", required=True)
    p.add_argument("--json-out", default=None)
    p.set_defaults(func=cmd_scan_workspace)
    p = scan_sub.add_parser("track-b", help="scan a Track B candidate tree")
    p.add_argument("--baseline-src", required=True)
    p.add_argument("--candidate-src", required=True)
    p.set_defaults(func=cmd_scan_track_b)

    hosted = sub.add_parser("hosted", help="hosted official evaluation (MVP)")
    hosted_sub = hosted.add_subparsers(dest="subcommand", required=True)
    p = hosted_sub.add_parser("init", help="initialize the hosted database")
    p.add_argument("--db", default="runs/hosted.sqlite")
    p.set_defaults(func=cmd_hosted_init)
    p = hosted_sub.add_parser("submit",
                              help="snapshot + enqueue a workspace or archive")
    p.add_argument("--track", default="A")
    p.add_argument("--workspace", default=None,
                   help="server-local workspace directory")
    p.add_argument("--archive", default=None,
                   help="a .tar.gz/.tar/.zip upload (safely extracted: no "
                        "symlinks, absolute paths, traversal, or oversized files)")
    p.add_argument("--run-id", required=True)
    p.add_argument("--db", default="runs/hosted.sqlite")
    p.set_defaults(func=cmd_hosted_submit)
    p = hosted_sub.add_parser("submit-track-b",
                              help="snapshot + enqueue a Track B candidate")
    p.add_argument("--candidate-src", required=True,
                   help="candidate source tree (engine-edited Stockfish)")
    p.add_argument("--baseline-src", required=True,
                   help="pinned baseline source tree")
    p.add_argument("--run-id", required=True)
    p.add_argument("--db", default="runs/hosted.sqlite")
    p.add_argument("--build-script", default="ceb_build.sh")
    p.add_argument("--engine-relpath", default="ceb_engine")
    p.set_defaults(func=cmd_hosted_submit_track_b)
    worker = hosted_sub.add_parser("worker", help="official evaluation worker")
    worker_sub = worker.add_subparsers(dest="subsubcommand", required=True)
    p = worker_sub.add_parser("run-once", help="claim + process one queued job")
    p.add_argument("--db", default="runs/hosted.sqlite")
    p.add_argument("--eval-pack", default=None,
                   help="private eval pack (REQUIRED to verify)")
    p.add_argument("--engine-jail", choices=["none", "docker"], default="docker",
                   help="confine the untrusted engine (default: docker; "
                        "verified results REQUIRE docker)")
    p.add_argument("--profile", choices=list(PROFILE_CHOICES),
                   default="official",
                   help="evaluation profile: smoke (diagnostic, never "
                        "verified), official, or final-production (preferred "
                        "by the leaderboard)")
    p.add_argument("--dev-allow-unjailed", action="store_true",
                   help="DEV ONLY: run a verifiable profile without the docker "
                        "jail; the result is forced to verified=false "
                        "(diagnostic) and never reaches the leaderboard")
    p.add_argument("--official-pack-hash", action="append", default=None,
                   help="allowlisted official eval-pack content hash (repeat or "
                        "comma-separate; also CEB_OFFICIAL_EVAL_PACK_HASHES)")
    p.add_argument("--official-pack-registry", default=None,
                   help="JSON/text file of allowlisted official eval-pack hashes")
    p.add_argument("--signing-key", default=None,
                   help="Ed25519 private key PEM for signing verified results "
                        "(else CEB_SIGNING_PRIVATE_KEY); REQUIRED to verify")
    p.add_argument("--build-wrapper", default=None,
                   help="trusted Track B build wrapper outside the candidate "
                        "tree (REQUIRED to verify Track B)")
    p.add_argument("--build-wrapper-hash", action="append", default=None,
                   help="allowlisted trusted build-wrapper hash (Track B; repeat/"
                        "comma; also CEB_TRACK_B_BUILD_WRAPPER_HASHES)")
    p.add_argument("--build-wrapper-registry", default=None,
                   help="JSON/text file of allowlisted build-wrapper hashes")
    p.add_argument("--track-b-baseline-hash", action="append", default=None,
                   help="allowlisted Track B baseline tree hash (repeat/comma; "
                        "also CEB_TRACK_B_BASELINE_HASHES)")
    p.add_argument("--track-b-baseline-registry", default=None,
                   help="JSON/text file of allowlisted Track B baseline hashes")
    p.add_argument("--bench-min-nps-ratio", type=float, default=None,
                   help="min candidate/baseline NPS ratio for verified Track B "
                        "(enforced only when both engines support `bench`)")
    p.add_argument("--dev-allow-demo-pack", action="store_true",
                   help="DEV ONLY: accept a committed/demo eval pack "
                        "(diagnostic-untrusted-pack; never verified)")
    p.add_argument("--dev-allow-unpinned-pack", action="store_true",
                   help="DEV ONLY: accept an official pack with no hash "
                        "allowlist (diagnostic-unpinned-pack; never verified)")
    p.add_argument("--dev-allow-unsigned", action="store_true",
                   help="DEV ONLY: run a verifiable profile without an Ed25519 "
                        "key (diagnostic-unsigned; never verified)")
    p.add_argument("--dev-allow-toy-baseline", action="store_true",
                   help="DEV ONLY: accept an untrusted Track B baseline "
                        "(diagnostic-untrusted-baseline; never verified)")
    p.add_argument("--dev-allow-unpinned-wrapper", action="store_true",
                   help="DEV ONLY: accept a build wrapper with no hash allowlist "
                        "(diagnostic-untrusted-wrapper; never verified)")
    p.add_argument("--dev-allow-no-bench", action="store_true",
                   help="DEV ONLY: do not fail a verified Track B on a low NPS "
                        "ratio")
    p.add_argument("--worker-id", default=None,
                   help="identifier recorded on claimed jobs (multi-worker)")
    p.add_argument("--lease-seconds", type=int, default=None,
                   help="claim lease; a stale running job past its lease may "
                        "be reclaimed by another worker")
    p.add_argument("--final-eval", action="store_true",
                   help="legacy: run a final_eval (maps to the final-eval "
                        "profile)")
    p.add_argument("--quick-test-mode", action="store_true",
                   help="legacy: tiny toy config (maps to the smoke profile; "
                        "never verified)")
    p.set_defaults(func=cmd_hosted_worker_run_once)
    result = hosted_sub.add_parser("result", help="inspect results")
    result_sub = result.add_subparsers(dest="subsubcommand", required=True)
    p = result_sub.add_parser("show", help="show results for a run")
    p.add_argument("--run-id", required=True)
    p.add_argument("--db", default="runs/hosted.sqlite")
    p.set_defaults(func=cmd_hosted_result_show)
    p = result_sub.add_parser(
        "export", help="export the selected verified result bundle (zip)")
    p.add_argument("--run-id", required=True)
    p.add_argument("--db", default="runs/hosted.sqlite")
    p.add_argument("--out", required=True, help="output .zip path")
    p.add_argument("--include-all-public", action="store_true",
                   help="diagnostic: bundle ALL public artifacts (not just the "
                        "selected verified result); not an official bundle")
    p.add_argument("--release-manifest", default=None,
                   help="include this public release manifest in the bundle")
    p.add_argument("--public-key", default=None,
                   help="public key PEM; its fingerprint is added to the bundle")
    p.add_argument("--public-key-fingerprint", default=None,
                   help="operator public key fingerprint (if not passing a key)")
    p.set_defaults(func=cmd_hosted_result_export)
    p = hosted_sub.add_parser("leaderboard", help="verified-only leaderboard")
    p.add_argument("--db", default="runs/hosted.sqlite")
    p.add_argument("--track", default="A")
    p.set_defaults(func=cmd_hosted_leaderboard)
    readiness = hosted_sub.add_parser(
        "readiness", help="official-readiness check")
    readiness_sub = readiness.add_subparsers(dest="subsubcommand", required=True)
    p = readiness_sub.add_parser("check", help="check public-official readiness")
    p.add_argument("--db", default="runs/hosted.sqlite")
    p.add_argument("--eval-pack", default=None)
    p.add_argument("--public-key", default=None)
    p.add_argument("--track", default="A")
    p.add_argument("--build-wrapper", default=None)
    p.add_argument("--signing-key", default=None)
    p.add_argument("--official-pack-hash", action="append", default=None)
    p.add_argument("--official-pack-registry", default=None)
    p.add_argument("--build-wrapper-hash", action="append", default=None)
    p.add_argument("--build-wrapper-registry", default=None)
    p.add_argument("--track-b-baseline-hash", action="append", default=None)
    p.add_argument("--track-b-baseline-registry", default=None)
    p.add_argument("--baseline-src", default=None,
                   help="Track B baseline tree to check for pinned-Stockfish trust")
    p.add_argument("--strict-public-official", action="store_true",
                   help="treat pinning / public key / keypair-match / baseline / "
                        "wrapper-hash anchors as BLOCKING (the final gate)")
    p.add_argument("--require-server", action="store_true",
                   help="also require the hosted API admin token (server mode)")
    p.add_argument("--json", action="store_true", help="also print JSON report")
    p.set_defaults(func=cmd_hosted_readiness_check)
    rel = hosted_sub.add_parser("release-manifest",
                                help="public release manifest for a season")
    rel_sub = rel.add_subparsers(dest="subsubcommand", required=True)
    p = rel_sub.add_parser("create", help="emit a secret-free release manifest")
    p.add_argument("--track", default="A")
    p.add_argument("--benchmark-version", default=None)
    p.add_argument("--season", default=None)
    p.add_argument("--eval-pack", required=True)
    p.add_argument("--official-pack-hash", action="append", default=None)
    p.add_argument("--official-pack-registry", default=None)
    p.add_argument("--public-key", required=True)
    p.add_argument("--track-b-baseline-hash", action="append", default=None)
    p.add_argument("--track-b-baseline-registry", default=None)
    p.add_argument("--build-wrapper-hash", action="append", default=None)
    p.add_argument("--build-wrapper-registry", default=None)
    p.add_argument("--leaderboard-policy", default=None)
    p.add_argument("--out", default=None, help="output JSON path (else stdout)")
    p.set_defaults(func=cmd_hosted_release_manifest_create)
    p = hosted_sub.add_parser("keygen", help="generate an Ed25519 signing keypair")
    p.add_argument("--private-key", required=True, help="output private key path")
    p.add_argument("--public-key", required=True, help="output public key path")
    p.set_defaults(func=cmd_hosted_keygen)
    p = hosted_sub.add_parser("sign-result", help="sign a result file")
    p.add_argument("--result", required=True)
    p.add_argument("--private-key", default=None,
                   help="Ed25519 private key PEM (else CEB_SIGNING_PRIVATE_KEY, "
                        "else legacy CEB_SIGNING_KEY HMAC)")
    p.set_defaults(func=cmd_hosted_sign_result)
    p = hosted_sub.add_parser("verify-result", help="verify a result file")
    p.add_argument("--result", required=True)
    p.add_argument("--public-key", default=None,
                   help="Ed25519 public key PEM for third-party verification")
    p.set_defaults(func=cmd_hosted_verify_result)

    return parser


def main(argv=None):
    from ceb.sanitize import debug_enabled, sanitize_exception

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        _print("interrupted")
        return 130
    except FileNotFoundError as exc:
        _print("error: %s" % exc)
        return 2
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - agent-facing output must be sanitized
        if debug_enabled():
            raise
        _print("error: %s" % sanitize_exception(exc))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
