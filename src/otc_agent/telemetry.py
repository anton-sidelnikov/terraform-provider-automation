from __future__ import annotations

import json
import logging
import threading
import time
import uuid
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator

from .security import redact


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": time.time(),
            "severity": record.levelname,
            "message": redact(record.getMessage()),
            "logger": record.name,
        }
        for key in ("trace_id", "span_id", "run_id", "stage", "service"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)


def trace_id_from_traceparent(value: str | None) -> str | None:
    if not value:
        return None
    match = re.fullmatch(r"[\da-f]{2}-([\da-f]{32})-[\da-f]{16}-[\da-f]{2}", value.lower())
    return match.group(1) if match and match.group(1) != "0" * 32 else None


@dataclass
class Metrics:
    _values: dict[tuple[str, tuple[tuple[str, str], ...]], float] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def increment(self, name: str, value: float = 1, **labels: str) -> None:
        key = (name, tuple(sorted(labels.items())))
        with self._lock:
            self._values[key] = self._values.get(key, 0) + value

    def render_prometheus(self) -> str:
        lines: list[str] = []
        with self._lock:
            items = sorted(self._values.items())
        for (name, labels), value in items:
            label_text = ",".join(f'{k}="{_escape(v)}"' for k, v in labels)
            suffix = f"{{{label_text}}}" if label_text else ""
            lines.append(f"otc_agent_{name}{suffix} {value}")
        return "\n".join(lines) + ("\n" if lines else "")


@dataclass(frozen=True)
class Span:
    trace_id: str
    span_id: str
    name: str
    started_at: float


@contextmanager
def span(name: str, *, trace_id: str | None = None) -> Iterator[Span]:
    current = Span(trace_id or uuid.uuid4().hex, uuid.uuid4().hex[:16], name, time.monotonic())
    logger = logging.getLogger("otc_agent.trace")
    logger.info("span.start", extra={"trace_id": current.trace_id, "span_id": current.span_id, "stage": name})
    try:
        yield current
    except Exception:
        logger.exception("span.error", extra={"trace_id": current.trace_id, "span_id": current.span_id, "stage": name})
        raise
    finally:
        logger.info(
            "span.end duration_ms=%.3f",
            (time.monotonic() - current.started_at) * 1000,
            extra={"trace_id": current.trace_id, "span_id": current.span_id, "stage": name},
        )


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
