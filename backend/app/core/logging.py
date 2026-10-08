"""
Application logging setup.

Plain structured-enough console logging. Never log secrets — passwords,
tokens, or connection strings must not appear in log output.
"""

import logging
import sys

from app.core.config import settings

_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | req=%(request_id)s | %(message)s"


def setup_logging() -> None:
    level = logging.DEBUG if settings.DEBUG else logging.INFO

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FORMAT))
    # Inject the per-request correlation id into every log record
    from app.core.middleware import RequestIDFilter
    handler.addFilter(RequestIDFilter())

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = [handler]

    # Quieten noisy third parties; keep SQLAlchemy at WARNING (echo controls SQL)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.DEBUG else logging.WARNING
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
