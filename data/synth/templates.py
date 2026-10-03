"""
가짜 문서 템플릿 렌더러 (PIL).
각 함수는 (RGB 이미지, 정답 dict) 를 돌려줍니다.
정답 dict 의 pii 는 [{"type", "value"}] — 평가 스크립트가 재현율 계산에 사용합니다.
"""
from __future__ import annotations

import os
import random

import qrcode
from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = [
    os.environ.get("PL_FONT", ""),
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "C:/Windows/Fonts/malgun.ttf",                     # Windows
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",      # macOS
]


def font(size: int) -> ImageFont.FreeTypeFont:
    for p in FONT_CANDIDATES:
        if p and os.path.exists(p):
            # .ttc 의 1번 인덱스가 KR 인 경우가 많지만, 0번도 한글 글리프를 포함
            return ImageFont.truetype(p, size, index=1 if p.endswith(".ttc") else 0)
    raise RuntimeError("한글 폰트를 찾을 수 없습니다. 환경변수 PL_FONT 에 .ttf 경로를 지정하세요.")


def _qr(text: str, size: int) -> Image.Image:
    q = qrcode.QRCode(border=1, box_size=10)
    q.add_data(text)
    q.make(fit=True)
    return q.make_image(fill_color="black", back_color="white").convert("RGB").resize((size, size), Image.NEAREST)


def parcel_label(d: dict, with_qr: bool, rng: random.Random) -> tuple[Image.Image, dict]:
    W, H = 900, 600
    im = Image.new("RGB", (W, H), "white")
    g = ImageDraw.Draw(im)
    g.rectangle([4, 4, W - 5, H - 5], outline="black", width=4)
    g.text((24, 18), d["courier"], font=font(44), fill="black")
    g.text((520, 30), f"운송장번호 {d['tracking'][:4]}-{d['tracking'][4:8]}-{d['tracking'][8:]}", font=font(26), fill="black")
    g.line([4, 90, W - 5, 90], fill="black", width=3)
    y = 110
    g.text((24, y), "받는분", font=font(28), fill="black")
    g.text((150, y), f"{d['to_name']}   {d['to_phone']}", font=font(40), fill="black")
    y += 64
    # 주소가 길면 두 줄로
    addr = d["to_addr"]
    cut = addr.find(",")
    lines = [addr[:cut], addr[cut + 2:]] if cut > 0 else [addr]
    for ln in lines:
        g.text((150, y), ln, font=font(34), fill="black")
        y += 50
    g.line([4, 300, W - 5, 300], fill="black", width=2)
    g.text((24, 320), "보내는분", font=font(24), fill="black")
    g.text((150, 318), f"{d['from_name']}   {d['from_phone']}", font=font(28), fill="black")
    g.text((24, 380), f"품명: {d['item']}", font=font(26), fill="black")
    # 바코드 흉내 (세로 줄)
    x = 24
    while x < 480:
        w = rng.choice([2, 3, 5])
        g.rectangle([x, 450, x + w, 560], fill="black")
        x += w + rng.choice([2, 3, 4])
    url = None
    if with_qr:
        url = f"https://track.example.com/p/{d['tracking']}"
        im.paste(_qr(url, 150), (W - 190, 420))

    pii = [
        {"type": "person_name", "value": d["to_name"]},
        {"type": "phone", "value": d["to_phone"]},
        {"type": "address", "value": d["to_addr"]},
        {"type": "tracking_number", "value": d["tracking"]},
        {"type": "person_name", "value": d["from_name"]},
        {"type": "phone", "value": d["from_phone"]},
    ]
    if url:
        pii.append({"type": "url", "value": url})
    return im, {"label": "parcel_label", "pii": pii}


def student_id(d: dict, rng: random.Random) -> tuple[Image.Image, dict]:
    W, H = 540, 860
    im = Image.new("RGB", (W, H), (235, 242, 250))
    g = ImageDraw.Draw(im)
    g.rectangle([0, 0, W, 120], fill=(20, 60, 120))
    g.text((30, 30), d["school"], font=font(50), fill="white")
    g.text((30, 140), "STUDENT ID CARD  학생증", font=font(26), fill=(20, 60, 120))
    # 사진 자리 (얼굴 대신 회색 실루엣)
    g.rectangle([150, 200, 390, 500], fill=(190, 195, 205))
    g.ellipse([215, 240, 325, 350], fill=(150, 155, 165))
    g.rectangle([190, 370, 350, 500], fill=(150, 155, 165))
    g.text((60, 540), f"성명  {d['name']}", font=font(40), fill="black")
    g.text((60, 610), f"학번  {d['number']}", font=font(40), fill="black")
    g.text((60, 680), f"소속  {d['dept']}", font=font(34), fill="black")
    pii = [
        {"type": "person_name", "value": d["name"]},
        {"type": "student_number", "value": d["number"]},
        {"type": "affiliation", "value": d["school"]},
    ]
    return im, {"label": "student_id", "pii": pii}
