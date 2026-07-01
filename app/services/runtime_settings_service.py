"""Runtime settings lookup with database fallback support."""

from __future__ import annotations

from typing import Any

try:
    from sqlmodel import select
except ImportError:  # pragma: no cover
    select = None
    AppSetting = None
    SessionFactory = None
    engine = None
else:  # pragma: no cover
    try:
        from app.db.models import AppSetting
        from app.db.session import Session as SessionFactory, engine
    except Exception:
        AppSetting = None
        SessionFactory = None
        engine = None


def get_runtime_setting(key: str, default: Any) -> Any:
    """Read a runtime setting from DB when available, else return default."""

    if select is None or AppSetting is None or SessionFactory is None or engine is None:
        return default

    try:
        with SessionFactory(engine) as session:
            setting = session.exec(select(AppSetting).where(AppSetting.key == key)).first()
    except Exception:
        return default

    if setting is None or setting.value is None:
        return default
    return setting.value


def get_float_setting(key: str, default: float) -> float:
    value = get_runtime_setting(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def get_bool_setting(key: str, default: bool) -> bool:
    value = get_runtime_setting(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def get_int_setting(key: str, default: int) -> int:
    value = get_runtime_setting(key, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def get_str_setting(key: str, default: str) -> str:
    value = get_runtime_setting(key, default)
    if value is None:
        return default
    return str(value)


def get_list_setting(key: str, default: list[str]) -> list[str]:
    value = get_runtime_setting(key, default)
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        parts = [item.strip() for item in value.split(",")]
        return [item for item in parts if item]
    return default


def get_runtime_str_setting(key: str, default: str) -> str:
    return get_str_setting(key, default)


def get_runtime_bool_setting(key: str, default: bool) -> bool:
    return get_bool_setting(key, default)


def get_runtime_int_setting(key: str, default: int) -> int:
    return get_int_setting(key, default)


def get_runtime_float_setting(key: str, default: float) -> float:
    return get_float_setting(key, default)


def get_runtime_list_setting(key: str, default: list[str]) -> list[str]:
    return get_list_setting(key, default)


def get_audio_bool_setting(key: str, default: bool) -> bool:
    return get_bool_setting(key, default)


def get_audio_int_setting(key: str, default: int) -> int:
    return get_int_setting(key, default)


def get_audio_float_setting(key: str, default: float) -> float:
    return get_float_setting(key, default)


def get_audio_str_setting(key: str, default: str) -> str:
    return get_str_setting(key, default)


def get_audio_list_setting(key: str, default: list[str]) -> list[str]:
    return get_list_setting(key, default)
