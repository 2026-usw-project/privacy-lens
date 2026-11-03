"""증명사진(face_photo) 학습 데이터 — MIDV-2020 photo 로 YOLO 데이터셋을 만든다.

MIDV-2020(CC BY-SA 2.5, 가상 신분증 10종 × 100장, 얼굴은 생성 얼굴)의 얼굴 영역을 인쇄된 증명사진 전체로
조금 넓혀(vision/midv.py 와 같은 비율) 한 클래스 'face_photo' 로 쓴다.

    학습/검증  문서 종류로 나눈다(기본 검증: srb_passport, svk_id). 처음 보는 신분증 모양에서 재야 해서
    멀리 찍힘  사진을 0.18~0.45 배로 줄여 배경 사진(없으면 잡음) 위에 붙인 사본을 더한다
    누운 사진  일부(기본 30%)를 90도 돌린 사본을 더한다(휴대폰 회전 정보가 지워진 사진)

    python -m vision.face_photo_data <midv photo 폴더> <출력 폴더> [배경 사진 폴더]

평가는 evaluate_models(): YuNet(서비스) 과 학습한 모델을 검증 종류 사진에서 크기·방향별로 잰다.
사진은 드라이브에만 둔다(저장소 금지).
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

from pipeline.types import Box
from vision import midv

VAL_TYPES = ("srb_passport", "svk_id")
MAX_SIDE = 1280
IMAGE_EXTS = {".jpg", ".jpeg", ".png"}


def items(root: Path) -> list[tuple[Path, str, Box, bool]]:
    """(사진, 문서 종류, 넓힌 증명사진 상자, EXIF 회전 적용 여부). 좌표는 회전 적용 뒤 기준."""
    import json
    root = Path(root)
    index: dict[tuple[str, str], Path] = {}
    for p in root.rglob("*"):
        if p.suffix.lower() in IMAGE_EXTS | {".tif", ".tiff"}:
            index.setdefault((p.parent.name, p.name), p)
    out = []
    for jp in sorted(p for p in root.rglob("*.json") if "clips" not in p.parts):
        for e in midv._entries(json.loads(jp.read_text(encoding="utf-8"))):
            img = midv._find_image(jp, e["filename"], index)
            if img is None:
                continue
            fields = {}
            for r in e.get("regions") or []:
                pts = midv._points(r.get("shape_attributes") or {})
                if pts:
                    fields.setdefault(midv._field(r), pts)
            face, quad = fields.get("face") or fields.get("photo"), fields.get("doc_quad")
            if not face or not quad:
                continue
            with Image.open(img) as raw:
                size = raw.size
                turned = ImageOps.exif_transpose(raw).size
            transpose = not midv._fits(quad, *size) and turned != size and midv._fits(quad, *turned)
            W, H = turned if transpose else size
            b = midv._bbox(face, W, H)
            if not b:
                continue
            x0, y0, x1, y1 = b
            gx, gy = (x1 - x0) * midv.FACE_GROW_X, (y1 - y0) * midv.FACE_GROW_Y
            g = midv._bbox([(x0 - gx, y0 - gy), (x1 + gx, y1 + gy)], W, H)
            if g:
                out.append((img, jp.stem, Box(int(g[0]), int(g[1]), int(g[2] - g[0]), int(g[3] - g[1])), transpose))
    return out


def load(path: Path, transpose: bool) -> Image.Image:
    with Image.open(path) as raw:
        im = ImageOps.exif_transpose(raw) if transpose else raw.copy()
    return im.convert("RGB")


def _fit(im: Image.Image, box: Box) -> tuple[Image.Image, Box]:
    s = min(1.0, MAX_SIDE / max(im.size))
    if s == 1.0:
        return im, box
    im = im.resize((int(im.width * s), int(im.height * s)), Image.LANCZOS)
    return im, Box(int(box.x * s), int(box.y * s), max(1, int(box.w * s)), max(1, int(box.h * s)))


def rotate90(im: Image.Image, box: Box, clockwise: bool) -> tuple[Image.Image, Box]:
    W, H = im.size
    if clockwise:  # (x, y) → (H - y, x)
        return im.transpose(Image.ROTATE_270), Box(H - box.y - box.h, box.x, box.h, box.w)
    return im.transpose(Image.ROTATE_90), Box(box.y, W - box.x - box.w, box.h, box.w)  # (x, y) → (y, W - x)


def zoom_out(im: Image.Image, box: Box, rng: random.Random, backgrounds: list[Path]) -> tuple[Image.Image, Box]:
    """멀리 찍힌 것처럼: 줄여서 배경 위 아무 곳에 붙인다."""
    s = rng.uniform(0.18, 0.45)
    small = im.resize((max(8, int(im.width * s)), max(8, int(im.height * s))), Image.LANCZOS)
    if rng.random() < 0.5:
        small = small.filter(ImageFilter.GaussianBlur(rng.uniform(0.3, 1.0)))
    W, H = im.size
    if backgrounds:
        bg = Image.open(rng.choice(backgrounds)).convert("RGB").resize((W, H))
    else:
        bg = Image.effect_noise((W, H), rng.uniform(20, 60)).convert("RGB")
    x, y = rng.randint(0, W - small.width), rng.randint(0, H - small.height)
    bg.paste(small, (x, y))
    nb = Box(x + int(box.x * s), y + int(box.y * s), max(1, int(box.w * s)), max(1, int(box.h * s)))
    return bg, nb


def _label(box: Box, W: int, H: int) -> str:
    return f"0 {(box.x + box.w / 2) / W:.6f} {(box.y + box.h / 2) / H:.6f} {box.w / W:.6f} {box.h / H:.6f}\n"


def build(midv_root: Path, out: Path, *, backgrounds: Path | None = None, val_types=VAL_TYPES,
          rotate_frac: float = 0.3, zoom_copies: int = 1, seed: int = 0) -> dict:
    rng = random.Random(seed)
    bgs = sorted(p for p in Path(backgrounds).rglob("*") if p.suffix.lower() in IMAGE_EXTS) if backgrounds else []
    counts = {"train": 0, "val": 0}
    for split in counts:
        (out / "images" / split).mkdir(parents=True, exist_ok=True)
        (out / "labels" / split).mkdir(parents=True, exist_ok=True)
    for path, doc, box, tr in items(midv_root):
        split = "val" if doc in val_types else "train"
        im, b = _fit(load(path, tr), box)
        stem = f"{doc}_{path.stem}"
        variants = [("", im, b)]
        for k in range(zoom_copies):
            variants.append((f"_z{k}", *zoom_out(im, b, rng, bgs)))
        if split == "train":
            for name, vim, vb in list(variants):
                if rng.random() < rotate_frac:
                    variants.append((name + "_r", *rotate90(vim, vb, rng.random() < 0.5)))
        for name, vim, vb in variants:
            vim.save(out / "images" / split / f"{stem}{name}.jpg", quality=rng.randint(80, 95))
            (out / "labels" / split / f"{stem}{name}.txt").write_text(_label(vb, *vim.size))
            counts[split] += 1
    (out / "data.yaml").write_text(f"path: {out}\ntrain: images/train\nval: images/val\nnames:\n  0: face_photo\n")
    return counts


def evaluate_models(midv_root: Path, models: dict, *, val_types=VAL_TYPES, scales=(1.0, 0.25, 0.125),
                    thresholds=(0.3, 0.4, 0.5, 0.6), limit: int | None = None) -> dict:
    """models: 이름 → detect(PIL) 가 ObjectBox 목록을 주는 객체(YuNet FaceDetector, YoloBoxes 등).

    정답은 넓힌 증명사진 상자, IoU 0.3. YuNet 은 얼굴만 잡아 상자가 작으므로 '얼굴 중심이 정답 상자 안'도 맞힘으로 친다."""
    from vision import objects_eval as oe
    its = [x for x in items(midv_root) if x[1] in val_types][:limit]
    res = {}
    for name, det in models.items():
        for rot in (False, True):
            for s in scales:
                samples = []
                for path, _, box, tr in its:
                    im, b = _fit(load(path, tr), box)
                    if s != 1.0:
                        im = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.LANCZOS)
                        b = Box(int(b.x * s), int(b.y * s), max(1, int(b.w * s)), max(1, int(b.h * s)))
                    if rot:
                        im, b = rotate90(im, b, True)
                    preds = []
                    for o in det.detect(im):
                        p = o.box
                        cx, cy = p.x + p.w / 2, p.y + p.h / 2
                        inside = b.x <= cx <= b.x + b.w and b.y <= cy <= b.y + b.h
                        preds.append(oe.Pred(b if inside else p, o.score))  # 중심이 안이면 정답 상자로 맞힘 처리
                    samples.append(([oe.GT(b)], preds))
                res[f"{name}|{'누움' if rot else '그대로'}|x{s}"] = oe.sweep(samples, list(thresholds))
    return res


class YoloBoxes:
    """우리가 학습한 YOLO 증명사진 모델을 FaceDetector 처럼 쓴다(평가용)."""

    def __init__(self, path, conf: float = 0.05, imgsz: int = 640):
        from ultralytics import YOLO
        self.m, self.conf, self.imgsz = YOLO(str(path), task="detect"), conf, imgsz

    def detect(self, im):
        from pipeline.objects import ObjectBox
        r = self.m.predict(im, conf=self.conf, imgsz=self.imgsz, verbose=False)[0]
        return [ObjectBox("face_photo", Box(int(a), int(b), int(c - a), int(d - b)), float(p))
                for p, (a, b, c, d) in zip(r.boxes.conf.tolist(), r.boxes.xyxy.tolist())]


if __name__ == "__main__":
    a = sys.argv[1:]
    print(build(Path(a[0]), Path(a[1]), backgrounds=Path(a[2]) if len(a) > 2 else None))
