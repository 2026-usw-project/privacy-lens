"""한국 번호판 합성 — 실제 한국 번호판 조각을 차량 장면 사진의 번호판 자리에 붙인다.

왜: 한국 번호판 학습 사진(Roboflow)은 번호판을 가까이 찍은 것뿐이라, 주차장처럼 차 전체가 나오는
장면에서 한국 번호판을 잘 못 찾는다(2026-11-03, 재현율 0.63). 장면 사진(Open Images, 해외 번호판
상자 라벨 있음)의 번호판 자리에 진짜 한국 번호판 조각을 붙이면 '장면 + 한국 번호판' 사진을 정답과 함께
만들 수 있다. 상자는 원래 라벨을 그대로 쓴다.

    조각   kr_train 데이터의 번호판 상자를 잘라 모은다(가로 48px 이상, 가로세로 1.4~6)
    붙이기 상자와 비율이 가까운 조각을 고르고, 상자 크기로 줄인 뒤 주변 밝기·대비에 맞추고 가장자리를 흐리게
    남기기 일부 번호판은 원래(해외) 그대로 둔다(keep). 해외 번호판을 잊지 않게

평가용 207장(hyunjin)은 여기에 쓰지 않는다. 사진은 드라이브에만 둔다(저장소 금지).
"""

from __future__ import annotations

import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from vision.objects_eval import yolo_labels, yolo_pairs

MIN_CROP_W = 48
ASPECT = (1.4, 6.0)


def collect_crops(roots: list[Path], *, limit: int = 4000, seed: int = 0) -> list[Image.Image]:
    """kr 데이터 폴더들에서 번호판 조각을 모은다."""
    rng = random.Random(seed)
    pairs = [p for r in roots for p in yolo_pairs(Path(r))]
    rng.shuffle(pairs)
    crops: list[Image.Image] = []
    for img, lab in pairs:
        try:
            im = Image.open(img).convert("RGB")
        except OSError:
            continue
        W, H = im.size
        for g in yolo_labels(lab, W, H):
            b = g.box
            if b.w < MIN_CROP_W or not (ASPECT[0] <= b.w / max(1, b.h) <= ASPECT[1]):
                continue
            x0, y0 = max(0, b.x), max(0, b.y)
            crops.append(im.crop((x0, y0, min(W, b.x + b.w), min(H, b.y + b.h))))
        if len(crops) >= limit:
            break
    return crops


def _match(crop: np.ndarray, region: np.ndarray) -> np.ndarray:
    """조각의 밝기·대비를 붙일 자리 주변에 맞춘다(채널별 평균·표준편차, 너무 세게는 안 함)."""
    c = crop.astype(np.float32)
    r = region.astype(np.float32)
    cm, cs = c.mean(axis=(0, 1)), c.std(axis=(0, 1)) + 1e-3
    rm, rs = r.mean(axis=(0, 1)), r.std(axis=(0, 1)) + 1e-3
    scale = np.clip(rs / cs, 0.6, 1.4)
    out = (c - cm) * (0.5 + 0.5 * scale) + (0.5 * cm + 0.5 * rm)
    return np.clip(out, 0, 255).astype(np.uint8)


def paste(scene: Image.Image, box, crop: Image.Image, rng: random.Random) -> Image.Image:
    w, h = box.w, box.h
    if w < 6 or h < 3:
        return scene
    piece = crop.resize((w, h), Image.BILINEAR)
    if min(w, h) < 24:  # 작은 번호판은 원래 사진처럼 살짝 흐리게
        piece = piece.filter(ImageFilter.GaussianBlur(rng.uniform(0.3, 0.8)))
    region = np.asarray(scene.crop((box.x, box.y, box.x + w, box.y + h)).convert("RGB"))
    if region.size:
        piece = Image.fromarray(_match(np.asarray(piece), region))
    mask = Image.new("L", (w, h), 255)
    edge = max(1, min(w, h) // 12)
    mask = mask.filter(ImageFilter.GaussianBlur(edge / 2)) if edge > 1 else mask
    out = scene.copy()
    out.paste(piece, (box.x, box.y), mask)
    return out


def build(scene_root: Path, crops: list[Image.Image], out_root: Path, *, keep: float = 0.2,
          min_box: int = 10, seed: int = 0, split: str = "train") -> int:
    """scene_root(YOLO 폴더)의 사진마다 번호판을 한국 조각으로 바꿔 out_root/images|labels/<split> 에 쓴다."""
    rng = random.Random(seed)
    if not crops:
        raise ValueError("번호판 조각이 없습니다")
    aspects = np.array([c.width / c.height for c in crops])
    (out_root / "images" / split).mkdir(parents=True, exist_ok=True)
    (out_root / "labels" / split).mkdir(parents=True, exist_ok=True)
    n = 0
    for img, lab in yolo_pairs(Path(scene_root)):
        im = Image.open(img).convert("RGB")
        W, H = im.size
        gts = yolo_labels(lab, W, H)
        changed = False
        for g in gts:
            b = g.box
            if min(b.w, b.h) < min_box or rng.random() < keep:
                continue
            target = b.w / max(1, b.h)
            near = np.argsort(np.abs(aspects - target))[:25]
            im = paste(im, b, crops[int(rng.choice(list(near)))], rng)
            changed = True
        if not changed:
            continue
        name = f"kr_{img.stem}"
        im.save(out_root / "images" / split / f"{name}.jpg", quality=rng.randint(80, 95))
        (out_root / "labels" / split / f"{name}.txt").write_text(lab.read_text())
        n += 1
    return n


def miss_grid(samples, pairs, *, thr: float = 0.4, limit: int = 48, cell: int = 160) -> Image.Image:
    """놓친 정답 번호판을 주변과 함께 잘라 격자 그림으로. 원인을 눈으로 본다(드라이브에만 저장)."""
    from vision.objects_eval import IOU, _iou
    tiles = []
    for (gts, preds), (img, _) in zip(samples, pairs):
        ps = [p for p in preds if p.score >= thr]
        missed = [g for g in gts if not g.ignore and not any(_iou(p.box, g.box) >= IOU for p in ps)]
        if not missed:
            continue
        im = Image.open(img).convert("RGB")
        for g in missed:
            b = g.box
            pad = max(b.w, b.h)
            t = im.crop((b.x - pad, b.y - pad, b.x + b.w + pad, b.y + b.h + pad)).resize((cell, cell))
            tiles.append(t)
            if len(tiles) >= limit:
                break
        if len(tiles) >= limit:
            break
    cols = 8
    rows = max(1, (len(tiles) + cols - 1) // cols)
    grid = Image.new("RGB", (cols * cell, rows * cell), (40, 40, 40))
    for i, t in enumerate(tiles):
        grid.paste(t, ((i % cols) * cell, (i // cols) * cell))
    return grid


def rotated_copies(roots: list[Path], out: Path, *, frac: float = 0.3, seed: int = 0) -> int:
    """학습 사진의 일부(frac)를 시계·반시계 90도로 돌린 사본을 out/images/train 에 만든다.

    돌려 찾기(PL_PLATE_ROTATE)를 하지 않아도 누운 사진에서 찾게 하려는 학습용 증강."""
    from vision.objects_eval import rotate_pairs
    rng = random.Random(seed)
    pairs = [p for r in roots for p in yolo_pairs(Path(r))]
    pick = [p for p in pairs if rng.random() < frac]
    cw = [p for p in pick if rng.random() < 0.5]
    ccw = [p for p in pick if p not in cw]
    tmp = Path(out)
    n = len(rotate_pairs(cw, tmp / "cw_tmp", clockwise=True)) + len(rotate_pairs(ccw, tmp / "ccw_tmp", clockwise=False))
    (tmp / "images" / "train").mkdir(parents=True, exist_ok=True)
    (tmp / "labels" / "train").mkdir(parents=True, exist_ok=True)
    for d in ("cw_tmp", "ccw_tmp"):
        for f in (tmp / d / "images").glob("*"):
            f.rename(tmp / "images" / "train" / f"{d[:2]}_{f.name}")
        for f in (tmp / d / "labels").glob("*"):
            f.rename(tmp / "labels" / "train" / f"{d[:2]}_{f.name}")
    return n


def train_next(*, base: str, oi_root: str, synth_root: str, kr_dirs: list[str], out_dir: str,
               epochs: int = 20, name: str = "plate_v003", extra_train: list[str] = ()) -> str:
    """이어 학습. 검증은 Open Images 검증 + 한국 데이터의 test 분할(학습에 안 씀).

    조기 종료를 끄고 마지막 가중치를 쓴다(v002 에서 해외 검증만으로 고른 best 가 한국에서 나빴다)."""
    import glob
    import shutil

    import yaml
    from ultralytics import YOLO
    trains = [f"{oi_root}/images/train", f"{synth_root}/images/train", *extra_train]
    vals = [f"{oi_root}/images/val"]
    for d in kr_dirs:
        for p in glob.glob(f"{d}/*/images"):
            (vals if "/test/" in p + "/" else trains).append(p)
    cfg = {"path": "/", "train": trains, "val": vals, "names": {0: "plate"}}
    yp = f"/content/{name}.yaml"
    yaml.safe_dump(cfg, open(yp, "w"), allow_unicode=True)
    print("학습:", trains, "\n검증:", vals)
    YOLO(base).train(data=yp, epochs=epochs, imgsz=640, batch=16, workers=2, project="/content/runs", name=name,
                     exist_ok=True, patience=0, verbose=False, plots=False)
    last = f"/content/runs/{name}/weights/last.pt"
    YOLO(last).export(format="onnx", imgsz=640)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    shutil.copy(last, f"{out_dir}/best.pt")
    shutil.copy(last.replace(".pt", ".onnx"), f"{out_dir}/best.onnx")
    return f"{out_dir}/best.onnx"
