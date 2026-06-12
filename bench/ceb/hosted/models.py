"""Schema names and status vocabularies for the hosted pipeline.

Schemas are versioned. v2 adds the evaluation `profile`, the
`verification_grade`, and Track B hosted support over the v1 shapes; the
verifier still accepts v1 result files for backward compatibility.
"""

# Result/leaderboard/job schemas (v2: profile + verification_grade + Track B).
SCHEMA_OFFICIAL_RESULT = "ceb.hosted.official_result/v2"
SCHEMA_OFFICIAL_RESULT_V1 = "ceb.hosted.official_result/v1"  # legacy, still verifiable
SCHEMA_TRACK_B_RESULT = "ceb.track_b.official_result/v1"
SCHEMA_LEADERBOARD = "ceb.hosted.leaderboard/v2"
SCHEMA_JOB = "ceb.hosted.job/v2"
SCHEMA_VERIFICATION = "ceb.hosted.verification/v1"

# Job kinds the worker can claim.
JOB_KIND_TRACK_A = "official_eval"
JOB_KIND_TRACK_B = "track_b_official_eval"
JOB_KINDS = (JOB_KIND_TRACK_A, JOB_KIND_TRACK_B)

JOB_STATUSES = ("queued", "running", "done", "failed")
RUN_STATUSES = ("created", "evaluating", "done")

# Round modes that may appear on a result row. quick is never verified.
EVAL_MODES = ("quick", "official_round", "final_eval", "final_production",
              "track_b_official")
VERIFIED_MODES = ("official_round", "final_eval", "final_production",
                  "track_b_official")

# Evaluation profiles (see ceb.hosted.profiles for the authoritative mapping).
PROFILES = ("smoke", "official", "final-production")

ARTIFACT_VISIBILITIES = ("public", "private", "admin")
