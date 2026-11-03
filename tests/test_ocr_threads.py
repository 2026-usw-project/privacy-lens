"""PL_PADDLE_THREADS: 엔진 하나가 쓰는 CPU 스레드 수. 가짜 paddleocr 모듈로 넘기는 인자만 본다."""

import sys
import types

import pytest

from pipeline import ocr


@pytest.fixture
def fake_paddle(monkeypatch):
    seen = {}

    class PaddleOCR:  # 3.x 처럼 모델 이름을 받고 나머지는 **kwargs
        def __init__(self, lang=None, text_detection_model_name=None, text_recognition_model_name=None,
                     use_textline_orientation=None, use_doc_orientation_classify=None, use_doc_unwarping=None,
                     **kwargs):
            seen.clear()
            seen.update(kwargs, lang=lang, det=text_detection_model_name)
            self.paddlex_pipeline = None

        def predict(self, image):
            return []

    module = types.ModuleType("paddleocr")
    module.PaddleOCR = PaddleOCR
    module.__version__ = "3.test"
    monkeypatch.setitem(sys.modules, "paddleocr", module)
    monkeypatch.setattr(ocr, "_paddle_defaults", lambda cls, lang: ("det-default", "rec-default"))
    return seen


def test_threads_passed_when_set(fake_paddle, monkeypatch):
    monkeypatch.setenv("PL_PADDLE_THREADS", "4")
    ocr.PaddleBackend()
    assert fake_paddle["cpu_threads"] == 4


def test_default_threads_untouched(fake_paddle, monkeypatch):
    monkeypatch.delenv("PL_PADDLE_THREADS", raising=False)
    ocr.PaddleBackend()
    assert "cpu_threads" not in fake_paddle


def test_threads_at_least_one(fake_paddle, monkeypatch):
    monkeypatch.setenv("PL_PADDLE_THREADS", "0")
    ocr.PaddleBackend()
    assert fake_paddle["cpu_threads"] == 1
