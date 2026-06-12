#!/usr/bin/env python3
"""Intentionally broken example: handshakes correctly but never answers a
'go' command. The public gate must fail this engine with a timeout."""

import sys
import time

for raw in sys.stdin:
    tokens = raw.split()
    if not tokens:
        continue
    cmd = tokens[0]
    if cmd == "uci":
        print("id name TimeoutEngine (broken example)")
        print("uciok")
    elif cmd == "isready":
        print("readyok")
    elif cmd == "go":
        time.sleep(3600)  # never produce a bestmove
    elif cmd == "quit":
        break
    sys.stdout.flush()
