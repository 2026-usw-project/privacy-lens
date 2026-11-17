"""한 클래스의 오탐(정답과 안 맞는 상자)이 어떤 사진 묶음·어떤 정답 물건 위에서 나오는지 센다.

    python -m vision.fp_check <데이터 폴더> <가중치> [클래스 이름] [검출 기준]

검증 분할(images/val, labels/val)만 본다. 사진·글자는 출력하지 않고 개수만 낸다.
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def _iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _labels(path: Path) -> list[tuple[int, tuple[float, float, float, float]]]:
    out = []
    if not path.exists():
        return out
    for ln in path.read_text().splitlines():
        v = ln.split()
        if len(v) < 5:
            continue
        cx, cy, w, h = map(float, v[1:5])
        out.append((int(v[0]), (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)))
    return out


def source_of(stem: str) -> str:
    """파일 이름 앞부분으로 데이터 묶음을 가른다(realcard_<zip>_… 는 zip 까지)."""
    parts = stem.split("_")
    if parts[0] == "realcard":                 # zip 이름에 _ 가 섞여 앞 네 조각까지 본다
        return "_".join(parts[:4])
    return parts[0]


def run(ds: str | Path, weights: str, cls_name: str = "id_card", conf: float = 0.6, batch: int = 32) -> dict:
    from ultralytics import YOLO

    ds = Path(ds)
    m = YOLO(weights)
    names = {int(k): v for k, v in m.names.items()}
    cid = next(k for k, v in names.items() if v == cls_name)
    imgs = sorted(p for p in (ds / "images" / "val").iterdir() if p.suffix.lower() in IMG_EXT)
    tp = fp = gt_total = missed = 0
    on_gt: collections.Counter = collections.Counter()      # 오탐이 겹친 정답 물건
    fp_src: collections.Counter = collections.Counter()     # 오탐이 나온 사진 묶음
    miss_src: collections.Counter = collections.Counter()   # 놓친 정답이 있던 사진 묶음
    for i in range(0, len(imgs), batch):
        part = imgs[i:i + batch]
        for p, r in zip(part, m.predict([str(x) for x in part], imgsz=640, conf=conf, verbose=False)):
            gts = _labels(ds / "labels" / "val" / (p.stem + ".txt"))
            mine = [g for c, g in gts if c == cid]
            gt_total += len(mine)
            hit = set()
            for c, box in zip(r.boxes.cls.tolist(), r.boxes.xyxyn.tolist()):
                if int(c) != cid:
                    continue
                best_same = max(((_iou(box, g), k) for k, g in enumerate(mine)), default=(0.0, -1))
                if best_same[0] >= 0.5 and best_same[1] not in hit:
                    tp += 1
                    hit.add(best_same[1])
                    continue
                fp += 1
                fp_src[source_of(p.stem)] += 1
                other = max(((_iou(box, g), c2) for c2, g in gts if c2 != cid), default=(0.0, -1))
                on_gt["배경" if other[0] < 0.3 else names.get(other[1], str(other[1]))] += 1
            for k in range(len(mine)):
                if k not in hit:
                    missed += 1
                    miss_src[source_of(p.stem)] += 1
    return {
        "클래스": cls_name, "기준": conf, "정답": gt_total, "맞음": tp, "오탐": fp, "놓침": missed,
        "오탐이 겹친 정답": dict(on_gt.most_common()),
        "오탐 사진 묶음": dict(fp_src.most_common()),
        "놓친 사진 묶음": dict(miss_src.most_common()),
    }


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) < 2:
        sys.exit(__doc__)
    print(json.dumps(run(a[0], a[1], *(a[2:3] or ["id_card"]), *(map(float, a[3:4]))), ensure_ascii=False, indent=1))
