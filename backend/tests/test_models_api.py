import httpx
import pytest

from app.services import model_check
from conftest import MODEL


def test_key_is_never_returned(client, model):
    assert "api_key" not in model and "api_key_enc" not in model
    assert model["api_key_hint"] == "****1234"
    assert "sk-secret-1234" not in client.get("/api/v1/models").text
    assert "sk-secret-1234" not in client.get(f"/api/v1/models/{model['id']}").text


def test_key_is_encrypted_at_rest(client, model):
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import ModelEndpoint

    with SessionLocal() as db:
        stored = db.scalar(select(ModelEndpoint.api_key_enc))
    assert stored != "sk-secret-1234" and "secret" not in stored


def test_duplicate_name_conflicts(client, model):
    r = client.post("/api/v1/models", json=MODEL)
    assert r.status_code == 409 and r.json()["code"] == "name_taken"


def test_validation(client):
    assert client.post("/api/v1/models", json={**MODEL, "base_url": "ftp://x"}).status_code == 422
    assert client.post("/api/v1/models", json={**MODEL, "protocol": "grpc"}).status_code == 422


def test_update_keeps_key_when_omitted(client, model):
    r = client.put(f"/api/v1/models/{model['id']}", json={"model_name": "gpt-y"})
    assert r.status_code == 200 and r.json()["model_name"] == "gpt-y" and r.json()["api_key_hint"] == "****1234"
    r = client.put(f"/api/v1/models/{model['id']}", json={"api_key": "sk-new-9999"})
    assert r.json()["api_key_hint"] == "****9999"


def test_cannot_delete_model_in_use(client, model, vmcq_dataset):
    client.post("/api/v1/runs", json={"model_ids": [model["id"]], "dataset_ids": [vmcq_dataset["id"]]})
    r = client.delete(f"/api/v1/models/{model['id']}")
    assert r.status_code == 409 and r.json()["code"] == "model_in_use"


# ---------------------------------------------------------------- connectivity check (mock HTTP)

def _install_mock(monkeypatch, handler):
    real = httpx.Client
    monkeypatch.setattr(model_check.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(model_check.random, "randint", lambda a, b: 123)


def _openai_handler(request: httpx.Request) -> httpx.Response:
    assert request.url.path == "/v1/chat/completions"
    body = __import__("json").loads(request.content)
    content = body["messages"][0]["content"]
    usage = {"prompt_tokens": 4100}
    if body.get("tools"):
        return httpx.Response(200, json={"choices": [{"message": {"content": None, "tool_calls": [{"id": "1"}]}}], "usage": usage})
    if isinstance(content, list):  # image request: the "model" reads the code back
        return httpx.Response(200, json={"choices": [{"message": {"content": "CODE-123"}}], "usage": usage})
    return httpx.Response(200, json={"choices": [{"message": {"content": "pong"}}], "usage": usage})


def test_check_openai_protocol(monkeypatch):
    _install_mock(monkeypatch, _openai_handler)
    r = model_check.check_model("openai", "http://gw.example.com", "k", "m")
    assert r["ok"] and all(c["ok"] for c in r["checks"].values())
    joined = " ".join(r["warnings"])
    assert "HTTP" in joined and "4100" in joined  # plain-http warning and big token baseline warning


def test_check_anthropic_protocol(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/messages"
        assert request.headers["x-api-key"] == "k" and request.headers["anthropic-version"]
        body = __import__("json").loads(request.content)
        content = body["messages"][0]["content"]
        usage = {"input_tokens": 10}
        if body.get("tools"):
            return httpx.Response(200, json={"content": [{"type": "tool_use", "name": "get_weather", "input": {}}], "usage": usage})
        if isinstance(content, list):
            assert content[0]["type"] == "image" and content[0]["source"]["type"] == "base64"
            return httpx.Response(200, json={"content": [{"type": "text", "text": "CODE-123"}], "usage": usage})
        return httpx.Response(200, json={"content": [{"type": "text", "text": "pong"}], "usage": usage})

    _install_mock(monkeypatch, handler)
    r = model_check.check_model("anthropic", "https://gw.example.com/v1", "k", "m")  # trailing /v1 must be tolerated
    assert r["ok"] and r["checks"]["tools"]["ok"] and r["warnings"] == []


def test_check_detects_a_model_that_does_not_see_images(monkeypatch):
    def handler(request):
        body = __import__("json").loads(request.content)
        if isinstance(body["messages"][0]["content"], list):
            return httpx.Response(200, json={"choices": [{"message": {"content": "I cannot see any image"}}], "usage": {}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "pong"}}], "usage": {}})

    _install_mock(monkeypatch, handler)
    r = model_check.check_model("openai", "https://gw.example.com", "k", "m")
    assert not r["ok"] and not r["checks"]["image"]["ok"] and r["checks"]["text"]["ok"]


def test_check_failure_never_leaks_the_key(monkeypatch):
    _install_mock(monkeypatch, lambda req: httpx.Response(401, text="bad key sk-leaky-key"))
    r = model_check.check_model("openai", "https://gw.example.com", "sk-leaky-key", "m")
    assert not r["ok"] and "sk-leaky-key" not in str(r)


def test_check_endpoint_stores_result(client, model, monkeypatch):
    _install_mock(monkeypatch, _openai_handler)
    r = client.post(f"/api/v1/models/{model['id']}/check")
    assert r.status_code == 200 and r.json()["ok"]
    assert client.get(f"/api/v1/models/{model['id']}").json()["last_check"]["ok"] is True


@pytest.mark.parametrize("url,expected", [("https://a.com", "https://a.com/v1"), ("https://a.com/v1/", "https://a.com/v1")])
def test_openai_base(url, expected):
    assert model_check.openai_base(url) == expected
