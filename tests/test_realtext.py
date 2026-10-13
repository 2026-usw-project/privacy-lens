"""실사 평가(eval.realtext). 실제 OCR 없이 세는 방식만 확인한다."""

import json

from PIL import Image

from eval import realtext
from pipeline.types import Box, TextSpan


class Fixed:
    """사진마다 정해 둔 글자를 돌려주는 OCR."""

    name = "fixed"

    def __init__(self, by_size):
        self.by_size = by_size

    def read(self, image):
        return list(self.by_size.get(image.size, []))


def test_counts_personal_alerts_and_sign_false_alarms(tmp_path):
    (tmp_path / "personal" / "images").mkdir(parents=True)
    (tmp_path / "signs" / "images").mkdir(parents=True)
    Image.new("RGB", (800, 600), "white").save(tmp_path / "personal" / "images" / "p.jpg")
    Image.new("RGB", (900, 600), "white").save(tmp_path / "signs" / "images" / "s.jpg")
    # 개인정보 영역 두 곳: 하나는 연락처(읽힘), 하나는 OCR 이 못 읽음
    (tmp_path / "personal" / "truth.json").write_text(
        json.dumps({"p.jpg": [[100, 100, 300, 40], [100, 400, 200, 40]]}), encoding="utf-8")
    ocr = Fixed({
        (800, 600): [TextSpan("연락처 010-2345-6789", Box(100, 100, 300, 40), 0.95)],
        (900, 600): [TextSpan("고객센터 1588-1234", Box(50, 50, 300, 40), 0.95)],
    })

    res = realtext.run(str(tmp_path), backend=ocr)

    full, naive = res["personal"]["+문맥·결합"], res["personal"]["정규식만"]
    assert full["regions"] == 2 and full["read"] == 1
    assert full["alert"] == 1 and full["cover"] == 1 and full["outside"] == 0
    # 간판의 고객센터 번호: 정규식만은 가림 권장으로 잘못 올리고, 문맥 판단은 참고로 내린다
    assert res["signs"]["정규식만"]["with_cover"] == 1
    assert res["signs"]["+문맥·결합"]["with_cover"] == 0
    assert naive["cover"] == 1
    assert "잘못 경고하는가" in realtext.report_text(res)
