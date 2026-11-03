"""글자 줄 방향 판별(auto): 끄고 읽은 결과가 이상할 때만 켜고 다시 읽어 줄마다 확신도 높은 쪽을 쓴다."""

import sys
import types

import pytest
from PIL import Image

from pipeline import ocr
from pipeline.types import Box, TextSpan


def span(text, conf, x=0, y=0, w=100, h=20):
    return TextSpan(text, Box(x, y, w, h), conf)


def test_upright_reading_needs_no_retry():
    lines = [span("연락처", .99), span("010-1234-5678", .98, y=30), span("배송지", .97, y=60),
             span("114동 1702호", .95, y=90), span("흐린 글자", .6, y=120)]   # 5줄 중 1줄만 흐림
    assert not ocr.needs_flip(lines)


def test_garbled_reading_triggers_retry():
    # 누운·뒤집힌 글자를 판별기 없이 읽으면 엉뚱한 글자가 낮은 확신도로 나온다
    assert ocr.needs_flip([span("ㅓㅏ윻", .4), span("9894-9029-010", .55, y=30), span("받는분", .97, y=60)])


def test_empty_or_single_letters_do_not_trigger():
    assert not ocr.needs_flip([])
    assert not ocr.needs_flip([span("a", .1), span("-", .2)])


def test_merge_keeps_more_confident_reading_per_line():
    upright = [span("010-6706-4686", .99), span("ㅁㄴㅇ", .3, y=40)]
    flipped = [span("9894-9029-010", .88), span("받는분", .97, y=40), span("새 줄", .9, y=200)]
    merged = ocr.merge_by_confidence(upright, flipped)
    assert [s.text for s in merged] == ["010-6706-4686", "받는분", "새 줄"]


def test_merge_ignores_far_boxes():
    merged = ocr.merge_by_confidence([span("가", .9)], [span("나", .99, x=500)])
    assert [s.text for s in merged] == ["가", "나"]


class FakePaddle:
    """predict(use_textline_orientation=…) 에 따라 다른 결과를 돌려준다."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls = []
        self.paddlex_pipeline = None

    def predict(self, image, use_textline_orientation=None):
        self.calls.append(use_textline_orientation)
        on = self.kwargs["use_textline_orientation"] if use_textline_orientation is None else use_textline_orientation
        texts, scores = (["받는분", "홍길동"], [0.99, 0.98]) if on else (["ㅁㄴ", "ㅇㄹ"], [0.3, 0.4])
        if self.kwargs.get("upright"):
            texts, scores = ["받는분", "홍길동"], [0.99, 0.98]
        polys = [[(0, 0), (100, 0), (100, 20), (0, 20)], [(0, 30), (100, 30), (100, 50), (0, 50)]]
        return [{"rec_texts": texts, "rec_scores": scores, "rec_polys": polys}]


@pytest.fixture
def fake(monkeypatch):
    made = []

    class PaddleOCR(FakePaddle):
        def __init__(self, lang=None, text_detection_model_name=None, text_recognition_model_name=None,
                     use_textline_orientation=None, use_doc_orientation_classify=None, use_doc_unwarping=None,
                     **kwargs):
            super().__init__(use_textline_orientation=use_textline_orientation, **kwargs)
            made.append(self)

    module = types.ModuleType("paddleocr")
    module.PaddleOCR = PaddleOCR
    module.__version__ = "3.test"
    monkeypatch.setitem(sys.modules, "paddleocr", module)
    monkeypatch.setattr(ocr, "_paddle_defaults", lambda cls, lang: ("det", "rec"))
    return made


IMG = Image.new("RGB", (120, 60), "white")


def test_auto_rereads_with_classifier_when_garbled(fake, monkeypatch):
    monkeypatch.delenv("PL_PADDLE_TEXTLINE", raising=False)
    backend = ocr.PaddleBackend()
    spans = backend.read(IMG)
    assert [s.text for s in spans] == ["받는분", "홍길동"]
    assert fake[0].calls == [False, True]
    assert fake[0].kwargs["use_textline_orientation"] is True   # 다시 읽을 수 있게 판별기 모델은 불러 둔다


def test_on_and_off_modes_read_once(fake, monkeypatch):
    for mode, expected in (("on", ["받는분", "홍길동"]), ("off", ["ㅁㄴ", "ㅇㄹ"])):
        monkeypatch.setenv("PL_PADDLE_TEXTLINE", mode)
        backend = ocr.PaddleBackend()
        assert [s.text for s in backend.read(IMG)] == expected
        assert fake[-1].calls == [None]
    assert fake[-1].kwargs["use_textline_orientation"] is False      # off 면 판별기 모델도 안 불러온다
