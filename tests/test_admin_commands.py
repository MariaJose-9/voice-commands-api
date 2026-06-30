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
import app.services.publish_service as publish_service
from app.db.models import (
    AppSetting,
    AuditLog,
    CatalogStatus,
    CatalogVersion,
    CommandDefinition,
    CommandExample,
    CommandName,
    EntityType,
    EntityValue,
    EntityValueAlias,
    UserRole,
)
from app.entity_extractor import extract_entities
from app.preprocessor import normalize_text


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


def test_admin_audio_tester_invalid_file_shows_controlled_error(
    client_with_sqlite,
    monkeypatch,
) -> None:
    client, _engine = client_with_sqlite

    def raise_error(upload_file, language_hint=None):
        raise ValueError("Unsupported audio file extension: .wav")

    monkeypatch.setattr(
        admin_router_module,
        "process_audio_transcription_upload",
        raise_error,
    )

    response = client.post(
        "/admin/audio-tester/transcribe",
        files={"file": ("sample.wav", b"fake-audio", "audio/wav")},
        follow_redirects=True,
    )

    assert response.status_code == 400
    assert "Unsupported audio file extension: .wav" in response.text


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
        session.add(
            CommandDefinition(
                code=CommandName.START_STREAM,
                display_name="Start Stream",
                category="Capture / Stream",
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
