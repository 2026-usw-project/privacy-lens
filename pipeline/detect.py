"""문서 검출(YOLO) 단계. 선택 사항이다.

OCR 만으로는 두 가지를 놓친다.

1. **글자가 작아서 OCR 이 아예 못 찾는 경우.** 사진 배경의 학생증처럼 글자가
   몇 픽셀밖에 안 되면 검출 단계에서 빠진다. 사람은 확대해 보면 읽는데도.
2. **못 읽었다는 사실조차 모르는 경우.** OCR 결과가 비면 경고할 근거가 없다.

YOLO 는 글자를 읽지 않고 '학생증 모양'을 찾는다. 그래서

  - 찾은 문서 영역을 잘라 **확대해서 OCR 을 다시** 돌리고(1 해결),
  - 그래도 못 읽으면 '문서로 보이는 영역이 있으나 내용을 확인하지 못했다'는
    **영역 경고**를 낸다(2 해결). 내용은 지어내지 않는다.

가중치가 없으면 이 단계는 통째로 건너뛰고 예전과 똑같이
동작한다. 학습은 vision/ 도구로 한다.

  PL_YOLO_WEIGHTS  best.pt 경로. 미설정이면 models/v<최대 숫자>/best.pt,
                   버전 폴더가 없으면 models/best.pt
  PL_YOLO_CONF     검출 기준 (기본 0.35)
  PL_YOLO_IMGSZ    입력 크기 (기본: 가중치 옆 metrics.json 의 imgsz, 없으면 1280)
"""

from __future__ import annotations

import json
import os
import re
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
    # 일상 사진 9종 모델(models/daily.onnx, D-19)에만 있는 클래스
    "card": "card",
    "receipt": "receipt",
    "document": "document",
    "ticket": "ticket",
    "health_item": "health_item",
}
# 내용을 못 읽었을 때 바로 '가림 권장'으로 올릴 문서. 신원·결제와 직결된다
COVER_WHEN_UNREAD = {"id_card", "name_tag", "card"}
# 원래 개인정보가 적혀 있는 물건. 읽었는데 개인정보를 못 찾았으면 '검토 권장'
ALWAYS_PERSONAL = {"waybill", "id_card", "name_tag", "card", "health_item"}

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


def model_family(model) -> str:
    """Ultralytics 모델의 계열 이름('yolo26', 'yolo11'). 알 수 없으면 빈 문자열.

    가중치 안에 학습할 때 쓴 구조 파일 이름(yolo26n.yaml 등)이 들어 있다.
    """
    inner = getattr(model, "model", model)
    yaml = getattr(inner, "yaml", None) or {}
    m = re.match(r"(yolo(?:v)?\d+)", str(yaml.get("yaml_file", "")).lower())
    return m.group(1) if m else ""


class YoloDetector:
    def __init__(self, weights: str | os.PathLike, conf: float | None = None,
                 imgsz: int | None = None):
        from .ultra import yolo_class  # 자동 설치 끔 + Image.open 원래대로(pipeline/ultra.py)

        YOLO = yolo_class()

        self.path = Path(weights)
        # .onnx 는 클래스 정보로 작업 종류를 알 수 없어 detect 로 알려 준다
        self.model = YOLO(str(self.path), task="detect") if self.path.suffix == ".onnx" else YOLO(str(self.path))
        self.names = {int(k): v for k, v in self.model.names.items()}
        self.conf = conf if conf is not None else float(os.environ.get("PL_YOLO_CONF", "0.35"))
        self.imgsz = imgsz or _imgsz_for(self.path)
        version = self.path.parent.name if self.path.parent.name.startswith("v") else self.path.stem
        self.family = model_family(self.model)
        # 화면 하단에 'YOLO v005·yolo26 (CPU)' 처럼 보인다. YOLO11 로 학습한 예전 모델과 구분하려고
        self.name = f"yolo:{version}·{self.family}" if self.family else f"yolo:{version}"
        self.device = ""
        self._lock = threading.Lock()

    def detect(self, image: Image.Image) -> list[Detection]:
        with self._lock:  # 추론기는 스레드 안전하다고 가정하지 않는다
            res = self.model.predict(image.convert("RGB"), conf=self.conf,
                                     imgsz=self.imgsz, verbose=False)[0]
            # 추론 후 실제 선택된 장치를 기록한다(CUDA 지원 여부로 추정하지 않음).
            self.device = str(self.model.predictor.device)
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


DEFAULT_WEIGHTS = Path(__file__).resolve().parent.parent / "models" / "best.pt"


def _default_weights() -> Path:
    """프로젝트 models 바로 아래의 v숫자 폴더를 숫자 순서로 비교한다."""
    models = DEFAULT_WEIGHTS.parent
    versions = [p for p in models.iterdir()
                if p.is_dir() and p.name.startswith("v")
                and p.name[1:].isascii() and p.name[1:].isdigit()] if models.is_dir() else []
    if versions:
        return max(versions, key=lambda p: (int(p.name[1:]), p.name)) / "best.pt"
    return DEFAULT_WEIGHTS

class MultiDetector:
    """문서 모델 + 일상 사진 9종 모델을 함께 돌린다. 같은 클래스 상자가 겹치면 확신도 높은 쪽만 남긴다."""

    def __init__(self, detectors: list):
        self.detectors = detectors
        self.name = "+".join(getattr(d, "name", "yolo") for d in detectors)

    @property
    def device(self) -> str:
        return getattr(self.detectors[0], "device", "")

    def detect(self, image: Image.Image) -> list[Detection]:
        found = [d for det in self.detectors for d in det.detect(image)]
        kept: list[Detection] = []
        for d in sorted(found, key=lambda x: -x.confidence):
            if all(k.name != d.name or not _overlaps(k.box, d.box, 0.6) for k in kept):
                kept.append(d)
        return kept


class TiledDetector:
    """작게 찍힌 물건용(D-21). 사진 전체를 한 번 보고, 큰 사진은 겹치게 grid×grid 조각으로 나눠 한 번 더 본다.

    입력 640 으로 줄이면 4000px 사진 구석의 송장은 몇십 px 이 되어 놓친다. 조각으로 보면 같은 물건이 2배 이상 크게 보인다.
    - 사진 긴 변이 min_side 보다 작으면 조각을 만들지 않는다(이미 충분히 크다).
    - 조각에서 찾은 상자가 조각을 자른 선에 닿으면 버린다(잘린 물건). 겹침(overlap) 덕분에 옆 조각이나 전체 보기에서 온전히 잡힌다.
    - 전체 보기 결과를 우선한다. 조각 결과는 같은 클래스 상자와 겹치지 않을 때만 더한다(큰 물건이 조각으로 쪼개지는 것 방지).
    """

    def __init__(self, inner, grid: int = 2, overlap: float = 0.2, min_side: int | None = None):
        self.inner = inner
        self.grid = max(1, int(grid))
        self.overlap = overlap
        self.min_side = min_side or 2 * int(getattr(inner, "imgsz", 640) or 640)
        self.name = f"{getattr(inner, 'name', 'yolo')}·조각{self.grid}x{self.grid}"

    @property
    def device(self) -> str:
        return getattr(self.inner, "device", "")

    def tiles(self, w: int, h: int) -> list[tuple[int, int, int, int]]:
        if self.grid < 2 or max(w, h) < self.min_side:
            return []
        out = []
        tw, th = w / (self.grid - (self.grid - 1) * self.overlap), h / (self.grid - (self.grid - 1) * self.overlap)
        for r in range(self.grid):
            for c in range(self.grid):
                x0, y0 = round(c * tw * (1 - self.overlap)), round(r * th * (1 - self.overlap))
                out.append((x0, y0, min(w, round(x0 + tw)), min(h, round(y0 + th))))
        return out

    def detect(self, image: Image.Image) -> list[Detection]:
        kept = list(self.inner.detect(image))
        w, h = image.size
        extra: list[Detection] = []
        for x0, y0, x1, y1 in self.tiles(w, h):
            for d in self.inner.detect(image.crop((x0, y0, x1, y1))):
                b = d.box
                cut = ((x0 > 0 and b.x <= 2) or (y0 > 0 and b.y <= 2)
                       or (x1 < w and b.x + b.w >= x1 - x0 - 2) or (y1 < h and b.y + b.h >= y1 - y0 - 2))
                if not cut:
                    extra.append(Detection(d.name, Box(b.x + x0, b.y + y0, b.w, b.h), d.confidence))
        for d in sorted(extra, key=lambda x: -x.confidence):
            if all(k.name != d.name or not _overlaps(k.box, d.box, 0.5) for k in kept):
                kept.append(d)
        return kept


DAILY_FILE = "daily.onnx"   # 드라이브 objects/daily_vNNN/best.onnx 를 models/daily.onnx 로 두면 자동으로 쓴다
DAILY_IMGSZ = 640           # 학습·내보내기 크기(vision/next_steps.train_daily)


def daily_model_path() -> Path | None:
    """PL_DAILY_MODEL(경로, 또는 off) > models/daily.onnx. 없으면 None."""
    raw = os.environ.get("PL_DAILY_MODEL", "").strip()
    if raw.lower() == "off":
        return None
    if raw:
        return Path(raw)
    default = DEFAULT_WEIGHTS.parent / DAILY_FILE
    return default if default.exists() else None


def _load_daily():
    path = daily_model_path()
    if path is None:
        return None
    try:
        if not path.exists():
            raise FileNotFoundError(path)
        imgsz = int(os.environ.get("PL_DAILY_IMGSZ", DAILY_IMGSZ))
        det = YoloDetector(path, imgsz=imgsz)
        # 조각 검출은 팀 실사로 효과를 재기 전까지 끈다(PLAN 16). 켜려면 PL_DAILY_TILES=2
        grid = int(os.environ.get("PL_DAILY_TILES", "0") or 0)
        return TiledDetector(det, grid=grid) if grid >= 2 else det
    except Exception as exc:
        print(f"[detect] 일상 사진 물건 검출을 끕니다: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None


_detector = None
_detector_lock = threading.Lock()
_UNSET = object()
_loaded: object = _UNSET


def get_detector():
    """지정 경로 또는 models 최신 버전의 best.pt 로 검출기를 한 번만 만든다.

    검출은 보조 단계다. 설정이 틀려도 서비스는 OCR 만으로 계속 돌아야 하므로
    예외를 던지지 않고 경고만 남긴다(사진·문자열은 남기지 않는다).
    """
    global _loaded
    with _detector_lock:
        if _loaded is _UNSET:
            _loaded = None
            if os.environ.get("PL_YOLO", "on").lower() == "off":
                return None
            docs = None
            configured = os.environ.get("PL_YOLO_WEIGHTS", "").strip()
            try:
                weights = Path(configured) if configured else _default_weights()
                if Path(weights).exists():
                    docs = YoloDetector(weights)
                elif configured:
                    raise FileNotFoundError(weights)
            except Exception as exc:
                print(f"[detect] 문서 검출을 끕니다: {type(exc).__name__}: {exc}", file=sys.stderr)
            found = [d for d in (docs, _load_daily()) if d is not None]
            _loaded = found[0] if len(found) == 1 else (MultiDetector(found) if found else None)
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
                     backend, *, raw_ocr: list[TextSpan] | None = None) -> tuple[list[TextSpan], int]:
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
        from .ocr import read_with_raw
        processed, raw = read_with_raw(backend, piece)
        if raw_ocr is not None:
            # 판정에 채택되지 않은 재판독도 원본 좌표로 보존한다.
            raw_ocr.extend(_to_original(s, crop, scale) for s in raw)
        again = [_to_original(s, crop, scale) for s in processed]
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
