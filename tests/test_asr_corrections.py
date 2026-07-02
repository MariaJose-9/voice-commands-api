from app.asr_corrections import apply_asr_corrections


def test_corrects_pantaya() -> None:
    assert apply_asr_corrections("pantaya dos") == "pantalla dos"


def test_corrects_licuada() -> None:
    assert apply_asr_corrections("mueve la licuada") == "mueve la izquierda"


def test_corrects_puladas() -> None:
    assert apply_asr_corrections("55 puladas") == "55 pulgadas"


def test_corrects_monito() -> None:
    assert apply_asr_corrections("monito uno") == "monitor uno"


def test_corrects_dereca() -> None:
    assert apply_asr_corrections("dereca") == "derecha"


def test_corrects_coja() -> None:
    assert apply_asr_corrections("coja la pantalla una") == "selecciona la pantalla una"


def test_corrects_split_aleja() -> None:
    assert apply_asr_corrections("a leja el monitor 2") == "aleja el monitor 2"


def test_corrects_split_acerca() -> None:
    assert apply_asr_corrections("a cerca el monitor uno") == "acerca el monitor uno"
