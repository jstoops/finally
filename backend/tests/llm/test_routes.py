"""POST /api/chat and GET /api/chat/history status codes and shapes (PLAN §8)."""

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.api import chat as chat_api
from app.llm import ChatResponse, LLMCallFailed
from app.llm import chat as chat_module


@pytest.fixture
def client(state):
    # Mirrors main.py's contract: HTTPException -> {"error": detail}
    app = FastAPI()

    @app.exception_handler(HTTPException)
    async def _http_error(request, exc):
        return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})

    app.include_router(chat_api.router)
    app.state.ctx = state
    with TestClient(app) as c:
        yield c


def test_post_chat_mock_buy(client, mock_mode):
    r = client.post("/api/chat", json={"message": "buy"})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"id", "role", "content", "actions", "created_at"}
    assert body["role"] == "assistant"
    assert body["actions"]["trades"][0]["status"] == "executed"
    assert body["created_at"].endswith("Z")


def test_post_chat_null_actions(client, mock_mode):
    r = client.post("/api/chat", json={"message": "hi"})
    assert r.status_code == 200
    assert r.json()["actions"] is None


def test_post_chat_503_when_unconfigured(client, monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "false")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    r = client.post("/api/chat", json={"message": "hi"})
    assert r.status_code == 503
    assert r.json() == {"error": "AI assistant is not configured. Set OPENROUTER_API_KEY in .env."}


def test_post_chat_502_on_llm_failure(client, real_mode, monkeypatch):
    async def fail(messages):
        raise LLMCallFailed("The AI assistant returned an invalid response.")

    monkeypatch.setattr(chat_module, "call_llm", fail)
    r = client.post("/api/chat", json={"message": "hi"})
    assert r.status_code == 502
    assert r.json() == {"error": "The AI assistant returned an invalid response."}
    history = client.get("/api/chat/history").json()["messages"]
    assert [m["role"] for m in history] == ["user"]


def test_post_chat_real_path_stubbed(client, real_mode, monkeypatch):
    async def ok(messages):
        return ChatResponse(message="Your portfolio is all cash.")

    monkeypatch.setattr(chat_module, "call_llm", ok)
    r = client.post("/api/chat", json={"message": "how am I doing"})
    assert r.status_code == 200
    assert r.json()["content"] == "Your portfolio is all cash."


def test_post_chat_validation(client, mock_mode):
    assert client.post("/api/chat", json={}).status_code == 422
    assert client.post("/api/chat", json={"message": 5}).status_code == 422
    r = client.post("/api/chat", json={"message": "   "})
    assert r.status_code == 400
    assert "error" in r.json()


def test_history_empty_then_ordered(client, mock_mode):
    assert client.get("/api/chat/history").json() == {"messages": []}
    client.post("/api/chat", json={"message": "hello"})
    client.post("/api/chat", json={"message": "buy"})
    msgs = client.get("/api/chat/history").json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert msgs[0] == {
        "id": msgs[0]["id"],
        "role": "user",
        "content": "hello",
        "actions": None,
        "created_at": msgs[0]["created_at"],
    }
    assert msgs[3]["actions"]["trades"][0]["ticker"] == "AAPL"


def test_history_last_50(client, mock_mode):
    for i in range(30):
        client.post("/api/chat", json={"message": f"hi {i}"})
    msgs = client.get("/api/chat/history").json()["messages"]
    assert len(msgs) == 50
    assert msgs[0]["content"] == "hi 5"
    assert msgs[-1]["role"] == "assistant"
