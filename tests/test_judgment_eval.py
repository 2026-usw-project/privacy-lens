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
    # 맨 앞 글자가 O 로 읽힌 번호도 정규화가 되돌린다(2026-11) → 글자는 맞게 읽은 것
    assert failures.classify(misread, ["O1O-1234-5678"], [])[0] == "③ 판단 실패"
    assert failures.classify({"text": "권선로 208", "expect": "cover"}, texts, [])[0] == "① 못 찾음"
    # 가리면 안 될 것을 못 읽은 건 결과적으로 맞음
    assert failures.classify({"text": "1588-1255", "expect": "none"}, texts, [])[0] == "맞음"


def test_baseline_check_catches_regression(tmp_path):
    import json
    rows = judgment.run(judgment.build(per_template=1))
    path = tmp_path / "base.json"
    path.write_text(json.dumps(judgment.snapshot(rows)), encoding="utf-8")
    assert judgment.check(rows, path) == []

    worse = [dict(r) for r in rows]
    hit = next(r for r in worse if r["expect"] == "cover" and r["verdict"] == "맞음")
    hit.update(got="none", verdict="놓침")
    fp = next(r for r in worse if r["expect"] == "none")
    fp.update(got="cover", verdict="오탐(가림)")
    problems = judgment.check(worse, path)
    assert any(hit["item"] in p for p in problems) and any("잘못 가림" in p for p in problems)

    # 정답 세트가 바뀌면 일부러 갱신하라고 막는다
    assert "정답 세트" in judgment.check(rows[:-1], path)[0]


def test_committed_baseline_matches_current_rules():
    # 판단 규칙을 고쳐 좋아졌는데 기준선을 안 올리면 다음 사람이 나빠져도 모른다
    rows = judgment.run(judgment.build())
    assert judgment.check(rows) == []
    assert judgment.improvements(rows) == [], "좋아졌으면 python -m eval.judgment --update"


def test_failure_history_row(tmp_path):
    rows = [
        {"photo": "a.jpg", "item": "이름", "expect": "cover", "got": "cover", "cause": "맞음"},
        {"photo": "a.jpg", "item": "휴대폰", "expect": "cover", "got": "review", "cause": "③ 판단 실패"},
        {"photo": "b.jpg", "item": "대표번호", "expect": "none", "got": "cover", "cause": "③ 판단 실패"},
    ]
    row = failures.summary_row(rows, ("paddleocr", "없음"), "메모")
    assert (row["사진"], row["맞음"], row["판단실패"], row["가림"], row["확인필요로만"], row["잘못가림"]) == (2, 1, 2, 1, 1, 1)
    p = failures.append_history(tmp_path, row)
    failures.append_history(tmp_path, row)
    lines = p.read_text(encoding="utf-8-sig").splitlines()
    assert len(lines) == 3 and lines[0].startswith("시각,")


def test_gold_loading_rules(tmp_path):
    import json
    def write(name, data):
        p = tmp_path / name
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return p
    # init 이 만든 빈 틀과 덜 된 정답은 채점하지 않는다
    assert failures.load_gold(write("a.json", {"items": [{"text": "", "expect": "cover", "item": ""}]})) is None
    assert failures.load_gold(write("b.json", {"items": [{"text": "홍길동", "expect": "cover"}], "checked": False})) is None
    # 직접 쓴 정답(checked 없음)과 '가릴 것 없는 사진'은 채점한다
    assert len(failures.load_gold(write("c.json", {"items": [{"text": "홍길동", "expect": "cover"}]}))) == 1
    assert failures.load_gold(write("d.json", {"items": [], "checked": True})) == []


def test_extra_covers_counts_cover_findings_outside_gold():
    texts = ["받는분 홍길동", "010-1234-5678", "130동 1343호"]
    found = [_finding(0, Severity.COVER, "홍길동"), _finding(1, Severity.COVER, "010-1234-5678"),
             _finding(2, Severity.COVER, "130동 1343호"), _finding(2, Severity.REVIEW, "x")]
    gold = [{"text": "홍길동", "expect": "cover"}, {"text": "010-1234-5678", "expect": "cover"}]
    assert failures.extra_covers(gold, texts, found) == 1
    assert failures.extra_covers([], texts, found) == 3


def test_init_copies_tool_and_keeps_existing_gold(tmp_path):
    from PIL import Image
    Image.new("RGB", (8, 8)).save(tmp_path / "a.jpg")
    Image.new("RGB", (8, 8)).save(tmp_path / "b.jpg")
    (tmp_path / "b.json").write_text('{"items": [{"text": "홍길동", "expect": "cover"}]}', encoding="utf-8")
    failures.init(tmp_path)
    assert (tmp_path / failures.TOOL_NAME).exists()
    assert (tmp_path / "a.json").exists()
    assert "홍길동" in (tmp_path / "b.json").read_text(encoding="utf-8")


def test_props_are_fake_valid_and_match_criteria(tmp_path):
    import json
    from samples import props
    pdf, manifest = props.write(tmp_path, sets=1, seed=3)
    assert pdf.exists() and pdf.stat().st_size > 10_000
    data = json.loads(manifest.read_text(encoding="utf-8"))["props"]
    assert len(data) == len(props.MAKERS)
    kinds = {v["kind"] for v in data.values()}
    assert {"송장", "학생증", "메모·포스트잇", "간판·전단"} <= kinds
    for pid, prop in data.items():
        assert prop["items"], pid
        for it in prop["items"]:
            assert it["expect"] in ("cover", "review", "none") and it["text"].strip()
            assert "@" not in it["text"] or it["text"].endswith("@example.com")
    # 같은 seed 면 같은 소품
    again = json.loads(props.write(tmp_path / "again", sets=1, seed=3)[1].read_text(encoding="utf-8"))["props"]
    assert again == data


def test_strip_removes_exif_and_applies_rotation(tmp_path):
    from PIL import Image
    im = Image.new("RGB", (40, 20), (200, 10, 10))
    exif = Image.Exif()
    exif[0x0112] = 6            # 시계 방향 90° 회전해서 봐야 하는 사진
    exif[0x010F] = "TestPhone"  # 기기 제조사
    im.save(tmp_path / "a.jpg", exif=exif)
    Image.new("RGB", (8, 8)).save(tmp_path / "plain.png")
    assert failures.strip(tmp_path) == 1
    with Image.open(tmp_path / "a.jpg") as out:
        assert not out.getexif() and out.size == (20, 40)
