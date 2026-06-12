"""Hosted evaluation profiles and verification grades (P0.2 / P0.3).

A *profile* is the single source of truth — shared by the worker, the DB, the
API, and the docs — for two decisions:

  1. which round mode (match settings) an evaluation uses, and
  2. whether the result is allowed to be VERIFIED and to appear on the
     official hosted leaderboard.

Profiles:
  smoke             tiny toy config for CI/plumbing. NEVER verified, never on
                    the official leaderboard (diagnostic only).
  official          standard official round; verified when every other gate
                    passes (private pack + scan + strict gate + engine jail +
                    signature).
  final-production  production-scale final evaluation (thousands of games,
                    paired openings); preferred by the leaderboard over
                    official; verified when every other gate passes.

Legacy: the `final-eval` profile maps to the historical final_eval round mode
and is treated as a final-tier verified result.

A profile being `verifiable` is NECESSARY but not SUFFICIENT for a verified
result: the worker still enforces the private eval pack, static scan, strict
gate, engine jail, and signing. A non-verifiable profile (smoke) can NEVER
produce a verified result no matter what flags are passed — there is no
"magic verified".
"""

from ceb.rounds.round_runner import (
    MODE_OFFICIAL, MODE_FINAL, MODE_FINAL_PRODUCTION)

# ----- profile names ----------------------------------------------------------
PROFILE_SMOKE = "smoke"
PROFILE_OFFICIAL = "official"
PROFILE_FINAL_PRODUCTION = "final-production"
PROFILE_FINAL_EVAL = "final-eval"  # legacy alias for the final_eval round mode

# CLI-selectable profiles (legacy final-eval kept out of the menu but accepted).
PROFILE_CHOICES = (PROFILE_SMOKE, PROFILE_OFFICIAL, PROFILE_FINAL_PRODUCTION)

# ----- verification grades (stored on the result + DB row) --------------------
GRADE_DIAGNOSTIC_SMOKE = "diagnostic-smoke"
GRADE_DIAGNOSTIC_UNJAILED = "diagnostic-unjailed"
GRADE_DIAGNOSTIC_UNSIGNED = "diagnostic-unsigned"
GRADE_DIAGNOSTIC_UNTRUSTED_PACK = "diagnostic-untrusted-pack"
GRADE_VERIFIED_OFFICIAL = "verified-official"
GRADE_VERIFIED_FINAL_PRODUCTION = "verified-final-production"
GRADE_VERIFIED_FINAL_EVAL = "verified-final-eval"

# ----- result tiers (leaderboard selection) -----------------------------------
TIER_DIAGNOSTIC = "diagnostic"
TIER_OFFICIAL = "official"
TIER_FINAL = "final"


class Profile:
    """An evaluation profile. Immutable-ish; treat as data."""

    __slots__ = ("name", "mode", "tier", "verifiable", "grade", "tiny_config")

    def __init__(self, name, mode, tier, verifiable, grade, tiny_config=False):
        self.name = name
        self.mode = mode
        self.tier = tier
        self.verifiable = verifiable
        self.grade = grade
        self.tiny_config = tiny_config


PROFILES = {
    PROFILE_SMOKE: Profile(
        PROFILE_SMOKE, MODE_OFFICIAL, TIER_DIAGNOSTIC,
        verifiable=False, grade=GRADE_DIAGNOSTIC_SMOKE, tiny_config=True),
    PROFILE_OFFICIAL: Profile(
        PROFILE_OFFICIAL, MODE_OFFICIAL, TIER_OFFICIAL,
        verifiable=True, grade=GRADE_VERIFIED_OFFICIAL),
    PROFILE_FINAL_PRODUCTION: Profile(
        PROFILE_FINAL_PRODUCTION, MODE_FINAL_PRODUCTION, TIER_FINAL,
        verifiable=True, grade=GRADE_VERIFIED_FINAL_PRODUCTION),
    PROFILE_FINAL_EVAL: Profile(
        PROFILE_FINAL_EVAL, MODE_FINAL, TIER_FINAL,
        verifiable=True, grade=GRADE_VERIFIED_FINAL_EVAL),
}


class ProfileError(ValueError):
    pass


def get_profile(name):
    """Resolve a profile by name. Raises ProfileError for unknown names."""
    profile = PROFILES.get(name)
    if profile is None:
        raise ProfileError(
            "unknown evaluation profile %r (use one of: %s)"
            % (name, ", ".join(PROFILE_CHOICES)))
    return profile


def profile_for_mode(mode):
    """Map a legacy round mode to the closest profile (backward compat)."""
    for profile in (PROFILES[PROFILE_FINAL_PRODUCTION],
                    PROFILES[PROFILE_FINAL_EVAL],
                    PROFILES[PROFILE_OFFICIAL]):
        if profile.mode == mode:
            return profile
    return PROFILES[PROFILE_OFFICIAL]


# ----- result-mode -> tier (used by leaderboard selection) --------------------
# A stored result row carries its round mode; map it to a tier so the
# leaderboard can prefer final-tier results over official-tier ones. "official"
# is the legacy v0.2 record name. track_b_official is the Track B hosted mode.
TRACK_B_OFFICIAL_MODE = "track_b_official"

FINAL_TIER_MODES = frozenset({MODE_FINAL, MODE_FINAL_PRODUCTION})
OFFICIAL_TIER_MODES = frozenset({MODE_OFFICIAL, "official"})
TRACK_B_TIER_MODES = frozenset({TRACK_B_OFFICIAL_MODE})


def result_tier(mode):
    """The leaderboard tier of a stored result row by its mode."""
    if mode in FINAL_TIER_MODES:
        return TIER_FINAL
    if mode in OFFICIAL_TIER_MODES:
        return TIER_OFFICIAL
    if mode in TRACK_B_TIER_MODES:
        # Track B has a single official tier of its own.
        return TIER_FINAL
    return TIER_DIAGNOSTIC
