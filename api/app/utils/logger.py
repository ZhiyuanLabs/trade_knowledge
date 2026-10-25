"""
Centralized structured logger.

Outputs JSON-formatted log lines in production (LOG_FORMAT=json)
and human-readable lines in development (LOG_FORMAT=text, default).

Usage:
    from app.utils.logger import get_logger
    log = get_logger(__name__)

    log.info("retriever.done", new_chunks=5, pool_size=12)
    log.warning("cache.miss", similarity=0.87)
    log.error("llm.timeout", node="planner", error=str(e))
"""

import logging
import os
import sys
import json
from datetime import datetime, timezone


LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FORMAT = os.getenv("LOG_FORMAT", "text").lower()  # "text" | "json"


class _JsonFormatter(logging.Formatter):
    """Emits one JSON object per log line — easy to ingest with any log aggregator."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Merge any extra kwargs passed via log.info("event", key=val)
        extras = {
            k: v
            for k, v in record.__dict__.items()
            if k
            not in {
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process", "message",
                "taskName",
            }
        }
        payload.update(extras)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


class _TextFormatter(logging.Formatter):
    """Human-readable format for local development."""

    LEVEL_COLORS = {
        "DEBUG":    "\033[36m",   # cyan
        "INFO":     "\033[32m",   # green
        "WARNING":  "\033[33m",   # yellow
        "ERROR":    "\033[31m",   # red
        "CRITICAL": "\033[35m",   # magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.LEVEL_COLORS.get(record.levelname, "")
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        base = f"{color}[{record.levelname[0]}]{self.RESET} {ts} [{record.name}] {record.getMessage()}"
        extras = {
            k: v
            for k, v in record.__dict__.items()
            if k
            not in {
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process", "message",
                "taskName",
            }
        }
        if extras:
            base += "  " + "  ".join(f"{k}={v}" for k, v in extras.items())
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


_configured = False


class StructuredLogger:
    """
    Thin wrapper over stdlib logging that accepts structured kwargs directly.

    Example:
        log.info("retriever.done", new_chunks=5, pool_size=12)
    """

    def __init__(self, logger: logging.Logger):
        self._logger = logger

    def _log(self, level: int, msg: str, *args, **kwargs) -> None:
        logging_kwargs: dict = {}
        extra = kwargs.pop("extra", None) or {}

        for key in ("exc_info", "stack_info", "stacklevel"):
            if key in kwargs:
                logging_kwargs[key] = kwargs.pop(key)

        if kwargs:
            extra = {**extra, **kwargs}

        if extra:
            logging_kwargs["extra"] = extra

        self._logger.log(level, msg, *args, **logging_kwargs)

    def debug(self, msg: str, *args, **kwargs) -> None:
        self._log(logging.DEBUG, msg, *args, **kwargs)

    def info(self, msg: str, *args, **kwargs) -> None:
        self._log(logging.INFO, msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs) -> None:
        self._log(logging.WARNING, msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs) -> None:
        self._log(logging.ERROR, msg, *args, **kwargs)

    def critical(self, msg: str, *args, **kwargs) -> None:
        self._log(logging.CRITICAL, msg, *args, **kwargs)

    def exception(self, msg: str, *args, **kwargs) -> None:
        kwargs.setdefault("exc_info", True)
        self._log(logging.ERROR, msg, *args, **kwargs)

    def __getattr__(self, name: str):
        return getattr(self._logger, name)


def _configure_root() -> None:
    global _configured
    if _configured:
        return
    _configured = True

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter() if LOG_FORMAT == "json" else _TextFormatter())

    root = logging.getLogger()
    root.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    # Remove any default handlers added by uvicorn/FastAPI before we configure
    root.handlers.clear()
    root.addHandler(handler)

    # Silence noisy third-party loggers unless DEBUG
    for noisy in ("httpx", "httpcore", "chromadb", "sentence_transformers", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> StructuredLogger:
    """Return a configured structured logger for the given module name."""
    _configure_root()
    return StructuredLogger(logging.getLogger(name))
