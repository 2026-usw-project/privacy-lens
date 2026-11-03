"""증명사진 얼굴 평가 — MIDV-2020 가상 신분증 사진(CC BY-SA 2.5, 얼굴은 생성 얼굴)으로 YuNet 을 잰다.

Open Images 얼굴(사람 사진)로 잰 숫자는 우리 쓰임새(사진 속 신분증·학생증의 증명사진)와 다르다.
신분증 사진은 흑백·작은 인쇄·반사·기울기가 있어 일반 얼굴 검출기 성능이 떨어진다고 알려져 있다
(Face Detection in Camera Captured Images of Identity Documents, arXiv:1911.03567).

    python -m vision.face_eval <photo.tar 를 푼 폴더>      # Colab 11번 칸이 부른다

사진을 줄여(문서가 멀리 찍힌 것처럼) 크기별로, 그리고 90도 돌려서도 잰다. 사진은 저장소에 넣지 않는다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageOps

from pipeline.types import Box
from vision import midv
from vision.objects_eval import GT, Pred, sweep

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}


def midv_faces(root: Path, *, limit_per_type: int | None = None) -> list[tuple[Path, list[Box], bool]]:
    """(사진 경로, 얼굴 상자들, EXIF 회전을 적용해야 하는지)."""
    root = Path(root)
    index: dict[tuple[str, str], Path] = {}
    for p in root.rglob("*"):
        if p.suffix.lower() in IMAGE_EXTS:
            index.setdefault((p.parent.name, p.name), p)
    out = []
    for jp in sorted(p for p in root.rglob("*.json") if "clips" not in p.parts):
        n = 0
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
            out.append((img, [Box(int(x0), int(y0), int(x1 - x0), int(y1 - y0))], transpose))
            n += 1
            if limit_per_type and n >= limit_per_type:
                break
    return out


def _open(path: Path, transpose: bool) -> Image.Image:
    with Image.open(path) as raw:
        im = ImageOps.exif_transpose(raw) if transpose else raw.copy()
    return im.convert("RGB")


def evaluate(items, detector, *, scales=(1.0, 0.5, 0.25, 0.125), rotate: bool = False,
             thresholds=(0.5, 0.6, 0.7)) -> dict:
    """크기별 정밀도·재현율. 정답은 인쇄 얼굴 타원이라 IoU 기준을 0.3 으로 둔다(얼굴 상자와 모양이 달라서)."""
    from vision import objects_eval as oe
    res = {}
    old = oe.IOU
    oe.IOU = 0.3
    try:
        for s in scales:
            samples = []
            for path, faces, tr in items:
                im = _open(path, tr)
                W, H = im.size
                if s != 1.0:
                    im = im.resize((max(1, int(W * s)), max(1, int(H * s))), Image.LANCZOS)
                gts = [GT(Box(int(b.x * s), int(b.y * s), max(1, int(b.w * s)), max(1, int(b.h * s)))) for b in faces]
                if rotate:  # 시계 90도: (x, y) → (H - y, x)
                    h = im.height
                    im = im.transpose(Image.ROTATE_270)
                    gts = [GT(Box(h - g.box.y - g.box.h, g.box.x, g.box.h, g.box.w)) for g in gts]
                preds = [Pred(o.box, o.score) for o in detector.detect(im)]
                samples.append((gts, preds))
            face_px = sorted(min(g.box.w, g.box.h) for gts, _ in samples for g in gts)
            res[f"x{s}"] = {"median_face_px": face_px[len(face_px) // 2] if face_px else None,
                            "rows": sweep(samples, list(thresholds))}
    finally:
        oe.IOU = old
    return res


def main(argv=None) -> None:
    from pipeline.objects import MODELS, YUNET_FILE, FaceDetector
    root = Path((argv or sys.argv[1:])[0])
    items = midv_faces(root)
    print("사진", len(items))
    det = FaceDetector(MODELS / YUNET_FILE, score=0.3)
    for rot in (False, True):
        r = evaluate(items, det, rotate=rot)
        for k, v in r.items():
            print(f"\n[{'90도 돌림' if rot else '그대로'} {k}] 얼굴 짧은 변 중간값 {v['median_face_px']}px")
            for row in v["rows"]:
                print(f"  기준 {row['thr']}: 정밀도 {row['precision']} 재현율 {row['recall']} (놓침 {row['fn']}, 오탐 {row['fp']})")


if __name__ == "__main__":
    main()
