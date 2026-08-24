from typing import Callable

from app.core.errors import AppError
from app.core.urls import PublicUrlError, resolve_host, validate_public_url as validate_target
from app.sourcing.constants import BLOCKED_HOSTS


class SourcePolicyError(AppError, ValueError):
    pass


def validate_public_url(
    url: str,
    resolver: Callable[[str], list[str]] = resolve_host,
) -> str:
    """Reject credentials, unusual ports, configured blocked hosts, and non-public targets."""
    try:
        return validate_target(
            url,
            schemes={"http", "https"},
            ports={80, 443},
            blocked_hosts=BLOCKED_HOSTS,
            resolver=resolver,
        )
    except PublicUrlError as error:
        raise SourcePolicyError(str(error)) from error
