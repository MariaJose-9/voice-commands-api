"""Runtime validation helpers for SET_SIZE command payloads."""

from __future__ import annotations

from app import config


DEFAULT_ALLOWED_SIZE_INCHES = [55, 65, 75, 95, 120]


def _get_runtime_bool(key: str, default: bool) -> bool:
    try:
        from app.services import runtime_settings_service

        return runtime_settings_service.get_runtime_bool_setting(key, default)
    except Exception:
        return default


def _get_runtime_int(key: str, default: int) -> int:
    try:
        from app.services import runtime_settings_service

        return runtime_settings_service.get_runtime_int_setting(key, default)
    except Exception:
        return default


def _get_runtime_int_list(key: str, default: list[int]) -> list[int]:
    try:
        from app.services import runtime_settings_service

        values = runtime_settings_service.get_runtime_list_setting(
            key,
            [str(value) for value in default],
        )
    except Exception:
        return default

    parsed: list[int] = []
    for value in values:
        try:
            parsed.append(int(str(value).strip()))
        except (TypeError, ValueError):
            continue
    return parsed or default


def is_valid_size_inches(size: int) -> bool:
    """Return whether a size in inches is allowed by runtime configuration."""

    if isinstance(size, bool) or not isinstance(size, int):
        return False
    if size <= 0:
        return False

    allow_dynamic = _get_runtime_bool(
        "ALLOW_DYNAMIC_SIZE_INCHES",
        config.ALLOW_DYNAMIC_SIZE_INCHES,
    )
    if allow_dynamic:
        min_size = _get_runtime_int("MIN_SIZE_INCHES", config.MIN_SIZE_INCHES)
        max_size = _get_runtime_int("MAX_SIZE_INCHES", config.MAX_SIZE_INCHES)
        return min_size <= size <= max_size

    allowed_sizes = _get_runtime_int_list(
        "ALLOWED_SIZE_INCHES",
        config.ALLOWED_SIZE_INCHES or DEFAULT_ALLOWED_SIZE_INCHES,
    )
    allowed_with_legacy_defaults = set(allowed_sizes) | set(DEFAULT_ALLOWED_SIZE_INCHES)
    return size in allowed_with_legacy_defaults
