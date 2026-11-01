"""판단 평가(eval.judgment)와 실패 원인 분류(eval.failures)의 채점 규칙."""

from __future__ import annotations

from eval import failures, judgment
from pipeline import kr_patterns as kp
from pipeline.types import Box, Certainty, Finding, Severity


def _finding(index, severity, evidence):
    return Finding(kind="x", box=Box(0, 0, 1, 1), certainty=Certainty.READ, severity=severity,
                   message="", evidence_text=evidence, span_index=index)


def test_fake_data_is_valid_and_deterministic():
    a, b = judgment.build(per_template=2), judgment.build(per_template=2)
    assert [s.lines for s in a] == [s.lines for s in b]
    f = judgment.Fake(1)
    assert kp.valid_rrn(f.rrn()) and kp.valid_luhn(f.card()) and kp.valid_brn(f.brn())
    assert f.email().endswith("@example.com")
    # 모든 정답 글자는 장면 안에 그대로 있다
    for sc in a:
        blob = " ".join(t for line in sc.lines for t in line)
        assert all(g.text in blob for g in sc.gold), sc.sid


def test_verdict_table():
    assert judgment.verdict("cover", "cover") == "맞음"
    assert judgment.verdict("cover", "review").startswith("약함")
    assert judgment.verdict("cover", "none") == "놓침"
    assert judgment.verdict("none", "cover").startswith("오탐")
    assert judgment.verdict("review", "cover").startswith("과함")


def test_labeled_waybill_is_fully_correct_with_current_rules():
    # 지금 규칙이 확실히 하는 것(라벨 있는 송장)은 계속 맞아야 한다. 규칙을 고치다 깨지면 여기서 걸린다
    scenes = [s for s in judgment.build(per_template=4) if s.category == "송장(라벨 있음)"]
    rows = judgment.run(scenes)
    assert rows and all(r["verdict"] == "맞음" for r in rows)


def test_summary_counts():
    s = judgment.summarize(judgment.run(judgment.build(per_template=1)))
    assert s["items"] == s["cover_total"] + s["review_total"] + s["none_total"]


def test_failure_causes():
    texts = ["받는분 홍길동", "01O-l234-5678", "고객센터"]
    gold = {"text": "홍길동", "expect": "cover"}
    assert failures.classify(gold, texts, [_finding(0, Severity.COVER, "홍길동")])[0] == "맞음"
    assert failures.classify(gold, texts, [])[0] == "③ 판단 실패"
    # 정규화로 O→0, l→1 을 되돌리면 같은 글자다 → 판단 단계까지 간 것
    phone = {"text": "010-1234-5678", "expect": "cover"}
    assert failures.classify(phone, texts, [])[0] == "③ 판단 실패"
    misread = {"text": "010-1234-5678", "expect": "cover"}
    assert failures.classify(misread, ["010-1284-5673"], [])[0] == "② 잘못 읽음"
    # 맨 앞 글자가 O 이면 지금 정규화가 되돌리지 못한다(숫자로 시작할 때만 보정) → 잘못 읽음
    assert failures.classify(misread, ["O1O-1234-5678"], [])[0] == "② 잘못 읽음"
    assert failures.classify({"text": "권선로 208", "expect": "cover"}, texts, [])[0] == "① 못 찾음"
    # 가리면 안 될 것을 못 읽은 건 결과적으로 맞음
    assert failures.classify({"text": "1588-1255", "expect": "none"}, texts, [])[0] == "맞음"
