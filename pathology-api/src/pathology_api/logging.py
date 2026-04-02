import logging
from typing import Any, Protocol

from aws_lambda_powertools import Logger

from pathology_api.request_context import get_correlation_id


class _CorrelationIdFilter(logging.Filter):
    """Injects the current correlation ID into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = get_correlation_id()
        return True


class LogProvider(Protocol):
    """Protocol defining required contract for a logger."""

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None: ...

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None: ...

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None: ...

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None: ...

    def exception(self, msg: str, *args: Any, **kwargs: Any) -> None: ...


def get_logger(service: str) -> LogProvider:
    """Get a configured logger instance."""
    logger = Logger(service=service, level="DEBUG", serialize_stacktrace=True)
    logger.addFilter(_CorrelationIdFilter())
    return logger
