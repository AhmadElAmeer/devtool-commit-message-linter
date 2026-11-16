"""Load configuration from `.cmlint.toml` or `[tool.cmlint]` in `pyproject.toml`.

    [tool.cmlint]
    types = ["feat", "fix", "docs", "chore"]
    scopes = ["api", "ui", "db"]
    scope-required = true
    header-max-length = 60
    imperative-mood = "error"
    ignore-patterns = ['^v\\d+\\.\\d+\\.\\d+']   # e.g. release-tool commits
"""
from __future__ import annotations

import re
import tomllib
from dataclasses import fields
from pathlib import Path

from .rules import Config


class ConfigError(ValueError):
    pass


FIELDS = {f.name.replace("_", "-"): f for f in fields(Config)}


def from_mapping(data: dict, source: str = "config") -> Config:
    cfg = Config()
    for key, value in data.items():
        if key not in FIELDS:
            raise ConfigError(f"{source}: unknown setting '{key}' (known: {', '.join(sorted(FIELDS))})")
        name = FIELDS[key].name
        default = getattr(cfg, name)
        if isinstance(default, bool):
            ok = isinstance(value, bool)
        elif isinstance(default, int):
            ok = isinstance(value, int) and not isinstance(value, bool) and value > 0
        elif isinstance(default, list):
            ok = isinstance(value, list) and all(isinstance(v, str) and v for v in value)
        else:
            ok = isinstance(value, str)
        if not ok:
            raise ConfigError(f"{source}: '{key}' has an invalid value {value!r}")
        if key == "imperative-mood" and value not in ("error", "warning", "off"):
            raise ConfigError(f"{source}: 'imperative-mood' must be error, warning or off")
        if key == "ignore-patterns":
            for pattern in value:
                try:
                    re.compile(pattern)
                except re.error as exc:
                    raise ConfigError(f"{source}: bad regex in 'ignore-patterns': {pattern!r} ({exc})") from None
        if key == "types" and not value:
            raise ConfigError(f"{source}: 'types' cannot be empty")
        setattr(cfg, name, value)
    return cfg


def find_config(start: Path) -> tuple[Config, str | None]:
    """Search `start` and its parents. Returns the config and the file it came from."""
    for folder in [start, *start.parents]:
        dedicated = folder / ".cmlint.toml"
        if dedicated.is_file():
            return from_mapping(_read(dedicated), str(dedicated)), str(dedicated)
        pyproject = folder / "pyproject.toml"
        if pyproject.is_file():
            section = _read(pyproject).get("tool", {}).get("cmlint")
            if section is not None:
                return from_mapping(section, f"{pyproject} [tool.cmlint]"), str(pyproject)
        if (folder / ".git").exists():
            break          # don't wander out of the repository
    return Config(), None


def _read(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: invalid TOML: {exc}") from None
