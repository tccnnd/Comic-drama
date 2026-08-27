"""Shared configuration utility functions.

Centralizes environment variable access and value coercion helpers that
were previously duplicated across scripts/ and backend/.
"""

from __future__ import annotations

import os


def env_value(*names: str, default: str = "") -> str:
    """Return the first non-empty environment variable from *names*."""
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return default


def env_optional_value(name: str, default: str = "") -> str:
    """Return *name*'s value if the variable is set (even if empty)."""
    if name in os.environ:
        return os.environ.get(name, "").strip()
    return default


def env_float(*names: str, default: float) -> float:
    """Return the first parseable float environment variable from *names*."""
    raw = env_value(*names, default="")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def env_bool(*names: str, default: bool = False) -> bool:
    """Return the first truthy environment variable from *names*."""
    raw = env_value(*names, default="")
    if not raw:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def coerce_int(value: object, default: int, minimum: int, maximum: int) -> int:
    """Coerce *value* to int, clamped to [minimum, maximum]."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def coerce_float(value: object, default: float, minimum: float, maximum: float) -> float:
    """Coerce *value* to float, clamped to [minimum, maximum]."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def coerce_bool(value: object, default: bool = False) -> bool:
    """Coerce *value* to bool, accepting common truthy/falsy string forms."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raw = str(value).strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default
