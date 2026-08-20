import logging

import pytest

from dealgraph.core.errors import AppError
from dealgraph.core.logging import RequestIdFilter, bind_request_id, request_headers


def test_request_context_is_shared_by_logs_and_http_headers() -> None:
    bind_request_id("req-test")
    record = logging.LogRecord("ida", logging.INFO, __file__, 1, "started", (), None)

    assert RequestIdFilter().filter(record) is True
    assert record.request_id == "req-test"
    assert request_headers() == {
        "User-Agent": "DealGraph/0.1.0 (public research; contact in repository)",
        "X-Kong-Request-ID": "req-test",
    }


def test_tracking_headers_cannot_be_overridden() -> None:
    bind_request_id("req-trusted")

    headers = request_headers(
        {"x-kong-request-id": "attacker", "user-agent": "attacker", "Authorization": "safe"}
    )

    assert {key.lower(): value for key, value in headers.items()} == {
        "authorization": "safe",
        "user-agent": "DealGraph/0.1.0 (public research; contact in repository)",
        "x-kong-request-id": "req-trusted",
    }


@pytest.mark.parametrize("request_id", ["bad\nheader", "x" * 129, "contains space"])
def test_request_id_rejects_log_and_header_injection(request_id: str) -> None:
    with pytest.raises(AppError, match="request ID"):
        bind_request_id(request_id)
