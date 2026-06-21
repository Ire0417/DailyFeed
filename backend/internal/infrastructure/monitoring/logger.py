import logging
import json
import sys
from internal.config.settings import settings


class StructuredFormatter(logging.Formatter):
    """A compact structured (JSON) log formatter."""

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        log = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": message,
        }
        if record.exc_info:
            log["exc"] = self.formatException(record.exc_info)
        if getattr(record, "agent", None):
            log["agent"] = record.agent
        if getattr(record, "user_id", None):
            log["user_id"] = record.user_id
        return json.dumps(log, ensure_ascii=False)


_loggers_initialized: set[str] = set()


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if name in _loggers_initialized:
        return logger

    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logger.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    if settings.debug:
        fmt = logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
        )
    else:
        fmt = StructuredFormatter()
    handler.setFormatter(fmt)
    logger.addHandler(handler)
    logger.propagate = False
    _loggers_initialized.add(name)
    return logger


def log_extra(agent: str | None = None, user_id: int | None = None) -> dict:
    extra = {}
    if agent:
        extra["agent"] = agent
    if user_id is not None:
        extra["user_id"] = user_id
    return extra
