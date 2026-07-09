from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("sqlmodel")

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import app.services.publish_service as publish_service
from app.db.models import (
    AppSetting,
    AuditLog,
    CatalogStatus,
    CatalogVersion,
    CommandDefinition,
    CommandExample,
    CommandParameter,
    EntityType,
    EntityValue,
    EntityValueAlias,
)
from app.schemas import CommandName
from app.services.settings_service import is_catalog_dirty, set_catalog_dirty


def _build_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_publish_catalog_creates_active_version_and_archives_previous(monkeypatch) -> None:
    session = _build_session()
    try:
        command = CommandDefinition(
            code=CommandName.START_STREAM,
            display_name="Start Stream",
            category="Capture / Stream",
            enabled=True,
        )
        session.add(command)
        session.commit()
        session.refresh(command)
        session.add(
            CommandExample(
                command_id=command.id,
                phrase="start stream",
                normalized_phrase="start stream",
                enabled=True,
            )
        )
        entity_type = EntityType(code="monitor", display_name="Monitor", enabled=True)
        session.add(entity_type)
        session.commit()
        session.refresh(entity_type)
        value = EntityValue(
            entity_type_id=entity_type.id,
            value="1",
            label="Monitor 1",
            enabled=True,
        )
        session.add(value)
        session.commit()
        session.refresh(value)
        session.add(
            EntityValueAlias(
                entity_value_id=value.id,
                phrase="monitor one",
                normalized_phrase="monitor one",
                enabled=True,
            )
        )
        session.add(AppSetting(key="FUZZY_THRESHOLD", value="88"))
        session.add(
            CatalogVersion(
                version_number=1,
                status=CatalogStatus.ACTIVE,
                snapshot_json={"commands": []},
            )
        )
        session.commit()
        set_catalog_dirty(session, True)

        monkeypatch.setattr(publish_service, "clear_all_runtime_caches", lambda: None)
        monkeypatch.setattr(
            publish_service,
            "rebuild_runtime_indexes",
            lambda: {"catalog_cache_cleared": True, "semantic_rebuilt": True, "semantic": {}},
        )

        result = publish_service.publish_catalog(session, actor_user_id=7)

        versions = session.exec(
            select(CatalogVersion).order_by(CatalogVersion.version_number)
        ).all()
        assert result == {
            "published": True,
            "version_number": 2,
            "commands": 1,
            "examples": 1,
            "semantic_rebuilt": True,
        }
        assert len(versions) == 2
        assert versions[0].status == CatalogStatus.ARCHIVED
        assert versions[1].status == CatalogStatus.ACTIVE
        assert versions[1].created_by == 7
        active_version = publish_service.get_active_version(session)
        assert active_version is not None
        assert active_version.version_number == 2
        assert versions[1].snapshot_json["version_number"] == 2
        assert "commands" in versions[1].snapshot_json
        assert "entities" in versions[1].snapshot_json
        assert "settings" in versions[1].snapshot_json
        assert is_catalog_dirty(session) is False

        audit_logs = session.exec(select(AuditLog)).all()
        assert len(audit_logs) == 1
        assert audit_logs[0].action == "publish_catalog"
    finally:
        session.close()


def test_build_catalog_snapshot_contains_runtime_shapes(monkeypatch) -> None:
    session = _build_session()
    try:
        session.add(AppSetting(key="ENABLE_SEMANTIC_MATCHER", value="true"))
        session.commit()

        monkeypatch.setattr(
            publish_service,
            "get_active_catalog",
            lambda session=None, force_refresh=False: [
                {"command": "START_STREAM", "examples": ["stream"], "priority": 50}
            ],
        )
        monkeypatch.setattr(
            publish_service,
            "get_active_entities",
            lambda force_refresh=False: {"monitor": {"1": ["monitor one"]}},
        )

        snapshot = publish_service.build_catalog_snapshot(session)

        assert snapshot["version_number"] == 1
        assert snapshot["commands"][0]["command"] == "START_STREAM"
        assert snapshot["entities"]["monitor"]["1"] == ["monitor one"]
        assert snapshot["settings"]["ENABLE_SEMANTIC_MATCHER"] == "true"
        assert "published_at" in snapshot
    finally:
        session.close()


def test_publish_catalog_rejects_custom_without_examples(monkeypatch) -> None:
    session = _build_session()
    try:
        command = CommandDefinition(
            code="CUSTOM_NO_EXAMPLES",
            display_name="No Examples",
            command_type="custom",
            status="draft",
            client_action_key="custom_no_examples",
            enabled=True,
        )
        session.add(command)
        session.commit()

        result = publish_service.publish_catalog(session)

        assert result["published"] is False
        assert any(error["field"] == "examples" for error in result["errors"])
        assert publish_service.get_active_version(session) is None
    finally:
        session.close()


def test_publish_catalog_rejects_custom_without_client_action_key() -> None:
    session = _build_session()
    try:
        command = CommandDefinition(
            code="CUSTOM_NO_ACTION",
            display_name="No Action",
            command_type="custom",
            status="draft",
            enabled=True,
        )
        session.add(command)
        session.commit()
        session.refresh(command)
        session.add(
            CommandExample(
                command_id=command.id,
                phrase="do custom",
                normalized_phrase="do custom",
                enabled=True,
            )
        )
        session.commit()

        result = publish_service.publish_catalog(session)

        assert result["published"] is False
        assert any(
            error["field"] == "client_action_key" for error in result["errors"]
        )
    finally:
        session.close()


def test_publish_catalog_valid_custom_becomes_active(monkeypatch) -> None:
    session = _build_session()
    try:
        command = CommandDefinition(
            code="CUSTOM_ROTATE_SCREEN",
            display_name="Rotate Screen",
            command_type="custom",
            status="draft",
            client_action_key="rotate_screen",
            enabled=True,
        )
        session.add(command)
        session.commit()
        session.refresh(command)
        session.add(
            CommandExample(
                command_id=command.id,
                phrase="rotate screen",
                normalized_phrase="rotate screen",
                enabled=True,
            )
        )
        session.commit()
        set_catalog_dirty(session, True)

        monkeypatch.setattr(publish_service, "clear_all_runtime_caches", lambda: None)
        monkeypatch.setattr(
            publish_service,
            "rebuild_runtime_indexes",
            lambda: {"catalog_cache_cleared": True, "semantic_rebuilt": False},
        )

        result = publish_service.publish_catalog(session)

        assert result["published"] is True
        refreshed = session.get(CommandDefinition, command.id)
        assert refreshed is not None
        assert refreshed.status == "active"
        assert publish_service.get_active_version(session) is not None
    finally:
        session.close()


def test_publish_catalog_corrects_core_protected_and_client_action(monkeypatch) -> None:
    session = _build_session()
    try:
        command = CommandDefinition(
            code=CommandName.CAPTURE.value,
            display_name="Capture",
            command_type="core",
            status="active",
            protected=False,
            client_action_key=None,
            enabled=True,
        )
        session.add(command)
        session.commit()
        session.refresh(command)
        session.add(
            CommandExample(
                command_id=command.id,
                phrase="capture",
                normalized_phrase="capture",
                enabled=True,
            )
        )
        session.commit()

        monkeypatch.setattr(publish_service, "clear_all_runtime_caches", lambda: None)
        monkeypatch.setattr(
            publish_service,
            "rebuild_runtime_indexes",
            lambda: {"catalog_cache_cleared": True, "semantic_rebuilt": False},
        )

        result = publish_service.publish_catalog(session)

        assert result["published"] is True
        refreshed = session.get(CommandDefinition, command.id)
        assert refreshed is not None
        assert refreshed.protected is True
        assert refreshed.client_action_key == "capture"
    finally:
        session.close()


def test_publish_catalog_blocks_required_parameter_with_disabled_entity() -> None:
    session = _build_session()
    try:
        entity_type = EntityType(
            code="angle_degrees",
            display_name="Angle",
            enabled=False,
        )
        command = CommandDefinition(
            code="CUSTOM_BAD_PARAM",
            display_name="Bad Param",
            command_type="custom",
            status="draft",
            client_action_key="bad_param",
            enabled=True,
        )
        session.add(entity_type)
        session.add(command)
        session.commit()
        session.refresh(entity_type)
        session.refresh(command)
        session.add(
            CommandExample(
                command_id=command.id,
                phrase="bad param",
                normalized_phrase="bad param",
                enabled=True,
            )
        )
        session.add(
            CommandParameter(
                command_id=command.id,
                slot_name="angle",
                entity_type_id=entity_type.id,
                target_field="angle",
                required=True,
            )
        )
        session.commit()

        result = publish_service.publish_catalog(session)

        assert result["published"] is False
        assert any(
            error["field"] == "parameter.entity_type" for error in result["errors"]
        )
        assert publish_service.get_active_version(session) is None
    finally:
        session.close()
