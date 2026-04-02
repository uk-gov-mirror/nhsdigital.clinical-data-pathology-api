from contextvars import ContextVar

_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")


def set_correlation_id(value: str) -> None:
    """Set the correlation ID for the current request context."""
    _correlation_id.set(value)


def reset_correlation_id() -> None:
    """Reset the correlation ID to the default empty string."""
    _correlation_id.set("")


def get_correlation_id() -> str:
    """Get the correlation ID for the current request context."""
    return _correlation_id.get()
