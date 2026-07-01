"""Initial seed utilities for command administration data."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from passlib.context import CryptContext
from sqlmodel import Session, select

from app.config import (
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    SEMANTIC_CONFIRMATION_THRESHOLD,
    SEMANTIC_THRESHOLD,
)
from app.db.models import (
    AdminUser,
    AppSetting,
    CommandDefinition,
    CommandExample,
    EntityType,
    EntityValue,
    EntityValueAlias,
    ExampleSource,
    MatchType,
    SettingValueType,
)
from app.db.session import Session as SessionType, engine
from app.preprocessor import normalize_text
from app.schemas import CommandName


CATALOG_PATH = Path(__file__).resolve().parent.parent / "commands" / "catalog.yml"
PASSWORD_CONTEXT = CryptContext(schemes=["bcrypt_sha256", "bcrypt"], deprecated="auto")


def _hash_password(password: str) -> str:
    """Hash the default admin password with a safe fallback for local envs."""

    try:
        return PASSWORD_CONTEXT.hash(password)
    except Exception:
        import bcrypt

        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _infer_category(code: str) -> str:
    """Infer a reasonable category from the command code."""

    if code in {"SELECT_MONITOR"}:
        return "Monitors"
    if code in {"MOVE_LEFT", "MOVE_RIGHT", "MOVE_UP", "MOVE_DOWN"}:
        return "Movement"
    if code in {"ZOOM_IN", "ZOOM_OUT", "INCREASE_SIZE", "DECREASE_SIZE", "SET_SIZE"}:
        return "Zoom / Size"
    if code in {"FOLLOW_ME", "STOP_FOLLOW_ME", "RECENTER_OBJECTS", "RESET_POSITION"}:
        return "Follow / Position"
    if code in {"SET_LAYOUT"}:
        return "Layouts"
    if code in {
        "SHOW_AITROL",
        "CLOSE_AITROL",
        "SHOW_VOICE_COMMANDS",
        "CLOSE_VOICE_COMMANDS",
        "OPEN_SETTINGS",
    }:
        return "Panels / UI"
    if code in {"CAPTURE", "START_STREAM", "START_RECORDING", "STOP_STREAM", "STOP_ACTIVE"}:
        return "Capture / Stream"
    return "General"


def seed_commands_from_yaml(
    session: Session, yaml_path: Optional[Path] = None
) -> dict:
    """Seed command definitions and examples from catalog.yml."""

    path = yaml_path or CATALOG_PATH
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    commands = payload.get("commands", [])
    created_commands = 0
    created_examples = 0

    for item in commands:
        code = item["command"]
        try:
            command_name = CommandName(code)
        except ValueError:
            continue

        command = session.exec(
            select(CommandDefinition).where(CommandDefinition.code == command_name)
        ).first()
        if command is None:
            command = CommandDefinition(
                code=command_name,
                display_name=code.replace("_", " ").title(),
                description=item.get("description"),
                category=item.get("category") or _infer_category(code),
                enabled=True,
                priority=item.get("priority", 50),
                min_confidence=0.72,
            )
            session.add(command)
            session.flush()
            created_commands += 1

        for phrase in item.get("examples", []):
            normalized_phrase = normalize_text(phrase)
            if not normalized_phrase:
                continue
            exists = session.exec(
                select(CommandExample).where(
                    CommandExample.command_id == command.id,
                    CommandExample.normalized_phrase == normalized_phrase,
                )
            ).first()
            if exists is not None:
                continue

            session.add(
                CommandExample(
                    command_id=command.id,
                    phrase=phrase,
                    normalized_phrase=normalized_phrase,
                    language=None,
                    match_type=MatchType.SEMANTIC,
                    enabled=True,
                    source=ExampleSource.SEED,
                )
            )
            created_examples += 1

    session.commit()
    return {
        "commands_created": created_commands,
        "examples_created": created_examples,
    }


def _get_or_create_entity_type(
    session: Session, code: str, display_name: str, description: Optional[str] = None
) -> EntityType:
    entity_type = session.exec(
        select(EntityType).where(EntityType.code == code)
    ).first()
    if entity_type is None:
        entity_type = EntityType(
            code=code,
            display_name=display_name,
            description=description,
            enabled=True,
        )
        session.add(entity_type)
        session.flush()
    return entity_type


def _get_or_create_entity_value(
    session: Session, entity_type_id: int, value: str, label: Optional[str] = None
) -> EntityValue:
    entity_value = session.exec(
        select(EntityValue).where(
            EntityValue.entity_type_id == entity_type_id,
            EntityValue.value == value,
        )
    ).first()
    if entity_value is None:
        entity_value = EntityValue(
            entity_type_id=entity_type_id,
            value=value,
            label=label,
            enabled=True,
        )
        session.add(entity_value)
        session.flush()
    return entity_value


def _create_aliases(
    session: Session, entity_value_id: int, phrases: list[str], language: Optional[str] = None
) -> int:
    created = 0
    for phrase in phrases:
        normalized_phrase = normalize_text(phrase)
        if not normalized_phrase:
            continue
        exists = session.exec(
            select(EntityValueAlias).where(
                EntityValueAlias.entity_value_id == entity_value_id,
                EntityValueAlias.normalized_phrase == normalized_phrase,
            )
        ).first()
        if exists is not None:
            continue
        session.add(
            EntityValueAlias(
                entity_value_id=entity_value_id,
                phrase=phrase,
                normalized_phrase=normalized_phrase,
                language=language,
                enabled=True,
            )
        )
        created += 1
    return created


def seed_default_entities(session: Session) -> dict:
    """Seed entity types, values, and aliases from the current extractor logic."""

    created_values = 0
    created_aliases = 0

    monitor = _get_or_create_entity_type(session, "monitor", "Monitor")
    layout = _get_or_create_entity_type(session, "layout", "Layout")
    size_inches = _get_or_create_entity_type(session, "size_inches", "Size Inches")

    monitor_1 = _get_or_create_entity_value(session, monitor.id, "1", "Monitor 1")
    monitor_2 = _get_or_create_entity_value(session, monitor.id, "2", "Monitor 2")
    layout_1 = _get_or_create_entity_value(session, layout.id, "1", "Layout 1")
    layout_2 = _get_or_create_entity_value(session, layout.id, "2", "Layout 2")
    for _ in [monitor_1, monitor_2, layout_1, layout_2]:
        created_values += 0

    created_aliases += _create_aliases(
        session,
        monitor_1.id,
        [
            "monitor one",
            "monitor 1",
            "monitor uno",
            "pantalla uno",
            "pantalla una",
            "pantalla 1",
            "la pantalla uno",
            "la pantalla una",
            "monitor numero uno",
            "monitor número uno",
            "pantalla numero uno",
            "pantalla número uno",
            "primera pantalla",
            "la primera pantalla",
            "primer monitor",
            "el primer monitor",
            "first monitor",
            "screen one",
            "screen 1",
            "screen number one",
            "display one",
            "display 1",
            "monito uno",
            "monito 1",
            "monitr one",
            "moniter one",
        ],
    )
    created_aliases += _create_aliases(
        session,
        monitor_2.id,
        [
            "monitor two",
            "monitor 2",
            "monitor dos",
            "pantalla dos",
            "pantalla 2",
            "la pantalla dos",
            "monitor numero dos",
            "monitor número dos",
            "pantalla numero dos",
            "pantalla número dos",
            "segunda pantalla",
            "la segunda pantalla",
            "segundo monitor",
            "el segundo monitor",
            "second monitor",
            "screen two",
            "screen 2",
            "screen number two",
            "display two",
            "display 2",
            "monito dos",
            "monito 2",
            "monitr two",
            "moniter two",
        ],
    )
    created_aliases += _create_aliases(
        session,
        layout_1.id,
        [
            "layout one",
            "layout 1",
            "layout uno",
            "first layout",
            "primer layout",
            "primer diseño",
            "primer diseno",
            "diseno uno",
            "diseño uno",
            "vista uno",
            "vista 1",
            "primera vista",
        ],
    )
    created_aliases += _create_aliases(
        session,
        layout_2.id,
        [
            "layout two",
            "layout 2",
            "layout dos",
            "second layout",
            "segundo layout",
            "segundo diseño",
            "segundo diseno",
            "diseno dos",
            "diseño dos",
            "vista dos",
            "vista 2",
            "segunda vista",
        ],
    )

    spoken_size_aliases = {
        "55": [
            "cincuenta y cinco",
            "cincuenta cinco",
            "cincuenta y cinco pulgadas",
            "cincuenta cinco pulgadas",
            "cincuenta y cinco puladas",
            "fifty five",
            "fifty five inch",
            "fifty five inches",
        ],
        "65": [
            "sesenta y cinco",
            "sesenta cinco",
            "sesenta y cinco pulgadas",
            "sesenta cinco pulgadas",
            "sesenta y cinco puladas",
            "sixty five",
            "sixty five inch",
            "sixty five inches",
        ],
        "75": [
            "setenta y cinco",
            "setenta cinco",
            "setenta y cinco pulgadas",
            "setenta cinco pulgadas",
            "setenta y cinco puladas",
            "seventy five",
            "seventy five inch",
            "seventy five inches",
        ],
        "95": [
            "noventa y cinco",
            "noventa cinco",
            "noventa y cinco pulgadas",
            "noventa cinco pulgadas",
            "noventa y cinco puladas",
            "ninety five",
            "ninety five inch",
            "ninety five inches",
        ],
        "120": [
            "ciento veinte",
            "cien veinte",
            "ciento veinte pulgadas",
            "cien veinte pulgadas",
            "ciento veinte puladas",
            "one hundred twenty",
            "one hundred twenty inch",
            "one hundred twenty inches",
            "one twenty",
            "one twenty inch",
            "one twenty inches",
        ],
    }

    for value in ["55", "65", "75", "95", "120"]:
        entity_value = _get_or_create_entity_value(
            session,
            size_inches.id,
            value,
            f"{value} inches",
        )
        created_aliases += _create_aliases(
            session,
            entity_value.id,
            [
                f"{value} inch",
                f"{value} inches",
                f"{value} pulgada",
                f"{value} pulgadas",
                f"{value} puladas",
                f"tamano {value}",
                f"tamaño {value}",
                f"tamano de {value}",
                f"tamaño de {value}",
                f"a {value}",
                f"en {value}",
                f"de {value}",
                f"pantalla {value}",
                f"pantalla de {value}",
                f"monitor {value}",
                f"monitor de {value}",
                f"set {value} inches",
                f"ponlo en {value} pulgadas",
            ]
            + spoken_size_aliases[value],
        )

    session.commit()
    created_values = session.exec(select(EntityValue)).all()
    return {
        "entity_types": 3,
        "entity_values_total": len(created_values),
        "aliases_created": created_aliases,
    }


def seed_default_settings(session: Session) -> dict:
    """Seed default runtime settings."""

    settings = {
        "FUZZY_THRESHOLD": "86",
        "SEMANTIC_THRESHOLD": str(SEMANTIC_THRESHOLD),
        "SEMANTIC_CONFIRMATION_THRESHOLD": str(SEMANTIC_CONFIRMATION_THRESHOLD),
        "ENABLE_SEMANTIC_MATCHER": "true",
        "ENABLE_OLLAMA_FALLBACK": "true",
        "TRANSCRIPTION_MODEL_NAME": "base",
        "LLM_COMMAND_MODE": "hybrid",
        "OLLAMA_MODEL": "qwen2.5:3b",
        "OLLAMA_TIMEOUT_SECONDS": "8",
        "LLM_ACCEPT_THRESHOLD": "0.78",
        "LLM_CONFIDENCE_CAP": "0.90",
        "ALLOW_DYNAMIC_SIZE_INCHES": "true",
        "MIN_SIZE_INCHES": "40",
        "MAX_SIZE_INCHES": "150",
    }
    created = 0

    for key, value in settings.items():
        setting = session.exec(select(AppSetting).where(AppSetting.key == key)).first()
        if setting is not None:
            continue
        session.add(
            AppSetting(
                key=key,
                value=value,
                value_type=SettingValueType.STR,
            )
        )
        created += 1

    session.commit()
    return {"settings_created": created}


def seed_default_admin_user(session: Session) -> dict:
    """Create the default admin user only if no user exists."""

    existing = session.exec(select(AdminUser)).first()
    if existing is not None:
        return {"admin_created": False, "email": existing.email}

    admin = AdminUser(
        email=ADMIN_EMAIL,
        password_hash=_hash_password(ADMIN_PASSWORD),
        role="admin",
        is_active=True,
    )
    session.add(admin)
    session.commit()
    return {"admin_created": True, "email": admin.email}


def run_seed(session: Session) -> dict:
    """Run the full seed pipeline."""

    return {
        "commands": seed_commands_from_yaml(session),
        "entities": seed_default_entities(session),
        "settings": seed_default_settings(session),
        "admin": seed_default_admin_user(session),
    }


def main() -> None:
    """CLI entry point for `python -m app.db.seed`."""

    if SessionType is None or engine is None:
        raise RuntimeError("Database dependencies are not installed.")

    with SessionType(engine) as session:
        result = run_seed(session)
        print(result)


if __name__ == "__main__":
    main()
