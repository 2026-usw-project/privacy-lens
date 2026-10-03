"""합성 송장 생성기.

명찰·송장이 라벨링된 공개 데이터셋은 없다. 템플릿에 가짜 정보를 채우고
원근 변환으로 실제 배경에 합성하면 좌표를 알고 있으니 라벨이 자동으로 나온다.

주의: 분할은 **템플릿 단위**로 해야 한다. 같은 템플릿의 변형본이 학습과
평가에 섞이면 누수다. 이미지 단위로 나누면 안 된다.

여기서 만드는 샘플에는 오탐 함정을 일부러 하나 넣어뒀다.
같은 종이에 '수취인 연락처'와 '고객센터' 번호가 둘 다 있다.
정규식만 쓰면 둘 다 똑같이 경고한다. 문맥을 보면 하나만 가리면 된다.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import numpy as np
import qrcode
from PIL import Image, ImageDraw, ImageFont

try:
    from .fonts import find_korean_font
except ImportError:  # 스크립트로 직접 실행할 때
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from fonts import find_korean_font

FONT_PATH, FONT_BOLD = find_korean_font()

SURNAMES = ["김", "이", "박", "최", "정", "강", "조", "윤", "장", "임"]
GIVEN = ["서연", "민준", "지우", "도윤", "하은", "시우", "예준", "수아"]
ROADS = ["테헤란로", "봉은사로", "동탄대로", "권선로", "중앙로", "번영로"]
CITIES = [
    ("경기도 수원시 영통구", "광교"),
    ("경기도 화성시", "동탄"),
    ("서울특별시 강남구", "역삼"),
]
COURIERS = ["한진택배", "로젠택배", "대한통운", "우체국택배"]


_FONT_CACHE: dict[tuple[int, bool], ImageFont.FreeTypeFont] = {}


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    key = (size, bold)
    if key not in _FONT_CACHE:
        _FONT_CACHE[key] = ImageFont.truetype(FONT_BOLD if bold else FONT_PATH, size)
    return _FONT_CACHE[key]


def make_waybill(seed: int = 0) -> tuple[Image.Image, dict]:
    """송장 한 장을 그린다. 정답 라벨을 함께 돌려준다."""
    rng = random.Random(seed)

    name = rng.choice(SURNAMES) + rng.choice(GIVEN)
    phone = f"010-{rng.randint(1000, 9999)}-{rng.randint(1000, 9999)}"
    city, dong = rng.choice(CITIES)
    road = rng.choice(ROADS)
    address = f"{city} {road} {rng.randint(1, 300)}"
    unit = f"{rng.randint(101, 130)}동 {rng.randint(101, 2504)}호"
    tracking = "".join(str(rng.randint(0, 9)) for _ in range(12))
    courier = rng.choice(COURIERS)
    center = rng.choice(["1588-0011", "1577-1234", "1588-1300"])

    W, H = 720, 460
    img = Image.new("RGB", (W, H), (252, 251, 247))
    d = ImageDraw.Draw(img)

    d.rectangle([0, 0, W - 1, H - 1], outline=(180, 178, 172), width=2)
    d.rectangle([0, 0, W, 58], fill=(238, 236, 230))
    d.text((24, 16), courier, font=_font(26, bold=True), fill=(30, 30, 34))
    d.text((W - 250, 22), "운송장번호", font=_font(15), fill=(110, 110, 115))
    d.text((W - 165, 18), tracking, font=_font(20, bold=True), fill=(30, 30, 34))

    d.line([(0, 58), (W, 58)], fill=(180, 178, 172), width=2)

    y = 84
    d.text((24, y), "받는분", font=_font(16), fill=(120, 120, 125))
    d.text((110, y - 4), name, font=_font(24, bold=True), fill=(20, 20, 24))

    y += 46
    d.text((24, y), "연락처", font=_font(16), fill=(120, 120, 125))
    d.text((110, y - 3), phone, font=_font(22), fill=(20, 20, 24))

    y += 46
    d.text((24, y), "배송지", font=_font(16), fill=(120, 120, 125))
    d.text((110, y - 2), address, font=_font(20), fill=(20, 20, 24))
    d.text((110, y + 26), unit, font=_font(20), fill=(20, 20, 24))

    # 오탐 함정: 같은 종이의 공개 번호
    y += 96
    d.line([(24, y), (W - 24, y)], fill=(205, 203, 198), width=1)
    d.text((24, y + 14), "고객센터", font=_font(16), fill=(120, 120, 125))
    d.text((110, y + 12), center, font=_font(20), fill=(60, 60, 66))
    d.text((260, y + 14), "배송문의는 고객센터로 연락 바랍니다",
           font=_font(15), fill=(130, 130, 136))

    qr = qrcode.make(f"https://trace.example.co.kr/t/{tracking}").resize((118, 118))
    img.paste(qr, (W - 150, H - 150))

    labels = {
        "name": name, "phone": phone, "address": address,
        "unit": unit, "tracking": tracking, "center": center,
        "truth_cover": [phone, address, unit],
        "truth_not_pii": [center, tracking],
    }
    return img, labels


def place_on_desk(waybill: Image.Image, seed: int = 0) -> Image.Image:
    """책상 배경에 송장을 원근 변환으로 올린다."""
    import cv2

    rng = random.Random(seed + 500)
    W, H = 1280, 860

    bg = Image.new("RGB", (W, H), (96, 84, 72))
    d = ImageDraw.Draw(bg)
    for i in range(0, H, 7):
        shade = 96 + int(14 * np.sin(i / 26.0)) + rng.randint(-4, 4)
        d.line([(0, i), (W, i)], fill=(shade, shade - 12, shade - 24), width=7)
    d.rectangle([70, 70, 470, 470], fill=(58, 60, 66))
    d.text((96, 96), "노트북", font=_font(18), fill=(120, 122, 128))

    src = np.float32([[0, 0], [waybill.width, 0],
                      [waybill.width, waybill.height], [0, waybill.height]])
    ox, oy = 470, 300
    jitter = lambda: rng.randint(-26, 26)
    dst = np.float32([
        [ox + jitter(), oy + jitter()],
        [ox + 700 + jitter(), oy + 18 + jitter()],
        [ox + 686 + jitter(), oy + 440 + jitter()],
        [ox + 14 + jitter(), oy + 424 + jitter()],
    ])

    M = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(
        np.array(waybill.convert("RGB")), M, (W, H),
        borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0),
    )
    mask = cv2.warpPerspective(
        np.full((waybill.height, waybill.width), 255, np.uint8), M, (W, H)
    )

    base = np.array(bg)
    out = np.where(mask[:, :, None] > 8, warped, base).astype(np.uint8)
    return Image.fromarray(out)


if __name__ == "__main__":
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out_dir.mkdir(parents=True, exist_ok=True)

    for seed in range(3):
        wb, labels = make_waybill(seed)
        wb.save(out_dir / f"waybill_{seed}_flat.png")
        place_on_desk(wb, seed).save(out_dir / f"waybill_{seed}_desk.png")
        print(f"seed={seed}  가려야 함={labels['truth_cover']}  "
              f"가리면 안 됨={labels['truth_not_pii']}")
