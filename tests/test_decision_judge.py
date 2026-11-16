"""Gemini Decision 판단(D-23). 네트워크 없이 가짜 transport 로 돈다. 값은 전부 가상."""

import json

import pytest
from PIL import Image

from pipeline import analyze, decision_judge, llm_judge, ocr, wording
from pipeline.llm_judge import JudgeConfig, LlmJudgeError, parse_config
from pipeline.types import Box, Certainty, Severity, TextSpan

SPANS = [
    TextSpan("받는분", Box(10, 10, 60, 20), 0.97),
    TextSpan("홍길동", Box(80, 10, 60, 20), 0.96),
    TextSpan("연락처 010-1234-5678", Box(10, 40, 200, 20), 0.95),
    TextSpan("고객센터 1588-0000", Box(10, 70, 200, 20), 0.94),
    TextSpan("흐린 글자", Box(10, 100, 80, 20), 0.30),
]
CFG = JudgeConfig("gemini_decision", "gemini-decision-1", "test-key-not-real")


def answer(sev="none", conf=0.95, kind="not_personal", label=0.05):
    return {"sev": {"type": "choice", "choice": sev, "confidence": conf}, "kind": {"type": "choice", "choice": kind,
            "confidence": 0.9}, "label": {"type": "noul", "noul": label, "confidence": max(label, 1 - label)}}


def fake(per_span, seen=None):
    """per_span: 조각 번호 → answer(...). 없는 조각은 '아님'. 물은 질문에만 답한다."""
    def transport(url, headers, body, timeout):
        if seen is not None:
            seen.append({"url": url, "headers": headers, "body": body})
        out = {}
        for key in body["questions"]:
            q, i = key.rsplit("_", 1)
            out[key] = per_span.get(int(i), answer())[q]
        return {"answers": out, "usage": {"total_input_tokens": 100, "total_output_tokens": 0}}
    return transport


# ------------------------------------------------------------------ 설정

def test_config_needs_key_and_sends_outside():
    with pytest.raises(ValueError) as err:
        parse_config('{"provider":"gemini_decision","model":"gemini-decision-1"}')
    assert str(err.value) == wording.LLM_KEY_MISSING
    cfg = parse_config('{"provider":"gemini_decision","model":"gemini-decision-1","api_key":"k"}')
    assert cfg.sends_outside and cfg.label == "Gemini Decision · gemini-decision-1"


@pytest.mark.parametrize("extra", ['"reasoning":"high"', '"fast":true'])
def test_no_reasoning_or_fast(extra):
    with pytest.raises(ValueError):
        parse_config('{"provider":"gemini_decision","model":"m","api_key":"k",' + extra + "}")


# ------------------------------------------------------------------ 판단

def test_request_shape_key_in_header():
    seen = []
    llm_judge.evaluate(SPANS, CFG, width=300, height=200, transport=fake({}, seen))
    assert len(seen) == 1
    req = seen[0]
    assert req["url"] == decision_judge.URL and "key" not in req["url"]
    assert req["headers"] == {"x-goog-api-key": "test-key-not-real"}
    body = req["body"]
    assert body["model"] == "gemini-decision-1"
    assert body["input"].startswith(decision_judge.RUBRIC) and "홍길동" in body["input"]
    # 조각마다 등급·종류·라벨 질문 셋
    assert sorted(body["questions"]) == sorted(f"{q}_{i}" for i in range(len(SPANS)) for q in ("sev", "kind", "label"))
    assert body["questions"]["sev_1"]["criteria"] == decision_judge.SEV_CRITERIA


def test_answers_become_findings_with_safe_wording():
    got = llm_judge.evaluate(SPANS, CFG, width=300, height=200, transport=fake({
        1: answer("cover", 0.97, "name"),
        2: answer("cover", 0.99, "mobile"),
        3: answer("public", 0.9, "service_line"),
    }))
    by = {f.kind: f for f in got}
    assert set(by) == {"name", "mobile", "service_line"}
    assert by["name"].severity is Severity.COVER and by["name"].evidence_text == "홍길동"
    assert by["name"].message == wording.found("name") and by["name"].detail["judge"] == "decision"
    assert by["service_line"].severity is Severity.INFO and by["service_line"].message == wording.found_public("service_line")
    assert by["mobile"].box == SPANS[2].box


def test_label_only_spans_are_not_values():
    got = llm_judge.evaluate(SPANS, CFG, width=300, height=200, transport=fake({
        0: answer("cover", 0.9, "name", label=0.95),   # '받는분' 라벨 자체
        1: answer("cover", 0.97, "name", label=0.1),
    }))
    assert [f.span_index for f in got] == [1]


def test_unknown_kind_falls_back_to_other():
    got = llm_judge.evaluate(SPANS, CFG, width=300, height=200, transport=fake({1: answer("review", 0.9, "not_personal")}))
    assert got[0].kind == "other" and got[0].severity is Severity.REVIEW


def test_low_ocr_confidence_needs_high_model_confidence():
    spans = [TextSpan("흐린값", Box(0, 0, 50, 20), 0.6), TextSpan("못읽음", Box(0, 40, 50, 20), 0.3)]
    weak = llm_judge.evaluate(spans, CFG, width=100, height=100, transport=fake({
        0: answer("cover", 0.6, "name"), 1: answer("cover", 0.85, "name")}))
    assert weak == []
    strong = llm_judge.evaluate(spans, CFG, width=100, height=100, transport=fake({
        0: answer("cover", 0.8, "name"), 1: answer("cover", 0.95, "name")}))
    partial, unread = sorted(strong, key=lambda f: f.span_index)
    assert partial.certainty is Certainty.PARTIAL and partial.severity is Severity.COVER
    # 못 읽은 글자는 내용 없이 영역으로만
    assert unread.certainty is Certainty.REGION_ONLY and unread.evidence_text is None
    assert unread.severity is Severity.REVIEW


def test_split_card_number_grouped_by_rules_not_model():
    # 9 로 시작하는 가상 카드번호(Luhn 통과)를 4자리씩
    valid_luhn = decision_judge.context.kp.valid_luhn
    digits = next(d for d in (f"941012341234123{c}" for c in range(10)) if valid_luhn(d))
    spans = [TextSpan(digits[k:k + 4], Box(10 + 70 * (k // 4), 10, 60, 20), 0.95) for k in range(0, 16, 4)]
    got = llm_judge.evaluate(spans, CFG, width=400, height=100,
                             transport=fake({i: answer("cover", 0.9, "card") for i in range(4)}))
    assert len(got) == 1
    card = got[0]
    assert card.kind == "card" and card.detail["span_indices"] == [0, 1, 2, 3]
    assert card.evidence_text == " ".join(digits[k:k + 4] for k in range(0, 16, 4))


def test_many_spans_split_into_calls_under_question_limit():
    spans = [TextSpan(f"낱말{i}", Box(10, 10 + 25 * i, 60, 20), 0.95) for i in range(350)]
    seen = []
    llm_judge.evaluate(spans, CFG, width=200, height=9000, transport=fake({}, seen))
    assert [len(s["body"]["questions"]) for s in seen] == [900, 150]
    assert all(len(s["body"]["questions"]) <= 1000 for s in seen)
    assert seen[0]["body"]["input"] == seen[1]["body"]["input"]  # 같은 입력으로 나눠 묻는다


def test_bad_reply_raises_safe_error_with_trace():
    trace = []
    with pytest.raises(LlmJudgeError) as err:
        llm_judge.evaluate(SPANS, CFG, width=300, height=200, trace=trace,
                           transport=lambda url, headers, body, timeout: {"answers": {"sev_0": "oops"}})
    assert str(err.value) == wording.LLM_BAD_RESPONSE
    assert trace and trace[-1]["ok"] is False
    assert "test-key-not-real" not in json.dumps(trace)


def test_no_spans_no_call():
    def boom(*a):
        raise AssertionError("부르면 안 된다")
    assert llm_judge.evaluate([], CFG, width=1, height=1, transport=boom) == []


def test_analyze_uses_decision_judge():
    img = Image.new("RGB", (300, 200), "white")
    report = analyze.analyze(img, backend=ocr.ScriptedBackend(SPANS), detector=None, judge=CFG,
                             llm_transport=fake({1: answer("cover", 0.97, "name")}))
    assert [f.kind for f in report.findings] == ["name"]
    assert report.judge == "Gemini Decision · gemini-decision-1" and report.judge_provider == "gemini_decision"


# ------------------------------------------------------------------ 모델 목록

def test_model_list_only_decision_models():
    seen = []

    def get(url, headers, timeout):
        seen.append((url, headers))
        return {"models": [{"name": "models/gemini-decision-1", "supportedGenerationMethods": ["createDecision"]},
                           {"name": "models/gemini-flash-latest", "supportedGenerationMethods": ["generateContent"]}]}
    names = llm_judge.list_models(JudgeConfig("gemini_decision", "", "k"), transport=get)
    assert names == ["gemini-decision-1"]
    assert "generativelanguage.googleapis.com/v1beta/models" in seen[0][0] and seen[0][1] == {"x-goog-api-key": "k"}
