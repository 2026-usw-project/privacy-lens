"""합성 사진으로 첫 모델을 만든다(초벌 라벨용 부트스트랩).

실사가 몇 장 없을 때 모델이 아무것도 못 그리면 초벌 라벨이 의미가 없다.
가상 송장·학생증을 배경에 원근 변환으로 붙이면 꼭짓점 좌표를 알고 있으니
라벨이 자동으로 나온다. 이걸로 첫 모델을 학습해 초벌 라벨을 시작한다.

합성 사진은 **학습(train)에만** 들어간다. 점수는 실사 val/test 로만 잰다.
실사가 충분히 모이면 `--synth-ratio` 를 줄이거나 빼도 된다.
"""

from __future__ import annotations

import datetime as dt
import random
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .workspace import DONE, Row, Workspace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from samples.fonts import find_korean_font  # noqa: E402
from samples.make_sample import make_waybill  # noqa: E402

FONT, FONT_BOLD = find_korean_font()
WAYBILL, ID_CARD, FACE, CODE = 0, 1, 4, 5

SCHOOLS = ["한빛대학교", "새솔대학교", "가람대학교", "누리대학교"]
DEPTS = ["정보보호학과", "컴퓨터학부", "경영학과", "디자인학과"]
NAMES = ["김서연", "이민준", "박지우", "최도윤", "정하은", "강시우"]
DISTRACT = ["노트북", "회의 자료", "2026 다이어리", "COFFEE", "책상 정리", "SALE 30%", "메모"]


def _font(size: int, bold: bool = False):
    return ImageFont.truetype(FONT_BOLD if bold else FONT, size)


def make_id_card(rng: random.Random) -> tuple[Image.Image, list[tuple[int, list]]]:
    """가상 학생증. 카드 안 증명사진·바코드 위치도 함께 돌려준다."""
    W, H = 640, 400
    color = rng.choice([(28, 70, 140), (20, 110, 90), (130, 40, 50), (60, 60, 70)])
    img = Image.new("RGB", (W, H), (248, 248, 246))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 78], fill=color)
    d.text((24, 20), rng.choice(SCHOOLS), font=_font(30, True), fill=(255, 255, 255))
    d.text((W - 150, 30), "STUDENT ID", font=_font(18), fill=(230, 230, 240))
    # 증명사진 자리: 실루엣만 그린다(실제 얼굴 사용 안 함)
    px, py, pw, ph = 30, 105, 150, 190
    d.rectangle([px, py, px + pw, py + ph], fill=(205, 212, 222))
    d.ellipse([px + 45, py + 30, px + 105, py + 95], fill=(150, 158, 170))
    d.ellipse([px + 20, py + 105, px + 130, py + 230], fill=(150, 158, 170))
    d.rectangle([px, py + ph, px + pw, py + ph + 10], fill=(248, 248, 246))
    d.text((210, 115), "성명", font=_font(18), fill=(110, 110, 115))
    d.text((280, 108), rng.choice(NAMES), font=_font(30, True), fill=(20, 20, 24))
    d.text((210, 165), "학과", font=_font(18), fill=(110, 110, 115))
    d.text((280, 162), rng.choice(DEPTS), font=_font(22), fill=(20, 20, 24))
    d.text((210, 210), "학번", font=_font(18), fill=(110, 110, 115))
    d.text((280, 207), f"20{rng.randint(19, 26)}{rng.randint(10000, 99999)}", font=_font(22), fill=(20, 20, 24))
    # 바코드
    bx, by, bw, bh = 210, 300, 380, 70
    x = bx
    while x < bx + bw:
        w = rng.choice([2, 3, 4, 6])
        if rng.random() < 0.55:
            d.rectangle([x, by, x + w - 1, by + bh], fill=(15, 15, 15))
        x += w
    parts = [(FACE, [px, py, px + pw, py + ph]), (CODE, [bx, by, bx + bw, by + bh])]
    return img, parts


def _background(rng: random.Random, W: int, H: int) -> Image.Image:
    base = np.array(rng.choice([(96, 84, 72), (180, 170, 150), (60, 64, 70), (210, 205, 198),
                                (120, 95, 70)]), np.float32)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    grad = (xx / W - 0.5) * rng.uniform(-40, 40) + (yy / H - 0.5) * rng.uniform(-40, 40)
    stripes = np.sin(yy / rng.uniform(8, 40)) * rng.uniform(0, 12)
    noise = np.random.default_rng(rng.randint(0, 1 << 30)).normal(0, 6, (H, W))
    arr = np.clip(base[None, None, :] + (grad + stripes + noise)[..., None], 0, 255).astype(np.uint8)
    img = Image.fromarray(arr)
    d = ImageDraw.Draw(img)
    for _ in range(rng.randint(0, 4)):  # 개인정보 아닌 글자·물건(오탐 연습)
        x, y = rng.randint(0, W - 300), rng.randint(0, H - 120)
        if rng.random() < 0.5:
            d.rectangle([x, y, x + rng.randint(150, 400), y + rng.randint(100, 300)],
                        fill=tuple(rng.randint(30, 230) for _ in range(3)))
        d.text((x + 10, y + 10), rng.choice(DISTRACT), font=_font(rng.randint(20, 48)),
               fill=tuple(rng.randint(0, 255) for _ in range(3)))
    return img


def _paste(bg: np.ndarray, obj: Image.Image, rng: random.Random, scale: float):
    """원근 변환으로 붙이고 변환 행렬을 돌려준다."""
    H, W = bg.shape[:2]
    ow, oh = obj.size
    tw = ow * scale
    th = oh * scale
    cx = rng.uniform(tw * 0.6, W - tw * 0.6)
    cy = rng.uniform(th * 0.6, H - th * 0.6)
    ang = np.deg2rad(rng.uniform(-35, 35) + (180 if rng.random() < 0.08 else 0))
    corners = np.array([[-tw / 2, -th / 2], [tw / 2, -th / 2], [tw / 2, th / 2], [-tw / 2, th / 2]])
    rot = np.array([[np.cos(ang), -np.sin(ang)], [np.sin(ang), np.cos(ang)]])
    dst = corners @ rot.T + [cx, cy]
    dst += np.array([[rng.uniform(-1, 1) * tw * 0.06, rng.uniform(-1, 1) * th * 0.06] for _ in range(4)])
    src = np.float32([[0, 0], [ow, 0], [ow, oh], [0, oh]])
    M = cv2.getPerspectiveTransform(src, dst.astype(np.float32))
    warped = cv2.warpPerspective(np.array(obj.convert("RGB")), M, (W, H))
    mask = cv2.warpPerspective(np.full((oh, ow), 255, np.uint8), M, (W, H))
    shade = rng.uniform(0.75, 1.1)
    warped = np.clip(warped.astype(np.float32) * shade, 0, 255).astype(np.uint8)
    bg[mask > 8] = warped[mask > 8]
    return M, mask


def _box_from(M, rect, W, H):
    x1, y1, x2, y2 = rect
    pts = np.float32([[[x1, y1]], [[x2, y1]], [[x2, y2]], [[x1, y2]]])
    t = cv2.perspectiveTransform(pts, M).reshape(-1, 2)
    xa, ya = np.clip(t[:, 0].min(), 0, W), np.clip(t[:, 1].min(), 0, H)
    xb, yb = np.clip(t[:, 0].max(), 0, W), np.clip(t[:, 1].max(), 0, H)
    if xb - xa < 4 or yb - ya < 4:
        return None
    return ((xa + xb) / 2 / W, (ya + yb) / 2 / H, (xb - xa) / W, (yb - ya) / H)


def make_scene(seed: int) -> tuple[Image.Image, list[str]]:
    rng = random.Random(seed)
    W, H = rng.choice([(1920, 1440), (1600, 1200), (1440, 1920), (2048, 1536)])
    bg = np.array(_background(rng, W, H))
    lines: list[str] = []
    occupied = np.zeros((H, W), np.uint8)

    n_obj = 0 if rng.random() < 0.15 else rng.randint(1, 2)  # 15% 는 물체 없는 사진
    for _ in range(n_obj):
        if rng.random() < 0.55:
            obj, _labels = make_waybill(rng.randint(0, 10_000))
            parts = [(CODE, [570, 310, 688, 428])]  # make_waybill 의 QR 위치
            cls = WAYBILL
        else:
            obj, parts = make_id_card(rng)
            cls = ID_CARD
        scale = rng.uniform(0.2, 0.7) * min(W, H) / max(obj.size)
        trial = bg.copy()
        M, mask = _paste(trial, obj, rng, scale)
        if (occupied[mask > 8] > 0).mean() > 0.05:  # 겹치면 다음
            continue
        bg = trial
        occupied |= (mask > 8).astype(np.uint8)
        ow, oh = obj.size
        for c, rect in [(cls, [0, 0, ow, oh])] + parts:
            b = _box_from(M, rect, W, H)
            if b:
                lines.append(f"{c} {b[0]:.6f} {b[1]:.6f} {b[2]:.6f} {b[3]:.6f}")

    out = Image.fromarray(bg)
    if rng.random() < 0.3:  # 흔들림·흐림
        out = Image.fromarray(cv2.GaussianBlur(np.array(out), (0, 0), rng.uniform(0.6, 1.8)))
    return out, lines


def run(ws: Workspace, n: int = 200, seed: int = 0) -> None:
    ws.init()
    rows = ws.load()
    made = 0
    for i in range(n):
        s = seed + i
        fid = f"syn{s:09d}"
        if fid in rows:
            continue
        img, lines = make_scene(s)
        img.save(ws.dataset / "images" / f"{fid}.jpg", "JPEG", quality=88)
        (ws.dataset / "labels" / f"{fid}.txt").write_text(
            "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        rows[fid] = Row(id=fid, group=f"synth_{s // 50}", source="synth", split="train",
                        status=DONE, added_at=dt.datetime.now().isoformat(timespec="seconds"),
                        orig_name="", prelabel="")
        made += 1
    ws.save(rows)
    from .build import write_lists
    write_lists(ws, rows)
    print(f"합성 사진 {made}장을 학습 데이터에 넣었습니다(train 전용).")
