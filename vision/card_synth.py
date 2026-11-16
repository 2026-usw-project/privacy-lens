"""가상 결제 카드를 일상 사진에 합성해 `card` 학습 사진을 늘린다.

왜: 실물 카드는 번호가 양각(튀어나오거나 파인 글자)이거나 카드와 같은 색이라 OCR 이 번호를 못 읽는다(2026-11-14).
그럴 때 서비스는 '카드째 가림 권장'으로 알리는데(pipeline/detect.py), 그러려면 카드 물건을 놓치지 않아야 한다.
공개 데이터의 카드는 대부분 가까이서 찍은 해외 카드라, 한국 일상 사진 속 작은 카드·세로형 카드·뒷면이 부족하다.
실물 카드 사진은 개인정보라 쓰지 않는다. 번호·이름은 전부 가상이고 카드사 이름·로고도 가상이다.

만드는 것: 카드 그림(가로·세로·뒷면, 번호는 양각/음각/같은 색 인쇄/또렷한 인쇄/없음) → 기울이고 원근을 줘서
일상 사진(이미 있는 학습 사진) 위에 붙임 → 라벨에 `card` 상자 추가. 원래 사진의 라벨은 그대로 둔다.
"""
from __future__ import annotations

import random
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from samples import fonts

CARD_CLASS = 1                      # vision/daily_data.CLASSES 의 "card"
NUMBER_CLASS = 9                    # 9종 뒤에 붙인 10번째 클래스 "card_number"(번호 줄). OCR 이 못 읽어도 자리를 찾는다
PREFIX = "synthcard_"
ISSUERS = ["누리카드", "한빛카드", "가온 check", "NURI CARD", "HANBIT", "다온페이", "GAON BANK"]
SURN = ["KIM", "LEE", "PARK", "CHOI", "JUNG", "KANG", "YOON", "HAN"]
GIVEN = ["MINJUN", "SEOYEON", "JIHO", "HAEUN", "DOYUN", "YEJIN", "SUAH", "JIWON"]
STYLES = ["emboss", "emboss", "engrave", "same", "same", "print", "none"]   # 번호 표현. 양각·같은 색을 많이


_FONT_PATHS: tuple[str, str] | None = None


def _font(px: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    global _FONT_PATHS
    if _FONT_PATHS is None:
        _FONT_PATHS = fonts.find_korean_font()
    return ImageFont.truetype(_FONT_PATHS[1 if bold else 0], max(8, int(px)))


def _luhn_number(r: random.Random) -> str:
    """실제 카드사에 없는 9로 시작하는 16자리(Luhn 통과)."""
    d = [9] + [r.randint(0, 9) for _ in range(14)]
    for last in range(10):
        total = 0
        for i, v in enumerate(reversed(d + [last])):
            v = v * 2 if i % 2 else v
            total += v - 9 if v > 9 else v
        if total % 10 == 0:
            return "".join(map(str, d + [last]))
    return ""


def _shade(c, k: float):
    return tuple(int(max(0, min(255, v + k))) for v in c)


def _relief(d: ImageDraw.ImageDraw, xy, text, font, base, style: str, r: random.Random, box: list | None = None):
    """번호·이름 글자. emboss=튀어나옴, engrave=파임, same=카드와 거의 같은 색, print=또렷함.
    box 를 주면 글자가 차지한 자리(x0, y0, x1, y1)를 거기에 합친다(번호 줄 라벨용)."""
    x, y = xy
    if box is not None:
        b = d.textbbox((x, y), text, font=font)
        box[:] = [min(box[0], b[0] - 4), min(box[1], b[1] - 4), max(box[2], b[2] + 4), max(box[3], b[3] + 4)] if box else \
                 [b[0] - 4, b[1] - 4, b[2] + 4, b[3] + 4]
    if style in ("emboss", "engrave"):
        hi, lo = (55, -60) if style == "emboss" else (-60, 55)
        off = r.choice([1, 2, 2])
        d.text((x - off, y - off), text, font=font, fill=_shade(base, hi))
        d.text((x + off, y + off), text, font=font, fill=_shade(base, lo))
        d.text((x, y), text, font=font, fill=_shade(base, r.randint(-8, 14)))
    elif style == "same":
        d.text((x, y), text, font=font, fill=_shade(base, r.choice([-1, 1]) * r.randint(18, 34)))
    else:
        lum = sum(base) / 3
        d.text((x, y), text, font=font, fill=(245, 245, 248) if lum < 140 else (30, 30, 36))


def render_card(r: random.Random, with_number_box: bool = False):
    """가상 카드 한 장(RGBA, 긴 변 856px). 모서리는 둥글고 바깥은 투명.
    with_number_box=True 면 (카드, 번호 줄 상자 또는 None) 을 돌려준다."""
    nb: list = []
    vertical = r.random() < 0.3
    back = r.random() < 0.2
    w, h = (540, 856) if vertical else (856, 540)
    base = r.choice([(28, 32, 44), (20, 20, 22), (0, 78, 118), (118, 30, 58), (230, 232, 236), (245, 240, 228),
                     (196, 170, 110), (60, 110, 90), (150, 152, 160), (250, 206, 60), (88, 66, 150)])
    base = _shade(base, r.randint(-12, 12))
    img = Image.new("RGB", (w, h), base)
    d = ImageDraw.Draw(img)
    for k in range(r.randint(0, 7)):                      # 은은한 무늬
        x = r.randint(-200, w)
        d.line([(x, 0), (x + r.randint(100, 400), h)], fill=_shade(base, r.choice([-14, 12])), width=r.randint(6, 40))
    if r.random() < 0.3:
        d.ellipse([w * r.uniform(.3, .9), -h * .3, w * 1.4, h * r.uniform(.5, 1.1)], fill=_shade(base, r.choice([-18, 16])))
    lum = sum(base) / 3
    ink = (240, 240, 245) if lum < 140 else (35, 35, 42)
    style = r.choice(STYLES)
    num = _luhn_number(r)
    groups = [num[i:i + 4] for i in range(0, 16, 4)]
    exp = f"{r.randint(1, 12):02d}/{r.randint(26, 31)}"
    name = f"{r.choice(SURN)} {r.choice(GIVEN)}"
    if back:
        d.rectangle([0, h * .08, w, h * .08 + (110 if not vertical else 90)], fill=(18, 18, 20))
        sy = int(h * .34)
        d.rectangle([w * .06, sy, w * .66, sy + 64], fill=(250, 250, 250))
        for k in range(8):
            d.line([(w * .06, sy + 6 + k * 8), (w * .66, sy + 6 + k * 8)], fill=(222, 218, 232), width=1)
        d.text((w * .70, sy + 12), f"{r.randint(100, 999)}", font=_font(40), fill=ink)
        fy = sy + 110
        if vertical:
            for g in groups:
                _relief(d, (w * .08, fy), g, _font(56), base, "print" if style == "none" else style, r, nb); fy += 70
        else:
            _relief(d, (w * .06, fy), " ".join(groups), _font(52), base, "print" if style == "none" else style, r, nb); fy += 76
        d.text((w * .06, fy + 6), "VALID THRU " + exp, font=_font(26, False), fill=ink)
        d.text((w * .06, h - 60), "고객센터 1588-" + str(r.randint(1000, 9999)), font=_font(22, False), fill=ink)
    else:
        d.text((w * .06, h * .06), r.choice(ISSUERS), font=_font(r.randint(36, 50)), fill=ink)
        if r.random() < 0.8:                                # IC 칩
            cx, cy = (w * .08, h * .30) if not vertical else (w * .34, h * .16)
            gold = r.choice([(212, 186, 118), (200, 200, 205)])
            d.rounded_rectangle([cx, cy, cx + 104, cy + 82], radius=12, fill=gold, outline=_shade(gold, -60), width=3)
            d.line([(cx, cy + 28), (cx + 104, cy + 28)], fill=_shade(gold, -60), width=2)
            d.line([(cx, cy + 56), (cx + 104, cy + 56)], fill=_shade(gold, -60), width=2)
            d.line([(cx + 52, cy), (cx + 52, cy + 82)], fill=_shade(gold, -60), width=2)
        if style != "none":
            if vertical:
                fy = h * .33
                for g in groups:
                    _relief(d, (w * .16, fy), g, _font(84), base, style, r, nb); fy += 92
            else:
                _relief(d, (w * .07, h * .54), "  ".join(groups), _font(r.randint(58, 66)), base, style, r, nb)
            ny = h * .86 if vertical else h * .80
            _relief(d, (w * .07, ny), name, _font(34), base, style if style != "print" else "print", r)
            d.text((w * .07 if vertical else w * .46, ny - 44 if vertical else h * .70), "VALID THRU " + exp,
                   font=_font(24, False), fill=ink)
        else:
            d.text((w * .07, h * .84), name, font=_font(30, False), fill=ink)
        mx, my = w * .74, h * (.86 if not vertical else .92)   # 상표 자리(가상 도형)
        d.rounded_rectangle([mx, my - 46, mx + 150 * (0.7 if vertical else 1), my + 10], radius=8,
                            fill=_shade(base, r.choice([-40, 40])))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=34, fill=255)
    out = img.convert("RGBA")
    out.putalpha(mask)
    return (out, tuple(nb) if nb else None) if with_number_box else out


def paste_card(bg: Image.Image, card: Image.Image, r: random.Random, avoid: list[tuple[float, float, float, float]] = (),
               inner: tuple | None = None):
    """카드를 기울이고 원근을 줘서 배경에 붙인다. 반환: (사진, (x0, y0, x1, y1) 픽셀 상자).
    inner(카드 그림 안의 상자, 예: 번호 줄)를 주면 (사진, 카드 상자, 옮겨진 inner 상자 또는 None) 을 돌려준다."""
    W, H = bg.size
    long_side = r.uniform(0.10, 0.50) * min(W, H) * (1.25 if r.random() < 0.3 else 1.0)
    k = long_side / max(card.size)
    cw, ch = max(12, int(card.width * k)), max(12, int(card.height * k))
    src = np.float32([[0, 0], [cw, 0], [cw, ch], [0, ch]])
    j = 0.14 * min(cw, ch)
    quad = src + np.float32([[r.uniform(-j, j), r.uniform(-j, j)] for _ in range(4)])       # 원근
    ang = np.deg2rad(r.choice([r.uniform(-35, 35), r.uniform(-35, 35), r.uniform(55, 125), r.uniform(-180, 180)]))
    c, s = np.cos(ang), np.sin(ang)
    center = quad.mean(0)
    quad = (quad - center) @ np.float32([[c, s], [-s, c]])
    quad -= quad.min(0)
    qw, qh = int(np.ceil(quad[:, 0].max())) + 2, int(np.ceil(quad[:, 1].max())) + 2
    if qw >= W or qh >= H:
        f = 0.9 * min(W / qw, H / qh)
        quad *= f
        qw, qh = int(np.ceil(quad[:, 0].max())) + 2, int(np.ceil(quad[:, 1].max())) + 2
    small = np.array(card.resize((cw, ch), Image.LANCZOS))
    M = cv2.getPerspectiveTransform(src, quad.astype(np.float32))
    warped = cv2.warpPerspective(small, M, (qw, qh), flags=cv2.INTER_AREA if k < 1 else cv2.INTER_LINEAR,
                                 borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
    # 다른 물건 상자 한가운데는 피한다(10번 시도)
    for _ in range(10):
        ox, oy = r.randint(0, max(0, W - qw)), r.randint(0, max(0, H - qh))
        cx, cy = (ox + qw / 2) / W, (oy + qh / 2) / H
        if not any(abs(cx - ax) < aw / 2 and abs(cy - ay) < ah / 2 for ax, ay, aw, ah in avoid):
            break
    layer = Image.fromarray(warped, "RGBA")
    if r.random() < 0.5:                                    # 조명: 밝기·대비를 조금 흔든다
        rgb = np.asarray(layer.convert("RGB")).astype(np.float32) * r.uniform(0.7, 1.15) + r.uniform(-14, 14)
        layer = Image.merge("RGBA", (*Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8)).split(), layer.getchannel("A")))
    out = bg.convert("RGB").copy()
    shadow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    shadow.putalpha(layer.getchannel("A").point(lambda v: int(v * 0.35)).filter(ImageFilter.GaussianBlur(max(2, qw // 60))))
    out.paste(shadow, (ox + max(1, qw // 80), oy + max(1, qh // 60)), shadow)
    if r.random() < 0.35:                                   # 초점이 안 맞은 카드
        layer = layer.filter(ImageFilter.GaussianBlur(r.uniform(0.6, 1.8)))
    out.paste(layer, (ox, oy), layer)
    x0, y0, x1, y1 = ox + quad[:, 0].min(), oy + quad[:, 1].min(), ox + quad[:, 0].max(), oy + quad[:, 1].max()
    if r.random() < 0.2:                                    # 다른 물건에 한쪽이 가려진 카드(상자는 보이는 부분만)
        cut = r.uniform(0.12, 0.3) * (x1 - x0)
        side = r.random() < 0.5
        px0 = int(x0 if side else x1 - cut)
        patch = bg.convert("RGB").crop((px0, int(y0), int(px0 + cut), int(y1)))
        out.paste(patch, (px0, int(y0)))
        x0, x1 = (x0 + cut, x1) if side else (x0, x1 - cut)
    box = (max(0.0, float(x0)), max(0.0, float(y0)), min(float(W), float(x1)), min(float(H), float(y1)))
    if inner is None:
        return out, box
    ix0, iy0, ix1, iy1 = (v * k for v in inner)
    pts = cv2.perspectiveTransform(np.float32([[[ix0, iy0], [ix1, iy0], [ix1, iy1], [ix0, iy1]]]), M)[0]
    n = (max(box[0], ox + pts[:, 0].min()), max(box[1], oy + pts[:, 1].min()),
         min(box[2], ox + pts[:, 0].max()), min(box[3], oy + pts[:, 1].max()))
    full = (pts[:, 0].max() - pts[:, 0].min()) * (pts[:, 1].max() - pts[:, 1].min())
    seen = max(0.0, n[2] - n[0]) * max(0.0, n[3] - n[1])
    # 가려져 절반도 안 보이거나 너무 작아(긴 변 14px 미만) 알아볼 수 없는 번호 줄은 라벨에 넣지 않는다
    ok = full > 0 and seen / full >= 0.5 and max(n[2] - n[0], n[3] - n[1]) >= 14
    return out, box, (tuple(float(v) for v in n) if ok else None)


def add_to_dataset(ds: Path, n: int = 3000, split: str = "train", seed: int = 7, max_side: int = 1280) -> dict:
    """YOLO 데이터셋(ds/images/<split>, ds/labels/<split>)에 합성 카드 사진 n 장을 더한다. 이미 있으면 건너뛴다."""
    img_dir, lab_dir = ds / "images" / split, ds / "labels" / split
    have = len(list(img_dir.glob(PREFIX + "*.jpg")))
    if have >= n:
        return {"추가": 0, "이미 있음": have}
    pool = sorted(p for p in img_dir.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png")
                  and not p.name.startswith(PREFIX))
    if not pool:
        raise FileNotFoundError(f"배경으로 쓸 사진이 없습니다: {img_dir}")
    r = random.Random(seed)
    made = 0
    for i in range(have, n):
        src = r.choice(pool)
        try:
            bg = Image.open(src).convert("RGB")
        except Exception:
            continue
        if min(bg.size) < 240:
            continue
        if max(bg.size) > max_side:
            bg.thumbnail((max_side, max_side))
        lab = lab_dir / (src.stem + ".txt")
        lines = [ln for ln in lab.read_text().splitlines() if ln.strip()] if lab.exists() else []
        avoid = [tuple(map(float, ln.split()[1:5])) for ln in lines]
        card, nbox = render_card(r, with_number_box=True)
        out, (x0, y0, x1, y1), num = paste_card(bg, card, r, avoid, inner=nbox or (0, 0, 1, 1))
        W, H = out.size
        if x1 - x0 < 8 or y1 - y0 < 8:
            continue
        lines.append(f"{CARD_CLASS} {(x0 + x1) / 2 / W:.6f} {(y0 + y1) / 2 / H:.6f} {(x1 - x0) / W:.6f} {(y1 - y0) / H:.6f}")
        if nbox and num:
            a0, b0, a1, b1 = num
            lines.append(f"{NUMBER_CLASS} {(a0 + a1) / 2 / W:.6f} {(b0 + b1) / 2 / H:.6f} {(a1 - a0) / W:.6f} {(b1 - b0) / H:.6f}")
        name = f"{PREFIX}{i:05d}"
        out.save(img_dir / (name + ".jpg"), quality=r.randint(78, 93))
        (lab_dir / (name + ".txt")).write_text("\n".join(lines) + "\n")
        made += 1
    return {"추가": made, "이미 있음": have}


# ------------------------------------------------------------------ 실물 카드 공개 데이터(Roboflow Universe)
# 받은 zip(YOLO 형식)을 드라이브 objects/raw/cards/ 에 두면 가져온다. 출처·라이선스는 vision/README.md.
REAL_PREFIX = "realcard_"


def map_card_class(name: str) -> int | None:
    """공개 데이터의 클래스 이름 → 우리 클래스. 카드 통째는 card, 번호 줄은 card_number, 나머지(이름·유효기간·로고)는 안 씀."""
    n = name.lower().replace("_", " ").replace("-", " ").strip()
    if "number" in n:
        return NUMBER_CLASS
    if n in ("card", "credit card", "valid credit card", "front side", "creditcard", "credit"):
        return CARD_CLASS
    return None


def _yaml_names(text: str) -> list[str]:
    """data.yaml 의 names 를 읽는다(목록 한 줄, 여러 줄 목록, 번호: 이름 세 모양)."""
    import re
    m = re.search(r"^names:\s*\[(.*?)\]", text, re.M | re.S)
    if m:
        return [v.strip().strip("'\"") for v in m.group(1).split(",") if v.strip()]
    block = re.search(r"^names:\s*\n((?:[ \t]+.*\n?)+)", text, re.M)
    if not block:
        return []
    out = []
    for ln in block.group(1).splitlines():
        ln = ln.strip()
        if ln.startswith("-"):
            out.append(ln[1:].strip().strip("'\""))
        elif ":" in ln:
            out.append(ln.split(":", 1)[1].strip().strip("'\""))
    return out


def _enclosing_card(boxes: list[tuple[float, float, float, float]]) -> str:
    """칸만 단 데이터의 card 상자. 이 데이터는 카드를 가까이 찍은 사진이라 칸 일부만 라벨이 달린 경우가 많아,
    칸들을 둘러싼 상자보다 사진 전체가 실제 카드에 더 가깝다(직접 확인함). 칸이 사진 밖으로 나가면 그만큼 넓힌다."""
    x0, y0 = min(0.0, *(b[0] for b in boxes)), min(0.0, *(b[1] for b in boxes))
    x1, y1 = max(1.0, *(b[2] for b in boxes)), max(1.0, *(b[3] for b in boxes))
    x0, y0, x1, y1 = max(0.0, x0), max(0.0, y0), min(1.0, x1), min(1.0, y1)
    return f"{CARD_CLASS} {(x0 + x1) / 2:.6f} {(y0 + y1) / 2:.6f} {x1 - x0:.6f} {y1 - y0:.6f}"


def import_real(ds: Path, zips: list[Path], max_side: int = 1280) -> dict:
    """Roboflow YOLO zip 들을 ds 에 더한다. train → train, valid·test → val. 이미 가져온 zip 은 건너뛴다.
    다각형 라벨은 둘러싼 상자로 바꾼다. 쓸 클래스가 하나도 없는 사진은 넣지 않는다."""
    import io
    import zipfile
    stats: dict = {}
    for zp in zips:
        tag = "".join(ch if ch.isalnum() else "_" for ch in zp.stem)[:40]
        marker = ds / f".{REAL_PREFIX}{tag}.done"
        if marker.exists():
            stats[zp.name] = "이미 가져옴"
            continue
        with zipfile.ZipFile(zp) as z:
            names_in = z.namelist()
            yml = next((n for n in names_in if n.endswith("data.yaml")), None)
            classes = _yaml_names(z.read(yml).decode("utf-8", "replace")) if yml else []
            mapping = {i: map_card_class(c) for i, c in enumerate(classes)}
            # 카드 통째 클래스 없이 칸(번호·이름·유효기간·로고)만 단 데이터: card 상자를 덧붙인다(_enclosing_card).
            # 이렇게 안 하면 사진 대부분을 차지한 카드가 '배경'으로 학습된다.
            fields_only = CARD_CLASS not in mapping.values() and len(classes) >= 3
            count = {"train": 0, "val": 0, "card": 0, "card_number": 0}
            for n in names_in:
                parts = n.replace("\\", "/").split("/")
                if "images" not in parts or not n.lower().endswith((".jpg", ".jpeg", ".png")):
                    continue
                src_split = next((p for p in parts if p in ("train", "valid", "val", "test")), "train")
                split = "train" if src_split == "train" else "val"
                stem = Path(parts[-1]).stem
                lab_name = n.replace("/images/", "/labels/").rsplit(".", 1)[0] + ".txt"
                if lab_name not in names_in:
                    continue
                rows = []
                all_boxes = []
                for ln in z.read(lab_name).decode("utf-8", "replace").splitlines():
                    v = ln.split()
                    if len(v) < 5 or not v[0].isdigit():
                        continue
                    nums = [float(t) for t in v[1:]]
                    if len(nums) == 4:
                        cx, cy, w, h = nums
                    else:                                   # 다각형 → 상자
                        xs, ys = nums[0::2], nums[1::2]
                        cx, cy, w, h = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, max(xs) - min(xs), max(ys) - min(ys)
                    if w <= 0 or h <= 0:
                        continue
                    all_boxes.append((cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2))
                    if mapping.get(int(v[0])) is None:
                        continue
                    cls = mapping[int(v[0])]
                    rows.append(f"{cls} {cx:.6f} {cy:.6f} {min(w, 1):.6f} {min(h, 1):.6f}")
                    count["card" if cls == CARD_CLASS else "card_number"] += 1
                if fields_only and len(all_boxes) >= 2:
                    rows.insert(0, _enclosing_card(all_boxes))
                    count["card"] += 1
                if not rows:
                    continue
                try:
                    im = Image.open(io.BytesIO(z.read(n))).convert("RGB")
                except Exception:
                    continue
                if max(im.size) > max_side:
                    im.thumbnail((max_side, max_side))
                out = f"{REAL_PREFIX}{tag}_{stem}"[:150]
                (ds / "images" / split).mkdir(parents=True, exist_ok=True)
                (ds / "labels" / split).mkdir(parents=True, exist_ok=True)
                im.save(ds / "images" / split / (out + ".jpg"), quality=90)
                (ds / "labels" / split / (out + ".txt")).write_text("\n".join(rows) + "\n")
                count[split] += 1
        marker.write_text("ok")
        stats[zp.name] = {"클래스": {c: mapping[i] for i, c in enumerate(classes)}, **count}
    return stats


def pseudo_label_cards(ds: Path, predict, batch: int = 32) -> dict:
    """card_number 만 있고 card 라벨이 없는 실물 사진에, 이전 모델이 찾은 card 상자를 덧붙인다.

    card-number-detecter 처럼 번호 줄만 라벨한 데이터는 카드 크기·위치가 제각각이라 사진 전체를 card 로 둘 수 없고,
    그대로 두면 카드가 배경으로 학습된다. predict(경로 목록) → 사진마다 [(cx, cy, w, h), ...](0~1) 를 돌려주는 함수.
    한 번만 돈다(.pseudo_cards.done)."""
    marker = ds / ".pseudo_cards.done"
    if marker.exists():
        return {"상태": "이미 함"}
    todo: list[tuple[Path, Path, list[str]]] = []
    for split in ("train", "val"):
        for lab in sorted((ds / "labels" / split).glob(f"{REAL_PREFIX}*.txt")):
            rows = [r for r in lab.read_text().splitlines() if r.strip()]
            cls = {r.split()[0] for r in rows}
            if str(CARD_CLASS) in cls or str(NUMBER_CLASS) not in cls:
                continue
            img = ds / "images" / split / (lab.stem + ".jpg")
            if img.exists():
                todo.append((img, lab, rows))
    added = found = 0
    for i in range(0, len(todo), batch):
        part = todo[i:i + batch]
        for (img, lab, rows), boxes in zip(part, predict([str(t[0]) for t in part])):
            if not boxes:
                continue
            found += 1
            new = [f"{CARD_CLASS} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}" for cx, cy, w, h in boxes]
            lab.write_text("\n".join(new + rows) + "\n")
            added += len(new)
    marker.write_text("ok")
    return {"대상 사진": len(todo), "card 찾은 사진": found, "덧붙인 card": added}


def yolo_card_predictor(weights: str, conf: float = 0.35, imgsz: int = 640):
    """pseudo_label_cards 에 넘길 예측 함수(이전 일상 모델의 card 클래스만)."""
    from ultralytics import YOLO
    m = YOLO(weights)

    def predict(paths: list[str]) -> list[list[tuple[float, float, float, float]]]:
        res = m.predict(paths, imgsz=imgsz, conf=conf, classes=[CARD_CLASS], verbose=False)
        return [[tuple(b) for b in r.boxes.xywhn.tolist()] for r in res]
    return predict
