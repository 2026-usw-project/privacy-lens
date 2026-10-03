"""
전체 파이프라인: 업로드 바이트 → AnalyzeResponse
  EXIF → 방향 보정 → OCR(2단계) → QR → 판정 · 위험도 → 요약
"""
from __future__ import annotations

import io
import time
import uuid

import numpy as np
from PIL import Image, ImageOps

from reader.judge import build_findings
from schema.models import AnalyzeResponse, ImageInfo, ModelVersions, Summary, Timing
from vision import ocr, qr

from . import exif as exif_mod

FORMATS = {"JPEG": "jpeg", "PNG": "png", "WEBP": "webp", "HEIF": "heic", "MPO": "jpeg"}
RANK = {"none": 0, "low": 1, "medium": 2, "high": 3}


class BadImage(Exception):
    pass


def _headline(findings, exif_info) -> str:
    risky = [f for f in findings if f.risk.level in ("medium", "high")]
    gps = exif_info.gps is not None
    if not risky and not gps:
        return "공유해도 괜찮아 보입니다. 눈에 띄는 개인정보를 찾지 못했습니다."
    parts = []
    if risky:
        parts.append(f"확인이 필요한 정보 {len(risky)}건")
    if gps:
        parts.append("촬영 위치 정보")
    from reader.judge import _josa
    joined = parts[0] if len(parts) == 1 else parts[0] + _josa(parts[0], "과", "와") + " " + parts[1]
    return "공유 전 " + joined + _josa(joined) + " 발견되었습니다."


def analyze(raw: bytes, debug: bool = False) -> AnalyzeResponse:
    t0 = time.perf_counter()
    exif_info = exif_mod.parse(raw)
    t1 = time.perf_counter()
    try:
        pil = Image.open(io.BytesIO(raw))
        fmt = FORMATS.get(pil.format or "", "jpeg")
        pil = ImageOps.exif_transpose(pil).convert("RGB")
    except Exception as e:
        raise BadImage(str(e)) from e
    img = np.asarray(pil)
    H, W = img.shape[:2]

    t2 = time.perf_counter()
    lines = ocr.read_lines(img)
    qr_dets = qr.decode(img)
    t3 = time.perf_counter()
    findings = build_findings(W, H, lines, qr_dets, debug=debug, ocr_engine=ocr.engine_name())
    t4 = time.perf_counter()
    del img, pil, raw                                   # 원본 미저장 정책

    top = max([f.risk.level for f in findings] + [exif_info.risk.level], key=RANK.get)
    ms = lambda a, b: int((b - a) * 1000)
    return AnalyzeResponse(
        request_id=uuid.uuid4(),
        image=ImageInfo(width=W, height=H, format=fmt),
        exif=exif_info,
        findings=findings,
        summary=Summary(level=top, finding_count=len(findings), headline=_headline(findings, exif_info)),
        timing=Timing(total_ms=ms(t0, t4), exif_ms=ms(t0, t1), detect_ms=0, ocr_ms=ms(t2, t3), judge_ms=ms(t3, t4)),
        models=ModelVersions(detector="demo: ocr-line-grouping (YOLO 미적용) + wechat-qr", ocr=ocr.engine_name()),
    )
