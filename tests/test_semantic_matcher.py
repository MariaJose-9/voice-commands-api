import numpy as np

import app.semantic_matcher as semantic_matcher
from app.preprocessor import normalize_text
from app.schemas import CommandName, MatchMethod


class FakeModel:
    def __init__(self, vectors):
        self.vectors = vectors

    def encode(self, texts):
        if isinstance(texts, str):
            texts = [texts]
        return np.asarray([self.vectors[text] for text in texts], dtype=float)


def _install_fake_semantic_index(monkeypatch):
    catalog = [
        {
            "command": "INCREASE_SIZE",
            "examples": ["make it bigger"],
        },
        {
            "command": "RECENTER_OBJECTS",
            "examples": ["center everything"],
        },
        {
            "command": "SHOW_VOICE_COMMANDS",
            "examples": ["open voice commands"],
        },
        {
            "command": "START_STREAM",
            "examples": ["start stream"],
        },
        {
            "command": "START_RECORDING",
            "examples": ["start recording"],
        },
        {
            "command": "STOP_STREAM",
            "examples": ["stop stream"],
        },
        {
            "command": "FOLLOW_ME",
            "examples": ["follow me"],
        },
        {
            "command": "SELECT_MONITOR",
            "requires_entities": ["monitor"],
            "examples": ["monitor one"],
        },
    ]

    vectors = {
        "make it bigger": [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "make the selected screen bigger": [0.97, 0.03, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "center everything": [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "put everything back in the middle": [0.0, 0.95, 0.05, 0.0, 0.0, 0.0, 0.0, 0.0],
        "open voice commands": [0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "open the commands panel": [0.0, 0.1, 0.9, 0.0, 0.0, 0.0, 0.0, 0.0],
        "start stream": [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0],
        "start broadcasting": [0.0, 0.0, 0.0, 0.95, 0.05, 0.0, 0.0, 0.0],
        "start recording": [0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0],
        "begin recording": [0.0, 0.0, 0.0, 0.0, 0.96, 0.04, 0.0, 0.0],
        "stop stream": [0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0],
        "stop the live video": [0.0, 0.0, 0.0, 0.0, 0.0, 0.94, 0.06, 0.0],
        "follow me": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0],
        "follow my movement": [0.0, 0.0, 0.0, 0.0, 0.0, 0.08, 0.92, 0.0],
        "monitor one": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0],
        "mntor one": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0],
        "totally unknown request": [0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1],
        "weak maybe command": [0.8, 0.0, 0.0, 0.6, 0.0, 0.0, 0.0, 0.0],
    }

    semantic_matcher._MODEL = None
    semantic_matcher._MODEL_LOAD_FAILED = False
    semantic_matcher._SEMANTIC_INDEX = []
    semantic_matcher._INDEX_BUILT = False

    monkeypatch.setattr(semantic_matcher, "_load_catalog", lambda: catalog)
    monkeypatch.setattr(semantic_matcher, "_get_model", lambda: FakeModel(vectors))


def test_get_model_loads_once(monkeypatch) -> None:
    semantic_matcher._MODEL = None
    semantic_matcher._MODEL_LOAD_FAILED = False
    calls = {"count": 0}

    class LoaderModel:
        def encode(self, texts):
            return np.asarray([[1.0, 0.0]], dtype=float)

    def fake_sentence_transformer(name):
        calls["count"] += 1
        return LoaderModel()

    import sys
    import types

    fake_module = types.SimpleNamespace(SentenceTransformer=fake_sentence_transformer)
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    monkeypatch.setattr(semantic_matcher, "SEMANTIC_MODEL_NAME", "fake-model")

    model_a = semantic_matcher._get_model()
    model_b = semantic_matcher._get_model()

    assert model_a is model_b
    assert calls["count"] == 1


def test_warmup_semantic_matcher_builds_index(monkeypatch) -> None:
    _install_fake_semantic_index(monkeypatch)
    result = semantic_matcher.warmup_semantic_matcher(force_rebuild=True)
    assert result["enabled"] is True
    assert result["model_loaded"] is True
    assert result["index_built"] is True
    assert result["examples_indexed"] > 0


def test_match_by_semantic_increase_size(monkeypatch) -> None:
    _install_fake_semantic_index(monkeypatch)
    command = semantic_matcher.match_by_semantic(
        normalize_text("make the selected screen bigger")
    )
    assert command is not None
    assert command.command == CommandName.INCREASE_SIZE
    assert command.method == MatchMethod.semantic
    assert command.confidence >= 0.72


def test_match_by_semantic_recenter(monkeypatch) -> None:
    _install_fake_semantic_index(monkeypatch)
    command = semantic_matcher.match_by_semantic(
        normalize_text("put everything back in the middle")
    )
    assert command is not None
    assert command.command == CommandName.RECENTER_OBJECTS


def test_match_by_semantic_show_voice_commands(monkeypatch) -> None:
    _install_fake_semantic_index(monkeypatch)
    command = semantic_matcher.match_by_semantic(
        normalize_text("open the commands panel")
    )
    assert command is not None
    assert command.command == CommandName.SHOW_VOICE_COMMANDS


def test_match_by_semantic_start_stream(monkeypatch) -> None:
    _install_fake_semantic_index(monkeypatch)
    command = semantic_matcher.match_by_semantic(normalize_text("start broadcasting"))
    assert command is not None
    assert command.command == CommandName.START_STREAM


def test_match_by_semantic_start_recording(monkeypatch) -> None:
    _install_fake_semantic_index(monkeypatch)
    command = semantic_matcher.match_by_semantic(normalize_text("begin recording"))
    assert command is not None
    assert command.command == CommandName.START_RECORDING


def test_match_by_semantic_stop_stream(monkeypatch) -> None:
    _install_fake_semantic_index(monkeypatch)
    command = semantic_matcher.match_by_semantic(normalize_text("stop the live video"))
    assert command is not None
    assert command.command == CommandName.STOP_STREAM


def test_match_by_semantic_follow_me(monkeypatch) -> None:
    _install_fake_semantic_index(monkeypatch)
    command = semantic_matcher.match_by_semantic(normalize_text("follow my movement"))
    assert command is not None
    assert command.command == CommandName.FOLLOW_ME


def test_match_by_semantic_returns_confirmation_band_match(monkeypatch) -> None:
    _install_fake_semantic_index(monkeypatch)
    command = semantic_matcher.match_by_semantic(
        normalize_text("weak maybe command"),
        threshold=0.95,
        confirmation_threshold=0.62,
    )
    assert command is not None
    assert 0.62 <= command.confidence < 0.95


def test_match_by_semantic_returns_none_below_confirmation_threshold(monkeypatch) -> None:
    _install_fake_semantic_index(monkeypatch)
    command = semantic_matcher.match_by_semantic(
        normalize_text("totally unknown request"),
        threshold=0.72,
        confirmation_threshold=0.99,
    )
    assert command is None


def test_match_by_semantic_skips_entity_only_without_entities(monkeypatch) -> None:
    _install_fake_semantic_index(monkeypatch)
    command = semantic_matcher.match_by_semantic(normalize_text("mntor one"))
    assert command is None


def test_get_semantic_candidates(monkeypatch) -> None:
    _install_fake_semantic_index(monkeypatch)
    candidates = semantic_matcher.get_semantic_candidates(
        normalize_text("open the commands panel"), limit=3
    )
    assert len(candidates) == 3
    assert candidates[0]["command"] == CommandName.SHOW_VOICE_COMMANDS.value
    assert set(candidates[0].keys()) == {"command", "example", "score"}


def test_match_by_semantic_handles_model_failure(monkeypatch) -> None:
    semantic_matcher._MODEL = None
    semantic_matcher._MODEL_LOAD_FAILED = False
    semantic_matcher._SEMANTIC_INDEX = []
    semantic_matcher._INDEX_BUILT = False

    monkeypatch.setattr(semantic_matcher, "_get_model", lambda: None)
    monkeypatch.setattr(
        semantic_matcher,
        "_load_catalog",
        lambda: [{"command": "INCREASE_SIZE", "examples": ["make it bigger"]}],
    )

    command = semantic_matcher.match_by_semantic(normalize_text("make it bigger"))
    assert command is None
