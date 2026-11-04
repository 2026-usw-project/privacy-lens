"""나뉘어 읽힌 카드번호, 학교마다 다른 학번, 한자 병기 이름. 값은 전부 가상(카드는 9 로 시작하는 Luhn 번호)."""

from pipeline import context
from pipeline import kr_patterns as kp
from pipeline.types import Box, TextSpan

CARD = "9410123412341237"   # Luhn 통과하는 가상 번호
assert kp.valid_luhn(CARD)


def row(texts, y=100, start=40, conf=0.95):
    out, x = [], start
    for t in texts:
        w = 22 * len(t)
        out.append(TextSpan(t, Box(x, y, w, 30), conf))
        x += w + 40
    return out


def cards(spans):
    return [f for f in context.evaluate(spans) if f.kind == "card"]


def test_four_groups_on_one_line_become_one_card():
    spans = row([CARD[i:i + 4] for i in range(0, 16, 4)])
    found = cards(spans)
    assert len(found) == 1 and found[0].severity.value == "cover"
    assert found[0].detail["span_indices"] == [0, 1, 2, 3]
    assert found[0].box.x == spans[0].box.x and found[0].box.x + found[0].box.w == spans[3].box.x + spans[3].box.w


def test_two_and_two_groups_also_join():
    assert len(cards(row([CARD[:8], CARD[8:]]))) == 1


def test_not_luhn_or_other_lines_not_joined():
    bad = CARD[:15] + str((int(CARD[15]) + 1) % 10)
    assert cards(row([bad[i:i + 4] for i in range(0, 16, 4)])) == []
    # 두 줄로 나뉜 숫자는 잇지 않는다
    split = row([CARD[0:4], CARD[4:8]], y=100) + row([CARD[8:12], CARD[12:16]], y=300)
    assert cards(split) == []


def test_single_span_card_not_double_counted():
    assert len(cards(row([" ".join(CARD[i:i + 4] for i in range(0, 16, 4))]))) == 1


def test_student_id_without_year_prefix_needs_clue():
    with_clue = row(["학생증"], y=40) + row(["22018093"], y=100)
    ids = [f for f in context.evaluate(with_clue) if f.kind == "student_id"]
    assert len(ids) == 1 and ids[0].severity.value == "review"
    assert [f for f in context.evaluate(row(["22018093"])) if f.kind == "student_id"] == []
    phone_like = row(["학생증"], y=40) + row(["01012345678"], y=100)
    assert [f for f in context.evaluate(phone_like) if f.kind == "student_id"] == []


def test_hanja_note_removed_from_name():
    assert kp.strip_hanja("한서린 (韓瑞潾)") == "한서린"
    assert kp.strip_hanja("김민수（金民秀）") == "김민수"
    assert kp.strip_hanja("한서린()") == "한서린"
    assert kp.strip_hanja("고객센터 (평일 9시)") == "고객센터 (평일 9시)"
    spans = row(["주민등록증"], y=40) + row(["한서린 (韓瑞潾)"], y=100)
    names = [f for f in context.evaluate(spans) if f.kind == "name"]
    assert names and names[0].evidence_text == "한서린" and names[0].severity.value == "cover"
