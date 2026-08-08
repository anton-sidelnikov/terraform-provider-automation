from __future__ import annotations

from pathlib import Path

from dotenv import find_dotenv, load_dotenv


class EnvironmentError(ValueError):
    pass


def load_environment(path: Path | None = None) -> Path | None:
    if path is not None:
        if path.is_symlink() or not path.is_file():
            raise EnvironmentError("environment file must be a regular file")
        load_dotenv(path, override=False)
        return path.resolve()
    discovered = find_dotenv(usecwd=True)
    if not discovered:
        return None
    value = Path(discovered)
    if value.is_symlink() or not value.is_file():
        raise EnvironmentError("discovered environment file must be a regular file")
    load_dotenv(value, override=False)
    return value.resolve()
