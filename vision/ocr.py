"""
[A] OCR — 2단계 방식 (PPT의 '크롭 OCR' 아이디어)

  1단계 글자 위치 검출 : 축소본(PL_DET_SIDE, 기본 1280px)에서 수행 → 빠름
  2단계 글자 인식      : 검출 박스를 원본 해상도에서 잘라 인식 → 작은 글자도 정확

측정 (2코어 CPU, 4032×3024 사진): 전체 1회 OCR 2560px = 23초 → 2단계 = 약 6초
※ 시간 대부분이 1단계(CRAFT 검출)이므로 GPU가 있으면 PL_GPU=1 로 크게 줄어듭니다.

엔진 선택: PL_OCR_ENGINE = easyocr (기본) | paddle
출력: schema.models.OCRLine 리스트 (원본 이미지 좌표)
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import List

import cv2
import numpy as np

from schema.models import BBox, OCRLine, Point

from . import geometry

ENGINE = os.environ.get("PL_OCR_ENGINE", "easyocr")
DET_SIDE = int(os.environ.get("PL_DET_SIDE", "1280"))
USE_GPU = os.environ.get("PL_GPU", "0") == "1"


@lru_cache(maxsize=1)
def _easyocr():
    import easyocr
    return easyocr.Reader(["ko", "en"], gpu=USE_GPU, verbose=False)


@lru_cache(maxsize=1)
def _paddle():
    from paddleocr import PaddleOCR   # paddleocr 3.x (이 환경에서는 모델 서버 차단으로 미검증)
    return PaddleOCR(lang="korean", use_doc_orientation_classify=False,
                     use_doc_unwarping=False, use_textline_orientation=False)


def engine_name() -> str:
    return {"easyocr": "easyocr-ko (det1280+full-res rec)", "paddle": "paddleocr-korean"}[ENGINE]


def warmup() -> None:
    read_lines(np.full((200, 600, 3), 255, np.uint8))


def _line(poly, text: str, conf: float, W: int, H: int, quad=None) -> OCRLine | None:
    xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
    x1, y1 = int(max(0, min(xs))), int(max(0, min(ys)))
    x2, y2 = int(min(W, max(xs))), int(min(H, max(ys)))
    text = text.strip()
    if not text or x2 <= x1 or y2 <= y1:
        return None
    polygon = [Point(x=round(x, 1), y=round(y, 1)) for x, y in quad] if quad else None
    return OCRLine(text=text, conf=float(min(max(conf, 0.0), 1.0)), bbox=BBox(x1=x1, y1=y1, x2=x2, y2=y2),
                   polygon=polygon)


def _easyocr_two_stage(image: np.ndarray) -> List[OCRLine]:
    """
    1) 축소본에서 CRAFT 단어 박스(기울어진 사각형) 검출
    2) 단어 박스를 줄로 묶음 (easyocr 기본 동작) — 이때 각 줄이 어떤 단어 박스로 만들어졌는지 기억
    3) 원본 해상도에서 줄 단위 인식
    4) 줄마다 소속 단어 박스들을 가장 작게 감싸는 '회전 사각형' 을 polygon 으로 저장 → 대각선 가림에 사용
    """
    from easyocr.utils import group_text_box

    r = _easyocr()
    H, W = image.shape[:2]
    s = min(1.0, DET_SIDE / max(H, W))
    small = cv2.resize(image, (int(W * s), int(H * s)), interpolation=cv2.INTER_AREA) if s < 1 else image
    words = r.get_textbox(r.detector, small, canvas_size=max(small.shape[:2]), mag_ratio=1.0,
                          text_threshold=0.7, link_threshold=0.4, low_text=0.4, poly=False, device=r.device,
                          optimal_num_chars=None, threshold=0.2, bbox_min_score=0.2, bbox_min_size=3,
                          max_candidates=0)[0]
    word_quads = [np.asarray(w, dtype=np.float32).reshape(4, 2) for w in words]
    horiz, free = group_text_box(words, 0.1, 0.5, 0.5, 0.7, 0.1, True)
    horiz = [b for b in horiz if max(b[1] - b[0], b[3] - b[2]) > 20]
    free = [f for f in free if max(max(c[0] for c in f) - min(c[0] for c in f), max(c[1] for c in f) - min(c[1] for c in f)) > 20]

    pad = 0.15   # 검출 박스를 살짝 넓혀 글자 끝이 잘리지 않게
    hb, quads = [], {}
    for x1, x2, y1, y2 in horiz:
        ph = (y2 - y1) * pad
        box = [int(max(0, (x1 - ph) / s)), int(min(W, (x2 + ph) / s)),
               int(max(0, (y1 - ph) / s)), int(min(H, (y2 + ph) / s))]
        hb.append(box)
        # 이 줄을 만든 단어 박스 = 줄 박스 안에 완전히 들어가는 단어 박스 (이웃 줄 모서리 조각 제외)
        members = [q for q in word_quads if geometry.contains([x1, x2, y1, y2], q.tolist(), tol=2.0)]
        if members:
            quads[(box[0], box[2])] = [[x / s, y / s] for x, y in geometry.min_area_quad(np.vstack(members))]
    fb = [[[p[0] / s, p[1] / s] for p in poly] for poly in free]
    for poly in fb:
        quads[(int(min(p[0] for p in poly)), int(min(p[1] for p in poly)))] = geometry.order_quad(poly)
    if not hb and not fb:
        return []
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    res = r.recognize(gray, horizontal_list=hb, free_list=fb, batch_size=8)
    out = []
    for poly, t, c in res:
        key = (int(min(p[0] for p in poly)), int(min(p[1] for p in poly)))
        if (ln := _line(poly, t, c, W, H, quads.get(key))):
            out.append(ln)
    return out


def _paddle_full(image: np.ndarray) -> List[OCRLine]:
    H, W = image.shape[:2]
    res = _paddle().predict(image)[0]
    return [ln for poly, t, c in zip(res["rec_polys"], res["rec_texts"], res["rec_scores"])
            if (ln := _line(poly.tolist(), t, c, W, H))]


def read_lines(image: np.ndarray) -> List[OCRLine]:
    """image: RGB uint8, EXIF 방향 보정이 끝난 원본 해상도"""
    lines = _easyocr_two_stage(image) if ENGINE == "easyocr" else _paddle_full(image)
    # 짧은 줄의 기울기를 주변 긴 줄 기준으로 보정
    idx = [i for i, l in enumerate(lines) if l.polygon]
    if idx:
        fixed = geometry.smooth_angles([[[p.x, p.y] for p in lines[i].polygon] for i in idx])
        for i, q in zip(idx, fixed):
            lines[i] = lines[i].model_copy(update={"polygon": [Point(x=round(x, 1), y=round(y, 1)) for x, y in q]})
    return sorted(lines, key=lambda l: (l.bbox.y1, l.bbox.x1))
