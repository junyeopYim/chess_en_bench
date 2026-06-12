"""Elo approximation from W/D/L counts.

v0.1 uses the logistic model:
    score_rate = (wins + 0.5 * draws) / games
    delta_elo  = -400 * log10(1 / score_rate - 1)
with the rate clamped away from 0/1 to avoid infinities, and a normal-
approximation confidence interval on the per-game score.
"""

import math


def score_rate(wins, draws, losses):
    games = wins + draws + losses
    if games <= 0:
        raise ValueError("no games")
    return (wins + 0.5 * draws) / games


def clamp_rate(rate, games):
    """Clamp into (0, 1) with a margin that shrinks as games grow."""
    eps = 1.0 / (2.0 * (games + 1))
    return min(max(rate, eps), 1.0 - eps)


def delta_elo(rate):
    """Elo difference implied by a (clamped) score rate."""
    if not 0.0 < rate < 1.0:
        raise ValueError("rate must be strictly inside (0, 1); clamp first")
    return -400.0 * math.log10(1.0 / rate - 1.0)


def delta_elo_from_wdl(wins, draws, losses):
    games = wins + draws + losses
    if games <= 0:
        raise ValueError("no games")
    return delta_elo(clamp_rate(score_rate(wins, draws, losses), games))


def delta_elo_ci(wins, draws, losses, z=1.96):
    """(lo, mid, hi) delta-Elo bounds via a normal approximation on the
    mean per-game score (draws count 0.5)."""
    games = wins + draws + losses
    if games <= 0:
        raise ValueError("no games")
    p = score_rate(wins, draws, losses)
    var = (wins * (1.0 - p) ** 2
           + draws * (0.5 - p) ** 2
           + losses * (0.0 - p) ** 2) / games
    se = math.sqrt(var / games)
    lo = clamp_rate(p - z * se, games)
    mid = clamp_rate(p, games)
    hi = clamp_rate(p + z * se, games)
    return delta_elo(lo), delta_elo(mid), delta_elo(hi)
