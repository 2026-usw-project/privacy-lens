"""서버 .env 의 기본 판단 모델(D-22): .env 읽기, PL_JUDGE_*, 화면에 키를 내려보내지 않기."""

import json
import os

import pytest

import envfile
from pipeline import llm_judge

KEY = "sk-test-not-real-1234"


def test_envfile_parse_and_load(tmp_path, monkeypatch):
    p = tmp_path / ".env"
    p.write_text('# 주석\nexport PL_A="따옴표 값"\nPL_B=plain # 뒤 주석\nPL_C=\'a#b\'\n1BAD=x\nPL_KEEP=file\n',
                 encoding="utf-8")
    monkeypatch.setenv("PL_KEEP", "shell")
    for name in ("PL_A", "PL_B", "PL_C"):
        monkeypatch.delenv(name, raising=False)
    added = envfile.load(p)
    assert sorted(added) == ["PL_A", "PL_B", "PL_C"]
    assert os.environ["PL_A"] == "따옴표 값" and os.environ["PL_B"] == "plain" and os.environ["PL_C"] == "a#b"
    assert os.environ["PL_KEEP"] == "shell"  # 이미 있는 환경 변수가 이긴다
    assert envfile.load(tmp_path / "없음.env") == []


def test_server_default_from_env():
    env = {"PL_JUDGE_PROVIDER": "Anthropic", "PL_JUDGE_MODEL": "claude-haiku-5-5", "PL_JUDGE_REASONING": "low",
           "PL_JUDGE_API_KEY": KEY, "PL_JUDGE_FAST": "true"}
    cfg = llm_judge.server_default(env)
    assert (cfg.provider, cfg.model, cfg.reasoning, cfg.api_key, cfg.fast) == ("anthropic", "claude-haiku-5-5", "low", KEY, True)
    assert llm_judge.server_default({}) is None
    assert llm_judge.server_default({"PL_JUDGE_PROVIDER": "rules"}) is None


@pytest.mark.parametrize("env", [
    {"PL_JUDGE_PROVIDER": "openai", "PL_JUDGE_MODEL": "m"},                                  # 키 없음
    {"PL_JUDGE_PROVIDER": "nope", "PL_JUDGE_MODEL": "m"},
    {"PL_JUDGE_PROVIDER": "anthropic", "PL_JUDGE_MODEL": "m", "PL_JUDGE_API_KEY": KEY, "PL_JUDGE_REASONING": "none"},
])
def test_server_default_invalid_does_not_leak_key(env):
    with pytest.raises(ValueError) as exc:
        llm_judge.server_default(env)
    assert KEY not in str(exc.value)


def test_public_default_has_no_key_or_url():
    cfg = llm_judge.server_default({"PL_JUDGE_PROVIDER": "ollama", "PL_JUDGE_MODEL": "q",
                                    "PL_JUDGE_BASE_URL": "http://10.0.0.5:11434"})
    pub = llm_judge.public_default(cfg)
    assert pub["has_url"] and pub["sends_outside"] and "10.0.0.5" not in json.dumps(pub)
    cloud = llm_judge.public_default(llm_judge.server_default(
        {"PL_JUDGE_PROVIDER": "gemini", "PL_JUDGE_MODEL": "g", "PL_JUDGE_API_KEY": KEY}))
    assert cloud["has_key"] and KEY not in json.dumps(cloud)
    assert llm_judge.public_default(None) == {"provider": "rules"}


def test_parse_config_fills_from_server_default():
    server = llm_judge.server_default({"PL_JUDGE_PROVIDER": "openai", "PL_JUDGE_MODEL": "m", "PL_JUDGE_API_KEY": KEY})
    same = llm_judge.parse_config(json.dumps({"provider": "openai", "model": "other"}), server=server)
    assert same.api_key == KEY and same.model == "other"
    own = llm_judge.parse_config(json.dumps({"provider": "openai", "model": "m", "api_key": "mine"}), server=server)
    assert own.api_key == "mine"  # 화면이 넣은 키가 이긴다
    with pytest.raises(ValueError):  # 다른 공급자에는 서버 키를 쓰지 않는다
        llm_judge.parse_config(json.dumps({"provider": "gemini", "model": "g"}), server=server)


def test_server_endpoint_and_analyze_use_env_key(monkeypatch):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    import server
    from pipeline import ocr
    from pipeline.types import Box, TextSpan
    from tests.test_server import png

    monkeypatch.setattr(server, "SERVER_JUDGE", llm_judge.server_default(
        {"PL_JUDGE_PROVIDER": "openai", "PL_JUDGE_MODEL": "m", "PL_JUDGE_REASONING": "low", "PL_JUDGE_API_KEY": KEY}))
    monkeypatch.setattr(server, "_backend", ocr.ScriptedBackend([TextSpan("받는분 010-1234-5678", Box(10, 10, 200, 20), 0.95)]))
    seen = {}

    def transport(url, headers, body, timeout):
        seen["auth"] = headers.get("Authorization")
        return {"choices": [{"message": {"content": json.dumps({"findings": []})}}]}

    monkeypatch.setattr(llm_judge, "_http_post", transport)
    client = TestClient(server.app)
    pub = client.get("/judge/default").json()
    assert pub["provider"] == "openai" and pub["reasoning"] == "low" and pub["has_key"] and KEY not in json.dumps(pub)
    judge = json.dumps({"provider": "openai", "model": "m", "api_key": "", "reasoning": "low"})
    r = client.post("/analyze", files={"image": ("a.png", png())}, data={"judge": judge})
    assert r.status_code == 200 and seen["auth"] == f"Bearer {KEY}"
    assert KEY not in r.text  # 응답(llm_trace 포함)에 키 전체가 나가지 않는다
