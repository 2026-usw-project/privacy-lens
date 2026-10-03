"""형식 판단(kr_patterns). OCR 없이 돈다."""

from pipeline import kr_patterns as kp


def kinds(text: str) -> list[tuple[str, str]]:
    return [(h.kind, h.text) for h in kp.scan(text)]


# ------------------------------------------------------------ 체크섬

def test_rrn_checksum():
    assert kp.valid_rrn("900101-1234568")
    assert not kp.valid_rrn("900101-1234567")
    assert not kp.valid_rrn("901301-1234568")  # 13월


def test_rrn_after_2020_is_not_dropped():
    # 2020.10 이후 발급분은 체크섬이 맞지 않는다. 형식이 맞으면 남긴다.
    assert ("rrn_unverified", "200101-3234567") in kinds("200101-3234567")
    assert ("rrn", "900101-1234568") in kinds("900101-1234568")
    # 구분자 없는 13자리는 앞자리가 날짜처럼 보이는 운송장번호일 수 있다
    assert kinds("5301012345678") == [("long_digits", "5301012345678")]


def test_brn_and_luhn():
    assert kp.valid_brn("220-81-62517")
    assert not kp.valid_brn("220-81-62518")
    assert kp.valid_luhn("4111 1111 1111 1111")
    assert not kp.valid_luhn("4111 1111 1111 1112")


# ------------------------------------------------------------ 숫자 경계

def test_phone_not_found_inside_long_digits():
    assert kinds("운송장 5301012345678") == [("long_digits", "5301012345678")]
    assert all(k != "landline" for k, _ in kinds("주문번호 98702123456789"))


def test_phone_still_found_with_separators():
    assert ("mobile", "010-1234-5678") in kinds("연락처 010-1234-5678")
    assert ("mobile", "01012345678") in kinds("01012345678")
    assert ("service_line", "1588-0011") in kinds("고객센터 1588-0011")


# ------------------------------------------------------------ 주소

def test_road_rejects_particles_and_counters():
    assert not any(k == "address_road" for k, _ in kinds("오늘 택배로 3개 보냄"))
    assert not any(k == "address_road" for k, _ in kinds("다음으로 5번"))
    assert not any(k == "address_road" for k, _ in kinds("2시로 30분 미룸"))


def test_road_accepts_addresses():
    assert ("address_road", "권선로 208") in kinds("권선로 208")
    assert any(k == "address_road" for k, _ in kinds("테헤란로 12-3"))


def test_unit_is_not_a_plate():
    assert kinds("121동 1655호") == [("address_unit", "121동 1655호")]
    assert ("plate", "12가 3456") in kinds("12가 3456")


# ------------------------------------------------------------ 정규화

def test_normalize_joins_split_hangul():
    assert kp.normalize("권 선 로 208") == "권선로 208"
    # 낱글자 뒤의 짧은 조각까지 한 낱말로
    assert "권선로" in kp.normalize("권 선로 208")
    assert kp.normalize("오늘 택배로") == "오늘 택배로"


def test_normalize_fixes_digit_lookalikes_only_between_digits():
    assert kp.normalize("010-l234-5678") == "010-1234-5678"
    assert kp.normalize("Olive") == "Olive"


# ------------------------------------------------------------ 이름

def test_looks_like_name():
    assert kp.looks_like_name("홍길동")
    assert kp.looks_like_name("남궁민수")
    assert not kp.looks_like_name("주소")       # 성씨 글자로 시작하지만 낱말
    assert not kp.looks_like_name("택배")       # 흔한 성씨 아님
    assert not kp.looks_like_name("홍길동동동")  # 너무 김


# ------------------------------------------------------------ 한글에 붙은 숫자

def test_numbers_glued_to_hangul_labels():
    # 파이썬 \b 는 한글을 단어 글자로 친다. 라벨에 붙은 숫자를 놓치면 안 된다.
    assert kinds("운송장번호909266858784") == [("long_digits", "909266858784")]
    assert kinds("주민번호900101-1234568") == [("rrn", "900101-1234568")]
    assert kinds("카드4111-1111-1111-1111") == [("card", "4111-1111-1111-1111")]
    assert kinds("사업자220-81-62517") == [("brn", "220-81-62517")]


def test_dashed_long_digits():
    assert kinds("6123-4567-8901") == [("long_digits", "6123-4567-8901")]
    assert kinds("2026-10-03") == []  # 날짜는 자릿수가 모자란다
    assert kinds("010-1234-5678") == [("mobile", "010-1234-5678")]
