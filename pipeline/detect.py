"""문서 검출(YOLO) 단계. 선택 사항이다.

OCR 만으로는 두 가지를 놓친다.

1. **글자가 작아서 OCR 이 아예 못 찾는 경우.** 사진 배경의 학생증처럼 글자가
   몇 픽셀밖에 안 되면 검출 단계에서 빠진다. 사람은 확대해 보면 읽는데도.
2. **못 읽었다는 사실조차 모르는 경우.** OCR 결과가 비면 경고할 근거가 없다.

YOLO 는 글자를 읽지 않고 '학생증 모양'을 찾는다. 그래서

  - 찾은 문서 영역을 잘라 **확대해서 OCR 을 다시** 돌리고(1 해결),
  - 그래도 못 읽으면 '문서로 보이는 영역이 있으나 내용을 확인하지 못했다'는
    **영역 경고**를 낸다(2 해결). 내용은 지어내지 않는다.

가중치가 없으면(PL_YOLO_WEIGHTS 미설정) 이 단계는 통째로 건너뛰고 예전과 똑같이
동작한다. 학습은 vision/ 도구로 한다.

  PL_YOLO_WEIGHTS  best.pt 경로. 없으면 끔
  PL_YOLO_CONF     검출 기준 (기본 0.35)
  PL_YOLO_IMGSZ    입력 크기 (기본: 가중치 옆 metrics.json 의 imgsz, 없으면 1280)
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from . import wording
from .types import Box, Certainty, Finding, Severity, TextSpan

# 학습 클래스 이름 → wording 의 문서 이름
DOC_CLASSES = {
    "waybill": "waybill",
    "id_card": "id_card",
    "name_tag": "badge",
    "screen": "screen",
}
# 내용을 못 읽었을 때 바로 '가림 권장'으로 올릴 문서. 신원과 직결된다
COVER_WHEN_UNREAD = {"id_card", "name_tag"}
# 원래 개인정보가 적혀 있는 문서. 읽었는데 개인정보를 못 찾았으면 '검토 권장'
ALWAYS_PERSONAL = {"waybill", "id_card", "name_tag"}

CONFIDENT = 0.75          # context._certainty_from_ocr 의 '내용 확인됨' 기준과 같게
MIN_READ_CHARS = 6        # 문서 안에서 확실히 읽은 글자가 이보다 적으면 '못 읽음'
REREAD_IF_CHARS_BELOW = 40  # 이만큼 이미 읽었고 글자도 크면 다시 읽지 않는다(시간)
REREAD_IF_TEXT_PX_BELOW = 22
MAX_REREAD = 4            # 사진 한 장에서 다시 읽을 문서 수 상한
TARGET_SIDE = 1600        # 잘라낸 문서를 이 크기까지 키운다
MAX_UPSCALE = 3.0


@dataclass
class Detection:
    name: str        # 학습 클래스 이름 (waybill, id_card, ...)
    box: Box
    confidence: float

    @property
    def is_document(self) -> bool:
        return self.name in DOC_CLASSES


class YoloDetector:
    def __init__(self, weights: str | os.PathLike, conf: float | None = None,
                 imgsz: int | None = None):
        from ultralytics import YOLO  # 무거우니 쓸 때만

        self.path = Path(weights)
        self.model = YOLO(str(self.path))
        self.names = {int(k): v for k, v in self.model.names.items()}
        self.conf = conf if conf is not None else float(os.environ.get("PL_YOLO_CONF", "0.35"))
        self.imgsz = imgsz or _imgsz_for(self.path)
        version = self.path.parent.name if self.path.parent.name.startswith("v") else self.path.stem
        self.name = f"yolo:{version}"
        self._lock = threading.Lock()

    def detect(self, image: Image.Image) -> list[Detection]:
        with self._lock:  # 추론기는 스레드 안전하다고 가정하지 않는다
            res = self.model.predict(image.convert("RGB"), conf=self.conf,
                                     imgsz=self.imgsz, verbose=False)[0]
        out = []
        for c, p, (x0, y0, x1, y1) in zip(res.boxes.cls.tolist(), res.boxes.conf.tolist(),
                                          res.boxes.xyxy.tolist()):
            box = Box(int(x0), int(y0), int(x1 - x0), int(y1 - y0))
            out.append(Detection(self.names.get(int(c), str(int(c))), box, float(p)))
        return out


def _imgsz_for(weights: Path) -> int:
    env = os.environ.get("PL_YOLO_IMGSZ")
    if env:
        return int(env)
    try:
        return int(json.loads((weights.parent / "metrics.json").read_text(encoding="utf-8"))["imgsz"])
    except Exception:
        return 1280


_detector = None
_detector_lock = threading.Lock()
_UNSET = object()
_loaded: object = _UNSET


def get_detector():
    """PL_YOLO_WEIGHTS 가 있으면 검출기를 한 번만 만든다. 없거나 실패하면 None.

    검출은 보조 단계다. 설정이 틀려도 서비스는 OCR 만으로 계속 돌아야 하므로
    예외를 던지지 않고 경고만 남긴다(사진·문자열은 남기지 않는다).
    """
    global _loaded
    with _detector_lock:
        if _loaded is _UNSET:
            _loaded = None
            weights = os.environ.get("PL_YOLO_WEIGHTS", "").strip()
            if weights and os.environ.get("PL_YOLO", "on").lower() != "off":
                try:
                    if not Path(weights).exists():
                        raise FileNotFoundError(weights)
                    _loaded = YoloDetector(weights)
                except Exception as exc:
                    print(f"[detect] 문서 검출을 끕니다: {type(exc).__name__}: {exc}", file=sys.stderr)
        return _loaded


# ------------------------------------------------------------------ 좌표

def _center_in(span_box: Box, region: Box) -> bool:
    return region.x <= span_box.cx <= region.x + region.w and region.y <= span_box.cy <= region.y + region.h


def _confident_chars(spans: list[TextSpan]) -> int:
    return sum(len(s.text.replace(" ", "")) for s in spans if s.ocr_confidence >= CONFIDENT)


def _crop_box(det: Box, width: int, height: int) -> Box:
    mx = int(det.w * 0.04) + 8
    my = int(det.h * 0.04) + 8
    x0, y0 = max(0, det.x - mx), max(0, det.y - my)
    x1, y1 = min(width, det.x + det.w + mx), min(height, det.y + det.h + my)
    return Box(x0, y0, max(1, x1 - x0), max(1, y1 - y0))


def _to_original(span: TextSpan, crop: Box, scale: float) -> TextSpan:
    b = span.box
    poly = None
    if b.poly:
        poly = tuple((px / scale + crop.x, py / scale + crop.y) for px, py in b.poly)
    box = Box(int(b.x / scale + crop.x), int(b.y / scale + crop.y),
              max(1, int(round(b.w / scale))), max(1, int(round(b.h / scale))), poly=poly)
    return TextSpan(text=span.text, box=box, ocr_confidence=span.ocr_confidence)


def reread_documents(image: Image.Image, spans: list[TextSpan], dets: list[Detection],
                     backend) -> tuple[list[TextSpan], int]:
    """문서 영역을 잘라 확대해서 다시 읽고, 더 잘 읽힌 쪽을 남긴다.

    문서 하나 안에서는 '전체 사진 OCR 결과'와 '확대 OCR 결과' 중 확실히 읽은 글자가
    많은 쪽을 통째로 쓴다. 조각끼리 섞으면 같은 줄이 두 번 들어가거나 반쪽이 된다.
    """
    docs = sorted((d for d in dets if d.is_document), key=lambda d: -d.confidence)
    spans = list(spans)
    reread = 0
    for det in docs:
        if reread >= MAX_REREAD:
            break
        inside = [s for s in spans if _center_in(s.box, det.box)]
        heights = [s.box.h for s in inside if s.ocr_confidence >= CONFIDENT]
        small = not heights or statistics.median(heights) < REREAD_IF_TEXT_PX_BELOW
        if _confident_chars(inside) >= REREAD_IF_CHARS_BELOW and not small:
            continue

        crop = _crop_box(det.box, image.width, image.height)
        scale = min(MAX_UPSCALE, max(1.0, TARGET_SIDE / max(crop.w, crop.h)))
        piece = image.crop((crop.x, crop.y, crop.x + crop.w, crop.y + crop.h))
        if scale > 1.0:
            piece = piece.resize((int(crop.w * scale), int(crop.h * scale)), Image.LANCZOS)
        reread += 1
        again = [_to_original(s, crop, scale) for s in backend.read(piece)]
        again = [s for s in again if _center_in(s.box, det.box)]

        if _confident_chars(again) > _confident_chars(inside):
            keep = [s for s in spans if not _center_in(s.box, det.box)]
            spans = keep + again
    return spans, reread


# ------------------------------------------------------------------ 영역 경고

def _overlaps(a: Box, b: Box, ratio: float = 0.3) -> bool:
    ix = max(0, min(a.x + a.w, b.x + b.w) - max(a.x, b.x))
    iy = max(0, min(a.y + a.h, b.y + b.h) - max(a.y, b.y))
    small = min(a.w * a.h, b.w * b.h) or 1
    return ix * iy / small >= ratio


def region_findings(dets: list[Detection], spans: list[TextSpan],
                    findings: list[Finding]) -> list[Finding]:
    """OCR 로 못 읽은 문서·증명사진·코드를 '영역'으로 알린다. 내용은 비워 둔다."""
    out: list[Finding] = []
    for det in dets:
        detail = {"source": "detector", "detector_class": det.name,
                  "detector_confidence": round(det.confidence, 3)}
        if det.is_document:
            inside = [s for s in spans if _center_in(s.box, det.box)]
            if _confident_chars(inside) < MIN_READ_CHARS:
                out.append(Finding(
                    kind="document", box=det.box, certainty=Certainty.REGION_ONLY,
                    severity=Severity.COVER if det.name in COVER_WHEN_UNREAD else Severity.REVIEW,
                    message=wording.region_only(DOC_CLASSES[det.name]), detail=detail,
                ))
                continue
            # 글자를 조금 읽었지만 개인정보 항목은 하나도 못 찾은 경우.
            # 송장·학생증·명찰은 원래 개인정보가 적힌 물건이라, 머리글('STUDENT ID',
            # 택배사 이름)만 읽고 넘어가면 사람은 읽는 이름·번호를 놓친다.
            found_pii = any(
                f.box is not None and f.severity is not Severity.INFO
                and _center_in(f.box, det.box) and f.kind not in ("qr", "barcode")
                for f in findings
            )
            if det.name in ALWAYS_PERSONAL and not found_pii:
                out.append(Finding(
                    kind="document", box=det.box, certainty=Certainty.PARTIAL,
                    severity=Severity.REVIEW,
                    message=wording.document_unconfirmed(DOC_CLASSES[det.name]), detail=detail,
                ))
        elif det.name == "face_photo":
            out.append(Finding(
                kind="face_photo", box=det.box, certainty=Certainty.REGION_ONLY,
                severity=Severity.REVIEW, message=wording.face_photo_region(), detail=detail,
            ))
        elif det.name == "barcode":
            # 해독에 성공한 QR·바코드는 metadata.check_codes 가 이미 냈다
            if any(f.kind in ("qr", "barcode") and f.box and _overlaps(f.box, det.box)
                   for f in findings):
                continue
            out.append(Finding(
                kind="barcode", box=det.box, certainty=Certainty.REGION_ONLY,
                severity=Severity.REVIEW, message=wording.qr_undecoded(), detail=detail,
            ))
    return out


def tag_documents(dets: list[Detection], findings: list[Finding]) -> None:
    """문서 영역 안의 항목에 어느 문서에서 나왔는지 적는다(글자로 추정한 힌트가 없을 때만)."""
    docs = [d for d in dets if d.is_document]
    for f in findings:
        if f.box is None or "document_hint" in f.detail:
            continue
        holders = [d for d in docs if _center_in(f.box, d.box)]
        if len(holders) == 1:
            f.detail["document_hint"] = DOC_CLASSES[holders[0].name]
