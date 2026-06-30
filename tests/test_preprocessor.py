from app.preprocessor import normalize_text


def test_normalize_text_removes_accents_and_extra_spaces() -> None:
    assert normalize_text("  Súbele   el tamaño!! ") == "sube el tamano"


def test_normalize_text_preserves_numbers_and_words() -> None:
    assert normalize_text("Monitor #1") == "monitor 1"


def test_normalize_text_keeps_inches_expression() -> None:
    assert normalize_text("Ponlo en 65 pulgadas.") == "pon en 65 pulgadas"


def test_normalize_text_lowercases_text() -> None:
    assert normalize_text("STOP STREAM!") == "stop stream"


def test_normalize_text_normalizes_curly_quotes() -> None:
    assert normalize_text("“Layout” dos") == "layout dos"
