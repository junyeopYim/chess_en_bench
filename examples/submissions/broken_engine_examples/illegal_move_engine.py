#!/usr/bin/env python3
"""Intentionally broken example: speaks UCI correctly but always answers
'bestmove e2e5', which is never a legal chess move. The public gate must
fail this engine at the legal-bestmove check."""

import sys

for raw in sys.stdin:
    tokens = raw.split()
    if not tokens:
        continue
    cmd = tokens[0]
    if cmd == "uci":
        print("id name IllegalMoveEngine (broken example)")
        print("uciok")
    elif cmd == "isready":
        print("readyok")
    elif cmd == "go":
        print("bestmove e2e5")
    elif cmd == "quit":
        break
    sys.stdout.flush()
