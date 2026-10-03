"""PaddleBackend 의 모델 고르기. 진짜 paddleocr 대신 가짜 모듈을 끼운다
(불러오는 데만 1분이 넘고 모델 가중치가 필요하다)."""

import sys
import types

import pytest

from pipeline.ocr import PADDLE_DEFAULT_DET, PaddleBackend


class Fake3x:
    """PaddleOCR 3.x 흉내. 받은 인자를 기록한다."""

    last_kwargs: dict = {}

    def __init__(self, lang=None, text_detection_model_name=None,
                 text_recognition_model_name=None, use_textline_orientation=None,
                 use_doc_orientation_classify=None, use_doc_unwarping=None, **kwargs):
        Fake3x.last_kwargs = {k: v for k, v in locals().items() if k not in ("self", "kwargs")}
        det, rec = text_detection_model_name, text_recognition_model_name
        if det is None:
            det, rec = self._get_ocr_model_names(lang, None)
        self._params = {"text_detection_model_name": det, "text_recognition_model_name": rec,
                        "use_textline_orientation": use_textline_orientation}

    def _get_ocr_model_names(self, lang, version):
        if lang == "korean":
            return "PP-OCRv5_server_det", "korean_PP-OCRv5_mobile_rec"
        return None, None

    def predict(self, img):
        return []


class Fake2x:
    """PaddleOCR 2.x 흉내. 모델을 이름으로 고르는 인자가 없다."""

    last_kwargs: dict = {}

    def __init__(self, lang=None, use_angle_cls=None, show_log=None):
        Fake2x.last_kwargs = {"lang": lang, "use_angle_cls": use_angle_cls}

    def ocr(self, img):
        return []


@pytest.fixture
def fake(monkeypatch):
    def install(cls):
        mod = types.ModuleType("paddleocr")
        mod.PaddleOCR = cls
        mod.__version__ = "9.9.9"
        monkeypatch.setitem(sys.modules, "paddleocr", mod)
        for var in ("PL_PADDLE_DET", "PL_PADDLE_REC", "PL_PADDLE_LANG"):
            monkeypatch.delenv(var, raising=False)
    return install


def test_default_is_v6_det_with_korean_rec(fake):
    fake(Fake3x)
    b = PaddleBackend()
    assert b.models["det"] == PADDLE_DEFAULT_DET == "PP-OCRv6_medium_det"
    # 검출만 정해도 인식이 한국어를 모르는 기본값으로 떨어지지 않는다
    assert b.models["rec"] == "korean_PP-OCRv5_mobile_rec"
    assert "lang" not in Fake3x.last_kwargs or Fake3x.last_kwargs["lang"] is None
    assert b.name == "paddleocr 9.9.9 · PP-OCRv6_medium_det + korean_PP-OCRv5_mobile_rec"


def test_auto_uses_library_choice(fake, monkeypatch):
    fake(Fake3x)
    monkeypatch.setenv("PL_PADDLE_DET", "auto")
    b = PaddleBackend()
    assert b.models == {"det": "PP-OCRv5_server_det", "rec": "korean_PP-OCRv5_mobile_rec"}
    assert Fake3x.last_kwargs["lang"] == "korean"


def test_rec_only_override(fake, monkeypatch):
    fake(Fake3x)
    monkeypatch.setenv("PL_PADDLE_REC", "my_rec")
    b = PaddleBackend()
    assert b.models == {"det": "PP-OCRv6_medium_det", "rec": "my_rec"}


def test_2x_ignores_default_but_rejects_explicit(fake, monkeypatch):
    fake(Fake2x)
    b = PaddleBackend()  # 기본 검출기는 2.x 에 걸지 않는다
    assert Fake2x.last_kwargs["lang"] == "korean"
    assert b.name == "paddleocr 9.9.9"
    monkeypatch.setenv("PL_PADDLE_DET", "PP-OCRv6_medium_det")
    with pytest.raises(RuntimeError):
        PaddleBackend()


def test_paddle_spans_keep_outline(fake, monkeypatch):
    class WithResult(Fake3x):
        def predict(self, img):
            return [{"rec_texts": ["010-1234-5678"], "rec_scores": [0.99],
                     "rec_polys": [[[10, 20], [110, 40], [106, 60], [6, 40]]]}]
    fake(WithResult)
    from PIL import Image
    [s] = PaddleBackend().read(Image.new("RGB", (200, 100)))
    assert (s.box.x, s.box.y, s.box.w, s.box.h) == (6, 20, 104, 40)
    assert s.box.poly == ((10.0, 20.0), (110.0, 40.0), (106.0, 60.0), (6.0, 40.0))
