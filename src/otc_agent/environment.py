from __future__ import annotations

import os
import re
from pathlib import Path


class EnvironmentError(ValueError):
    pass


_ASSIGNMENT = re.compile(r"(?:export[ \t]+)?([A-Za-z_][A-Za-z0-9_]*)[ \t]*=[ \t]*(.*)")


def load_environment(path: Path | None = None) -> Path | None:
    if path is not None:
        if path.is_symlink() or not path.is_file():
            raise EnvironmentError("environment file must be a regular file")
        _load_file(path)
        return path.resolve()
    discovered = _find_environment_file(Path.cwd())
    if discovered is None:
        return None
    if discovered.is_symlink() or not discovered.is_file():
        raise EnvironmentError("discovered environment file must be a regular file")
    _load_file(discovered)
    return discovered.resolve()


def _find_environment_file(start: Path) -> Path | None:
    current = start.resolve()
    while True:
        candidate = current / ".env"
        if candidate.exists() or candidate.is_symlink():
            return candidate
        if current.parent == current:
            return None
        current = current.parent


def _load_file(path: Path) -> None:
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise EnvironmentError("unable to read environment file as UTF-8") from exc
    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _ASSIGNMENT.fullmatch(line)
        if match is None:
            raise EnvironmentError(f"invalid environment assignment on line {line_number}")
        name, raw_value = match.groups()
        value = _parse_value(raw_value, line_number)
        os.environ.setdefault(name, value)


def _parse_value(raw_value: str, line_number: int) -> str:
    value = raw_value.strip()
    if not value:
        return ""
    if value[0] in {"'", '"'}:
        quote = value[0]
        if len(value) < 2 or value[-1] != quote:
            raise EnvironmentError(f"unterminated environment value on line {line_number}")
        value = value[1:-1]
        if quote == '"':
            value = value.replace(r"\n", "\n").replace(r"\t", "\t").replace(r"\"", '"').replace(r"\\", "\\")
        return value
    comment = re.search(r"[ \t]+#", value)
    return value[: comment.start()].rstrip() if comment else value
