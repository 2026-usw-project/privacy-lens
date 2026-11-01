"""2026-11 판단 보강: 계좌·비밀번호·학번, 메일 문맥, OCR 잡음. 가상 정보만 쓴다."""

from pipeline import context, wording
from pipeline import kr_patterns as kp
from pipeline.types import Box, Severity, TextSpan


def span(text, x, y, w=200, h=20, conf=0.95):
    return TextSpan(text, Box(x, y, w, h), conf)


def kinds(findings, kind):
    return [f for f in findings if f.kind == kind]


# ------------------------------------------------------------ 계좌

def test_account_with_bank_word_in_same_span_or_line_above():
    fs = context.evaluate([span("국민 381-594119-57-851", 0, 0, 300)])
    [a] = kinds(fs, "account")
    assert a.severity is Severity.COVER and a.evidence_text == "381-594119-57-851"

    fs = context.evaluate([span("월세 신한", 0, 0, 100), span("110-123-456789", 0, 30, 200)])
    assert kinds(fs, "account")


def test_long_digits_without_bank_word_stay_info():
    # 라벨 없는 긴 숫자는 계좌·회원번호·주문번호를 구분할 수 없다
    fs = context.evaluate([span("회원번호 381594119578", 0, 0, 300)])
    assert not kinds(fs, "account")
    assert all(f.severity is Severity.INFO for f in kinds(fs, "long_digits"))


def test_bank_name_only_as_a_word():
    # '우리 집'의 '우리'는 은행이 아니다. 하지만 낱말 '우리'는 은행으로 볼 수밖에 없다 → 붙은 말만 거른다
    fs = context.evaluate([span("우리집 택배 3815941195", 0, 0, 300)])
    assert not kinds(fs, "account")


def test_tracking_label_wins_over_account():
    fs = context.evaluate([span("운송장번호 381594119578", 0, 0, 300)])
    assert kinds(fs, "tracking") and not kinds(fs, "account")


# ------------------------------------------------------------ 비밀번호

def test_password_after_label_same_span_right_span_and_next_line():
    fs = context.evaluate([span("현관 비밀번호 9723*", 0, 0, 300)])
    [p] = kinds(fs, "password")
    assert p.evidence_text == "9723*" and p.severity is Severity.COVER

    fs = context.evaluate([span("PW:", 0, 0, 40), span("abc1234", 60, 0, 120)])
    assert [f.evidence_text for f in kinds(fs, "password")] == ["abc1234"]

    fs = context.evaluate([span("와이파이 비번", 0, 0, 160), span("nuri8402!", 0, 30, 140)])
    assert [f.evidence_text for f in kinds(fs, "password")] == ["nuri8402!"]


def test_password_words_without_value_are_ignored():
    fs = context.evaluate([span("비밀번호 변경", 0, 0, 200), span("비밀번호를 입력하세요", 0, 30, 300),
                           span("shopping 1234", 0, 60, 200), span("NURI_5G", 0, 90, 100)])
    assert not kinds(fs, "password")


def test_password_value_must_have_a_digit():
    # 영문 낱말만 있는 값은 아이디·모델명과 구분할 수 없다
    fs = context.evaluate([span("비번 sunflower", 0, 0, 200)])
    assert not kinds(fs, "password")


# ------------------------------------------------------------ 학번·사번

def test_student_id_cover_on_card_review_alone():
    fs = context.evaluate([span("한빛대학교", 0, 0, 160), span("학생증", 0, 30, 80),
                           span("학번 20231234", 0, 60, 200)])
    [s] = kinds(fs, "student_id")
    assert s.severity is Severity.COVER and s.evidence_text == "20231234"

    fs = context.evaluate([span("사번", 0, 0, 40), span("1029384", 60, 0, 120)])
    [s] = kinds(fs, "student_id")
    assert s.severity is Severity.REVIEW


def test_digits_without_id_label_are_not_student_id():
    fs = context.evaluate([span("20231234", 0, 0, 120)])
    assert not kinds(fs, "student_id")


# ------------------------------------------------------------ 메일·라벨

def test_public_word_of_other_value_does_not_lower_personal_mail():
    # '고객센터 help@…' 의 공개 단어가 윗줄의 개인 메일까지 끌어내리던 버그
    fs = context.evaluate([span("hana39@example.com", 0, 0, 220),
                           span("고객센터 help@example.org", 0, 30, 300)])
    personal = next(f for f in kinds(fs, "email") if f.evidence_text.startswith("hana"))
    public = next(f for f in kinds(fs, "email") if f.evidence_text.startswith("help"))
    assert personal.severity is not Severity.INFO
    assert public.severity is Severity.INFO


def test_public_word_without_own_value_still_lowers():
    # 공개 단어만 있는 조각(값 없음)은 예전처럼 근처 값을 공개로 본다
    fs = context.evaluate([span("배달 문의", 0, 0, 120), span("010-1234-5678", 0, 30, 200)])
    [m] = kinds(fs, "mobile")
    assert m.severity is Severity.INFO


def test_sender_label_marks_name_and_mail():
    fs = context.evaluate([span("보낸사람", 0, 0, 80), span("황지아", 100, 0, 80),
                           span("jiyoon32@example.com", 0, 30, 240)])
    assert kinds(fs, "name")[0].severity is Severity.COVER
    assert kinds(fs, "email")[0].severity is Severity.COVER


# ------------------------------------------------------------ OCR 잡음

def test_symbol_inside_label_and_leading_o():
    fs = context.evaluate([span("받-는분", 0, 0, 80), span("박민준", 100, 0, 80),
                           span("연락·처", 0, 30, 80), span("O1O-1234-5678", 100, 30, 200)])
    assert kinds(fs, "name")[0].severity is Severity.COVER
    [m] = kinds(fs, "mobile")
    assert m.severity is Severity.COVER and m.evidence_text == "010-1234-5678"


def test_leading_o_fix_leaves_words_alone():
    assert kp.normalize("Oil 12345") == "Oil 12345"
    assert kp.normalize("HELLO 12") == "HELLO 12"
    assert kp.normalize("O2-123-4567") == "02-123-4567"


def test_new_kinds_have_safe_wording():
    for kind in ("account", "password", "student_id"):
        assert kind in wording.KIND_NOUN
        wording.found(kind, near="계좌")


def test_every_backend_kind_has_a_screen_label():
    # 새 kind 를 추가하고 화면 매핑을 빠뜨리면 '개인정보 후보'로만 보인다
    import re
    from pathlib import Path
    core = (Path(__file__).resolve().parents[1] / "web/frontend-demo/dist/core.js").read_text(encoding="utf-8")
    block = core[core.index("const KINDS"):core.index("};", core.index("const KINDS"))]
    screen = set(re.findall(r"(\w+):\[", block))
    missing = set(wording.KIND_NOUN) - screen - {"gps"}  # gps 는 영역이 아니라 위치정보 안내로 따로 보인다
    assert not missing, f"core.js KINDS 에 없는 kind: {sorted(missing)}"
