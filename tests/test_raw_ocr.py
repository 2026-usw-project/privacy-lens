"""가상 OCR 결과로 필터 전 원문 보존과 재판독 좌표를 검증한다."""

from PIL import Image

from pipeline.analyze import analyze
from pipeline.detect import Detection, reread_documents
from pipeline.ocr import ScriptedBackend, TesseractBackend, read_with_raw
from pipeline.types import Box, TextSpan


def test_raw_keeps_non_personal_and_low_confidence_text():
    spans = [TextSpan("일반 안내문", Box(10, 20, 80, 20), 0.0),
             TextSpan("연락처 010-1234-5678", Box(10, 50, 180, 20), 0.99)]
    report = analyze(Image.new("RGB", (300, 200)), backend=ScriptedBackend(spans),
                     detector=None, check_codes=False, check_meta=False)
    data = report.as_dict()
    assert data["raw_ocr"] == [s.as_dict() for s in spans]
    assert any(f["kind"] == "mobile" for f in data["findings"])
    assert all(f["evidence_text"] != "일반 안내문" for f in data["findings"])


def test_rejected_reread_kept_in_original_coordinates():
    original = TextSpan("원본 안내", Box(100, 100, 60, 10), 0.9)
    raw = [original]
    crop_span = TextSpan("낮은 신뢰도", Box(30, 60, 90, 30,
                         poly=((30, 60), (120, 60), (120, 90), (30, 90))), 0.1)
    spans, count = reread_documents(Image.new("RGB", (600, 600)), [original],
        [Detection("waybill", Box(100, 100, 200, 100), 0.9)],
        ScriptedBackend([crop_span]), raw_ocr=raw)
    assert count == 1
    assert spans == [original]  # 기존 판정에는 더 잘 읽은 원본만 쓴다.
    assert raw[0] == original
    assert raw[1].text == crop_span.text
    assert raw[1].box == Box(94, 108, 30, 10,
                            poly=((94, 108), (124, 108), (124, 118), (94, 118)))


def test_tesseract_raw_precedes_line_merge(monkeypatch):
    import pytesseract
    calls = []
    def result(*args, **kwargs):
        calls.append(1)
        return {"text": ["안내", "문구", ""], "conf": [90, 0, -1],
                "left": [10, 40, 0], "top": [10, 10, 0],
                "width": [25, 25, 0], "height": [20, 20, 0]}
    monkeypatch.setattr(pytesseract, "image_to_data", result)
    backend = TesseractBackend()
    backend._checked = True
    merged, raw = read_with_raw(backend, Image.new("RGB", (100, 100)))
    assert len(calls) == 1
    assert [s.text for s in raw] == ["안내", "문구"]
    assert raw[1].ocr_confidence == 0
    assert [s.text for s in merged] == ["안내 문구"]
