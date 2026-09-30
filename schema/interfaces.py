"""
모듈 간 함수 시그니처 계약.
각 담당자는 아래 이름·입출력 그대로 구현하면 D의 서버가 조립만 하면 됩니다.

image: numpy.ndarray (H, W, 3), RGB, uint8, EXIF 방향 보정이 끝난 원본 해상도
"""
from __future__ import annotations

from typing import List, Protocol

import numpy as np

from .models import Detection, ExifInfo, Finding


class Detector(Protocol):
    """[A] 비전 검출 — YOLO + SAHI + QR 디코딩"""
    def detect(self, image: np.ndarray) -> List[Detection]: ...


class Reader(Protocol):
    """[B] 판독 · 판정 — 크롭 OCR + 정규식/NER + 위험도"""
    def read_and_judge(self, image: np.ndarray, detections: List[Detection]) -> List[Finding]: ...


class ExifParser(Protocol):
    """[D] EXIF — raw bytes 에서 파싱 (방향 보정 전 원본 파일 기준)"""
    def parse(self, raw: bytes) -> ExifInfo: ...
