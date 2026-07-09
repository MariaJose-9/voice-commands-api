from __future__ import annotations

import importlib
from io import BytesIO

import pytest
import yaml

pytest.importorskip("sqlalchemy")
pytest.importorskip("sqlmodel")

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import app.main as main_module
from app.audio.schemas import AudioNormalizeResponse, AudioTranscriptionResponse
import app.services.entity_catalog_service as entity_catalog_service
from app.services import command_spec_service
import app.services.publish_service as publish_service
from app.db.models import (
    AppSetting,
    AuditLog,
    CatalogStatus,
    CatalogVersion,
    CommandDefinition,
    CommandExample,
    CommandParameter,
    CommandName,
    EntityType,
    EntityValue,
    EntityValueAlias,
    UserRole,
)
from app.entity_extractor import extract_entities
from app.preprocessor import normalize_text
from app.v2.schemas import DynamicCommand, NormalizeV2Response


admin_router_module = importlib.import_module("app.admin.router")


class FakeUser:
    id = 1
    email = "admin@example.com"
    role = UserRole.ADMIN


@pytest.fixture
def client_with_sqlite(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    monkeypatch.setattr(admin_router_module, "SessionFactory", Session)
    monkeypatch.setattr(admin_router_module, "engine", engine)
    monkeypatch.setattr(admin_router_module, "get_current_admin_user", lambda token: FakeUser())

    return TestClient(main_module.app), engine


def test_admin_commands_page_lists_commands(client_with_sqlite) -> None:
    client, engine = client_with_sqlite
    with Session(engine) as session:
        command = CommandDefinition(
            code=CommandName.START_STREAM,
            display_name="Start Stream",
            category="Capture / Stream",
        )
        session.add(command)
        session.commit()
        session.refresh(command)
        session.add(
            CommandExample(
                command_id=command.id,
                phrase="start stream",
                normalized_phrase="start stream",
            )
        )
        session.commit()

    response = client.get("/admin/commands")
    assert response.status_code == 200
    assert "START_STREAM" in response.text
    assert "Start Stream" in response.text
    assert "New custom command" in response.text
    assert "Type" in response.text
    assert "Status" in response.text
    assert "Protected" in response.text


def test_admin_create_custom_command_valid(client_with_sqlite) -> None:
    client, engine = client_with_sqlite

    response = client.post(
        "/admin/commands/new",
        data={
            "code": "CUSTOM_ROTATE_SCREEN",
            "display_name": "Rotate Screen",
            "description": "Rotate selected screen",
            "category": "Custom",
            "client_action_key": "rotate_screen",
            "priority": "55",
            "min_confidence": "0.75",
            "enabled": "on",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/admin/commands/")

    with Session(engine) as session:
        command = session.exec(
            select(CommandDefinition).where(
                CommandDefinition.code == "CUSTOM_ROTATE_SCREEN"
            )
        ).first()
        assert command is not None
        assert command.display_name == "Rotate Screen"
        assert command.command_type == "custom"
        assert command.status == "draft"
        assert command.protected is False
        assert command.client_action_key == "rotate_screen"
        assert command.priority == 55
        assert command.min_confidence == 0.75
        dirty = session.exec(
            select(AppSetting).where(AppSetting.key == "CATALOG_DIRTY")
        ).first()
        assert dirty is not None
        assert dirty.value == "true"
        audit = session.exec(
            select(AuditLog).where(AuditLog.action == "custom_command_create")
        ).first()
        assert audit is not None
        assert audit.entity_id == command.id


def test_admin_create_custom_command_rejects_invalid_code(client_with_sqlite) -> None:
    client, _engine = client_with_sqlite

    response = client.post(
        "/admin/commands/new",
        data={
            "code": "custom bad",
            "display_name": "Bad Command",
            "client_action_key": "bad_command",
            "priority": "50",
            "min_confidence": "0.72",
            "enabled": "on",
        },
    )

    assert response.status_code == 400
    assert "uppercase letters, numbers, and underscores" in response.text


def test_admin_create_custom_command_rejects_duplicate_code(client_with_sqlite) -> None:
    client, engine = client_with_sqlite
    with Session(engine) as session:
        session.add(
            CommandDefinition(
                code="CUSTOM_DUPLICATE",
                display_name="Duplicate",
                command_type="custom",
                status="draft",
                client_action_key="custom_duplicate",
            )
        )
        session.commit()

    response = client.post(
        "/admin/commands/new",
        data={
            "code": "CUSTOM_DUPLICATE",
            "display_name": "Duplicate Again",
            "client_action_key": "custom_duplicate_again",
            "priority": "50",
            "min_confidence": "0.72",
            "enabled": "on",
        },
    )

    assert response.status_code == 400
    assert "Code already exists" in response.text


def test_admin_create_custom_command_rejects_core_code(client_with_sqlite) -> None:
    client, _engine = client_with_sqlite

    response = client.post(
        "/admin/commands/new",
        data={
            "code": "SELECT_MONITOR",
            "display_name": "Select Monitor Override",
            "client_action_key": "select_monitor_override",
            "priority": "50",
            "min_confidence": "0.72",
            "enabled": "on",
        },
    )

    assert response.status_code == 400
    assert "protected core command" in response.text


def test_admin_core_protected_command_cannot_be_deleted(client_with_sqlite) -> None:
    client, engine = client_with_sqlite
    with Session(engine) as session:
        command = CommandDefinition(
            code=CommandName.START_STREAM.value,
            display_name="Start Stream",
            command_type="core",
            status="active",
            protected=True,
        )
        session.add(command)
        session.commit()
        session.refresh(command)
        command_id = command.id

    response = client.post(f"/admin/commands/{command_id}/delete")

    assert response.status_code == 400
    assert "Only unprotected custom draft commands" in response.text
    with Session(engine) as session:
        assert session.get(CommandDefinition, command_id) is not None


def test_admin_core_protected_command_update_does_not_change_code_or_type(
    client_with_sqlite,
) -> None:
    client, engine = client_with_sqlite
    with Session(engine) as session:
        command = CommandDefinition(
            code=CommandName.CAPTURE.value,
            display_name="Capture",
            command_type="core",
            status="active",
            protected=True,
        )
        session.add(command)
        session.commit()
        session.refresh(command)
        command_id = command.id

    response = client.post(
        f"/admin/commands/{command_id}/update",
        data={
            "code": "CUSTOM_CAPTURE",
            "command_type": "custom",
            "display_name": "Capture Updated",
            "description": "",
            "category": "Capture / Stream",
            "priority": "75",
            "min_confidence": "0.8",
            "enabled": "on",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    with Session(engine) as session:
        command = session.get(CommandDefinition, command_id)
        assert command is not None
        assert command.code == CommandName.CAPTURE.value
        assert command.command_type == "core"
        assert command.display_name == "Capture Updated"


def test_admin_custom_draft_can_be_deleted(client_with_sqlite) -> None:
    client, engine = client_with_sqlite
    with Session(engine) as session:
        command = CommandDefinition(
            code="CUSTOM_DRAFT_DELETE",
            display_name="Draft Delete",
            command_type="custom",
            status="draft",
            protected=False,
        )
        session.add(command)
        session.commit()
        session.refresh(command)
        command_id = command.id

    response = client.post(f"/admin/commands/{command_id}/delete", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/commands"
    with Session(engine) as session:
        assert session.get(CommandDefinition, command_id) is None
        dirty = session.exec(
            select(AppSetting).where(AppSetting.key == "CATALOG_DIRTY")
        ).first()
        assert dirty is not None
        assert dirty.value == "true"


def test_admin_custom_active_deprecates_and_cannot_be_deleted(
    client_with_sqlite,
) -> None:
    client, engine = client_with_sqlite
    with Session(engine) as session:
        command = CommandDefinition(
            code="CUSTOM_ACTIVE",
            display_name="Active Custom",
            command_type="custom",
            status="active",
            protected=False,
        )
        session.add(command)
        session.commit()
        session.refresh(command)
        command_id = command.id

    delete_response = client.post(f"/admin/commands/{command_id}/delete")
    assert delete_response.status_code == 400

    deprecate_response = client.post(
        f"/admin/commands/{command_id}/deprecate",
        follow_redirects=False,
    )
    assert deprecate_response.status_code == 303

    with Session(engine) as session:
        command = session.get(CommandDefinition, command_id)
        assert command is not None
        assert command.status == "deprecated"
        assert command.enabled is False
        dirty = session.exec(
            select(AppSetting).where(AppSetting.key == "CATALOG_DIRTY")
        ).first()
        assert dirty is not None
        assert dirty.value == "true"


def test_admin_disabled_command_not_in_active_specs(
    client_with_sqlite,
    monkeypatch,
) -> None:
    _client, engine = client_with_sqlite
    monkeypatch.setattr(command_spec_service, "SessionFactory", Session)
    monkeypatch.setattr(command_spec_service, "engine", engine)
    command_spec_service.clear_command_spec_cache()
    with Session(engine) as session:
        session.add(
            CommandDefinition(
                code="CUSTOM_DISABLED_SPEC",
                display_name="Disabled Spec",
                command_type="custom",
                status="disabled",
                enabled=False,
            )
        )
        session.commit()

    specs = command_spec_service.get_active_command_specs(force_refresh=True)

    assert all(spec.code != "CUSTOM_DISABLED_SPEC" for spec in specs)


def test_admin_command_detail_renders_parameters_section(client_with_sqlite) -> None:
    client, engine = client_with_sqlite
    with Session(engine) as session:
        command = CommandDefinition(
            code="CUSTOM_PARAM_RENDER",
            display_name="Param Render",
            command_type="custom",
            status="draft",
        )
        entity_type = EntityType(code="distance", display_name="Distance", enabled=True)
        session.add(command)
        session.add(entity_type)
        session.commit()
        session.refresh(command)
        session.refresh(entity_type)
        session.add(
            CommandParameter(
                command_id=command.id,
                slot_name="distance",
                entity_type_id=entity_type.id,
                target_field="value",
                extraction_hint="Extract distance.",
            )
        )
        session.commit()
        command_id = command.id

    response = client.get(f"/admin/commands/{command_id}")

    assert response.status_code == 200
    assert "Parameters / Entities" in response.text
    assert "distance" in response.text
    assert "Extract distance." in response.text


def test_admin_add_parameter_to_custom_command(client_with_sqlite) -> None:
    client, engine = client_with_sqlite
    with Session(engine) as session:
        command = CommandDefinition(
            code="CUSTOM_PARAM_ADD",
            display_name="Param Add",
            command_type="custom",
            status="draft",
        )
        entity_type = EntityType(code="angle_degrees", display_name="Angle", enabled=True)
        session.add(command)
        session.add(entity_type)
        session.commit()
        session.refresh(command)
        session.refresh(entity_type)
        command_id = command.id
        entity_type_id = entity_type.id

    response = client.post(
        f"/admin/commands/{command_id}/parameters",
        data={
            "slot_name": "angle",
            "entity_type_id": str(entity_type_id),
            "target_field": "angle",
            "required": "on",
            "allow_multiple": "",
            "default_value": "90",
            "description": "Rotation angle",
            "extraction_hint": "Extract degrees",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/admin/commands/{command_id}"
    with Session(engine) as session:
        parameter = session.exec(select(CommandParameter)).first()
        assert parameter is not None
        assert parameter.slot_name == "angle"
        assert parameter.target_field == "angle"
        assert parameter.required is True
        assert parameter.default_value == "90"
        dirty = session.exec(
            select(AppSetting).where(AppSetting.key == "CATALOG_DIRTY")
        ).first()
        assert dirty is not None
        assert dirty.value == "true"


def test_admin_add_parameter_rejects_duplicate_slot_name(client_with_sqlite) -> None:
    client, engine = client_with_sqlite
    with Session(engine) as session:
        command = CommandDefinition(
            code="CUSTOM_PARAM_DUP",
            display_name="Param Dup",
            command_type="custom",
            status="draft",
        )
        entity_type = EntityType(code="distance", display_name="Distance", enabled=True)
        session.add(command)
        session.add(entity_type)
        session.commit()
        session.refresh(command)
        session.refresh(entity_type)
        session.add(
            CommandParameter(
                command_id=command.id,
                slot_name="amount",
                entity_type_id=entity_type.id,
                target_field="value",
            )
        )
        session.commit()
        command_id = command.id
        entity_type_id = entity_type.id

    response = client.post(
        f"/admin/commands/{command_id}/parameters",
        data={
            "slot_name": "amount",
            "entity_type_id": str(entity_type_id),
            "target_field": "value",
        },
    )

    assert response.status_code == 400
    assert "already exists" in response.text


def test_admin_cannot_delete_required_parameter_from_core_protected(
    client_with_sqlite,
) -> None:
    client, engine = client_with_sqlite
    with Session(engine) as session:
        command = CommandDefinition(
            code=CommandName.SELECT_MONITOR.value,
            display_name="Select Monitor",
            command_type="core",
            status="active",
            protected=True,
        )
        entity_type = EntityType(code="monitor", display_name="Monitor", enabled=True)
        session.add(command)
        session.add(entity_type)
        session.commit()
        session.refresh(command)
        session.refresh(entity_type)
        parameter = CommandParameter(
            command_id=command.id,
            slot_name="monitor",
            entity_type_id=entity_type.id,
            target_field="monitor",
            required=True,
        )
        session.add(parameter)
        session.commit()
        session.refresh(parameter)
        parameter_id = parameter.id

    response = client.post(f"/admin/command-parameters/{parameter_id}/delete")

    assert response.status_code == 400
    assert "cannot be deleted" in response.text
    with Session(engine) as session:
        assert session.get(CommandParameter, parameter_id) is not None


def test_admin_deletes_custom_draft_parameter(client_with_sqlite) -> None:
    client, engine = client_with_sqlite
    with Session(engine) as session:
        command = CommandDefinition(
            code="CUSTOM_PARAM_DELETE",
            display_name="Param Delete",
            command_type="custom",
            status="draft",
        )
        entity_type = EntityType(code="distance", display_name="Distance", enabled=True)
        session.add(command)
        session.add(entity_type)
        session.commit()
        session.refresh(command)
        session.refresh(entity_type)
        parameter = CommandParameter(
            command_id=command.id,
            slot_name="distance",
            entity_type_id=entity_type.id,
            target_field="value",
        )
        session.add(parameter)
        session.commit()
        session.refresh(parameter)
        command_id = command.id
        parameter_id = parameter.id

    response = client.post(
        f"/admin/command-parameters/{parameter_id}/delete",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/admin/commands/{command_id}"
    with Session(engine) as session:
        assert session.get(CommandParameter, parameter_id) is None


def test_admin_add_example_sets_normalized_phrase_and_dirty_flag(client_with_sqlite) -> None:
    client, engine = client_with_sqlite
    with Session(engine) as session:
        command = CommandDefinition(
            code=CommandName.SHOW_VOICE_COMMANDS,
            display_name="Show Voice Commands",
            category="Panels / UI",
        )
        session.add(command)
        session.commit()
        session.refresh(command)
        command_id = command.id

    response = client.post(
        f"/admin/commands/{command_id}/examples",
        data={
            "phrase": "Open Commands Panel",
            "language": "en",
            "match_type": "semantic",
            "enabled": "on",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"/admin/commands/{command_id}"

    with Session(engine) as session:
        example = session.exec(select(CommandExample)).first()
        assert example is not None
        assert example.phrase == "Open Commands Panel"
        assert example.normalized_phrase == "open commands panel"
        assert example.source.value == "admin"

        dirty = session.exec(select(AppSetting).where(AppSetting.key == "CATALOG_DIRTY")).first()
        assert dirty is not None
        assert dirty.value == "true"


def test_admin_create_entity_alias_and_extractor_uses_it(client_with_sqlite, monkeypatch) -> None:
    client, engine = client_with_sqlite
    monkeypatch.setattr(entity_catalog_service, "SessionFactory", Session)
    monkeypatch.setattr(entity_catalog_service, "engine", engine)

    with Session(engine) as session:
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
        entity_type_id = entity_type.id
        value_id = value.id

    response = client.post(
        f"/admin/entity-values/{value_id}/aliases",
        data={"phrase": "display alpha", "language": "en", "enabled": "on"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"/admin/entities/{entity_type_id}"

    with Session(engine) as session:
        alias = session.exec(select(EntityValueAlias)).first()
        assert alias is not None
        assert alias.normalized_phrase == "display alpha"
        assert alias.enabled is True

    entity_catalog_service.clear_entity_catalog_cache()
    entities = extract_entities(normalize_text("use display alpha"))
    assert entities["monitor"] == 1


def test_admin_toggle_entity_alias_disables_it(client_with_sqlite, monkeypatch) -> None:
    client, engine = client_with_sqlite
    monkeypatch.setattr(entity_catalog_service, "SessionFactory", Session)
    monkeypatch.setattr(entity_catalog_service, "engine", engine)

    with Session(engine) as session:
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
        alias = EntityValueAlias(
            entity_value_id=value.id,
            phrase="display beta",
            normalized_phrase="display beta",
            enabled=True,
        )
        session.add(alias)
        session.commit()
        session.refresh(alias)
        alias_id = alias.id

    response = client.post(
        f"/admin/entity-aliases/{alias_id}/toggle",
        follow_redirects=False,
    )
    assert response.status_code == 303

    with Session(engine) as session:
        alias = session.get(EntityValueAlias, alias_id)
        assert alias is not None
        assert alias.enabled is False


def test_admin_tester_save_example_marks_catalog_dirty(client_with_sqlite) -> None:
    client, engine = client_with_sqlite
    with Session(engine) as session:
        command = CommandDefinition(
            code=CommandName.START_STREAM,
            display_name="Start Stream",
            category="Capture / Stream",
        )
        session.add(command)
        session.commit()
        session.refresh(command)
        command_id = command.id

    response = client.post(
        "/admin/tester/save-example",
        data={
            "phrase": "Start Broadcast",
            "command_id": str(command_id),
            "language": "en",
            "match_type": "semantic",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/tester"

    with Session(engine) as session:
        example = session.exec(select(CommandExample)).first()
        assert example is not None
        assert example.phrase == "Start Broadcast"
        assert example.normalized_phrase == "start broadcast"
        assert example.source.value == "admin"

        dirty = session.exec(
            select(AppSetting).where(AppSetting.key == "CATALOG_DIRTY")
        ).first()
        assert dirty is not None
        assert dirty.value == "true"


def test_admin_tester_v2_renderizes_selector(client_with_sqlite) -> None:
    client, _engine = client_with_sqlite

    response = client.get("/admin/tester")

    assert response.status_code == 200
    assert "API Version" in response.text
    assert "Client Capabilities" in response.text
    assert 'value="v2"' in response.text


def test_admin_tester_v2_shows_custom_command(
    client_with_sqlite,
    monkeypatch,
) -> None:
    client, engine = client_with_sqlite
    with Session(engine) as session:
        session.add(
            CommandDefinition(
                code="ROTATE_SCREEN",
                display_name="Rotate Screen",
                command_type="custom",
                status="active",
                client_action_key="rotate_screen",
            )
        )
        session.commit()

    monkeypatch.setattr(
        admin_router_module,
        "normalize_command_text_v2",
        lambda **kwargs: NormalizeV2Response(
            ok=True,
            raw_text=kwargs["text"],
            normalized_text=kwargs["text"].lower(),
            language=kwargs.get("language_hint"),
            commands=[
                DynamicCommand(
                    code="ROTATE_SCREEN",
                    type="custom",
                    client_action_key="rotate_screen",
                    confidence=0.91,
                    method="llm",
                    params={"angle": 90},
                    raw_fragment="rota noventa grados",
                )
            ],
            needs_confirmation=False,
        ),
    )

    response = client.post(
        "/admin/tester/run",
        data={
            "text": "rota pantalla dos noventa grados",
            "language_hint": "es",
            "api_version": "v2",
            "client_capabilities": '["rotate_screen"]',
        },
    )

    assert response.status_code == 200
    assert "Dynamic Commands" in response.text
    assert "ROTATE_SCREEN" in response.text
    assert "rotate_screen" in response.text
    assert "Save phrase as example" in response.text


def test_admin_tester_save_example_for_custom_command(client_with_sqlite) -> None:
    client, engine = client_with_sqlite
    with Session(engine) as session:
        command = CommandDefinition(
            code="ROTATE_SCREEN",
            display_name="Rotate Screen",
            command_type="custom",
            status="active",
            client_action_key="rotate_screen",
        )
        session.add(command)
        session.commit()
        session.refresh(command)
        command_id = command.id

    response = client.post(
        "/admin/tester/save-example",
        data={
            "phrase": "rota pantalla dos noventa grados",
            "command_id": str(command_id),
            "language": "es",
            "match_type": "semantic",
            "api_version": "v2",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    with Session(engine) as session:
        example = session.exec(select(CommandExample)).first()
        assert example is not None
        assert example.command_id == command_id
        assert example.normalized_phrase == "rota pantalla dos noventa grados"
        assert example.source.value == "admin"


def test_admin_catalog_publish_creates_active_version(client_with_sqlite, monkeypatch) -> None:
    client, engine = client_with_sqlite
    with Session(engine) as session:
        command = CommandDefinition(
            code=CommandName.START_STREAM,
            display_name="Start Stream",
            category="Capture / Stream",
        )
        session.add(command)
        session.commit()
        session.refresh(command)
        session.add(
            CommandExample(
                command_id=command.id,
                phrase="start stream",
                normalized_phrase="start stream",
            )
        )
        session.commit()
        session.add(
            CatalogVersion(
                version_number=1,
                status=CatalogStatus.ACTIVE,
                snapshot_json={"commands": []},
            )
        )
        session.commit()

    monkeypatch.setattr(publish_service, "clear_all_runtime_caches", lambda: None)
    monkeypatch.setattr(
        publish_service,
        "rebuild_runtime_indexes",
        lambda: {"catalog_cache_cleared": True, "semantic_rebuilt": False, "semantic": None},
    )

    response = client.post("/admin/catalog/publish", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/catalog/versions"

    with Session(engine) as session:
        active = session.exec(
            select(CatalogVersion).where(CatalogVersion.status == CatalogStatus.ACTIVE)
        ).all()
        assert len(active) == 1
        assert active[0].version_number == 2


def test_admin_catalog_export_yaml_returns_valid_yaml(client_with_sqlite) -> None:
    client, engine = client_with_sqlite
    with Session(engine) as session:
        command = CommandDefinition(
            code=CommandName.START_STREAM,
            display_name="Start Stream",
            description="Starts streaming",
            category="Capture / Stream",
        )
        session.add(command)
        session.commit()
        session.refresh(command)
        session.add(
            CommandExample(
                command_id=command.id,
                phrase="start stream",
                normalized_phrase="start stream",
            )
        )
        session.commit()

    response = client.get("/admin/catalog/export-yaml")
    assert response.status_code == 200
    payload = yaml.safe_load(response.text)
    assert "commands" in payload
    assert payload["commands"][0]["command"] == "START_STREAM"
    assert "start stream" in payload["commands"][0]["examples"]


def test_admin_catalog_import_yaml_adds_example(client_with_sqlite) -> None:
    client, engine = client_with_sqlite
    with Session(engine) as session:
        command = CommandDefinition(
            code=CommandName.START_STREAM,
            display_name="Start Stream",
            category="Capture / Stream",
        )
        session.add(command)
        session.commit()

    payload = {
        "commands": [
            {
                "command": "START_STREAM",
                "description": "Starts streaming",
                "category": "Capture / Stream",
                "examples": ["begin stream now"],
            }
        ]
    }
    response = client.post(
        "/admin/catalog/import-yaml",
        files={"catalog_file": ("catalog.yml", yaml.safe_dump(payload), "application/x-yaml")},
    )
    assert response.status_code == 200
    assert "Added examples: 1" in response.text

    with Session(engine) as session:
        example = session.exec(
            select(CommandExample).where(
                CommandExample.normalized_phrase == "begin stream now"
            )
        ).first()
        assert example is not None
        dirty = session.exec(
            select(AppSetting).where(AppSetting.key == "CATALOG_DIRTY")
        ).first()
        assert dirty is not None
        assert dirty.value == "true"
        audit = session.exec(select(AuditLog)).first()
        assert audit is not None
        assert audit.action == "import_yaml"


def test_admin_catalog_import_yaml_rejects_invalid_command(client_with_sqlite) -> None:
    client, _engine = client_with_sqlite
    payload = {
        "commands": [
            {
                "command": "NOT_A_REAL_COMMAND",
                "examples": ["whatever"],
            }
        ]
    }
    response = client.post(
        "/admin/catalog/import-yaml",
        files={"catalog_file": ("catalog.yml", yaml.safe_dump(payload), "application/x-yaml")},
    )
    assert response.status_code == 400
    assert "Invalid command: NOT_A_REAL_COMMAND" in response.text


def test_viewer_cannot_publish_catalog(client_with_sqlite, monkeypatch) -> None:
    client, _engine = client_with_sqlite

    class ViewerUser(FakeUser):
        role = UserRole.VIEWER

    monkeypatch.setattr(
        admin_router_module,
        "get_current_admin_user",
        lambda token: ViewerUser(),
    )

    response = client.post("/admin/catalog/publish", follow_redirects=False)
    assert response.status_code == 403


def test_editor_cannot_update_settings(client_with_sqlite, monkeypatch) -> None:
    client, _engine = client_with_sqlite

    class EditorUser(FakeUser):
        role = UserRole.EDITOR

    monkeypatch.setattr(
        admin_router_module,
        "get_current_admin_user",
        lambda token: EditorUser(),
    )

    response = client.post(
        "/admin/settings/update",
        data={"FUZZY_THRESHOLD": "90"},
        follow_redirects=False,
    )
    assert response.status_code == 403


def test_admin_settings_page_shows_audio_fields(client_with_sqlite) -> None:
    client, _engine = client_with_sqlite

    response = client.get("/admin/settings")

    assert response.status_code == 200
    assert "ENABLE_AUDIO_TRANSCRIPTION" in response.text
    assert "TRANSCRIPTION_MODEL_NAME" in response.text
    assert "MAX_AUDIO_FILE_MB" in response.text
    assert "ALLOWED_AUDIO_MIME_TYPES" in response.text
    assert "LLM_COMMAND_MODE" in response.text
    assert "OLLAMA_MODEL" in response.text
    assert "ALLOW_DYNAMIC_SIZE_INCHES" in response.text


def test_admin_settings_update_saves_llm_command_mode(client_with_sqlite) -> None:
    client, engine = client_with_sqlite

    response = client.post(
        "/admin/settings/update",
        data={
            "LLM_COMMAND_MODE": "hybrid",
            "OLLAMA_BASE_URL": "http://localhost:11434",
            "OLLAMA_MODEL": "qwen2.5:3b",
            "OLLAMA_TIMEOUT_SECONDS": "8",
            "LLM_ACCEPT_THRESHOLD": "0.78",
            "LLM_CONFIDENCE_CAP": "0.90",
            "MIN_SIZE_INCHES": "40",
            "MAX_SIZE_INCHES": "150",
            "ALLOWED_SIZE_INCHES": "55,65,72,120",
            "ENABLE_OLLAMA_FALLBACK": "on",
            "ALLOW_DYNAMIC_SIZE_INCHES": "on",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    with Session(engine) as session:
        mode = session.exec(
            select(AppSetting).where(AppSetting.key == "LLM_COMMAND_MODE")
        ).first()
        audit = session.exec(
            select(AuditLog).where(AuditLog.action == "llm_settings_update")
        ).first()
        assert mode is not None
        assert mode.value == "hybrid"
        assert audit is not None
        assert audit.payload_json["runtime_refresh_required"] is True


def test_admin_settings_update_rejects_invalid_llm_mode(client_with_sqlite) -> None:
    client, engine = client_with_sqlite

    response = client.post(
        "/admin/settings/update",
        data={
            "LLM_COMMAND_MODE": "invalid",
            "OLLAMA_TIMEOUT_SECONDS": "8",
            "LLM_ACCEPT_THRESHOLD": "0.78",
            "LLM_CONFIDENCE_CAP": "0.90",
            "MIN_SIZE_INCHES": "40",
            "MAX_SIZE_INCHES": "150",
            "ALLOWED_SIZE_INCHES": "55,65",
        },
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert "LLM_COMMAND_MODE must be one of" in response.text
    with Session(engine) as session:
        mode = session.exec(
            select(AppSetting).where(AppSetting.key == "LLM_COMMAND_MODE")
        ).first()
        assert mode is None


def test_admin_settings_update_saves_dynamic_size_settings(client_with_sqlite) -> None:
    client, engine = client_with_sqlite

    response = client.post(
        "/admin/settings/update",
        data={
            "LLM_COMMAND_MODE": "fallback",
            "OLLAMA_TIMEOUT_SECONDS": "8",
            "LLM_ACCEPT_THRESHOLD": "0.78",
            "LLM_CONFIDENCE_CAP": "0.90",
            "MIN_SIZE_INCHES": "42",
            "MAX_SIZE_INCHES": "160",
            "ALLOWED_SIZE_INCHES": "55, 72, 100",
            "ALLOW_DYNAMIC_SIZE_INCHES": "on",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    with Session(engine) as session:
        dynamic = session.exec(
            select(AppSetting).where(AppSetting.key == "ALLOW_DYNAMIC_SIZE_INCHES")
        ).first()
        min_size = session.exec(
            select(AppSetting).where(AppSetting.key == "MIN_SIZE_INCHES")
        ).first()
        max_size = session.exec(
            select(AppSetting).where(AppSetting.key == "MAX_SIZE_INCHES")
        ).first()
        allowed = session.exec(
            select(AppSetting).where(AppSetting.key == "ALLOWED_SIZE_INCHES")
        ).first()
        assert dynamic is not None and dynamic.value == "true"
        assert min_size is not None and min_size.value == "42"
        assert max_size is not None and max_size.value == "160"
        assert allowed is not None and allowed.value == "55, 72, 100"


def test_admin_audio_tester_invalid_file_shows_controlled_error(
    client_with_sqlite,
    monkeypatch,
) -> None:
    client, _engine = client_with_sqlite

    def raise_error(upload_file, language_hint=None):
        raise ValueError("Unsupported audio file extension: .exe")

    monkeypatch.setattr(
        admin_router_module,
        "process_audio_transcription_upload",
        raise_error,
    )

    response = client.post(
        "/admin/audio-tester/transcribe",
        files={"file": ("sample.exe", b"fake-audio", "application/octet-stream")},
        follow_redirects=True,
    )

    assert response.status_code == 400
    assert "Unsupported audio file extension: .exe" in response.text


def test_admin_audio_tester_normalize_uses_mocked_audio_flow(
    client_with_sqlite,
    monkeypatch,
) -> None:
    client, _engine = client_with_sqlite

    monkeypatch.setattr(
        admin_router_module,
        "process_audio_normalization_upload",
        lambda upload_file, language_hint=None, context_json=None: AudioNormalizeResponse(
            ok=True,
            transcription=AudioTranscriptionResponse(
                ok=True,
                text="monitor two and zoom in",
                language="en",
                duration_seconds=1.2,
                engine="faster_whisper",
                model="base",
                segments=[],
            ),
            normalization=main_module.normalize_command_text(
                "monitor two and zoom in",
                language_hint="en",
            ),
            message=None,
        ),
    )
    monkeypatch.setattr(
        admin_router_module,
        "build_debug_response",
        lambda payload: {
            "raw_text": payload.text,
            "normalized_text": "monitor two and zoom in",
            "fragments": ["monitor two", "zoom in"],
            "entities_by_fragment": [
                {"fragment": "monitor two", "entities": {"monitor": 2}},
            ],
            "rule_matches": [],
            "fuzzy_candidates": [],
            "semantic_candidates": [],
            "final_response": {},
        },
    )

    response = client.post(
        "/admin/audio-tester/normalize",
        files={"file": ("sample.mp3", b"fake-audio", "audio/mpeg")},
        data={"language_hint": "en", "context_json": '{"selected_monitor": null}'},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "monitor two and zoom in" in response.text
    assert "SELECT_MONITOR" in response.text
    assert "Entities By Fragment" in response.text
    assert "Fuzzy Candidates" in response.text
    assert "Semantic Candidates" in response.text
    assert "Convert transcription to example" in response.text


def test_admin_can_publish_catalog(client_with_sqlite, monkeypatch) -> None:
    client, engine = client_with_sqlite
    with Session(engine) as session:
        command = CommandDefinition(
            code=CommandName.START_STREAM,
            display_name="Start Stream",
            category="Capture / Stream",
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
        session.commit()

    monkeypatch.setattr(publish_service, "clear_all_runtime_caches", lambda: None)
    monkeypatch.setattr(
        publish_service,
        "rebuild_runtime_indexes",
        lambda: {"catalog_cache_cleared": True, "semantic_rebuilt": False, "semantic": None},
    )

    response = client.post("/admin/catalog/publish", follow_redirects=False)
    assert response.status_code == 303


def test_admin_publish_catalog_shows_validation_errors(client_with_sqlite) -> None:
    client, engine = client_with_sqlite
    with Session(engine) as session:
        session.add(
            CommandDefinition(
                code="CUSTOM_INVALID_PUBLISH",
                display_name="Invalid Publish",
                command_type="custom",
                status="draft",
                client_action_key="invalid_publish",
                enabled=True,
            )
        )
        session.commit()

    response = client.post("/admin/catalog/publish")

    assert response.status_code == 400
    assert "Catalog publish failed" in response.text
    assert "At least one enabled example is required" in response.text
