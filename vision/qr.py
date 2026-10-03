"""
[A] QR 코드 디코딩 → Detection(label=qr_barcode)
OpenCV WeChatQRCode (opencv-contrib) 우선, 없으면 기본 QRCodeDetector.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import List

import cv2
import numpy as np

from schema.models import BBox, CodeDecode, Detection

# WeChatQRCode 는 4000px 원본에서 특정 사진에 수십 초~무한 대기하는 문제가 있어 축소본에서 검출합니다.
# 측정(합성 사진 15장): 1600px 4/4 검출 · 최대 0.9초 / 2560px 4/4 · 5.3초 / 원본 → 일부 사진 멈춤
QR_SIDE = int(os.environ.get("PL_QR_SIDE", "1600"))


@lru_cache(maxsize=1)
def _detector():
    if hasattr(cv2, "wechat_qrcode_WeChatQRCode"):
        return "wechat", cv2.wechat_qrcode_WeChatQRCode()
    return "basic", cv2.QRCodeDetector()


def decode(image: np.ndarray, start_id: int = 0) -> List[Detection]:
    H, W = image.shape[:2]
    kind, det = _detector()
    f = min(1.0, QR_SIDE / max(H, W))
    small = cv2.resize(image, None, fx=f, fy=f, interpolation=cv2.INTER_AREA) if f < 1 else image
    bgr = cv2.cvtColor(small, cv2.COLOR_RGB2BGR)
    if kind == "wechat":
        texts, points = det.detectAndDecode(bgr)
    else:
        ok, texts, points, _ = det.detectAndDecodeMulti(bgr)
        texts, points = (texts, points) if ok else ([], [])
    out: List[Detection] = []
    for text, pts in zip(texts, points):
        pts = np.asarray(pts, dtype=np.float32).reshape(-1, 2) / f    # 원본 좌표로 환산
        x1, y1 = int(max(0, pts[:, 0].min())), int(max(0, pts[:, 1].min()))
        x2, y2 = int(min(W, pts[:, 0].max())), int(min(H, pts[:, 1].max()))
        if x2 <= x1 or y2 <= y1:
            continue
        out.append(Detection(
            id=start_id + len(out), label="qr_barcode",
            bbox=BBox(x1=x1, y1=y1, x2=x2, y2=y2), det_conf=1.0,
            code=CodeDecode(decoded=bool(text), format="QR_CODE", payload=text or None),
        ))
    return out
