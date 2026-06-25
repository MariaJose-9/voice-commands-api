from __future__ import annotations

import app.services.debug_service as debug_service
from app.schemas import NormalizeRequest


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
