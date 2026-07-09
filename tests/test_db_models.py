from __future__ import annotations

import pytest


sqlmodel = pytest.importorskip("sqlmodel")

from app.db.models import (  # noqa: E402
    AdminUser,
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
    ExampleSource,
    MatchType,
    NormalizationLog,
    ReviewStatus,
    SettingValueType,
)
from app.schemas import CommandName  # noqa: E402


def test_admin_user_model_instantiates() -> None:
    user = AdminUser(email="admin@example.com", password_hash="hashed")
    assert user.email == "admin@example.com"
    assert user.role == "admin"
    assert user.is_active is True


def test_command_models_instantiate() -> None:
    definition = CommandDefinition(
        code=CommandName.SELECT_MONITOR.value,
        display_name="Select Monitor",
        command_type="core",
        status="active",
        protected=True,
        client_action_key="select_monitor",
    )
    example = CommandExample(
        command_id=1,
        phrase="monitor one",
        normalized_phrase="monitor one",
        match_type=MatchType.EXACT,
        source=ExampleSource.SEED,
    )
    assert definition.code == CommandName.SELECT_MONITOR.value
    assert definition.command_type == "core"
    assert definition.status == "active"
    assert definition.protected is True
    assert definition.client_action_key == "select_monitor"
    assert example.match_type == MatchType.EXACT
    assert example.source == ExampleSource.SEED


def test_custom_command_definition_instantiates() -> None:
    definition = CommandDefinition(
        code="CUSTOM_OPEN_PATIENT_CHART",
        display_name="Open Patient Chart",
        command_type="custom",
        status="draft",
        protected=False,
        client_action_key="open_patient_chart",
    )

    assert definition.code == "CUSTOM_OPEN_PATIENT_CHART"
    assert definition.command_type == "custom"
    assert definition.status == "draft"
    assert definition.protected is False
    assert definition.client_action_key == "open_patient_chart"


def test_command_parameter_model_instantiates() -> None:
    parameter = CommandParameter(
        command_id=1,
        slot_name="size",
        entity_type_id=2,
        target_field="size_inches",
        required=True,
        allow_multiple=False,
        default_value="75",
        description="Target screen size in inches.",
        extraction_hint="Extract exact size in inches.",
    )

    assert parameter.command_id == 1
    assert parameter.slot_name == "size"
    assert parameter.entity_type_id == 2
    assert parameter.target_field == "size_inches"
    assert parameter.required is True
    assert parameter.default_value == "75"


def test_command_parameter_rejects_empty_slot_name() -> None:
    with pytest.raises(ValueError):
        CommandParameter.model_validate(
            {
                "command_id": 1,
                "slot_name": " ",
                "entity_type_id": 1,
                "target_field": "monitor",
            }
        )


def test_entity_models_instantiate() -> None:
    entity_type = EntityType(code="monitor", display_name="Monitor")
    entity_value = EntityValue(entity_type_id=1, value="1", label="Monitor 1")
    alias = EntityValueAlias(
        entity_value_id=1,
        phrase="monitor one",
        normalized_phrase="monitor one",
    )
    assert entity_type.code == "monitor"
    assert entity_value.value == "1"
    assert alias.normalized_phrase == "monitor one"


def test_log_and_settings_models_instantiate() -> None:
    normalization_log = NormalizationLog(
        raw_text="monitor one",
        normalized_text="monitor one",
        result_json={"commands": ["SELECT_MONITOR"]},
        review_status=ReviewStatus.PENDING,
    )
    catalog_version = CatalogVersion(
        version_number=1,
        status=CatalogStatus.DRAFT,
        snapshot_json={"commands": []},
    )
    setting = AppSetting(key="semantic_enabled", value="true")
    audit = AuditLog(action="create_command", payload_json={"id": 1})

    assert normalization_log.review_status == ReviewStatus.PENDING
    assert catalog_version.status == CatalogStatus.DRAFT
    assert setting.value_type == SettingValueType.STR
    assert audit.action == "create_command"
