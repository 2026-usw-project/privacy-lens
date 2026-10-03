"""출력 문구. 단정 표현은 실서비스보다 여기서 먼저 터져야 한다."""

import pytest

from pipeline import wording


def test_every_template_passes_assert_safe():
    for msg in wording.all_templates():
        assert wording.assert_safe(msg) == msg


def test_assert_safe_raises():
    with pytest.raises(ValueError):
        wording.assert_safe("여기가 당신의 집입니다")


def test_josa():
    assert wording.josa("문자열") == "문자열이"
    assert wording.josa("번호") == "번호가"
    assert wording.josa("010") == "010이"
    assert wording.josa("주소", "으로/로") == "주소로"
    assert wording.josa("번호판", "으로/로") == "번호판으로"
    assert wording.josa("문자열", "으로/로") == "문자열로"  # ㄹ 받침


def test_no_particle_errors_in_templates():
    for msg in wording.all_templates():
        assert "열가 " not in msg and "열으로" not in msg
