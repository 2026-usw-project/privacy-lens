"""LLM 판단(판단 모델 창). 네트워크 없이 가짜 transport 로 돈다. 값은 전부 가상."""

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
        {"i": [1], "kind": "name", "severity": "cover", "text": "홍길동", "basis": "label", "label_i": 0},
        # 라벨과 값이 한 조각: 값 앞부분이 라벨
        {"i": 2, "kind": "mobile", "severity": "cover", "text": "010-1234-5678", "basis": "label", "label_i": 2},
        {"i": 3, "kind": "service_line", "severity": "info", "text": "1588-0000", "basis": "label", "label_i": 3},
    ])))
    by = {f.kind: f for f in out}
    assert by["name"].severity is Severity.COVER and by["name"].box == SPANS[1].box
    assert by["name"].message == wording.found("name", near="받는분")
    assert by["name"].detail["basis"] == "label" and by["name"].detail["basis_box"] == SPANS[0].box.as_dict()
    assert by["mobile"].evidence_text == "010-1234-5678"
    assert by["mobile"].message == wording.found("mobile", near="연락처")
    assert by["service_line"].message == wording.found_public("service_line", near="고객센터")


def test_invented_text_is_not_shown():
    out = llm_judge.evaluate(SPANS, CFG, width=300, height=200, transport=fake(reply([
        {"i": 2, "kind": "mobile", "severity": "cover", "text": "010-9999-9999", "basis": "format"},
    ])))
    assert out[0].evidence_text == SPANS[2].text   # 조각에 없는 값 대신 조각 원문
    assert out[0].message == wording.found("mobile") and out[0].context_words == []


# 카드 장면(가상): 카드번호가 4자리씩 끊겨 읽히고, 아래에 유효기간 라벨과 영문 이름, 멀리 떨어진 다른 종이
CARD = [
    TextSpan("가상카드", Box(20, 20, 120, 30), 0.97),         # 0 카드사
    TextSpan("1234", Box(20, 100, 80, 30), 0.96),             # 1
    TextSpan("5678", Box(110, 100, 80, 30), 0.96),            # 2
    TextSpan("9012", Box(200, 100, 80, 30), 0.96),            # 3
    TextSpan("3456", Box(290, 100, 80, 30), 0.96),            # 4
    TextSpan("VALID THRU", Box(20, 150, 110, 20), 0.95),      # 5
    TextSpan("01/30", Box(140, 150, 60, 20), 0.95),           # 6
    TextSpan("HONG GILDONG", Box(20, 190, 200, 24), 0.95),    # 7
    TextSpan("고객센터", Box(1500, 1500, 100, 24), 0.95),       # 8 다른 종이, 멀리
]


def card_eval(findings):
    return llm_judge.evaluate(CARD, CFG, width=2000, height=2000, transport=fake(reply(findings)))


def test_split_value_becomes_one_item_with_joined_box():
    out = card_eval([{"i": [1, 2, 3, 4], "kind": "card", "severity": "cover", "text": "1234 5678 9012 3456",
                      "basis": "format"}])
    assert len(out) == 1
    assert out[0].box.as_dict() == {"x": 20, "y": 100, "w": 350, "h": 30}
    assert out[0].evidence_text == "1234 5678 9012 3456" and out[0].detail["parts"] == 4


def test_label_must_be_near_and_not_a_value():
    out = card_eval([
        {"i": [1, 2, 3, 4], "kind": "card", "severity": "cover", "basis": "format"},
        {"i": 6, "kind": "other", "severity": "cover", "text": "01/30", "basis": "label", "label_i": 5},
        # 멀리 있는 조각을 라벨로 → 형식 근거로 내림
        {"i": 7, "kind": "name", "severity": "cover", "basis": "label", "label_i": 8},
    ])
    by = {f.kind: f for f in out}
    assert by["other"].message == wording.found("other", near="VALID THRU")
    assert by["name"].message == wording.found("name") and by["name"].detail["basis"] == "format"

    # 다른 개인정보 값(카드번호 조각)을 라벨로 → 내림
    out = card_eval([
        {"i": [1, 2, 3, 4], "kind": "card", "severity": "cover", "basis": "format"},
        {"i": 7, "kind": "name", "severity": "cover", "basis": "label", "label_i": 4},
    ])
    name = next(f for f in out if f.kind == "name")
    assert name.context_words == [] and "3456" not in name.message


def test_linked_and_document_basis_name_kinds_not_values():
    out = card_eval([
        {"i": [1, 2, 3, 4], "kind": "card", "severity": "cover", "basis": "format"},
        {"i": 7, "kind": "name", "severity": "cover", "basis": "linked", "with": [1, 99]},
        {"i": 0, "kind": "other", "severity": "review", "basis": "document", "doc": "id_card"},
    ])
    by = {f.kind: f for f in out}
    assert by["name"].message == wording.found_linked("name", "card")
    assert "1234" not in by["name"].message and by["name"].detail["linked_kinds"] == ["card"]
    assert by["other"].message == wording.found_in_document("other", "id_card")
    assert by["other"].detail["document_hint"] == "id_card"

    # 목록에 없는 문서, 이번 출력에 없는 개인정보와의 연결 → 형식 근거
    out = card_eval([
        {"i": 7, "kind": "name", "severity": "cover", "basis": "linked", "with": [6]},
        {"i": 0, "kind": "other", "severity": "review", "basis": "document", "doc": "passport"},
    ])
    assert all(f.detail["basis"] == "format" for f in out)


def test_honorific_only_for_names():
    spans = [TextSpan("홍길동님", Box(0, 0, 80, 20), 0.95)]
    out = llm_judge.evaluate(spans, CFG, width=100, height=100, transport=fake(reply([
        {"i": 0, "kind": "name", "severity": "review", "text": "홍길동", "basis": "honorific"}])))
    assert out[0].message == wording.found_honorific("name")


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


def test_trace_records_exchange_with_masked_key():
    trace = []
    llm_judge.evaluate(SPANS, CFG, width=300, height=200, transport=fake(reply([
        {"i": 1, "kind": "name", "severity": "cover", "text": "홍길동"}])), trace=trace)
    entry = trace[0]
    assert entry["ok"] is True and entry["kind"] == "judge" and entry["provider"] == "openai"
    assert entry["headers"]["Authorization"] == "Bearer …real"
    assert entry["request"]["messages"][1]["content"]   # 보낸 내용
    assert entry["response"]["choices"]                  # 받은 내용
    assert "sk-test-not-real" not in json.dumps(trace, ensure_ascii=False)


def test_trace_kept_when_reply_unparseable():
    trace = []
    with pytest.raises(LlmJudgeError) as err:
        llm_judge.evaluate(SPANS, CFG, width=300, height=200, trace=trace,
                           transport=fake({"choices": [{"message": {"content": "모르겠어요"}}]}))
    assert err.value.trace is trace and trace[0]["ok"] is False
    assert trace[0]["error"] == wording.LLM_BAD_RESPONSE and trace[0]["response"]["choices"]


def test_trace_kept_when_provider_fails():
    def boom(*_):
        raise LlmJudgeError(wording.LLM_AUTH_FAILED, status=401, provider_body='{"error":"bad key"}')
    trace = []
    with pytest.raises(LlmJudgeError):
        llm_judge.evaluate(SPANS, CFG, width=300, height=200, transport=boom, trace=trace)
    assert trace[0]["status"] == 401 and trace[0]["response"] == '{"error":"bad key"}'


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
    span = user["spans"][2]
    assert span["text"] == SPANS[2].text and span["box"] == [10, 40, 200, 20]
    # 글줄 관계: '홍길동'의 바로 왼쪽은 '받는분', 같은 줄에서 두 번째
    name = user["spans"][1]
    assert name["left"] == 0 and name["line"] == user["spans"][0]["line"] and name["order"] == 1
    assert user["spans"][0]["left"] is None


def test_relations_lines_and_documents():
    rel = llm_judge._relations(CARD)
    assert {rel[k]["line"] for k in (1, 2, 3, 4)} == {rel[1]["line"]}          # 카드번호 네 조각은 한 줄
    assert [rel[k]["order"] for k in (1, 2, 3, 4)] == [0, 1, 2, 3]
    assert rel[2]["left"] == 1 and rel[6]["left"] == 5
    assert rel[0]["line"] < rel[1]["line"] < rel[5]["line"] < rel[7]["line"]   # 위에서 아래로
    assert rel[8]["doc"] != rel[1]["doc"]                                       # 멀리 있는 종이는 다른 묶음


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
