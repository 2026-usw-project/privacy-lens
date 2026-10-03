"""
가짜 문서를 배경 사진에 합성해 데모·테스트용 사진을 만듭니다.

  python -m data.synth.compose --n 15 --out data/demo            # 기본 합성 배경
  python -m data.synth.compose --n 15 --bg-dir 내배경폴더 --out data/demo   # 실제 책상 사진을 배경으로

출력
  data/demo/img_000.jpg ...         합성 사진 (일부는 가짜 GPS EXIF 포함)
  data/demo/truth.json              정답 (문서 종류 · 박스 · 개인정보 값)  → data/eval.py 가 사용
  data/demo/labels/img_000.txt      YOLO 형식 라벨 (클래스 인덱스 = schema/classes.txt 순서)
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import cv2
import numpy as np
import piexif
from PIL import Image, ImageDraw, ImageFilter

from . import fake, templates

CLASSES = (Path(__file__).parents[2] / "schema/classes.txt").read_text().split()
OUT_W, OUT_H = 4032, 3024


# ── 배경 ───────────────────────────────────────────────
def synthetic_background(rng: random.Random) -> Image.Image:
    """책상 느낌의 배경 + 개인정보가 아닌 방해 요소(책 표지, 머그컵)"""
    base = np.array([rng.randint(120, 190), rng.randint(90, 150), rng.randint(60, 110)], np.float32)
    grad = np.linspace(0.85, 1.1, OUT_W, dtype=np.float32)[None, :, None]
    noise = np.random.default_rng(rng.randint(0, 1 << 30)).normal(0, 6, (OUT_H, OUT_W, 1)).astype(np.float32)
    # 나뭇결
    grain = (np.sin(np.linspace(0, rng.uniform(40, 90), OUT_H))[:, None, None] * 8).astype(np.float32)
    arr = np.clip(base * grad + noise + grain, 0, 255).astype(np.uint8)
    im = Image.fromarray(arr)
    g = ImageDraw.Draw(im)
    # 방해 요소 1: 책 표지 (오탐 테스트용 — 개인정보 아님)
    bx, by = rng.randint(200, 1400), rng.randint(200, 1200)
    g.rectangle([bx, by, bx + 900, by + 1200], fill=(rng.randint(30, 200), 40, 90))
    g.text((bx + 60, by + 120), "파이썬 프로그래밍", font=templates.font(90), fill="white")
    g.text((bx + 60, by + 260), "개정 3판", font=templates.font(60), fill="white")
    # 방해 요소 2: 머그컵
    mx, my = rng.randint(2600, 3400), rng.randint(200, 900)
    g.ellipse([mx, my, mx + 500, my + 500], fill=(240, 240, 235), outline=(200, 200, 200), width=12)
    return im


def load_background(bg_files: list[Path], rng: random.Random) -> Image.Image:
    if not bg_files:
        return synthetic_background(rng)
    im = Image.open(rng.choice(bg_files)).convert("RGB")
    return im.resize((OUT_W, OUT_H))


# ── 왜곡 + 붙여넣기 ─────────────────────────────────────
def warp_paste(bg: np.ndarray, doc: Image.Image, target_w: int, rng: random.Random) -> list[list[float]]:
    """원근 왜곡한 문서를 bg 위에 붙이고, 붙인 네 꼭짓점을 반환"""
    d = np.array(doc)
    h, w = d.shape[:2]
    scale = target_w / w
    tw, th = target_w, int(h * scale)
    H, W = bg.shape[:2]
    x0 = rng.randint(80, W - tw - 80)
    y0 = rng.randint(80, H - th - 80)
    j = 0.08  # 꼭짓점 흔들기 비율
    dst = np.float32([
        [x0 + rng.uniform(0, j) * tw, y0 + rng.uniform(0, j) * th],
        [x0 + tw - rng.uniform(0, j) * tw, y0 + rng.uniform(0, j) * th],
        [x0 + tw - rng.uniform(0, j) * tw, y0 + th - rng.uniform(0, j) * th],
        [x0 + rng.uniform(0, j) * tw, y0 + th - rng.uniform(0, j) * th],
    ])
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    M = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(d, M, (W, H))
    mask = cv2.warpPerspective(np.full((h, w), 255, np.uint8), M, (W, H))
    # 조명 변화
    warped = np.clip(warped.astype(np.float32) * rng.uniform(0.75, 1.0), 0, 255).astype(np.uint8)
    bg[mask > 0] = warped[mask > 0]
    return dst.tolist()


def gps_exif(rng: random.Random) -> bytes:
    def dms(v: float):
        d = int(v); m = int((v - d) * 60); s = round(((v - d) * 60 - m) * 60 * 100)
        return ((d, 1), (m, 1), (s, 100))
    lat, lon = 37.20 + rng.random() * 0.1, 126.95 + rng.random() * 0.1
    exif = {
        "0th": {piexif.ImageIFD.Make: b"DemoPhone", piexif.ImageIFD.Model: b"PL-1"},
        "Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:10:01 14:22:10"},
        "GPS": {piexif.GPSIFD.GPSLatitudeRef: b"N", piexif.GPSIFD.GPSLatitude: dms(lat),
                piexif.GPSIFD.GPSLongitudeRef: b"E", piexif.GPSIFD.GPSLongitude: dms(lon)},
    }
    return piexif.dump(exif)


# ── 메인 ───────────────────────────────────────────────
def make_one(i: int, rng: random.Random, bg_files: list[Path], negative: bool) -> tuple[Image.Image, dict, bytes | None]:
    bg = np.array(load_background(bg_files, rng))
    objects = []
    if not negative:
        kinds = ["parcel"] if rng.random() < 0.6 else ["parcel", "student"]
        if rng.random() < 0.2:
            kinds = ["student"]
        for k in kinds:
            if k == "parcel":
                doc, truth = templates.parcel_label(fake.parcel(rng), with_qr=rng.random() < 0.5, rng=rng)
                tw = rng.randint(900, 1400)          # 사진 폭의 22~35%
            else:
                doc, truth = templates.student_id(fake.student_card(rng), rng)
                tw = rng.randint(450, 650)
            quad = warp_paste(bg, doc, tw, rng)
            xs, ys = [p[0] for p in quad], [p[1] for p in quad]
            truth["bbox"] = {"x1": int(min(xs)), "y1": int(min(ys)), "x2": int(max(xs)), "y2": int(max(ys))}
            objects.append(truth)
    im = Image.fromarray(bg)
    if rng.random() < 0.5:
        im = im.filter(ImageFilter.GaussianBlur(rng.uniform(0.6, 1.6)))   # 초점 흐림
    exif = gps_exif(rng) if rng.random() < 0.4 else None
    return im, {"file": f"img_{i:03d}.jpg", "negative": negative, "has_gps": exif is not None, "objects": objects}, exif


def make_hard(i: int, rng: random.Random, bg_files: list[Path]) -> tuple[Image.Image, dict]:
    """어려운 비위험 사진 — 상호·대표번호·사업장 주소·ISBN·고객센터처럼 개인정보로 오인하기 쉬운 글자만 있는 사진"""
    bg = np.array(load_background(bg_files, rng))
    for _ in range(rng.randint(1, 2)):
        doc, _truth = rng.choice(templates.HARD)(rng)
        warp_paste(bg, doc, rng.randint(700, 1100), rng)
    im = Image.fromarray(bg)
    if rng.random() < 0.5:
        im = im.filter(ImageFilter.GaussianBlur(rng.uniform(0.6, 1.6)))
    return im, {"file": f"img_{i:03d}.jpg", "negative": True, "hard": True, "has_gps": False, "objects": []}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=15)
    ap.add_argument("--neg", type=int, default=3, help="개인정보 없는 사진 수 (오탐 측정용)")
    ap.add_argument("--hard", type=int, default=0, help="어려운 비위험 사진 수 (상호·대표번호 등). 0이면 기존과 같은 사진만 만듦")
    ap.add_argument("--out", default="data/demo")
    ap.add_argument("--bg-dir", default=None)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()

    rng = random.Random(a.seed)
    out = Path(a.out); (out / "labels").mkdir(parents=True, exist_ok=True)
    bg_files = sorted(Path(a.bg_dir).glob("*.jp*g")) if a.bg_dir else []
    truths = []
    for i in range(a.n + a.neg):
        im, t, exif = make_one(i, rng, bg_files, negative=i >= a.n)
        kw = {"quality": rng.randint(80, 92)}
        if exif:
            kw["exif"] = exif
        im.save(out / t["file"], **kw)
        with open(out / "labels" / t["file"].replace(".jpg", ".txt"), "w") as f:
            for o in t["objects"]:
                b = o["bbox"]
                cx, cy = (b["x1"] + b["x2"]) / 2 / OUT_W, (b["y1"] + b["y2"]) / 2 / OUT_H
                bw, bh = (b["x2"] - b["x1"]) / OUT_W, (b["y2"] - b["y1"]) / OUT_H
                f.write(f"{CLASSES.index(o['label'])} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}\n")
        truths.append(t)
        print("wrote", t["file"], [o["label"] for o in t["objects"]], "GPS" if t["has_gps"] else "")
    rng_h = random.Random(a.seed + 1000)          # 별도 난수 — --hard 를 줘도 앞쪽 사진은 그대로
    for j in range(a.hard):
        im, t = make_hard(a.n + a.neg + j, rng_h, bg_files)
        im.save(out / t["file"], quality=rng_h.randint(80, 92))
        (out / "labels" / t["file"].replace(".jpg", ".txt")).write_text("")
        truths.append(t)
        print("wrote", t["file"], "hard-negative")
    (out / "truth.json").write_text(json.dumps(truths, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
