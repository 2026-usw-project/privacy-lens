"""글자가 아닌 이미지 객체 — 얼굴·증명사진·번호판(D-16).

OCR 이 못 하는 일만 맡는다. 직접 학습하지 않고 성능이 공개된 모델을 쓴다.

  얼굴    OpenCV YuNet(MIT). WIDER Face 검증셋 AP 0.88/0.87/0.75(쉬움/보통/어려움, opencv_zoo 기준).
          10~300px 얼굴용이라 사진을 두 크기로 줄여 두 번 찾는다.
  증명사진 얼굴이 카드 위에 있으면(문서 검출의 학생증·카드 상자 안, 또는 근처 OCR 글자에
          '학생증·주민등록증·성명' 같은 단서나 이름·주민번호·학번 항목이 있으면) 증명사진으로 본다.
  번호판  선택. PL_PLATE_MODEL 에 YOLO 번호판 모델(.onnx 권장)을 주면 쓴다.
          글자는 OCR 이 차량번호로 이미 잡으므로, 글자를 못 읽은 번호판만 영역으로 알린다.

어떤 얼굴을 알릴지는 팀 정책(D-18)이라 환경변수로 고른다.
  PL_FACES=card(기본)  증명사진만 가림 권장. 사진 속 사람 얼굴은 알리지 않는다
  PL_FACES=all         + 사진 속 모든 얼굴을 검토 권장으로
  PL_FACES=off         얼굴 검출을 하지 않는다

모델 파일은 저장소에 넣지 않는다(*.onnx 무시). 받기:
    python -m pipeline.objects download      # YuNet 을 models/ 에 받고 SHA-256 을 확인한다

보안: .pt(PyTorch) 가중치는 pickle 이라 여는 순간 안의 코드가 실행될 수 있다. 남이 올린 모델은
.onnx 를 쓰고, 받은 파일의 해시를 기록해 둔다(vision/README.md).
"""

from __future__ import annotations

import hashlib
import os
import sys
import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from . import kr_patterns as kp
from . import wording
from .types import Box, Certainty, Finding, Severity, TextSpan

MODELS = Path(__file__).resolve().parent.parent / "models"

YUNET_FILE = "face_detection_yunet_2023mar.onnx"
YUNET_URL = ("https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
             "face_detection_yunet/face_detection_yunet_2023mar.onnx")
YUNET_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"

FACE_SCORE = 0.7
FACE_SCALES = (1600, 640)     # 긴 변을 이만큼으로 줄여 두 번. 작은 얼굴과 큰 얼굴을 다 받으려고
CARD_CONTEXT_EM = 4.0         # 얼굴 높이의 이 배수 안에 카드 단서가 있으면 증명사진
CARD_WORDS = (kp.CONTEXT_DOCUMENT["student"] + kp.CONTEXT_DOCUMENT["badge"]
              + ["주민등록증", "운전면허", "면허증", "신분증", "여권", "PASSPORT", "성명", "생년월일",
                 "IDCARD", "STUDENT"])
CARD_KINDS = {"name", "rrn", "rrn_unverified", "student_id"}
CARD_DETECTIONS = {"id_card", "name_tag"}
PLATE_CONF = 0.4


def face_mode(value: str | None = None) -> str:
    mode = (value or os.environ.get("PL_FACES", "card")).strip().lower()
    return mode if mode in ("off", "card", "all") else "card"


# ------------------------------------------------------------------ 모델

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download_yunet(dest: Path | None = None) -> Path:
    dest = dest or MODELS / YUNET_FILE
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    urllib.request.urlretrieve(YUNET_URL, tmp)
    digest = _sha256(tmp)
    if digest != YUNET_SHA256:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"YuNet 파일 해시가 다릅니다({digest[:12]}…). 받지 않았습니다.")
    tmp.replace(dest)
    return dest


@dataclass
class ObjectBox:
    kind: str          # face, plate
    box: Box
    score: float


class FaceDetector:
    name = "yunet"

    def __init__(self, model: Path):
        import cv2
        if not hasattr(cv2, "FaceDetectorYN"):
            raise RuntimeError("OpenCV 4.5.4 이상이 필요합니다(FaceDetectorYN)")
        self._cv2 = cv2
        self._det = cv2.FaceDetectorYN.create(str(model), "", (320, 320), FACE_SCORE, 0.3, 5000)
        self._lock = threading.Lock()

    def detect(self, image: Image.Image) -> list[ObjectBox]:
        cv2 = self._cv2
        bgr = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2BGR)
        H, W = bgr.shape[:2]
        found: list[ObjectBox] = []
        for side in FACE_SCALES:
            s = min(1.0, side / max(W, H))
            img = bgr if s == 1.0 else cv2.resize(bgr, (max(1, int(W * s)), max(1, int(H * s))),
                                                 interpolation=cv2.INTER_AREA)
            with self._lock:
                self._det.setInputSize((img.shape[1], img.shape[0]))
                _, faces = self._det.detect(img)
            for f in (faces if faces is not None else []):
                x, y, w, h = (float(v) / s for v in f[:4])
                box = Box(max(0, int(x)), max(0, int(y)), int(min(w, W - x)), int(min(h, H - y)))
                if box.w > 2 and box.h > 2:
                    found.append(ObjectBox("face", box, float(f[-1])))
            if s == 1.0:
                break  # 원본이 이미 작으면 한 번이면 된다
        return _nms(found, 0.4)


class PlateDetector:
    def __init__(self, model: Path):
        from ultralytics import YOLO
        self.model = YOLO(str(model), task="detect")
        self.name = f"plate:{model.name}"
        self._lock = threading.Lock()

    def detect(self, image: Image.Image) -> list[ObjectBox]:
        with self._lock:
            r = self.model.predict(image.convert("RGB"), conf=PLATE_CONF, verbose=False)[0]
        out = []
        for p, (x0, y0, x1, y1) in zip(r.boxes.conf.tolist(), r.boxes.xyxy.tolist()):
            out.append(ObjectBox("plate", Box(int(x0), int(y0), int(x1 - x0), int(y1 - y0)), float(p)))
        return out


def _iou(a: Box, b: Box) -> float:
    ix = max(0, min(a.x + a.w, b.x + b.w) - max(a.x, b.x))
    iy = max(0, min(a.y + a.h, b.y + b.h) - max(a.y, b.y))
    inter = ix * iy
    union = a.w * a.h + b.w * b.h - inter
    return inter / union if union else 0.0


def _nms(boxes: list[ObjectBox], thr: float) -> list[ObjectBox]:
    kept: list[ObjectBox] = []
    for b in sorted(boxes, key=lambda o: -o.score):
        if all(_iou(b.box, k.box) < thr for k in kept):
            kept.append(b)
    return kept


_lock = threading.Lock()
_cache: dict[str, object] = {}


def _load(key: str, factory):
    """한 번만 만든다. 실패하면 경고만 남기고 None(서비스는 OCR 만으로 계속 돈다)."""
    with _lock:
        if key not in _cache:
            try:
                _cache[key] = factory()
            except Exception as exc:
                print(f"[objects] {key} 를 끕니다: {type(exc).__name__}: {exc}", file=sys.stderr)
                _cache[key] = None
        return _cache[key]


def get_face_detector():
    if face_mode() == "off":
        return None
    path = Path(os.environ.get("PL_FACE_MODEL") or MODELS / YUNET_FILE)
    if not path.exists():
        return None  # 받지 않았으면 조용히 끈다. run.py --check 가 안내한다
    return _load(f"face:{path}", lambda: FaceDetector(path))


def get_plate_detector():
    raw = os.environ.get("PL_PLATE_MODEL", "").strip()
    if not raw:
        return None
    path = Path(raw)
    return _load(f"plate:{path}", lambda: PlateDetector(path))


# ------------------------------------------------------------------ 판단

def _inside(inner: Box, outer: Box) -> bool:
    return outer.x <= inner.cx <= outer.x + outer.w and outer.y <= inner.cy <= outer.y + outer.h


def _card_clue(face: Box, spans: list[TextSpan], findings: list[Finding], dets) -> str | None:
    """얼굴이 카드 위에 있다는 단서. 없으면 None."""
    for d in dets or []:
        if d.name in CARD_DETECTIONS and _inside(face, d.box):
            return d.name
    reach = face.expanded(int(face.h * CARD_CONTEXT_EM))
    for s in spans:
        if s.box.intersects(reach):
            flat = kp.label_key(kp.normalize(s.text)).upper()
            word = next((w for w in CARD_WORDS if kp.label_key(w).upper() in flat), None)
            if word:
                return word
    for f in findings:
        if f.kind in CARD_KINDS and f.box is not None and f.box.intersects(reach) \
                and f.severity is not Severity.INFO:
            return f.kind
    return None


def find_objects(image: Image.Image, spans: list[TextSpan], findings: list[Finding],
                 dets=None, *, mode: str | None = None, face_detector=None,
                 plate_detector=None) -> list[Finding]:
    """얼굴·증명사진·번호판 항목. 검출기를 안 주면 환경변수 설정대로 만든다."""
    mode = face_mode(mode)
    # None 이면 환경변수 설정대로 만들고, False 를 주면 끈다(시험·비교용)
    faces = get_face_detector() if face_detector is None else (face_detector or None)
    plates = get_plate_detector() if plate_detector is None else (plate_detector or None)
    out: list[Finding] = []

    if faces is not None and mode != "off":
        already = [f.box for f in findings if f.kind == "face_photo" and f.box is not None]
        for o in faces.detect(image):
            if any(_iou(o.box, b) > 0.3 or _inside(o.box, b) for b in already):
                continue  # 문서 검출이 이미 증명사진으로 냈다
            detail = {"source": "object", "model": getattr(faces, "name", "face"), "score": round(o.score, 3)}
            clue = _card_clue(o.box, spans, findings, dets)
            if clue:
                detail["clue"] = clue
                out.append(Finding(kind="face_photo", box=o.box, certainty=Certainty.REGION_ONLY,
                                   severity=Severity.COVER, message=wording.face_photo_region(), detail=detail))
            elif mode == "all":
                out.append(Finding(kind="face", box=o.box, certainty=Certainty.REGION_ONLY,
                                   severity=Severity.REVIEW, message=wording.face_region(), detail=detail))

    if plates is not None:
        read = [f.box for f in findings if f.kind == "plate" and f.box is not None]
        for o in plates.detect(image):
            if any(b.intersects(o.box) for b in read):
                continue  # OCR 이 번호를 읽어 차량번호 항목이 이미 있다
            out.append(Finding(kind="plate", box=o.box, certainty=Certainty.REGION_ONLY,
                               severity=Severity.REVIEW, message=wording.plate_region(),
                               detail={"source": "object", "model": getattr(plates, "name", "plate"),
                                       "score": round(o.score, 3)}))
    return out


def status() -> list[str]:
    """run.py --check 용 한 줄 설명들."""
    lines = []
    mode = face_mode()
    yunet = Path(os.environ.get("PL_FACE_MODEL") or MODELS / YUNET_FILE)
    if mode == "off":
        lines.append("얼굴 검출 꺼짐(PL_FACES=off)")
    elif yunet.exists():
        lines.append(f"얼굴 검출 YuNet ({mode})")
    else:
        lines.append("얼굴 모델 없음 — python -m pipeline.objects download")
    plate = os.environ.get("PL_PLATE_MODEL", "").strip()
    lines.append(f"번호판 검출 {Path(plate).name}" if plate else "번호판 검출 꺼짐(PL_PLATE_MODEL 없음)")
    return lines


if __name__ == "__main__":
    if sys.argv[1:] == ["download"]:
        print(f"받았습니다: {download_yunet()}")
    else:
        print("\n".join(status()))
