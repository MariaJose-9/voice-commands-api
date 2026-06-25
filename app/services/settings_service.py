"""Application settings helpers."""

from __future__ import annotations

from sqlmodel import select

from app.db.models import AppSetting, SettingValueType


CATALOG_DIRTY_KEY = "CATALOG_DIRTY"


def set_catalog_dirty(session, dirty: bool) -> None:
    """Persist the catalog dirty flag in AppSetting."""

    setting = session.exec(
        select(AppSetting).where(AppSetting.key == CATALOG_DIRTY_KEY)
    ).first()
    value = "true" if dirty else "false"

    if setting is None:
        setting = AppSetting(
            key=CATALOG_DIRTY_KEY,
            value=value,
            value_type=SettingValueType.STR,
        )
        session.add(setting)
    else:
        setting.value = value

    session.commit()


def is_catalog_dirty(session) -> bool:
    """Return the persisted catalog dirty flag."""

    setting = session.exec(
        select(AppSetting).where(AppSetting.key == CATALOG_DIRTY_KEY)
    ).first()
    if setting is None:
        return False
    return str(setting.value).strip().lower() == "true"
