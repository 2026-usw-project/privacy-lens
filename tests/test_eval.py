"""평가 스크립트의 채점 로직 테스트 — 평가가 틀리면 모든 수치가 틀리므로 손으로 만든 작은 예제로 확인"""
from data.eval import match, same


def test_numbers_compare_digits_only():
    assert same("phone", "010-0107-2163", "010 0107 2163")
    assert not same("phone", "010-0107-2163", "010-0107-2168")


def test_name_one_char_misread():
    assert not same("person_name", "윤아하", "운아하")                 # 정확 일치는 아님
    assert same("person_name", "윤아하", "운아하", lenient=True)       # 한 글자 오인식은 허용 모드에서 인정
    assert not same("person_name", "윤아하", "안하윤", lenient=True)   # 다른 사람 이름은 허용해도 불일치


def test_address_ignores_spaces_and_commas():
    assert same("address", "경기도 수원시 권선구 월드컵북로 37, 29동 165호", "경기도수원시 권선구 월드컵북로 37 29동 165호")


def test_match_is_one_to_one():
    gt = [("phone", "010-0000-0001"), ("phone", "010-0000-0002")]
    pred = [("phone", "010-0000-0001")]
    out = match(gt, pred)
    assert out["phone"] == [1, 1, 0]            # 하나만 찾았으니 TP 1, FN 1


def test_extra_prediction_is_false_positive():
    out = match([("phone", "010-0000-0001")], [("phone", "010-0000-0001"), ("person_name", "맛나식당")])
    assert out["phone"] == [1, 0, 0] and out["person_name"] == [0, 0, 1]


def test_modes_differ_on_wrong_value():
    gt, pred = [("person_name", "윤아하")], [("person_name", "운아하")]
    assert match(gt, pred, "strict")["person_name"] == [0, 1, 1]
    assert match(gt, pred, "lenient")["person_name"] == [1, 0, 0]
    assert match(gt, pred, "type")["person_name"] == [1, 0, 0]
