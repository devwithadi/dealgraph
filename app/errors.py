"""Expected application errors and the single CLI error boundary."""

from __future__ import annotations

import logging
import sys


class AppError(Exception):
    def __init__(self, message: str, *, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def report_cli_error(error: Exception, request_id: str) -> int:
    logger = logging.getLogger("ida")
    if isinstance(error, AppError):
        logger.info("run failed: %s", error)
        message, exit_code = str(error), error.exit_code
    else:
        logger.exception("unexpected run failure")
        message, exit_code = "Unexpected failure. Re-run with --verbose for details.", 1
    print(f"Error [{request_id}]: {message}", file=sys.stderr)
    return exit_code
