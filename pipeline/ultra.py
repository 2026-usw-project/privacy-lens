"""Ultralytics(YOLO)를 서버에서 안전하게 불러온다.

Ultralytics 는 import 되는 순간 PIL.Image.open 을 자기 함수로 바꿔 둔다(ultralytics/utils/patches.py).
그 함수는 사진으로 읽을 수 없는 파일을 만나면 pi-heif 패키지를 확인·설치하려 들고, 없으면
ModuleNotFoundError: No module named 'pi_heif' 를 낸다. 서버는 이를 '읽을 수 없는 파일(400)'로 알아보지
못해 500 이 났다(2026-11-07, 원격 서버에서 사진이 아닌 파일을 올렸을 때). 또 자동 설치가 켜져 있으면
요청 처리 중에 패키지를 설치한다.

HEIC 는 서버가 pillow-heif 로 이미 열기 때문에(server.py) 이 바꿔치기가 필요 없다. 그래서 YOLO 를 불러온 뒤
Image.open 을 원래대로 돌려놓는다.
"""

from __future__ import annotations

import importlib.util
import os

from PIL import Image


def preload_torch() -> bool:
    """Windows 에서 Paddle(GPU)보다 PyTorch 를 먼저 불러온다. 불러왔으면 True.

    Windows 의 PyTorch 는 CUDA·cuDNN·OpenMP DLL 을 torch/lib 에 따로 들고 있고, paddlepaddle-gpu 는 pip 의
    nvidia-* 패키지 DLL 을 쓴다. 이름이 같은 DLL 은 먼저 불러온 쪽이 쓰이기 때문에, Paddle 을 먼저 불러온 뒤
    PyTorch(YOLO)를 불러오면 OSError [WinError 127] 로 멈췄다(2026-11-14, RTX 3070 Laptop, torch 2.6.0+cu126,
    paddlepaddle-gpu 3.2.2 cu126). PyTorch 를 먼저 불러오면 함께 동작했다(cuDNN 9.5 로 버전도 맞춰야 한다, README).
    Linux 는 둘 다 pip 의 nvidia-* 패키지를 써서 이 문제가 없으므로 아무것도 하지 않는다.
    """
    if os.name != "nt" or importlib.util.find_spec("torch") is None:
        return False
    try:
        import torch  # noqa: F401
    except Exception:  # PyTorch 가 깨져 있어도 OCR 은 돌아야 한다
        return False
    return True


def restore_pil_open() -> bool:
    """Ultralytics 가 바꾼 Image.open 을 원래 함수로 돌려놓는다. 돌려놓았으면 True."""
    try:
        from ultralytics.utils import patches
    except ImportError:
        return False
    original = getattr(patches, "_image_open", None)
    patched = getattr(patches, "image_open", None)
    if original is not None and patched is not None and Image.open is patched:
        Image.open = original
        return True
    return False


def yolo_class():
    """from ultralytics import YOLO 대신 쓴다. 자동 설치를 끄고, Image.open 을 원래대로 둔다."""
    # 서버가 요청을 처리하다 패키지를 내려받아 설치하지 않게 한다(Ultralytics 자동 설치는 기본 켜짐).
    # 실제로 첫 분석 중에 onnx·onnxruntime(GPU 면 onnxruntime-gpu 160MB)을 설치했다. 필요한 것은 vision/requirements.txt
    os.environ.setdefault("YOLO_AUTOINSTALL", "false")
    from ultralytics import YOLO  # 무거우니 쓸 때만

    restore_pil_open()
    return YOLO
