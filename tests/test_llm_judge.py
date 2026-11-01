"""LLM 판단(개발자 모드). 네트워크 없이 가짜 transport 로 돈다. 값은 전부 가상."""

import json

import pytest
from PIL import Image

from pipeline import analyze, llm_judge, ocr, wording
from pipeline.llm_judge import JudgeConfig, LlmJudgeError, parse_config
from pipeline.types import Box, Certainty, Severity, TextSpan

SPANS = [
    TextSpan("받는분", Box(10, 10, 60, 20), 0.97),
    TextSpan("홍길동", Box(80, 10, 60, 20), 0.96),
    TextSpan("연락처 010-1234-5678", Box(10, 40, 200, 20), 0.95),
    TextSpan("고객센터 1588-0000", Box(10, 70, 200, 20), 0.94),
    TextSpan("흐린 글자", Box(10, 100, 80, 20), 0.30),
]
CFG = JudgeConfig("openai", "test-model", "sk-test-not-real")


def reply(findings) -> dict:
    """OpenAI 형식의 응답."""
    return {"choices": [{"message": {"content": json.dumps({"findings": findings}, ensure_ascii=False)}}]}


def fake(response, seen=None):
    def transport(url, headers, body, timeout):
        if seen is not None:
            seen.update(url=url, headers=headers, body=body)
        return response
    return transport


# ------------------------------------------------------------------ 설정

def test_rules_or_empty_means_no_llm():
    assert parse_config(None) is None
    assert parse_config("") is None
    assert parse_config('{"provider":"rules"}') is None


@pytest.mark.parametrize("raw, message", [
    ("not json", wording.LLM_CONFIG_INVALID),
    ('{"provider":"unknown","model":"m"}', wording.LLM_CONFIG_INVALID),
    ('{"provider":"openai","model":""}', wording.LLM_MODEL_MISSING),
    ('{"provider":"gemini","model":"m"}', wording.LLM_KEY_MISSING),
    ('{"provider":"custom","model":"m"}', wording.LLM_URL_MISSING),
    ('{"provider":"custom","model":"m","base_url":"file:///etc"}', wording.LLM_URL_MISSING),
])
def test_bad_config_rejected(raw, message):
    with pytest.raises(ValueError) as err:
        parse_config(raw)
    assert str(err.value) == message


def test_ollama_needs_no_key_and_has_default_url():
    cfg = parse_config('{"provider":"ollama","model":"qwen2.5:7b"}')
    assert cfg.base_url == "http://127.0.0.1:11434"
    assert not cfg.sends_outside
    assert parse_config('{"provider":"anthropic","model":"m","api_key":"k"}').sends_outside


# ------------------------------------------------------------------ 판단

def test_llm_findings_become_report_items():
    out = llm_judge.evaluate(SPANS, CFG, width=300, height=200, transport=fake(reply([
        {"i": 1, "kind": "name", "severity": "cover", "text": "홍길동", "near": "받는분"},
        {"i": 2, "kind": "mobile", "severity": "cover", "text": "010-1234-5678", "near": "연락처"},
        {"i": 3, "kind": "service_line", "severity": "info", "text": "1588-0000", "near": "고객센터"},
    ])))
    by = {f.kind: f for f in out}
    assert by["name"].severity is Severity.COVER and by["name"].box == SPANS[1].box
    assert by["name"].message == wording.found("name", near="받는분")
    assert by["mobile"].evidence_text == "010-1234-5678"
    assert by["service_line"].message == wording.found_public("service_line", near="고객센터")
    assert all(f.detail == {"judge": "llm"} for f in out)


def test_invented_text_and_labels_are_not_shown():
    out = llm_judge.evaluate(SPANS, CFG, width=300, height=200, transport=fake(reply([
        {"i": 2, "kind": "mobile", "severity": "cover", "text": "010-9999-9999", "near": "수취인 전화"},
    ])))
    assert out[0].evidence_text == SPANS[2].text   # 조각에 없는 값 대신 조각 원문
    assert out[0].context_words == []               # 사진에 없는 라벨은 근거로 쓰지 않는다


def test_unreadable_span_stays_region_only():
    out = llm_judge.evaluate(SPANS, CFG, width=300, height=200, transport=fake(reply([
        {"i": 4, "kind": "name", "severity": "cover", "text": "흐린 글자"},
    ])))
    assert out[0].certainty is Certainty.REGION_ONLY and out[0].evidence_text is None


def test_invalid_items_dropped():
    out = llm_judge.evaluate(SPANS, CFG, width=300, height=200, transport=fake(reply([
        {"i": 99, "kind": "name", "severity": "cover"},
        {"i": 1, "kind": "made_up", "severity": "cover"},
        {"i": 1, "kind": "name", "severity": "very high"},
        {"i": True, "kind": "name", "severity": "cover"},
        "not an object",
        {"i": 1, "kind": "name", "severity": "cover", "text": "홍길동"},
        {"i": 1, "kind": "name", "severity": "cover", "text": "홍길동"},
    ])))
    assert len(out) == 1


def test_code_fence_and_chatter_tolerated():
    text = '설명입니다\n```json\n{"findings":[{"i":1,"kind":"name","severity":"review","text":"홍길동"}]}\n```'
    out = llm_judge.evaluate(SPANS, CFG, width=300, height=200,
                             transport=fake({"choices": [{"message": {"content": text}}]}))
    assert out[0].severity is Severity.REVIEW


def test_unparseable_reply_raises_safe_error():
    with pytest.raises(LlmJudgeError) as err:
        llm_judge.evaluate(SPANS, CFG, width=300, height=200,
                           transport=fake({"choices": [{"message": {"content": "모르겠어요"}}]}))
    assert str(err.value) == wording.LLM_BAD_RESPONSE


def test_no_spans_no_call():
    def boom(*_):
        raise AssertionError("부르면 안 된다")
    assert llm_judge.evaluate([], CFG, width=1, height=1, transport=boom) == []


@pytest.mark.parametrize("provider, url_part, key_header, response", [
    ("openai", "api.openai.com/v1/chat/completions", "Authorization",
     {"choices": [{"message": {"content": '{"findings":[]}'}}]}),
    ("openrouter", "openrouter.ai/api/v1/chat/completions", "Authorization",
     {"choices": [{"message": {"content": '{"findings":[]}'}}]}),
    ("anthropic", "api.anthropic.com/v1/messages", "x-api-key",
     {"content": [{"type": "text", "text": '{"findings":[]}'}]}),
    ("gemini", "generativelanguage.googleapis.com/v1beta/models/m-1:generateContent", "x-goog-api-key",
     {"candidates": [{"content": {"parts": [{"text": '{"findings":[]}'}]}}]}),
])
def test_cloud_providers_send_key_in_header_not_url(provider, url_part, key_header, response):
    seen = {}
    llm_judge.evaluate(SPANS, JudgeConfig(provider, "m-1", "sk-test-not-real"), width=300, height=200,
                       transport=fake(response, seen))
    assert url_part in seen["url"] and "sk-test" not in seen["url"]
    assert "sk-test-not-real" in seen["headers"][key_header]


def test_local_providers():
    seen = {}
    llm_judge.evaluate(SPANS, JudgeConfig("ollama", "qwen", "", "http://127.0.0.1:11434"), width=300, height=200,
                       transport=fake({"message": {"content": '{"findings":[]}'}}, seen))
    assert seen["url"] == "http://127.0.0.1:11434/api/chat" and seen["headers"] == {}
    llm_judge.evaluate(SPANS, JudgeConfig("custom", "local", "", "http://localhost:1234/v1"), width=300, height=200,
                       transport=fake({"choices": [{"message": {"content": '{"findings":[]}'}}]}, seen))
    assert seen["url"] == "http://localhost:1234/v1/chat/completions" and "Authorization" not in seen["headers"]


def test_prompt_carries_spans_and_positions():
    seen = {}
    llm_judge.evaluate(SPANS, CFG, width=300, height=200, transport=fake(reply([]), seen))
    user = json.loads(seen["body"]["messages"][1]["content"])
    assert user["image"] == {"width": 300, "height": 200}
    assert user["spans"][2]["text"] == SPANS[2].text and user["spans"][2]["y"] == 40


# ------------------------------------------------------------------ 파이프라인

def test_analyze_uses_llm_instead_of_rules():
    img = Image.new("RGB", (300, 200), "white")
    report = analyze.analyze(img, backend=ocr.ScriptedBackend(SPANS), detector=None, judge=CFG,
                             llm_transport=fake(reply([])))
    # 규칙이라면 '연락처' 옆 휴대폰을 찾았을 것이다. LLM 이 비었다고 하면 비어 있어야 한다.
    assert [f for f in report.findings if f.kind == "mobile"] == []
    assert report.judge == "ChatGPT · test-model" and report.judge_provider == "openai"

    rules = analyze.analyze(img, backend=ocr.ScriptedBackend(SPANS), detector=None)
    assert any(f.kind == "mobile" for f in rules.findings)
    assert rules.as_dict()["judge"] == "규칙 기반"


# ------------------------------------------------------------------ 모델 목록

def fake_get(pages, seen):
    def get(url, headers, timeout):
        seen.append((url, headers))
        return pages[len(seen) - 1]
    return get


@pytest.mark.parametrize("provider, url_part, page", [
    ("openai", "api.openai.com/v1/models", {"data": [{"id": "m-b"}, {"id": "m-a"}]}),
    ("openrouter", "openrouter.ai/api/v1/models", {"data": [{"id": "m-a"}, {"id": "m-b"}]}),
    ("anthropic", "api.anthropic.com/v1/models", {"data": [{"id": "m-a"}, {"id": "m-b"}], "has_more": False}),
    ("gemini", "generativelanguage.googleapis.com/v1beta/models",
     {"models": [{"name": "models/m-a", "supportedGenerationMethods": ["generateContent"]},
                 {"name": "models/m-b", "supportedGenerationMethods": ["generateContent", "countTokens"]},
                 {"name": "models/embed", "supportedGenerationMethods": ["embedContent"]}]}),
])
def test_cloud_model_lists(provider, url_part, page):
    seen = []
    names = llm_judge.list_models(JudgeConfig(provider, "", "sk-test-not-real"), transport=fake_get([page], seen))
    assert names == ["m-a", "m-b"]
    assert url_part in seen[0][0] and "sk-test" not in seen[0][0]
    assert any("sk-test-not-real" in v for v in seen[0][1].values())


def test_local_model_lists():
    seen = []
    assert llm_judge.list_models(JudgeConfig("ollama", "", "", "http://127.0.0.1:11434"),
                                 transport=fake_get([{"models": [{"name": "qwen2.5:7b"}]}], seen)) == ["qwen2.5:7b"]
    assert seen[0] == ("http://127.0.0.1:11434/api/tags", {})
    seen = []
    llm_judge.list_models(JudgeConfig("custom", "", "", "http://localhost:1234/v1"),
                          transport=fake_get([{"data": [{"id": "local"}]}], seen))
    assert seen[0] == ("http://localhost:1234/v1/models", {})


def test_model_list_follows_pages():
    seen = []
    pages = [{"data": [{"id": "a"}], "has_more": True, "last_id": "a"}, {"data": [{"id": "b"}], "has_more": False}]
    assert llm_judge.list_models(JudgeConfig("anthropic", "", "k"), transport=fake_get(pages, seen)) == ["a", "b"]
    assert "after_id=a" in seen[1][0]
    seen = []
    pages = [{"models": [{"name": "models/a"}], "nextPageToken": "t2"}, {"models": [{"name": "models/b"}]}]
    assert llm_judge.list_models(JudgeConfig("gemini", "", "k"), transport=fake_get(pages, seen)) == ["a", "b"]
    assert "pageToken=t2" in seen[1][0]


def test_model_list_needs_key_not_model():
    assert parse_config('{"provider":"openai","api_key":"k"}', need_model=False).model == ""
    with pytest.raises(ValueError):
        parse_config('{"provider":"openai"}', need_model=False)


def test_bad_model_list_reply():
    with pytest.raises(LlmJudgeError):
        llm_judge.list_models(JudgeConfig("openai", "", "k"), transport=fake_get([{"oops": 1}], []))
