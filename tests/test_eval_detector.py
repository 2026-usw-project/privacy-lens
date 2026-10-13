"""문서 검출 전후 비교(eval.detector). 실제 모델·OCR 없이 세는 방식만 확인한다."""

from PIL import Image

from eval import detector as ev
from pipeline.detect import Detection
from pipeline.types import Box


class FakeDetector:
    name = "yolo:test"

    def __init__(self, dets):
        self.dets = dets

    def detect(self, image):
        return list(self.dets)


class BlankOcr:
    """아무 글자도 못 읽는 OCR. 사진 전체든 잘라낸 조각이든."""

    name = "blank"

    def read(self, image):
        return []


def test_unreadable_small_card_is_counted_only_with_detector():
    img = Image.new("RGB", (2000, 1500), "white")
    card = Box(300, 300, 200, 130)                       # 긴 변 200 / 짧은 변 1500 = 0.13 → 작음
    det = FakeDetector([Detection("id_card", card, 0.9),
                        Detection("waybill", Box(1500, 1200, 300, 200), 0.6)])  # 정답에 없는 검출

    r = ev.evaluate([("a", img, [("id_card", card)])], BlankOcr(), det)

    assert r["total"]["작음"] == 1
    assert r["검출 없음"]["found"]["작음"] == 0 and r["검출 있음"]["found"]["작음"] == 1
    assert r["검출 있음"]["read"]["작음"] == 0           # 영역 경고뿐, 내용은 못 읽음
    assert r["검출 없음"]["stray"] == 0 and r["검출 있음"]["stray"] == 1   # 엉뚱한 곳의 영역 경고
    assert r["검출 없음"]["missed"] == ["a:id_card(작음)"]
    assert "검출 있음" in ev.report_text(r)


def test_load_docs_keeps_only_document_classes(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("1 0.5 0.5 0.2 0.1\n4 0.5 0.5 0.05 0.05\n5 0.1 0.1 0.05 0.05\n", encoding="utf-8")
    docs = ev.load_docs(p, 1000, 800)
    assert [n for n, _ in docs] == ["id_card"]          # 증명사진·바코드는 문서가 아니다
    assert docs[0][1].w == 200 and docs[0][1].h == 80
