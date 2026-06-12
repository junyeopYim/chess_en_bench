"""Hidden-safe error handling.

Errors that may describe hidden evaluation data carry two messages:

  public_message  — safe for agent-facing output (CLI, feedback, reports):
                    category + row id (when configured safe) + "content
                    withheld". Never FENs, move sequences, file paths beyond
                    a basename, or tracebacks.
  private_message — full detail for operator logs and private artifacts.

sanitize_exception() maps any exception to its public form; unknown
exception types are reduced to their class name because arbitrary messages
may embed positions (e.g. ValueError from FEN parsing).

Set CEB_DEBUG=1 to let the CLI re-raise full tracebacks (operator use only;
never in hosted agent-facing services).
"""

import os

DEBUG_ENV = "CEB_DEBUG"


class SanitizedError(Exception):
    """Base for errors with separate public/private messages."""

    def __init__(self, public_message, private_message=None):
        super().__init__(public_message)
        self.public_message = public_message
        self.private_message = private_message or public_message


def debug_enabled(environ=None):
    return bool((environ or os.environ).get(DEBUG_ENV))


def sanitize_exception(exc):
    """Public-safe one-line description of any exception."""
    if isinstance(exc, SanitizedError):
        return exc.public_message
    public = getattr(exc, "public_message", None)
    if isinstance(public, str) and public:
        return public
    # Arbitrary exception messages may quote hidden content; withhold them.
    return ("internal error (%s); details withheld — operators can rerun "
            "with %s=1" % (type(exc).__name__, DEBUG_ENV))


def private_detail(exc):
    """Operator-facing detail (for private artifacts/logs)."""
    if isinstance(exc, SanitizedError):
        return exc.private_message
    return "%s: %s" % (type(exc).__name__, exc)
