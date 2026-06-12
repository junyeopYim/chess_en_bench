"""Internal Python UCI match runner (fallback when fastchess/cutechess are absent).

Every move is validated against the internal oracle; illegal moves, timeouts,
and crashes lose the game for the offending side and are tallied separately
for penalty scoring.
"""

import time

from ceb.chess import (
    START_FEN, parse_fen, board_to_fen,
    generate_legal, make_move, in_check,
)
from ceb.chess.movegen import is_insufficient_material, repetition_key
from ceb.chess.pgn import game_to_text, write_games_text
from ceb.uci.client import UCIClient, EngineTimeout, EngineCrashed, EngineError

RESULT_WHITE = "1-0"
RESULT_BLACK = "0-1"
RESULT_DRAW = "1/2-1/2"

FAULT_ILLEGAL = "illegal"
FAULT_TIMEOUT = "timeout"
FAULT_CRASH = "crash"


def _loss_for(side_white):
    return RESULT_BLACK if side_white else RESULT_WHITE


def play_game(white_cmd, black_cmd, *, start_fen=START_FEN, movetime_ms=100,
              max_plies=200, grace_ms=3000, white_name="white",
              black_name="black", seed=None, cwds=(None, None),
              white_options=None, black_options=None,
              halfmove_draw_plies=100):
    """Play one game. Returns a dict game record.

    cwds: (white_cwd, black_cwd) working directories for the two processes.
    white_options/black_options: extra UCI options sent via 'setoption'
    before the game (e.g. limited-strength anchor settings); engines that
    do not know an option simply ignore it.
    halfmove_draw_plies: halfmove-clock draw threshold (100 = fifty-move
    rule; set 150 for a 75-move policy).

    Draw adjudication: checkmate/stalemate from the oracle, the halfmove
    clock, threefold repetition, insufficient material (K vs K, K+B vs K,
    K+N vs K), and the max-plies cap. Engines are only asked to move in
    positions with at least one legal move; a 'bestmove 0000' there counts
    as an illegal-move fault.
    """
    record = {
        "white": white_name,
        "black": black_name,
        "start_fen": start_fen,
        "movetime_ms": movetime_ms,
        "max_plies": max_plies,
        "moves": [],
        "result": RESULT_DRAW,
        "reason": "",
        "fault": None,        # None | {"side": "white"|"black", "kind": ...}
        "final_fen": None,
        "plies": 0,
    }
    board = parse_fen(start_fen)
    moves_uci = []
    clients = {}

    def fault(side_white, kind, reason):
        record["result"] = _loss_for(side_white)
        record["reason"] = reason
        record["fault"] = {"side": "white" if side_white else "black", "kind": kind}

    try:
        try:
            white = UCIClient(white_cmd, cwd=cwds[0], name=white_name)
            clients["w"] = white
            white.handshake()
            white.new_game()
        except EngineError as exc:
            fault(True, FAULT_CRASH, "white failed to start: %s" % exc)
            return record
        try:
            black = UCIClient(black_cmd, cwd=cwds[1], name=black_name)
            clients["b"] = black
            black.handshake()
            black.new_game()
        except EngineError as exc:
            fault(False, FAULT_CRASH, "black failed to start: %s" % exc)
            return record

        for client, options in ((white, white_options), (black, black_options)):
            pending = dict(options or {})
            if seed is not None:
                pending.setdefault("Seed", seed)
            for name, value in pending.items():
                try:
                    client.send("setoption name %s value %s" % (name, value))
                except EngineError:
                    pass

        start_is_startpos = start_fen == START_FEN
        seen_positions = {repetition_key(board): 1}
        while True:
            legal = {m.uci(): m for m in generate_legal(board)}
            if not legal:
                if in_check(board):
                    winner_white = not board.white_to_move()
                    record["result"] = RESULT_WHITE if winner_white else RESULT_BLACK
                    record["reason"] = "checkmate"
                else:
                    record["reason"] = "stalemate"
                break
            if seen_positions[repetition_key(board)] >= 3:
                record["reason"] = "threefold repetition"
                break
            if is_insufficient_material(board):
                record["reason"] = "insufficient material"
                break
            if board.halfmove_clock >= halfmove_draw_plies:
                record["reason"] = ("fifty-move rule"
                                    if halfmove_draw_plies == 100 else
                                    "halfmove-clock draw (%d plies)"
                                    % halfmove_draw_plies)
                break
            if len(moves_uci) >= max_plies:
                record["reason"] = "draw adjudicated at max plies"
                break

            mover_white = board.white_to_move()
            client = white if mover_white else black
            try:
                client.set_position(None if start_is_startpos else start_fen,
                                    moves_uci)
                best = client.go_movetime(movetime_ms, grace_ms=grace_ms)
            except EngineTimeout as exc:
                fault(mover_white, FAULT_TIMEOUT, str(exc))
                break
            except EngineError as exc:
                fault(mover_white, FAULT_CRASH, str(exc))
                break

            move = legal.get(best)
            if move is None:
                fault(mover_white, FAULT_ILLEGAL,
                      "illegal move %r in position %s" % (best, board_to_fen(board)))
                break
            board = make_move(board, move)
            moves_uci.append(best)
            key = repetition_key(board)
            seen_positions[key] = seen_positions.get(key, 0) + 1
    finally:
        for client in clients.values():
            client.close()

    record["moves"] = moves_uci
    record["plies"] = len(moves_uci)
    record["final_fen"] = board_to_fen(board)
    return record


def play_match(candidate_cmd, opponent_cmd, *, games=2, movetime_ms=100,
               max_plies=200, grace_ms=3000, candidate_name="candidate",
               opponent_name="opponent", start_fens=None, base_seed=1,
               candidate_cwd=None, games_text_path=None, openings=None,
               opponent_uci_options=None, candidate_uci_options=None):
    """Alternating-color match. Returns a JSON-serializable match report
    with results from the candidate's perspective.

    openings: list of {"id", "start_fen"} dicts; consecutive game pairs use
    the same opening with colors swapped, so each opening is played by the
    candidate as both white and black. Overrides start_fens when given.
    """
    if openings:
        start_fens = [o["start_fen"] for o in openings]
        opening_ids = [o["id"] for o in openings]
    else:
        start_fens = list(start_fens or [START_FEN])
        opening_ids = [None] * len(start_fens)
    report = {
        "schema": "ceb.match.report/v1",
        "candidate": candidate_name,
        "opponent": opponent_name,
        "games_planned": games,
        "movetime_ms": movetime_ms,
        "max_plies": max_plies,
        "openings": [oid for oid in opening_ids if oid is not None],
        "games": [],
        "totals": {"wins": 0, "draws": 0, "losses": 0},
        "candidate_faults": {FAULT_ILLEGAL: 0, FAULT_TIMEOUT: 0, FAULT_CRASH: 0},
        "opponent_faults": {FAULT_ILLEGAL: 0, FAULT_TIMEOUT: 0, FAULT_CRASH: 0},
        "elapsed_s": None,
    }
    started = time.monotonic()
    game_texts = []

    for i in range(games):
        candidate_white = i % 2 == 0
        pair = (i // 2) % len(start_fens)
        start_fen = start_fens[pair]
        if candidate_white:
            rec = play_game(candidate_cmd, opponent_cmd, start_fen=start_fen,
                            movetime_ms=movetime_ms, max_plies=max_plies,
                            grace_ms=grace_ms, white_name=candidate_name,
                            black_name=opponent_name, seed=base_seed + i,
                            cwds=(candidate_cwd, None),
                            white_options=candidate_uci_options,
                            black_options=opponent_uci_options)
        else:
            rec = play_game(opponent_cmd, candidate_cmd, start_fen=start_fen,
                            movetime_ms=movetime_ms, max_plies=max_plies,
                            grace_ms=grace_ms, white_name=opponent_name,
                            black_name=candidate_name, seed=base_seed + i,
                            cwds=(None, candidate_cwd),
                            white_options=opponent_uci_options,
                            black_options=candidate_uci_options)
        rec["candidate_color"] = "white" if candidate_white else "black"
        rec["opening_id"] = opening_ids[pair]
        report["games"].append(rec)

        if rec["result"] == RESULT_DRAW:
            report["totals"]["draws"] += 1
        elif (rec["result"] == RESULT_WHITE) == candidate_white:
            report["totals"]["wins"] += 1
        else:
            report["totals"]["losses"] += 1

        if rec["fault"]:
            fault_is_candidate = (rec["fault"]["side"] == "white") == candidate_white
            bucket = "candidate_faults" if fault_is_candidate else "opponent_faults"
            report[bucket][rec["fault"]["kind"]] += 1

        game_texts.append(game_to_text(
            rec["white"], rec["black"], rec["result"], rec["moves"],
            start_fen=start_fen, reason=rec["reason"]))

    report["elapsed_s"] = round(time.monotonic() - started, 2)
    if games_text_path:
        write_games_text(games_text_path, game_texts)
        report["games_text"] = str(games_text_path)
    return report
