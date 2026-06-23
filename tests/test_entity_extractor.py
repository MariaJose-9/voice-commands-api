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
