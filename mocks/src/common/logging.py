from aws_lambda_powertools import Logger


def get_logger(name: str) -> Logger:
    """Get a configured logger instance."""
    return Logger(service=name, level="DEBUG", serialize_stacktrace=True)
