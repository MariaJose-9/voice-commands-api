from __future__ import annotations

import app.ollama_fallback as ollama_fallback
from app.schemas import CommandName, MatchMethod


class FakeResponse:
    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("http error")

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url, json):
        return self.response


def test_ollama_fallback_returns_normalized_response(monkeypatch) -> None:
    payload = {
        "message": {
            "content": '{"ok": true, "raw_text": "start broadcast", '
            '"normalized_text": "start broadcast", "language": "en", '
            '"commands": [{"command": "START_STREAM"}], '
            '"needs_confirmation": true, "message": null}'
        }
    }
    monkeypatch.setattr(
        ollama_fallback.httpx,
        "Client",
        lambda timeout: FakeClient(FakeResponse(payload)),
    )

    response = ollama_fallback.ollama_fallback_normalize(
        text="start broadcast",
        normalized_text="start broadcast",
        language_hint="en",
    )

    assert response is not None
    assert response.needs_confirmation is True
    assert response.commands[0].command == CommandName.START_STREAM
    assert response.commands[0].method == MatchMethod.llm
    assert response.commands[0].confidence == 0.70


def test_ollama_fallback_ignores_invalid_json(monkeypatch) -> None:
    payload = {"message": {"content": "not-json"}}
    monkeypatch.setattr(
        ollama_fallback.httpx,
        "Client",
        lambda timeout: FakeClient(FakeResponse(payload)),
    )

    response = ollama_fallback.ollama_fallback_normalize(
        text="weird input",
        normalized_text="weird input",
    )
    assert response is None


def test_ollama_fallback_ignores_unavailable_service(monkeypatch) -> None:
    def raising_client(timeout):
        raise RuntimeError("connection failed")

    monkeypatch.setattr(ollama_fallback.httpx, "Client", raising_client)
    response = ollama_fallback.ollama_fallback_normalize(
        text="weird input",
        normalized_text="weird input",
    )
    assert response is None
