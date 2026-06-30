import pytest

try:
    from sqlalchemy.pool import StaticPool
    from sqlmodel import Session, SQLModel, create_engine
except ImportError:  # pragma: no cover
    StaticPool = None
    Session = None
    SQLModel = None
    create_engine = None

import app.entity_extractor as entity_extractor
import app.services.entity_catalog_service as entity_catalog_service
from app.db.models import EntityType, EntityValue, EntityValueAlias
from app.entity_extractor import extract_entities
from app.preprocessor import normalize_text


def test_extract_monitor_one_variants() -> None:
    entities = extract_entities(normalize_text("select monitor one"))
    assert entities["monitor"] == 1
    assert entities["layout"] is None
    assert entities["size_inches"] is None


def test_extract_monitor_two_variants() -> None:
    entities = extract_entities(normalize_text("screen 2"))
    assert entities["monitor"] == 2


def test_extract_monitor_spanish_aliases() -> None:
    entities = extract_entities(normalize_text("pantalla dos"))
    assert entities["monitor"] == 2


def test_extract_monitor_common_typo_alias() -> None:
    entities = extract_entities(normalize_text("mueve el monito uno a la derecha"))
    assert entities["monitor"] == 1


def test_extract_layout_one() -> None:
    entities = extract_entities(normalize_text("first layout"))
    assert entities["layout"] == 1


def test_extract_layout_two_spanish() -> None:
    entities = extract_entities(normalize_text("segundo layout"))
    assert entities["layout"] == 2


def test_extract_supported_size_inches() -> None:
    entities = extract_entities(normalize_text("Ponlo en 65 pulgadas."))
    assert entities["size_inches"] == 65


def test_extract_size_from_tamano_alias() -> None:
    entities = extract_entities(normalize_text("tamano 120"))
    assert entities["size_inches"] == 120


def test_extract_size_without_space_before_unit() -> None:
    entities = extract_entities(normalize_text("hola cambia el tamano de la pantalla 2 a 55inch"))
    assert entities["size_inches"] == 55


def test_extract_size_from_transcription_typo_puladas() -> None:
    entities = extract_entities(
        normalize_text("pantalla 2 mueve la derecha y luego en el tamaño de 55 puladas")
    )
    assert entities["size_inches"] == 55


def test_extract_invalid_size_returns_none() -> None:
    entities = extract_entities(normalize_text("set 70 inches"))
    assert entities["size_inches"] is None


def test_extract_flags_stop_stream_follow() -> None:
    entities = extract_entities(normalize_text("stop stream and disable follow me"))
    assert entities["flags"] == {
        "has_stop": True,
        "has_stream": True,
        "has_follow": True,
    }


def test_extract_flags_spanish_aliases() -> None:
    entities = extract_entities(normalize_text("parar transmision y activar seguimiento"))
    assert entities["flags"]["has_stop"] is True
    assert entities["flags"]["has_stream"] is True
    assert entities["flags"]["has_follow"] is True


def test_extract_entities_default_shape() -> None:
    entities = extract_entities(normalize_text("open settings"))
    assert entities == {
        "monitor": None,
        "layout": None,
        "size_inches": None,
        "flags": {
            "has_stop": False,
            "has_stream": False,
            "has_follow": False,
        },
    }


def test_extract_entities_uses_db_alias_after_cache_clear(monkeypatch) -> None:
    if create_engine is None or SQLModel is None or Session is None or StaticPool is None:
        pytest.skip("sqlalchemy/sqlmodel not installed")

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        entity_type = EntityType(code="monitor", display_name="Monitor", enabled=True)
        session.add(entity_type)
        session.commit()
        session.refresh(entity_type)

        entity_value = EntityValue(
            entity_type_id=entity_type.id,
            value="1",
            label="Monitor 1",
            enabled=True,
        )
        session.add(entity_value)
        session.commit()
        session.refresh(entity_value)

        session.add(
            EntityValueAlias(
                entity_value_id=entity_value.id,
                phrase="display alpha",
                normalized_phrase="display alpha",
                enabled=True,
            )
        )
        session.commit()

    monkeypatch.setattr(entity_catalog_service, "SessionFactory", Session)
    monkeypatch.setattr(entity_catalog_service, "engine", engine)
    entity_catalog_service.clear_entity_catalog_cache()

    entities = entity_extractor.extract_entities(normalize_text("use display alpha"))
    assert entities["monitor"] == 1


def test_extract_entities_fallback_when_db_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(entity_catalog_service, "SessionFactory", None)
    monkeypatch.setattr(entity_catalog_service, "engine", None)
    entity_catalog_service.clear_entity_catalog_cache()

    entities = entity_extractor.extract_entities(normalize_text("mueve el monito uno"))
    assert entities["monitor"] == 1
