"""정규식 룰셋 단위 테스트 — 실제 OCR 오인식 사례를 포함 (pytest)"""
from reader.rules import find_pii, mask, normalize_digits, is_address
from schema.models import BBox, OCRLine


def L(text, x1=0, y1=0, x2=500, y2=40, conf=0.9):
    return OCRLine(text=text, conf=conf, bbox=BBox(x1=x1, y1=y1, x2=x2, y2=y2))


def types(lines):
    return sorted(h.type for h in find_pii(lines))


def test_phone_and_name_same_line():
    hits = find_pii([L("운아하   010-0107-2163")])          # 실제 OCR 결과 그대로
    assert {h.type for h in hits} == {"phone", "person_name"}
    assert next(h for h in hits if h.type == "person_name").value == "운아하"


def test_phone_variants():
    for t in ["010 1234 5678", "010.1234.5678", "01012345678", "010~1234-5678"]:
        assert "phone" in types([L(t)]), t


def test_ocr_digit_fix():
    assert normalize_digits("010-12l4-5678") == "010-1214-5678"
    assert "phone" in types([L("010-O123-4567")])


def test_tracking_with_misread_keyword():
    assert "tracking_number" in types([L("운승장번호 5787-1331-5098")])


def test_address_two_lines_merged():
    hits = find_pii([L("경기도 수원시 권선구 월드컵북로 37", y1=0, y2=40), L("29동 165호", y1=50, y2=90)])
    addr = [h for h in hits if h.type == "address"]
    assert len(addr) == 1 and addr[0].value.endswith("29동 165호")


def test_address_negative():
    assert not is_address("파이썬 프로그래밍 개정 3판")
    assert not is_address("품명: 도서")


def test_student_number_same_row():
    lines = [L("학번", x1=0, x2=80), L("20239280", x1=100, x2=300)]
    assert "student_number" in types(lines)
    assert "student_number" in types([L("학번 20239280")])


def test_rrn_and_card_luhn():
    assert "rrn" in types([L("주민번호 900101-1234567")])
    assert "card_number" in types([L("4111 1111 1111 1111")])
    assert "card_number" not in types([L("1234 5678 9012 3456")])   # Luhn 실패


def test_plate():
    assert "plate_number" in types([L("12가 3456")])
    assert "plate_number" not in types([L("12쀍 3456")])


def test_book_cover_no_pii():
    assert types([L("파이씬 프로그래망"), L("개정 3판")]) == []


def test_masks():
    assert mask("phone", "010-0107-2163") == "010-****-2163"
    assert mask("person_name", "윤아하") == "윤*하"
    assert mask("rrn", "900101-1234567") == "900101-*******"
    assert mask("address", "경기도 수원시 권선구 와우안길 17") == "경기도 수원시 권선구 ****"
    assert mask("url", "https://track.example.com/p/123") == "https://track.example.com/****"
