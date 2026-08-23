from __future__ import annotations

import logging
import re
from contextvars import ContextVar
from typing import Mapping
from uuid import uuid4

from app.core.errors import AppError

USER_AGENT = "DealGraph/0.1.0 (public research; contact in repository)"
_request_id: ContextVar[str] = ContextVar("request_id", default="unbound")


def new_request_id() -> str:
    return f"req-{uuid4().hex[:16]}"


def bind_request_id(request_id: str | None = None) -> str:
    value = request_id or new_request_id()
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", value):
        raise AppError("request ID must be 1-128 letters, numbers, dots, colons, or hyphens", exit_code=2)
    _request_id.set(value)
    return value


def current_request_id() -> str:
    return _request_id.get()


def request_headers(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    reserved = {"user-agent", "x-kong-request-id"}
    supplied = {key: value for key, value in (extra or {}).items() if key.lower() not in reserved}
    return {
        **supplied,
        "User-Agent": USER_AGENT,
        "X-Kong-Request-ID": _request_id.get(),
    }


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        return True


def configure_logging(verbose: bool = False) -> logging.Logger:
    logger = logging.getLogger("dealgraph")
    logger.handlers.clear()
    handler = logging.StreamHandler()
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(logging.Formatter("%(levelname)s [%(request_id)s] %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO if verbose else logging.CRITICAL)
    logger.propagate = False
    return logger
