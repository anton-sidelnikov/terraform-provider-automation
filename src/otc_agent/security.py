from __future__ import annotations

import hashlib
import ipaddress
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .domain import ChangeRequest


class SecurityViolation(ValueError):
    pass


_INJECTION_SIGNALS = (
    "ignore previous",
    "ignore all instructions",
    "system prompt",
    "developer message",
    "reveal secret",
    "exfiltrate",
    "run shell",
    "execute command",
)
_SECRET = re.compile(
    r"(?i)(authorization:\s*bearer\s+\S+|(?:api[_-]?key|token|password|secret)\s*[:=]\s*\S+)"
)


@dataclass(frozen=True)
class IntakeAssessment:
    digest: str
    injection_signals: tuple[str, ...]
    untrusted: bool = True


def validate_request(request: ChangeRequest) -> IntakeAssessment:
    if not request.service and not request.docs_repository:
        raise SecurityViolation("service or documentation repository must be provided")
    if request.service and len(request.service) > 64:
        raise SecurityViolation("service must contain at most 64 characters")
    if not request.description or len(request.description.encode("utf-8")) > 16_384:
        raise SecurityViolation("description must contain 1..16384 UTF-8 bytes")
    if any(unicodedata.category(ch) == "Cc" and ch not in "\n\r\t" for ch in request.description):
        raise SecurityViolation("description contains disallowed control characters")
    if request.issue_url:
        validate_public_url(request.issue_url, {"github.com"})
    if request.correlation_id and not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", request.correlation_id):
        raise SecurityViolation("correlation_id contains unsupported characters")
    lowered = request.description.casefold()
    signals = tuple(signal for signal in _INJECTION_SIGNALS if signal in lowered)
    digest = hashlib.sha256(request.description.encode("utf-8")).hexdigest()
    return IntakeAssessment(digest=digest, injection_signals=signals)


def validate_public_url(url: str, allowed_hosts: set[str]) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise SecurityViolation("only credential-free HTTPS URLs are allowed")
    host = parsed.hostname.rstrip(".").lower()
    if host not in allowed_hosts:
        raise SecurityViolation(f"host {host!r} is not allow-listed")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if not address.is_global:
        raise SecurityViolation("private, loopback, and link-local addresses are forbidden")


def safe_workspace_path(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    resolved_root = root.resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise SecurityViolation("path escapes the workspace")
    return candidate


def redact(value: str) -> str:
    return _SECRET.sub("[REDACTED]", value)
