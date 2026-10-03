"""
알려진 오탐 — 사람 이름이 아닌 글자를 이름으로 잡는 사례 (2026-10-03 확인)

규칙이 고쳐지면 xfail(strict) 가 XPASS 로 실패하므로 그때 이 표시를 지운다.
※ 상호·대표번호·사업장 주소·도시 단위 주소를 개인정보로 볼지는 정책 결정(docs/DECISIONS.md D-10)이라
   여기서는 단정하지 않고, 누가 봐도 틀린 '이름 판정'만 고정한다.
"""
import pytest

from reader.rules import find_pii
from schema.models import BBox, OCRLine


def _types(text: str):
    return {h.type for h in find_pii([OCRLine(text=text, conf=0.9, bbox=BBox(x1=0, y1=0, x2=500, y2=40))])}


@pytest.mark.xfail(strict=True, reason="전화번호 앞의 아무 한글 단어를 이름으로 판정 (reader/rules.py _name_tokens strict=False)")
@pytest.mark.parametrize("text", ["맛나식당 031-123-4567", "행복약국 010-1234-5678", "대표전화 02-1234-5678",
                                  "문의 031-123-4567 (평일 9시~18시)"])
def test_shop_or_label_word_is_not_a_person_name(text):
    assert "person_name" not in _types(text)


def test_control_real_name_with_phone_still_detected():
    """대조군: 받는분 + 이름 + 번호는 계속 잡혀야 함 (위 오탐을 고치다 이것을 놓치지 않도록)"""
    assert {"person_name", "phone"} <= _types("받는분 홍길동 010-1234-5678")
