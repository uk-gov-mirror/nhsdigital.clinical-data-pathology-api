import logging
from unittest.mock import patch

import pytest
from aws_lambda_powertools import Logger

from pathology_api.logging import LogProvider, _CorrelationIdFilter, get_logger
from pathology_api.request_context import reset_correlation_id, set_correlation_id


def _make_log_record() -> logging.LogRecord:
    return logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="test message",
        args=(),
        exc_info=None,
    )


class TestCorrelationIdFilter:
    def test_filter_is_a_logging_filter_subclass(self) -> None:
        assert issubclass(_CorrelationIdFilter, logging.Filter)

    def test_filter_always_returns_true(self) -> None:
        f = _CorrelationIdFilter()
        record = _make_log_record()
        assert f.filter(record) is True

    def test_filter_injects_empty_string_when_no_correlation_id_set(self) -> None:
        f = _CorrelationIdFilter()
        record = _make_log_record()
        f.filter(record)
        assert record.correlation_id == ""  # type: ignore[attr-defined]

    def test_filter_injects_active_correlation_id(self) -> None:
        f = _CorrelationIdFilter()
        record = _make_log_record()
        set_correlation_id("abc-123")
        f.filter(record)
        reset_correlation_id()
        assert record.correlation_id == "abc-123"  # type: ignore[attr-defined]

    def test_filter_injects_empty_string_after_correlation_id_reset(
        self,
    ) -> None:
        f = _CorrelationIdFilter()
        set_correlation_id("to-be-cleared")
        record_during = _make_log_record()
        f.filter(record_during)
        assert record_during.correlation_id == "to-be-cleared"  # type: ignore[attr-defined]
        reset_correlation_id()
        record_after = _make_log_record()
        f.filter(record_after)
        assert record_after.correlation_id == ""  # type: ignore[attr-defined]

    def test_filter_uses_get_correlation_id(self) -> None:
        f = _CorrelationIdFilter()
        record = _make_log_record()
        with patch(
            "pathology_api.logging.get_correlation_id", return_value="mocked-id"
        ) as mock_fn:
            f.filter(record)
            mock_fn.assert_called_once()
        assert record.correlation_id == "mocked-id"  # type: ignore[attr-defined]

    def test_filter_overwrites_existing_correlation_id_attribute(self) -> None:
        f = _CorrelationIdFilter()
        record = _make_log_record()
        record.correlation_id = "old-id"
        set_correlation_id("new-id")
        f.filter(record)
        reset_correlation_id()
        assert record.correlation_id == "new-id"  # type: ignore[attr-defined]

    def test_filter_handles_different_correlation_id_values(self) -> None:
        f = _CorrelationIdFilter()
        values = ["uuid-1234-5678", "X-Corr-99", "a" * 100]
        for value in values:
            record = _make_log_record()
            set_correlation_id(value)
            f.filter(record)
            reset_correlation_id()
            assert record.correlation_id == value  # type: ignore[attr-defined]


class TestLogProvider:
    @pytest.mark.parametrize(
        "method", ["debug", "info", "warning", "error", "exception"]
    )
    def test_log_provider_defines_required_methods(self, method: str) -> None:
        assert hasattr(LogProvider, method)


class TestGetLogger:
    def test_returns_powertools_logger_instance(self) -> None:
        logger = get_logger("service-instance-check")
        assert isinstance(logger, Logger)

    def test_service_name_is_set_correctly(self) -> None:
        logger = get_logger("my-pathology-service")
        assert isinstance(logger, Logger)
        assert logger.service == "my-pathology-service"

    def test_different_service_names_produce_distinct_loggers(self) -> None:
        logger_a = get_logger("service-a")
        logger_b = get_logger("service-b")
        assert isinstance(logger_a, Logger)
        assert isinstance(logger_b, Logger)
        assert logger_a.service != logger_b.service

    def test_log_level_is_debug(self) -> None:
        get_logger("service-level-test")
        stdlib_logger = logging.getLogger("service-level-test")
        assert stdlib_logger.level == logging.DEBUG

    @pytest.mark.parametrize(
        "method", ["debug", "info", "warning", "error", "exception"]
    )
    def test_has_callable_method(self, method: str) -> None:
        logger = get_logger(f"service-{method}-method")
        assert callable(getattr(logger, method, None))

    def test_correlation_id_filter_is_registered_on_stdlib_logger(self) -> None:
        get_logger("service-filter-stdlib")
        stdlib_logger = logging.getLogger("service-filter-stdlib")
        assert any(isinstance(f, _CorrelationIdFilter) for f in stdlib_logger.filters)

    def test_correlation_id_filter_is_applied_to_log_records(self) -> None:
        get_logger("service-filter-applied")
        stdlib_logger = logging.getLogger("service-filter-applied")
        record = _make_log_record()
        set_correlation_id("applied-id")
        stdlib_logger.filter(record)
        reset_correlation_id()
        assert record.correlation_id == "applied-id"  # type: ignore[attr-defined]

    def test_correlation_id_filter_injects_empty_string_by_default(self) -> None:
        get_logger("service-filter-empty")
        stdlib_logger = logging.getLogger("service-filter-empty")
        record = _make_log_record()
        stdlib_logger.filter(record)
        assert record.correlation_id == ""  # type: ignore[attr-defined]
