import logging

from app.logging import RequestIdFilter, bind_request_id, request_headers


def test_request_context_is_shared_by_logs_and_http_headers() -> None:
    bind_request_id("req-test")
    record = logging.LogRecord("ida", logging.INFO, __file__, 1, "started", (), None)

    assert RequestIdFilter().filter(record) is True
    assert record.request_id == "req-test"
    assert request_headers() == {
        "User-Agent": "IDA-case-study/1.0 (public research; contact in repository)",
        "X-Kong-Request-ID": "req-test",
    }
