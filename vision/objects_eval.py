"""이미지 객체(얼굴·번호판) 평가 — 기준값을 바꿔 가며 정밀도·재현율을 잰다.

처음 잰 YuNet 정밀도 0.606(2026-11-02)은 평가 방식 때문에 낮게 나왔다.
  - 20px 미만 얼굴을 정답에서 뺐는데, 그 얼굴을 찾은 것까지 오탐으로 셌다
  - Open Images 의 '여러 얼굴을 한 상자로 묶은 라벨'(IsGroupOf) 안의 얼굴도 오탐으로 셌다
여기서는 이런 것을 '무시'로 따로 세고(COCO·WIDER 평가와 같은 방식), 점수 기준을 바꿔 가며 잰다.

    정답 한 개 = GT(box, ignore)   ignore=True 면 맞혀도 틀려도 세지 않는다
    예측 한 개 = Pred(box, score)

Colab 노트북(vision/colab_objects.ipynb 7~9번 칸)이 이 파일을 쓴다. 사진은 저장소에 넣지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pipeline.objects import _iou
from pipeline.types import Box

IOU = 0.5


@dataclass
class GT:
    box: Box
    ignore: bool = False


@dataclass
class Pred:
    box: Box
    score: float


def _center_in(p: Box, g: Box) -> bool:
    cx, cy = p.x + p.w / 2, p.y + p.h / 2
    return g.x <= cx <= g.x + g.w and g.y <= cy <= g.y + g.h


def match(gts: list[GT], preds: list[Pred], *, thr: float, min_size: int = 0) -> tuple[int, int, int]:
    """한 사진의 (맞힘, 놓침, 오탐). 점수 thr 미만·min_size 미만 예측은 버린다."""
    care = [g for g in gts if not g.ignore and min(g.box.w, g.box.h) >= min_size]
    skip = [g for g in gts if g.ignore or min(g.box.w, g.box.h) < min_size]
    used: set[int] = set()
    tp = fp = 0
    for p in sorted((p for p in preds if p.score >= thr), key=lambda p: -p.score):
        if min(p.box.w, p.box.h) < min_size:
            continue
        best, bi = 0.0, -1
        for i, g in enumerate(care):
            if i not in used:
                v = _iou(p.box, g.box)
                if v > best:
                    best, bi = v, i
        if best >= IOU:
            used.add(bi); tp += 1
        elif any(_iou(p.box, g.box) >= 0.3 or _center_in(p.box, g.box) for g in skip):
            continue  # 묶음 라벨·작은 얼굴을 찾은 것: 세지 않음
        else:
            fp += 1
    return tp, len(care) - len(used), fp


def sweep(samples: list[tuple[list[GT], list[Pred]]], thresholds, *, min_size: int = 0) -> list[dict]:
    """기준값마다 정밀도·재현율·F1."""
    rows = []
    for t in thresholds:
        tp = fn = fp = 0
        for gts, preds in samples:
            a, b, c = match(gts, preds, thr=t, min_size=min_size)
            tp += a; fn += b; fp += c
        p = tp / max(1, tp + fp)
        r = tp / max(1, tp + fn)
        rows.append({"thr": round(float(t), 3), "min_size": min_size, "tp": tp, "fn": fn, "fp": fp,
                     "precision": round(p, 4), "recall": round(r, 4),
                     "f1": round(2 * p * r / max(1e-9, p + r), 4)})
    return rows


def pick(rows: list[dict], *, min_precision: float = 0.85) -> dict:
    """정밀도가 min_precision 이상인 것 중 재현율이 가장 높은 기준. 없으면 F1 최대."""
    ok = [r for r in rows if r["precision"] >= min_precision]
    return max(ok, key=lambda r: (r["recall"], r["precision"])) if ok else max(rows, key=lambda r: r["f1"])


def table(rows: list[dict]) -> str:
    out = [f"{'기준':>6} {'최소px':>6} {'정밀도':>7} {'재현율':>7} {'F1':>6} {'맞힘':>5} {'놓침':>5} {'오탐':>5}"]
    for r in rows:
        out.append(f"{r['thr']:>6} {r['min_size']:>6} {r['precision']:>7} {r['recall']:>7} {r['f1']:>6} "
                   f"{r['tp']:>5} {r['fn']:>5} {r['fp']:>5}")
    return "\n".join(out)


# ------------------------------------------------------------------ 읽기

def yolo_labels(label: Path, W: int, H: int) -> list[GT]:
    """YOLO txt(클래스 무시, 모두 한 종류로) → 정답."""
    out = []
    for line in (label.read_text().splitlines() if label.exists() else []):
        parts = line.split()
        if len(parts) < 5:
            continue
        if len(parts) > 5:  # 다각형 라벨이면 외곽 상자로
            xs, ys = [float(v) for v in parts[1::2]], [float(v) for v in parts[2::2]]
            x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
            cx, cy, w, h = (x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0
        else:
            cx, cy, w, h = map(float, parts[1:5])
        out.append(GT(Box(int((cx - w / 2) * W), int((cy - h / 2) * H), int(w * W), int(h * H))))
    return out


def yolo_pairs(root: Path) -> list[tuple[Path, Path]]:
    """폴더 아래 모든 images/*.jpg 와 짝인 labels/*.txt."""
    pairs = []
    for img in sorted(root.rglob("*")):
        if img.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp") and "images" in img.parts:
            parts = list(img.parts)
            i = len(parts) - 1 - parts[::-1].index("images")
            parts[i] = "labels"
            pairs.append((img, Path(*parts).with_suffix(".txt")))
    return pairs


def roboflow_originals(pairs: list[tuple[Path, Path]]) -> list[tuple[Path, Path]]:
    """Roboflow 내보내기에서 같은 원본을 늘린 사진(이름_jpg.rf.<해시>)은 하나만 남긴다.

    학습 분할만 늘려 두므로 평가에 그대로 쓰면 같은 장면을 여러 번 센다."""
    seen, out = set(), []
    for img, lab in pairs:
        key = img.name.split(".rf.")[0]
        if key not in seen:
            seen.add(key)
            out.append((img, lab))
    return out


def recall_by_size(samples: list[tuple[list[GT], list[Pred]]], *, thr: float,
                   bins=(0, 16, 32, 64, 10**9)) -> list[dict]:
    """정답 상자의 짧은 변 크기 구간별 재현율. 작은 것을 놓치는지 본다."""
    rows = []
    for lo, hi in zip(bins, bins[1:]):
        hit = tot = 0
        for gts, preds in samples:
            ps = [p for p in preds if p.score >= thr]
            for g in gts:
                if g.ignore or not (lo <= min(g.box.w, g.box.h) < hi):
                    continue
                tot += 1
                hit += any(_iou(p.box, g.box) >= IOU for p in ps)
        rows.append({"size": f"{lo}~{hi if hi < 10**9 else ''}px", "total": tot,
                     "recall": round(hit / tot, 4) if tot else None})
    return rows


def predict_plates(model_path, pairs: list[tuple[Path, Path]], *, conf: float = 0.05,
                   imgsz: int = 640) -> list[tuple[list[GT], list[Pred]]]:
    """YOLO 번호판 모델로 (정답, 예측) 목록을 만든다. 우리 모델(.pt/.onnx)만 넣는다(남의 .pt 금지)."""
    from PIL import Image
    from ultralytics import YOLO
    m = YOLO(str(model_path), task="detect")
    out = []
    for img, lab in pairs:
        im = Image.open(img).convert("RGB")
        W, H = im.size
        r = m.predict(im, conf=conf, imgsz=imgsz, verbose=False)[0]
        preds = [Pred(Box(int(a), int(b), int(c - a), int(d - b)), float(p))
                 for p, (a, b, c, d) in zip(r.boxes.conf.tolist(), r.boxes.xyxy.tolist())]
        out.append((yolo_labels(lab, W, H), preds))
    return out


def size_report(samples, *, thr: float = 0.4) -> str:
    rows = sweep(samples, [0.3, 0.4, 0.5])
    return table(rows) + "\n크기별 재현율: " + ", ".join(
        f"{r['size']} {r['recall']}({r['total']})" for r in recall_by_size(samples, thr=thr))


def split_orientation(pairs: list[tuple[Path, Path]]) -> tuple[list, list]:
    """사진을 (바로 선 것, 옆으로 누운 것)으로 나눈다. 번호판 상자가 세로로 길면 사진이 90도 누운 것으로 본다.

    hyunjin 평가 사진 207장 중 일부는 휴대폰 회전 정보(EXIF)가 빠진 채 누워 있다(2026-11-03 확인:
    EXIF 회전 정보 0장, 번호판 259개 중 75개가 세로로 김). 서비스는 EXIF 를 적용하므로 이런 사진은 바로 서서 들어온다."""
    from PIL import Image
    up, side = [], []
    for img, lab in pairs:
        W, H = Image.open(img).size
        gts = yolo_labels(lab, W, H)
        (side if any(g.box.h > g.box.w for g in gts) else up).append((img, lab))
    return up, side


def rotate_pairs(pairs: list[tuple[Path, Path]], out: Path, *, clockwise: bool = True) -> list[tuple[Path, Path]]:
    """사진과 YOLO 라벨을 함께 90도 돌려 out/images, out/labels 에 쓴다."""
    from PIL import Image
    (out / "images").mkdir(parents=True, exist_ok=True)
    (out / "labels").mkdir(parents=True, exist_ok=True)
    res = []
    for img, lab in pairs:
        im = Image.open(img)
        im = im.transpose(Image.ROTATE_270 if clockwise else Image.ROTATE_90)
        lines = []
        for line in (lab.read_text().splitlines() if lab.exists() else []):
            p = line.split()
            if len(p) < 5:
                continue
            cx, cy, w, h = map(float, p[1:5])
            ncx, ncy = (1 - cy, cx) if clockwise else (cy, 1 - cx)
            lines.append(f"{p[0]} {ncx:.6f} {ncy:.6f} {h:.6f} {w:.6f}")
        ni, nl = out / "images" / img.name, out / "labels" / (img.stem + ".txt")
        im.save(ni)
        nl.write_text("\n".join(lines) + ("\n" if lines else ""))
        res.append((ni, nl))
    return res
