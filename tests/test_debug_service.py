from __future__ import annotations

import app.services.debug_service as debug_service
from app.schemas import CommandName, MatchMethod, NormalizeRequest, NormalizeResponse, NormalizedCommand
from app.services import size_validation_service


def _enable_hybrid_llm(monkeypatch) -> None:
    monkeypatch.setattr(
        debug_service.runtime_settings_service,
        "get_runtime_str_setting",
        lambda key, default: {
            "LLM_COMMAND_MODE": "hybrid",
            "OLLAMA_MODEL": "qwen2.5:3b",
        }.get(key, default),
    )
    monkeypatch.setattr(
        debug_service.runtime_settings_service,
        "get_bool_setting",
        lambda key, default: True if key == "ENABLE_OLLAMA_FALLBACK" else default,
    )


def test_build_debug_response_returns_fragments_and_final_response(
    monkeypatch,
) -> None:
    monkeypatch.setattr(debug_service, "ENABLE_SEMANTIC_MATCHER", False)

    payload = NormalizeRequest(text="monitor two and left", language_hint="en")
    response = debug_service.build_debug_response(payload)

    assert response["fragments"] == ["monitor two", "left"]
    assert "final_response" in response
    assert [item["command"] for item in response["final_response"]["commands"]] == [
        "SELECT_MONITOR",
        "MOVE_LEFT",
    ]
    assert "completeness" in response


def test_build_debug_response_flags_incomplete_size_intent(monkeypatch) -> None:
    monkeypatch.setattr(debug_service, "ENABLE_SEMANTIC_MATCHER", False)
    _enable_hybrid_llm(monkeypatch)
    monkeypatch.setattr(
        size_validation_service,
        "_get_runtime_bool",
        lambda key, default: True,
    )
    monkeypatch.setattr(
        size_validation_service,
        "_get_runtime_int",
        lambda key, default: {"MIN_SIZE_INCHES": 40, "MAX_SIZE_INCHES": 150}[key],
    )
    monkeypatch.setattr(
        debug_service,
        "interpret_commands_with_llm",
        lambda **kwargs: NormalizeResponse(
            ok=True,
            raw_text=kwargs["raw_text"],
            normalized_text=kwargs["normalized_text"],
            language=kwargs["language_hint"],
            commands=[
                NormalizedCommand(
                    command=CommandName.SELECT_MONITOR,
                    confidence=0.95,
                    method=MatchMethod.llm,
                    monitor=1,
                    raw_fragment="monitor 1",
                ),
                NormalizedCommand(
                    command=CommandName.SET_SIZE,
                    confidence=0.95,
                    method=MatchMethod.llm,
                    size_inches=72,
                    raw_fragment="redimensiona a 72 pulgadas",
                ),
            ],
            needs_confirmation=False,
            message=None,
        ),
    )

    payload = NormalizeRequest(
        text="Redimensiona a 72 pulgadas el monitor 1",
        language_hint="es",
    )
    response = debug_service.build_debug_response(payload)

    assert response["completeness"]["is_complete"] is False
    assert response["completeness"]["should_call_llm"] is True
    assert (
        response["completeness"]["reason"]
        == "explicit_size_intent_missing_set_size"
    )
    assert "set_size" in response["completeness"]["unresolved_intents"]
    assert "redimensiona" in response["completeness"]["uncovered_text"]
    assert response["llm"]["mode"] == "hybrid"
    assert response["llm"]["enabled"] is True
    assert response["llm"]["should_call"] is True
    assert response["llm"]["reason"] == "explicit_size_intent_missing_set_size"
    assert response["llm"]["called"] is True
    assert response["llm"]["success"] is True
    assert response["llm"]["model"] == "qwen2.5:3b"
    assert response["llm"]["merged"] is True
    assert "prompt" not in response["llm"]


def test_build_debug_response_does_not_call_llm_for_complete_monitor_size(
    monkeypatch,
) -> None:
    monkeypatch.setattr(debug_service, "ENABLE_SEMANTIC_MATCHER", False)
    _enable_hybrid_llm(monkeypatch)
    called = {"value": False}

    def fake_llm(**kwargs):
        called["value"] = True
        return None

    monkeypatch.setattr(debug_service, "interpret_commands_with_llm", fake_llm)

    payload = NormalizeRequest(
        text="Necesito que el monitor 2 esté en 75 pulgadas",
        language_hint="es",
    )
    response = debug_service.build_debug_response(payload)

    assert response["completeness"]["is_complete"] is True
    assert response["llm"]["mode"] == "hybrid"
    assert response["llm"]["should_call"] is False
    assert response["llm"]["called"] is False
    assert response["llm"]["reason"] is None
    assert called["value"] is False
    assert response["merge"]["deduplicated"] is True
    assert response["merge"]["duplicates_removed"] == []
    assert response["merge"]["conflicts"] == []


def test_build_debug_response_marks_monitor_only_complete(monkeypatch) -> None:
    monkeypatch.setattr(debug_service, "ENABLE_SEMANTIC_MATCHER", False)
    _enable_hybrid_llm(monkeypatch)
    called = {"value": False}

    def fake_llm(**kwargs):
        called["value"] = True
        return None

    monkeypatch.setattr(debug_service, "interpret_commands_with_llm", fake_llm)

    payload = NormalizeRequest(text="monitor 1", language_hint="es")
    response = debug_service.build_debug_response(payload)

    assert response["completeness"]["is_complete"] is True
    assert response["completeness"]["should_call_llm"] is False
    assert response["llm"]["should_call"] is False
    assert response["llm"]["called"] is False
    assert called["value"] is False
    assert "prompt" not in response["llm"]


def test_build_debug_response_reports_llm_duplicate_set_size(monkeypatch) -> None:
    monkeypatch.setattr(debug_service, "ENABLE_SEMANTIC_MATCHER", False)
    _enable_hybrid_llm(monkeypatch)
    monkeypatch.setattr(
        debug_service,
        "_llm_should_call",
        lambda mode, enabled, base_response, completeness: (True, "forced_test"),
    )

    def fake_llm(**kwargs):
        return NormalizeResponse(
            ok=True,
            raw_text=kwargs["raw_text"],
            normalized_text=kwargs["normalized_text"],
            language=kwargs["language_hint"],
            commands=[
                NormalizedCommand(
                    command=CommandName.SET_SIZE,
                    confidence=0.90,
                    method=MatchMethod.llm,
                    monitor=2,
                    size_inches=75,
                    raw_fragment="75 pulgadas",
                ),
            ],
            needs_confirmation=False,
            message=None,
        )

    monkeypatch.setattr(debug_service, "interpret_commands_with_llm", fake_llm)

    payload = NormalizeRequest(
        text="Necesito que el monitor 2 esté en 75 pulgadas",
        language_hint="es",
    )
    response = debug_service.build_debug_response(payload)

    assert response["llm"]["should_call"] is True
    assert response["llm"]["called"] is True
    set_size_duplicates = [
        item
        for item in response["merge"]["duplicates_removed"]
        if item["semantic_key"] == ["SET_SIZE", 75]
    ]
    assert set_size_duplicates == [
        {
            "semantic_key": ["SET_SIZE", 75],
            "kept_method": "entity_rule",
            "removed_methods": ["llm"],
        }
    ]
    assert response["merge"]["conflicts"] == []
