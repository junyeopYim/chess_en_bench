"""Schema names and status vocabularies for the hosted pipeline."""

SCHEMA_OFFICIAL_RESULT = "ceb.hosted.official_result/v1"
SCHEMA_LEADERBOARD = "ceb.hosted.leaderboard/v1"

JOB_KINDS = ("official_eval",)
JOB_STATUSES = ("queued", "running", "done", "failed")

RUN_STATUSES = ("created", "evaluating", "done")

EVAL_MODES = ("quick", "official_round", "final_eval")
VERIFIED_MODES = ("official_round", "final_eval")  # quick is never verified

ARTIFACT_VISIBILITIES = ("public", "private", "admin")
