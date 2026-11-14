"""Ultralytics 가 PIL.Image.open 을 바꿔 둔 뒤에도 사진이 아닌 파일은 400 이어야 한다(pipeline/ultra.py).

2026-11-07 원격 서버: YOLO 모델을 불러온 뒤 사진이 아닌 파일을 올리면
ModuleNotFoundError: No module named 'pi_heif' 로 500 이 났다.
"""

import sys

import pytest
from PIL import Image

pytest.importorskip("httpx")
patches = pytest.importorskip("ultralytics.utils.patches")
from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
from pipeline import ultra  # noqa: E402


@pytest.fixture
def patched_open(monkeypatch):
    """Ultralytics 를 불러온 직후 상태: Image.open 이 바뀌어 있고 pi_heif 는 없다."""
    monkeypatch.setattr(Image, "open", patches.image_open)
    monkeypatch.setattr(patches, "_pil_plugins_registered", False)
    monkeypatch.setitem(sys.modules, "pi_heif", None)          # import 하면 ImportError
    monkeypatch.setenv("YOLO_AUTOINSTALL", "false")
    return monkeypatch


def post_not_image(path="/analyze"):
    data = {"ticket": "pil-open-0001"} if path != "/redact/preview" else {"boxes": "[]"}
    return TestClient(server.app).post(path, data=data, files={"image": ("a.png", b"not an image", "image/png")})


def test_server_answers_400_even_while_patched(patched_open):
    r = post_not_image("/redact/preview")
    assert r.status_code == 400 and "이미지로 읽을 수 없는" in r.json()["detail"]


def test_loading_yolo_restores_pil_open(patched_open):
    assert ultra.restore_pil_open() is True
    assert Image.open is patches._image_open
    assert ultra.restore_pil_open() is False                    # 이미 원래대로면 그대로
    r = post_not_image("/redact/preview")
    assert r.status_code == 400


def test_yolo_class_keeps_autoinstall_off_and_open_original(monkeypatch):
    monkeypatch.delenv("YOLO_AUTOINSTALL", raising=False)
    import os
    ultra.yolo_class()
    assert os.environ["YOLO_AUTOINSTALL"] == "false"
    assert Image.open is not patches.image_open


def test_preload_torch_only_on_windows(monkeypatch):
    """Windows GPU 에서 Paddle 보다 PyTorch 를 먼저 불러온다(DLL 충돌). 다른 OS 는 건드리지 않는다."""
    import importlib.util as iu
    monkeypatch.setattr(iu, "find_spec", lambda name, *a: object() if name == "torch" else None)
    monkeypatch.setattr(ultra.os, "name", "posix")
    assert ultra.preload_torch() is False
    monkeypatch.setattr(ultra.os, "name", "nt")
    assert ultra.preload_torch() is True            # torch 가 설치돼 있으면 불러온다
    monkeypatch.setattr(iu, "find_spec", lambda name, *a: None)
    assert ultra.preload_torch() is False           # 없으면 그냥 넘어간다
