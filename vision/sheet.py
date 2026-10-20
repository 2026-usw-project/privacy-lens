"""검수 시트: 묶음마다 박스를 그린 썸네일을 한 장에 모은다.

2차 검수자가 묶음 하나(10~30장)를 1분 안에 훑어보게 하려는 것이다. 기본은
1차 검수가 끝나고 데이터셋 반영을 기다리는 사진(review/done/*.ok)이고,
--dataset 이면 이미 데이터셋에 들어간 실사 사진을 그린다.

결과는 작업 폴더의 검수시트/ 에 JPG 로 저장한다. 드라이브 웹·휴대폰에서 바로 열린다.
글자는 영어·숫자만 그린다(Colab 에 한글 폰트가 없어도 되게).
"""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

from .classes import NAMES
from .workspace import DONE, Workspace

# 라벨 도구(label_tool.html)와 같은 색
COLORS = ["#e4572e", "#2e86de", "#17a589", "#f1c40f", "#c0398b", "#7f8c8d", "#8e44ad", "#d35400", "#16a085"]
THUMB = 480
COLS = 5
PER_SHEET = 30


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow 10.1 미만
        return ImageFont.load_default()


def _thumb(img_path, label_path, caption: str) -> Image.Image:
    with Image.open(img_path) as im:
        im = im.convert("RGB")
        W, H = im.size
        im.thumbnail((THUMB, THUMB))
    s = im.width / W
    tile = Image.new("RGB", (THUMB, THUMB + 28), "white")
    tile.paste(im, ((THUMB - im.width) // 2, 0))
    ox = (THUMB - im.width) // 2
    d = ImageDraw.Draw(tile)
    lines = label_path.read_text(encoding="utf-8").split() if label_path.exists() else []
    n = 0
    for i in range(0, len(lines) - 4, 5):
        c, cx, cy, w, h = int(lines[i]), *map(float, lines[i + 1:i + 5])
        x0, y0 = ox + (cx - w / 2) * W * s, (cy - h / 2) * H * s
        x1, y1 = ox + (cx + w / 2) * W * s, (cy + h / 2) * H * s
        col = COLORS[c % len(COLORS)]
        d.rectangle([x0, y0, x1, y1], outline=col, width=3)
        d.text((x0 + 3, max(0, y0 - 15)), NAMES.get(c, str(c)), fill=col, font=_font(13))
        n += 1
    d.text((6, THUMB + 6), f"{caption}  boxes:{n}", fill="black", font=_font(15))
    return tile


def run(ws: Workspace, dataset: bool = False) -> list:
    rows = ws.load()
    base = ws.dataset if dataset else ws.review
    if dataset:
        ids = [r.id for r in rows.values() if r.status == DONE and r.source == "real"]
    else:
        ids = [p.stem for p in sorted((ws.review / "done").glob("*.ok"))]

    groups: dict[str, list[str]] = {}
    for fid in ids:
        row = rows.get(fid)
        if (base / "images" / f"{fid}.jpg").exists():
            groups.setdefault(row.group if row else "unknown", []).append(fid)

    out_dir = ws.root / "검수시트"
    out_dir.mkdir(exist_ok=True)
    written = []
    for group, items in sorted(groups.items()):
        for page, start in enumerate(range(0, len(items), PER_SHEET), 1):
            chunk = items[start:start + PER_SHEET]
            rows_n = (len(chunk) + COLS - 1) // COLS
            sheet = Image.new("RGB", (COLS * THUMB, rows_n * (THUMB + 28)), (230, 230, 230))
            for k, fid in enumerate(chunk):
                tile = _thumb(base / "images" / f"{fid}.jpg", base / "labels" / f"{fid}.txt", fid)
                sheet.paste(tile, ((k % COLS) * THUMB, (k // COLS) * (THUMB + 28)))
            path = out_dir / f"{'dataset' if dataset else 'review'}_{group}_{page}.jpg"
            sheet.save(path, "JPEG", quality=85)
            written.append(path)
            print(f"  {path.relative_to(ws.root)}  ({len(chunk)}장)")
    if not written:
        print("시트로 만들 사진이 없습니다." + ("" if dataset else " 1차 검수(Enter)한 사진이 아직 없습니다."))
    return written
