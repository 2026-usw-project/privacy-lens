"""VISPR-redactions — 일상 사진 속 개인정보 위치 라벨(Orekondy et al., CVPR 2018).

왜: 교수님 피드백(2026-11-04) — 목표는 '일부러 넣은 개인정보'가 아니라 일상 사진에 자연스럽게 찍힌 개인정보를 잡는 것.
이 데이터는 Flickr 에 사람들이 올린 일상 사진 8,473장에 개인정보 24종의 위치(다각형)를 단 것이다.

    라벨: CC BY-NC 4.0(비상업). 사진: 원래 Flickr 라이선스 → 드라이브·런타임에만 두고 저장소·발표 자료에 넣지 않는다.
    받기: datasets.d2.mpi-inf.mpg.de (등록 없음). 사진 train 7.3GB, val 2.9GB, test 5.2GB.
    한계: 해외 사진(영어 글자, 외국 신분증·번호판). 한국 사진 성능은 팀 실사로 따로 잰다.

라벨 형식(공식 평가 코드 기준): json['annotations'] = {image_id: {image_path, image_height, image_width,
attributes: [{attr_id, instance_id, polygons | segmentation, ...}]}}.

    python -m vision.redactions download <폴더> [train val test]   # Colab
    python -m vision.redactions yolo <폴더> <출력>                   # 물체형 클래스 → YOLO 데이터
    python -m vision.redactions eval <폴더> [장수]                   # 지금 서비스(analyze)가 일상 사진에서 무엇을 찾나
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

BASE = "https://datasets.d2.mpi-inf.mpg.de/orekondy18cvpr/v1"
SPLITS = ("train2017", "val2017", "test2017")

# 개인정보 24종(+무시 4종). 한국어 이름은 결과 표에 쓴다.
ATTR_KO = {
    "a105_face_all": "얼굴", "a108_license_plate_all": "번호판", "a109_person_body": "사람",
    "a110_nudity_all": "노출", "a26_handwriting": "손글씨", "a39_disability_physical": "신체 장애",
    "a43_medicine": "의료", "a7_fingerprint": "지문", "a8_signature": "서명",
    "a29_ausweis": "신분증", "a30_credit_card": "신용카드", "a31_passport": "여권", "a32_drivers_license": "운전면허증",
    "a33_student_id": "학생증", "a35_mail": "우편물", "a37_receipt": "영수증", "a38_ticket": "티켓",
    "a106_address_current_all": "현재 주소", "a107_address_home_all": "집 주소", "a111_name_all": "이름",
    "a24_birth_date": "생년월일", "a49_phone": "전화번호", "a73_landmark": "랜드마크·표지판",
    "a82_date_time": "날짜·시간", "a90_email": "이메일",
}
IGNORE = {"a70_education_history", "a18_ethnic_clothing", "a85_username"}

# YOLO 로 학습할 물체형 묶음. 기존 문서 클래스(vision/classes.py)와 이름을 맞춘다.
GROUPS = {
    "id_card": ["a29_ausweis", "a31_passport", "a32_drivers_license", "a33_student_id"],
    "card": ["a30_credit_card"],
    "waybill": ["a35_mail"],          # 우편물·봉투·송장
    "receipt": ["a37_receipt"],
    "ticket": ["a38_ticket"],
}


def download(root: Path, splits=SPLITS, *, images: bool = True, keep: Path | None = None) -> None:
    """Colab 용. 라벨 json 과 사진 tar 를 받아 root/annotations, root/images/<split> 에 둔다.
    keep(드라이브 폴더)을 주면 tar 를 거기에 먼저 받아 두어, 런타임이 끊겨도 다시 받지 않는다."""
    root = Path(root)
    (root / "annotations").mkdir(parents=True, exist_ok=True)
    for sp in splits:
        js = root / "annotations" / f"{sp}.json"
        if not js.exists():
            subprocess.run(["curl", "-sSfL", "-o", str(js), f"{BASE}/annotations/{sp}.json"], check=True)
        if images and not (root / "images" / sp).exists():
            (root / "images").mkdir(exist_ok=True)
            if keep:
                tar = Path(keep) / f"{sp}.tar.gz"
                if not tar.exists():
                    print(f"{sp} 사진 받는 중(드라이브에 보관)…", flush=True)
                    tar.parent.mkdir(parents=True, exist_ok=True)
                    subprocess.run(["curl", "-sSfL", "-o", str(tar) + ".part", f"{BASE}/images/{sp}.tar.gz"], check=True)
                    Path(str(tar) + ".part").rename(tar)
                print(f"{sp} 사진 푸는 중…", flush=True)
                subprocess.run(["tar", "xzf", str(tar), "-C", str(root / "images")], check=True)
            else:
                print(f"{sp} 사진 받는 중…", flush=True)
                subprocess.run(f"curl -sSfL {BASE}/images/{sp}.tar.gz | tar xz -C {root / 'images'}", shell=True,
                               check=True)


# ------------------------------------------------------------------ 읽기

def _box(gt: dict, W: int, H: int) -> tuple[float, float, float, float] | None:
    """(x, y, w, h). bbox → 다각형 → RLE 순서로 쓴다."""
    if gt.get("bbox"):
        x, y, w, h = gt["bbox"]
        return float(x), float(y), float(w), float(h)
    polys = gt.get("polygons") or []
    xs = [p[i] for p in polys for i in range(0, len(p) - 1, 2)]
    ys = [p[i + 1] for p in polys for i in range(0, len(p) - 1, 2)]
    if xs and ys:
        x0, y0 = max(0.0, min(xs)), max(0.0, min(ys))
        x1, y1 = min(float(W), max(xs)), min(float(H), max(ys))
        return x0, y0, x1 - x0, y1 - y0
    seg = gt.get("segmentation")
    if seg:
        from pycocotools import mask as mu
        if isinstance(seg.get("counts"), str):
            seg = dict(seg, counts=seg["counts"].encode())
        x, y, w, h = mu.toBbox(seg).tolist()
        return x, y, w, h
    return None


def load(anno_json: Path) -> list[dict]:
    """[{image_id, name, W, H, insts: [(attr_id, (x, y, w, h)), ...]}]"""
    data = json.load(open(anno_json))["annotations"]
    out = []
    for image_id, e in data.items():
        W, H = int(e["image_width"]), int(e["image_height"])
        insts = []
        for gt in e.get("attributes", []):
            a = gt.get("attr_id")
            if a in IGNORE or a not in ATTR_KO:
                continue
            b = _box(gt, W, H)
            if b and b[2] >= 2 and b[3] >= 2:
                insts.append((a, b))
        out.append({"image_id": image_id, "name": Path(e.get("image_path", image_id + ".jpg")).name,
                    "W": W, "H": H, "insts": insts})
    return out


def find_image(images_root: Path, name: str) -> Path | None:
    for p in (images_root / name, *images_root.glob(f"*/{name}")):
        if p.exists():
            return p
    return None


# ------------------------------------------------------------------ YOLO 데이터

def to_yolo(root: Path, out: Path, *, groups: dict = GROUPS, splits=("train2017", "val2017"),
            keep_empty: float = 0.15, seed: int = 0) -> dict:
    """물체형 묶음만 YOLO 라벨로. 해당 물체가 없는 사진은 keep_empty 비율만 배경으로 남긴다."""
    root, out = Path(root), Path(out)
    rng = random.Random(seed)
    names = list(groups)
    to_cls = {a: i for i, g in enumerate(names) for a in groups[g]}
    counts: dict = defaultdict(int)
    for sp in splits:
        tag = "train" if sp.startswith("train") else "val"
        (out / "images" / tag).mkdir(parents=True, exist_ok=True)
        (out / "labels" / tag).mkdir(parents=True, exist_ok=True)
        for r in load(root / "annotations" / f"{sp}.json"):
            lines = []
            for a, (x, y, w, h) in r["insts"]:
                if a in to_cls:
                    lines.append(f"{to_cls[a]} {(x + w / 2) / r['W']:.6f} {(y + h / 2) / r['H']:.6f} "
                                 f"{w / r['W']:.6f} {h / r['H']:.6f}")
                    counts[f"{tag}:{names[to_cls[a]]}"] += 1
            if not lines and rng.random() > keep_empty:
                continue
            img = find_image(root / "images" / sp, r["name"]) or find_image(root / "images", r["name"])
            if img is None:
                counts["사진 없음"] += 1
                continue
            dst = out / "images" / tag / img.name
            if not dst.exists():
                dst.symlink_to(img.resolve())
            (out / "labels" / tag / (img.stem + ".txt")).write_text("\n".join(lines) + ("\n" if lines else ""))
            counts[f"{tag}:사진"] += 1
    (out / "data.yaml").write_text(
        f"path: {out}\ntrain: images/train\nval: images/val\nnames:\n" +
        "".join(f"  {i}: {n}\n" for i, n in enumerate(names)))
    return dict(counts)


# ------------------------------------------------------------------ 지금 서비스 평가

def _hit(gt, boxes) -> bool:
    """찾은 상자 중 하나가 정답과 IoU 0.3 이상이거나, 서로의 중심을 덮으면 찾은 것으로 본다.

    글자 개인정보는 서비스가 단어 단위로 찾고 정답은 줄·영역 단위라 IoU 만으로는 너무 엄하다."""
    gx, gy, gw, gh = gt
    gcx, gcy = gx + gw / 2, gy + gh / 2
    for (x, y, w, h) in boxes:
        ix = max(0.0, min(gx + gw, x + w) - max(gx, x))
        iy = max(0.0, min(gy + gh, y + h) - max(gy, y))
        inter = ix * iy
        union = gw * gh + w * h - inter
        if union > 0 and inter / union >= 0.3:
            return True
        cx, cy = x + w / 2, y + h / 2
        if gx <= cx <= gx + gw and gy <= cy <= gy + gh:
            return True
        if x <= gcx <= x + w and y <= gcy <= y + h:
            return True
    return False


def evaluate_service(root: Path, *, split: str = "test2017", limit: int | None = 300, seed: int = 0,
                     analyze_fn=None) -> dict:
    """지금 서비스(pipeline.analyze, 규칙 기반)가 일상 사진의 개인정보를 몇 % 찾는지. 개인정보 종류별 재현율.

    오탐은 재지 않는다(정답에 없는 것도 개인정보일 수 있어 이 데이터로는 정밀도를 공정하게 못 잰다)."""
    from PIL import Image
    root = Path(root)
    if analyze_fn is None:
        from pipeline.analyze import analyze
        analyze_fn = analyze
    recs = [r for r in load(root / "annotations" / f"{split}.json") if r["insts"]]
    random.Random(seed).shuffle(recs)
    recs = recs[:limit] if limit else recs
    tot: dict = defaultdict(int)
    hit: dict = defaultdict(int)
    kinds: dict = defaultdict(lambda: defaultdict(int))
    for k, r in enumerate(recs):
        img = find_image(root / "images" / split, r["name"]) or find_image(root / "images", r["name"])
        if img is None:
            continue
        im = Image.open(img).convert("RGB")
        if im.size != (r["W"], r["H"]):   # 라벨 크기와 다르면 좌표를 맞춘다
            im = im.resize((r["W"], r["H"]))
        rep = analyze_fn(im)
        found = [(f.kind, (f.box.x, f.box.y, f.box.w, f.box.h)) for f in rep.findings if f.box]
        for a, b in r["insts"]:
            tot[a] += 1
            got = [kd for kd, fb in found if _hit(b, [fb])]
            if got:
                hit[a] += 1
                for kd in set(got):
                    kinds[a][kd] += 1
        if (k + 1) % 25 == 0:
            print(f"{k + 1}/{len(recs)}", flush=True)
    rows = []
    for a in sorted(tot, key=lambda a: -tot[a]):
        rows.append({"attr": a, "이름": ATTR_KO.get(a, a), "정답": tot[a], "찾음": hit[a],
                     "재현율": round(hit[a] / tot[a], 3),
                     "찾은 항목": dict(sorted(kinds[a].items(), key=lambda kv: -kv[1])[:3])})
    return {"split": split, "images": len(recs), "rows": rows}


def table(res: dict) -> str:
    lines = [f"VISPR-redactions {res['split']} {res['images']}장 — 종류별로 찾은 비율",
             f"{'종류':<10} {'정답':>5} {'찾음':>5} {'재현율':>6}  주로 찾은 항목"]
    for r in res["rows"]:
        lines.append(f"{r['이름']:<10} {r['정답']:>5} {r['찾음']:>5} {r['재현율']:>6.2f}  {r['찾은 항목']}")
    return "\n".join(lines)


if __name__ == "__main__":
    cmd, *rest = sys.argv[1:] or ["help"]
    if cmd == "download":
        download(Path(rest[0]), rest[1:] or SPLITS)
    elif cmd == "yolo":
        print(to_yolo(Path(rest[0]), Path(rest[1])))
    elif cmd == "eval":
        res = evaluate_service(Path(rest[0]), limit=int(rest[1]) if len(rest) > 1 else 300)
        print(table(res))
        out = Path(rest[0]) / "eval_service.json"
        out.write_text(json.dumps(res, ensure_ascii=False, indent=1))
        print("저장:", out)
    else:
        print(__doc__)
