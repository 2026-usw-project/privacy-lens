"""합성 사진으로 학습 데이터를 채운다(첫 모델 + 실사로 채우기 어려운 빈 곳).

가상 송장·학생증·명찰·화면을 배경에 원근 변환으로 붙이면 꼭짓점 좌표를 알고 있으니
라벨이 자동으로 나온다. 한국에서 볼 법한 모양을 본뜨되, 실제 택배사·학교 이름과 로고는
쓰지 않는다(samples.make_sample 의 가로형 송장만 예전 그대로).

  송장    가로형(samples) · 세로형 라벨 · 소형 스티커(이름·번호 일부 가림 포함). 바코드·QR 도 박스
  학생증  가로형·세로형·밝은 카드(잔무늬·사진 오른쪽), 반사광. 증명사진(실루엣·그림 얼굴)·바코드도 박스
  명찰    가슴 명찰 · 행사 이름표 · 책상 이름표
  화면    휴대폰·모니터에 가짜 메신저·주문내역·택배 조회·메일. **화면 부분만** 박스(테두리 제외)
  방해물  송장이 아닌 한국어 서류·메모·영수증(박스 없음). 글자 있는 종이를 송장으로 착각하지 않게
  크기    40% 는 사진 짧은 변의 5~20% 로 작게. 서비스가 노리는 '배경에 작게 찍힌' 경우다
  놓임    30% 는 기대 세운 원근, 35% 는 책등·물건에 일부 가려짐(박스는 보이는 부분만)
  배경    데이터셋에 물체 없는 사진(직접 찍은 배경, import-bg 로 넣은 공개·AI 배경)이 있으면
          절반은 그 위에, 나머지는 만든 무늬 위에

합성 사진은 **학습(train)에만** 들어간다. 점수는 실사 val/test 로만 잰다.
"""

from __future__ import annotations

import datetime as dt
import random
import sys
from pathlib import Path

import cv2
import numpy as np
import qrcode
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from .classes import NAMES
from .workspace import DONE, Row, Workspace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from samples.fonts import find_korean_font  # noqa: E402
from samples.make_sample import GIVEN, SURNAMES, make_waybill  # noqa: E402

GEN = 3  # 생성기 버전. 파일 이름에 넣어 예전 합성(syn000…)과 겹치지 않게 한다
FONT, FONT_BOLD = find_korean_font()
_IDX = {n: i for i, n in NAMES.items()}
WAYBILL, ID_CARD, NAME_TAG, SCREEN = (_IDX[n] for n in ("waybill", "id_card", "name_tag", "screen"))
FACE, CODE = _IDX["face_photo"], _IDX["barcode"]

# 모두 가상의 이름이다
SCHOOLS = ["한빛대학교", "새솔대학교", "가람대학교", "누리대학교", "다온대학교", "미르대학교"]
DEPTS = ["정보보호학과", "컴퓨터학부", "경영학과", "디자인학과", "간호학과", "기계공학과"]
COURIERS = ["렌즈택배", "한빛로지스", "새솔익스프레스", "가람택배", "누리배송"]
CITIES = [("서울특별시", "마포구"), ("경기도", "수원시 권선구"), ("부산광역시", "해운대구"),
          ("대구광역시", "수성구"), ("인천광역시", "연수구"), ("대전광역시", "유성구"), ("광주광역시", "북구")]
ROADS = ["가람로", "새솔길", "한빛대로", "누리로", "다온길", "미르로", "보람로"]
APTS = ["프라이버시아파트", "렌즈빌", "가람마을", "새솔타운", "누리하이츠"]
ITEMS = ["무선 이어폰", "운동화", "책 2권", "생활용품", "키보드", "화장품 세트"]
ORGS = ["2026 정보보호 세미나", "프라이버시 렌즈 워크숍", "가람대학교 축제", "신입생 오리엔테이션"]
DISTRACT = ["노트북", "회의 자료", "2026 다이어리", "COFFEE", "책상 정리", "SALE 30%", "메모"]
PALETTE = [(28, 70, 140), (20, 110, 90), (130, 40, 50), (60, 60, 70), (170, 90, 20), (90, 50, 140)]


def _font(size: int, bold: bool = False):
    return ImageFont.truetype(FONT_BOLD if bold else FONT, max(8, int(size)))


def _name(rng) -> str:
    return rng.choice(SURNAMES) + rng.choice(GIVEN)


def _phone(rng, masked=False) -> str:
    mid = "****" if masked else str(rng.randint(1000, 9999))
    return f"010-{mid}-{rng.randint(1000, 9999)}"


def _address(rng) -> tuple[str, str]:
    city, gu = rng.choice(CITIES)
    return (f"{city} {gu} {rng.choice(ROADS)} {rng.randint(1, 300)}",
            f"{rng.choice(APTS)} {rng.randint(101, 120)}동 {rng.randint(1, 25)}0{rng.randint(1, 4)}호")


def _barcode(d, rng, x, y, w, h):
    cx = x
    while cx < x + w:
        bw = rng.choice([2, 3, 4, 6])
        if rng.random() < 0.55:
            d.rectangle([cx, y, min(cx + bw - 1, x + w), y + h], fill=(15, 15, 15))
        cx += bw
    return [x, y, x + w, y + h]


def _qr(img, rng, x, y, size):
    img.paste(qrcode.make(f"https://example.com/t/{rng.randint(10**8, 10**9)}").resize((size, size)), (x, y))
    return [x, y, x + size, y + size]


def _centered(d, text, y, W, font, fill):
    d.text(((W - d.textlength(text, font=font)) / 2, y), text, font=font, fill=fill)


# ------------------------------------------------------------------ 물체들
# 각 함수는 (그림, 물체 전체의 클래스 또는 None, [(클래스, 그림 안 사각형), …]) 을 돌려준다

def waybill_vertical(rng):
    W, H = 500, 760
    img = Image.new("RGB", (W, H), (252, 252, 248))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W - 1, H - 1], outline=(40, 40, 40), width=3)
    d.rectangle([0, 0, W, 70], fill=rng.choice(PALETTE))
    d.text((20, 18), rng.choice(COURIERS), font=_font(30, True), fill="white")
    d.text((20, 85), f"운송장번호 {rng.randint(1000, 9999)}-{rng.randint(1000, 9999)}-{rng.randint(1000, 9999)}",
           font=_font(20, True), fill=(30, 30, 30))
    parts = [(CODE, _barcode(d, rng, 20, 118, 460, 80))]
    y = 222
    line1, line2 = _address(rng)
    for label, value, size in [("받는 분", _name(rng), 34), ("연락처", _phone(rng), 26),
                               ("주소", line1, 20), ("", line2, 20)]:
        if label:
            d.text((20, y + 6), label, font=_font(17), fill=(110, 110, 110))
        d.text((110, y), value, font=_font(size, True), fill=(20, 20, 20))
        y += size + 22
    d.line([15, y, W - 15, y], fill=(120, 120, 120), width=2)
    y += 14
    d.text((20, y), f"보내는 분  {_name(rng)}  {_phone(rng, masked=True)}", font=_font(17), fill=(70, 70, 70))
    d.text((20, y + 30), f"품목  {rng.choice(ITEMS)}", font=_font(17), fill=(70, 70, 70))
    parts.append((CODE, _qr(img, rng, W - 150, H - 150, 130)))
    return img, WAYBILL, parts


def waybill_sticker(rng):
    W, H = 440, 270
    img = Image.new("RGB", (W, H), (255, 255, 252))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W - 1, H - 1], outline=(70, 70, 70), width=2)
    d.text((14, 10), rng.choice(COURIERS), font=_font(20, True), fill=rng.choice(PALETTE))
    masked = rng.random() < 0.5  # 이름·번호 일부를 * 로 가린 스티커도 흔하다
    name = _name(rng)
    name = name[0] + "*" + name[2:] if masked and len(name) > 2 else name
    d.text((14, 48), name, font=_font(34, True), fill=(20, 20, 20))
    d.text((14, 98), _phone(rng, masked=masked), font=_font(22), fill=(30, 30, 30))
    d.text((14, 132), _address(rng)[0], font=_font(16), fill=(40, 40, 40))
    return img, WAYBILL, [(CODE, _barcode(d, rng, 14, 170, 410, 70))]


def waybill_classic(rng):
    img, _labels = make_waybill(rng.randint(0, 10_000))
    return img, WAYBILL, [(CODE, [570, 310, 688, 428])]  # make_waybill 의 QR 위치


def _face(pw: int, ph: int, rng) -> Image.Image:
    """증명사진 자리. 실루엣이나 단순한 그림 얼굴만 그린다(실존 인물 사진은 쓰지 않는다)."""
    photo = Image.new("RGB", (pw, ph), rng.choice([(205, 212, 222), (230, 232, 236), (210, 225, 240), (245, 245, 245)]))
    d = ImageDraw.Draw(photo)
    if rng.random() < 0.4:
        d.ellipse([pw * .3, ph * .15, pw * .7, ph * .5], fill=(150, 158, 170))
        d.ellipse([pw * .13, ph * .55, pw * .87, ph * 1.2], fill=(150, 158, 170))  # 아래는 사진 칸에서 잘린다
        return photo
    skin = rng.choice([(241, 206, 175), (224, 180, 140), (198, 150, 110), (250, 220, 195)])
    d.ellipse([pw * .12, ph * .62, pw * .88, ph * 1.25],
              fill=rng.choice([(30, 40, 60), (240, 240, 240), (70, 70, 75), (110, 30, 40)]))  # 어깨·옷
    d.rectangle([pw * .42, ph * .5, pw * .58, ph * .68], fill=skin)                        # 목
    d.ellipse([pw * .28, ph * .14, pw * .72, ph * .6], fill=skin)                          # 얼굴
    d.chord([pw * .25, ph * .06, pw * .75, ph * .46], 180, 360,
            fill=rng.choice([(25, 20, 20), (60, 40, 30), (90, 70, 50)]))                   # 머리
    for ex in (.38, .57):
        d.ellipse([pw * ex, ph * .33, pw * (ex + .05), ph * .36], fill=(40, 30, 30))      # 눈
    d.line([pw * .45, ph * .48, pw * .55, ph * .48], fill=(150, 80, 80), width=max(1, pw // 60))
    return photo


def _glare(img: Image.Image, rng, strength=(40, 90)) -> None:
    """코팅·플라스틱 카드의 비스듬한 반사광."""
    W, H = img.size
    g = Image.new("L", (W, H), 0)
    x, w = rng.uniform(-0.3, 0.8) * W, rng.uniform(0.1, 0.3) * W
    ImageDraw.Draw(g).polygon([(x, 0), (x + w, 0), (x + w - 0.4 * W, H), (x - 0.4 * W, H)],
                              fill=rng.randint(*strength))
    img.paste(Image.new("RGB", (W, H), (255, 255, 255)), (0, 0), g.filter(ImageFilter.GaussianBlur(W * 0.03)))


def id_card(rng):
    # 'light' 는 밝은 바탕·얇은 띠·잔무늬·사진 오른쪽인 신분증류 카드의 공통 모양(특정 신분증을 본뜨지 않음)
    style = rng.choice(["band", "band", "light"])
    vertical = style == "band" and rng.random() < 0.35
    W, H = (400, 640) if vertical else (640, 400)
    color = rng.choice(PALETTE)
    img = Image.new("RGB", (W, H), (248, 248, 246) if style == "band" else (252, 252, 250))
    d = ImageDraw.Draw(img)
    if style == "band":
        d.rectangle([0, 0, W, 78], fill=color)
        d.text((24, 20), rng.choice(SCHOOLS), font=_font(28, True), fill="white")
        d.text((W - 140, 30), "STUDENT ID", font=_font(16), fill=(230, 230, 240))
    else:
        for k in range(14):  # 옅은 잔무늬
            pts = [(x, 200 + 120 * np.sin(x / (40 + k * 7) + k)) for x in range(0, W, 8)]
            d.line(pts, fill=tuple(min(255, c + 150) for c in color), width=1)
        d.rectangle([0, 0, W, 10], fill=color)
        d.text((30, 26), rng.choice(SCHOOLS + ["렌즈전자", "가람상사", "누리시청"]), font=_font(26, True), fill=color)
    if vertical:
        px, py, pw, ph = (W - 170) // 2, 105, 170, 210
        tx, ty = 40, 340
    else:
        left = style == "band" and rng.random() < 0.7
        px, py, pw, ph = (30 if left else W - 180), (105 if style == "band" else 80), 150, 190
        tx, ty = (210 if left else 30), (112 if style == "band" else 95)
    img.paste(_face(pw, ph, rng), (px, py))
    parts = [(FACE, [px, py, px + pw, py + ph])]
    for i, (label, value, size) in enumerate([("성명", _name(rng), 30), ("학과", rng.choice(DEPTS), 22),
                                              ("학번", f"20{rng.randint(19, 26)}{rng.randint(10000, 99999)}", 22)]):
        y = ty + i * 50
        d.text((tx, y + 6), label, font=_font(17), fill=(110, 110, 115))
        d.text((tx + 66, y), value, font=_font(size, size > 24), fill=(20, 20, 24))
    if rng.random() < (0.7 if style == "band" else 0.4):
        bx, by = (40, H - 90) if vertical else (tx, 300)
        parts.append((CODE, _barcode(d, rng, bx, by, min(380, W - bx - 30), 60)))
    if rng.random() < 0.5:
        _glare(img, rng)
    return img, ID_CARD, parts


def name_tag(rng):
    kind = rng.choice(["chest", "event", "desk"])
    name, org = _name(rng), rng.choice(ORGS)
    if kind == "chest":
        W, H = 380, 140
        img = Image.new("RGB", (W, H), rng.choice([(255, 255, 255), (245, 240, 225)]))
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, W, 34], fill=rng.choice(PALETTE))
        d.text((12, 5), rng.choice(SCHOOLS + ["렌즈전자", "가람상사"]), font=_font(18, True), fill="white")
        _centered(d, name, 46, W, _font(54, True), (20, 20, 20))
    elif kind == "event":
        W, H = 420, 320
        img = Image.new("RGB", (W, H), (255, 255, 255))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([W // 2 - 40, 14, W // 2 + 40, 30], radius=8, fill=(200, 200, 200))  # 끈 구멍
        d.rectangle([0, 44, W, 100], fill=rng.choice(PALETTE))
        _centered(d, org, 58, W, _font(24, True), (255, 255, 255))
        _centered(d, name, 130, W, _font(76, True), (20, 20, 20))
        _centered(d, rng.choice(DEPTS), 240, W, _font(24), (80, 80, 80))
    else:
        W, H = 720, 200
        img = Image.new("RGB", (W, H), rng.choice([(250, 250, 250), (235, 240, 248)]))
        d = ImageDraw.Draw(img)
        d.rectangle([0, H - 26, W, H], fill=rng.choice(PALETTE))
        _centered(d, rng.choice(["팀장", "과장", "주임", "연구원", "조교"]), 16, W, _font(26), (90, 90, 90))
        _centered(d, name, 56, W, _font(88, True), (20, 20, 20))
    d.rectangle([0, 0, W - 1, H - 1], outline=(150, 150, 150), width=2)
    if rng.random() < 0.3:  # 명찰 케이스 반사
        _glare(img, rng, (30, 70))
    return img, NAME_TAG, []


def _screen_content(rng, W, H) -> Image.Image:
    app = rng.choice(["chat", "order", "track", "mail"])
    dark = rng.random() < 0.25
    bg, fg, sub = ((24, 26, 30), (235, 235, 235), (150, 150, 155)) if dark else \
        ((255, 255, 255), (25, 25, 25), (120, 120, 125))
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    s = min(W / 360, H / 560)  # 글자 크기 기준(휴대폰 360×560 기준). 모니터는 높이에 맞춘다
    title = {"chat": _name(rng), "order": "주문 상세", "track": "배송 조회", "mail": "받은편지함"}[app]
    d.rectangle([0, 0, W, 56 * s], fill=rng.choice(PALETTE))
    d.text((16 * s, 14 * s), title, font=_font(22 * s, True), fill="white")
    y = 72 * s
    line1, line2 = _address(rng)
    if app == "chat":
        msgs = ["택배 받았어?", "주소 다시 보내줄게", line1, line2, f"연락처 {_phone(rng)}", "고마워!"]
        for i, m in enumerate(msgs):
            right = i % 2 == 1
            tw = d.textlength(m, font=_font(16 * s)) + 24 * s
            x = W - tw - 14 * s if right else 14 * s
            d.rounded_rectangle([x, y, x + tw, y + 34 * s], radius=12 * s,
                                fill=(255, 228, 77) if right else ((60, 62, 68) if dark else (238, 238, 240)))
            d.text((x + 12 * s, y + 7 * s), m, font=_font(16 * s), fill=(20, 20, 20) if right else fg)
            y += 46 * s
    else:
        rows = {
            "order": [("상품", rng.choice(ITEMS)), ("받는 분", _name(rng)), ("연락처", _phone(rng)),
                      ("배송지", line1), ("", line2), ("결제 금액", f"{rng.randint(1, 99) * 1000:,}원")],
            "track": [("운송장번호", f"{rng.randint(1000, 9999)}-{rng.randint(1000, 9999)}-{rng.randint(1000, 9999)}"),
                      ("택배사", rng.choice(COURIERS)), ("받는 분", _name(rng)), ("현재 상태", "배송 출발"),
                      ("", "10.14 09:12 간선 하차"), ("", "10.13 22:40 집하")],
            "mail": [("보낸 사람", f"{_name(rng)} <lens{rng.randint(1, 99)}@example.com>"), ("제목", "주문하신 상품 안내"),
                     ("", "안녕하세요, 배송지를 확인해 주세요."), ("", line1), ("", f"문의 {_phone(rng)}")],
        }[app]
        for label, value in rows:
            if label:
                d.text((16 * s, y), label, font=_font(14 * s), fill=sub)
            d.text((16 * s, y + 18 * s), value, font=_font(17 * s, bool(label)), fill=fg)
            y += 48 * s
    return img


def screen(rng):
    if rng.random() < 0.55:  # 휴대폰
        W, H, m, top = 320, 640, 12, 40
    else:                    # 모니터·노트북 화면
        W, H, m, top = 760, 480, 22, 22
    img = Image.new("RGB", (W, H), (20, 20, 22))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, W - 1, H - 1], radius=28 if W < H else 10, fill=(18, 18, 20), outline=(70, 70, 75))
    rect = [m, top, W - m, H - m]
    content = _screen_content(rng, rect[2] - rect[0], rect[3] - rect[1])
    img.paste(content, (rect[0], rect[1]))
    if rng.random() < 0.4:  # 화면 반사
        glare = Image.new("L", content.size, 0)
        ImageDraw.Draw(glare).polygon([(0, 0), (content.width * .6, 0), (0, content.height * .5)], fill=40)
        img.paste(Image.new("RGB", content.size, (255, 255, 255)), (rect[0], rect[1]), glare)
    return img, None, [(SCREEN, rect)]  # 기기 테두리는 박스 안 함


def paper(rng):
    """방해물: 송장이 아닌 한국어 종이. 박스 없음."""
    W, H = rng.choice([(500, 700), (420, 600), (300, 520)])
    img = Image.new("RGB", (W, H), rng.choice([(252, 252, 250), (248, 244, 232), (240, 246, 250)]))
    d = ImageDraw.Draw(img)
    kind = rng.choice(["회의록", "공지사항", "영수증", "견적서", "안내문", "메모"])
    _centered(d, kind, 24, W, _font(30, True), (30, 30, 30))
    y = 90
    words = ["일정", "참석", "안건", "검토", "예산", "확인", "자료", "제출", "변경", "결과", "다음", "주간"]
    while y < H - 40:
        if kind == "영수증":
            d.text((24, y), f"{rng.choice(ITEMS)}", font=_font(16), fill=(50, 50, 50))
            d.text((W - 110, y), f"{rng.randint(1, 50) * 1000:,}", font=_font(16), fill=(50, 50, 50))
        else:
            d.text((24, y), " ".join(rng.choice(words) for _ in range(rng.randint(3, 7))), font=_font(17), fill=(60, 60, 60))
        y += rng.randint(28, 40)
    return img, None, []


MAKERS = [(waybill_classic, 0.10), (waybill_vertical, 0.12), (waybill_sticker, 0.08),
          (id_card, 0.24), (name_tag, 0.16), (screen, 0.20), (paper, 0.10)]


# ------------------------------------------------------------------ 장면

def _background(rng: random.Random, W: int, H: int, photos=()) -> Image.Image:
    if photos and rng.random() < 0.5:
        with Image.open(rng.choice(photos)) as im:
            return ImageOps.fit(ImageOps.exif_transpose(im).convert("RGB"), (W, H))
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
    tw, th = ow * scale, oh * scale
    cx = rng.uniform(tw * 0.6, W - tw * 0.6)
    cy = rng.uniform(th * 0.6, H - th * 0.6)
    ang = np.deg2rad(rng.uniform(-35, 35) + (180 if rng.random() < 0.08 else 0))
    corners = np.array([[-tw / 2, -th / 2], [tw / 2, -th / 2], [tw / 2, th / 2], [-tw / 2, th / 2]])
    if rng.random() < 0.3:  # 책장·벽에 기대 세운 모양: 윗변이 좁고 짧아 보인다
        k = rng.uniform(0.1, 0.3)
        corners[0, 0] += tw * k / 2
        corners[1, 0] -= tw * k / 2
        corners[[0, 1], 1] += th * rng.uniform(0.0, 0.3)
        ang = np.deg2rad(rng.uniform(-12, 12))
    rot = np.array([[np.cos(ang), -np.sin(ang)], [np.sin(ang), np.cos(ang)]])
    dst = corners @ rot.T + [cx, cy]
    dst += np.array([[rng.uniform(-1, 1) * tw * 0.06, rng.uniform(-1, 1) * th * 0.06] for _ in range(4)])
    src = np.float32([[0, 0], [ow, 0], [ow, oh], [0, oh]])
    M = cv2.getPerspectiveTransform(src, dst.astype(np.float32))
    warped = cv2.warpPerspective(np.array(obj.convert("RGB")), M, (W, H), flags=cv2.INTER_AREA)
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


def _occlude(bg: np.ndarray, mask: np.ndarray, rng, blocked: np.ndarray) -> np.ndarray | None:
    """물체 한쪽을 책등·물건 같은 막대로 가리고, 가린 영역(True)을 돌려준다. 최대 40% 까지만 가린다.

    막대가 먼저 붙인 다른 물체(blocked)에 닿으면 그 물체의 라벨이 틀어지므로 가리지 않는다(None).
    """
    H, W = bg.shape[:2]
    ys, xs = np.nonzero(mask > 8)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    w, h, f = x1 - x0, y1 - y0, rng.uniform(0.15, 0.4)
    side = rng.choice(["left", "right", "bottom"])
    if side == "left":
        r = (x0 - int(w * rng.uniform(0.1, 0.6)), y0 - int(h * .3), x0 + int(w * f), y1 + int(h * .3))
    elif side == "right":
        r = (x1 - int(w * f), y0 - int(h * .3), x1 + int(w * rng.uniform(0.1, 0.6)), y1 + int(h * .3))
    else:
        r = (x0 - int(w * .3), y1 - int(h * f), x1 + int(w * .3), y1 + int(h * rng.uniform(0.1, 0.6)))
    rx0, ry0, rx1, ry1 = max(0, r[0]), max(0, r[1]), min(W, r[2]), min(H, r[3])
    if blocked[ry0:ry1, rx0:rx1].any():
        return None
    bg[ry0:ry1, rx0:rx1] = [rng.randint(20, 220) for _ in range(3)]
    for _ in range(rng.randint(0, 3)):  # 책등 띠
        if side == "bottom":
            yy = rng.randint(ry0, max(ry0, ry1 - 3))
            bg[yy:yy + 3, rx0:rx1] = [rng.randint(150, 255) for _ in range(3)]
        else:
            xx = rng.randint(rx0, max(rx0, rx1 - 3))
            bg[ry0:ry1, xx:xx + 3] = [rng.randint(150, 255) for _ in range(3)]
    occ = np.zeros((H, W), bool)
    occ[ry0:ry1, rx0:rx1] = True
    return occ


def _visible_box(M, rect, occ: np.ndarray, W: int, H: int, keep: float = 0.5):
    """가려진 물체는 **보이는 부분만** 박스. 절반 넘게 가려진 부분(증명사진·바코드)은 박스를 안 친다."""
    x1, y1, x2, y2 = rect
    pts = cv2.perspectiveTransform(np.float32([[[x1, y1]], [[x2, y1]], [[x2, y2]], [[x1, y2]]]), M).reshape(-1, 2)
    region = np.zeros((H, W), np.uint8)
    cv2.fillConvexPoly(region, np.round(pts).astype(np.int32), 1)
    total = int(region.sum())
    vis = region.astype(bool) & ~occ
    if total == 0 or vis.sum() < keep * total:
        return None
    ys, xs = np.nonzero(vis)
    xa, xb, ya, yb = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    if xb - xa < 4 or yb - ya < 4:
        return None
    return ((xa + xb) / 2 / W, (ya + yb) / 2 / H, (xb - xa) / W, (yb - ya) / H)


def make_scene(seed: int, photos=()) -> tuple[Image.Image, list[str]]:
    rng = random.Random(seed)
    W, H = rng.choice([(1920, 1440), (1600, 1200), (1440, 1920), (2048, 1536)])
    bg = np.array(_background(rng, W, H, photos))
    lines: list[str] = []
    occupied = np.zeros((H, W), np.uint8)
    placed: list[np.ndarray] = []

    n_obj = 0 if rng.random() < 0.15 else rng.choice([1, 1, 2, 2, 3])  # 15% 는 물체 없는 사진
    for _ in range(n_obj):
        maker = rng.choices([m for m, _ in MAKERS], weights=[w for _, w in MAKERS])[0]
        obj, cls, parts = maker(rng)
        small = rng.random() < 0.4
        target = rng.uniform(0.05, 0.2) if small else rng.uniform(0.2, 0.6)  # 짧은 변 대비 긴 변
        scale = target * min(W, H) / max(obj.size)
        trial = bg.copy()
        M, mask = _paste(trial, obj, rng, scale)
        new = mask > 8
        # 겹치면 다음. 새 물체 기준뿐 아니라 먼저 붙인 물체를 5% 넘게 덮어도 안 된다(그 물체 라벨이 틀어진다)
        if (occupied[new] > 0).mean() > 0.05 or any((m & new).sum() > 0.05 * m.sum() for m in placed):
            continue
        bg = trial
        blocked = occupied > 0
        occupied |= new.astype(np.uint8)
        placed.append(new)
        whole = [(cls, [0, 0, obj.width, obj.height])] if cls is not None else []
        occ = _occlude(bg, mask, rng, blocked) if whole and rng.random() < 0.35 else None  # 책 사이에 꽂힘
        if occ is not None:
            occupied |= occ.astype(np.uint8)
        for i, (c, rect) in enumerate(whole + parts):
            # 물체 전체는 조금만 보여도 박스(안 치면 '배경'으로 배운다), 증명사진·바코드는 절반 이상 보일 때만
            keep = 0.2 if whole and i == 0 else 0.5
            b = _box_from(M, rect, W, H) if occ is None else _visible_box(M, rect, occ, W, H, keep)
            if b:
                lines.append(f"{c} {b[0]:.6f} {b[1]:.6f} {b[2]:.6f} {b[3]:.6f}")

    out = Image.fromarray(bg)
    if rng.random() < 0.5:  # 조명
        out = ImageEnhance.Brightness(out).enhance(rng.uniform(0.6, 1.3))
        out = ImageEnhance.Contrast(out).enhance(rng.uniform(0.7, 1.2))
    if rng.random() < 0.3:  # 흔들림·흐림
        out = Image.fromarray(cv2.GaussianBlur(np.array(out), (0, 0), rng.uniform(0.6, 1.8)))
    return out, lines


def _background_photos(ws: Workspace, rows) -> list[Path]:
    """데이터셋의 물체 없는 사진(빈 라벨): 직접 찍은 배경과 import-bg 로 넣은 공개·AI 배경. 합성 배경으로 쓴다."""
    out = []
    for r in rows.values():
        if r.status == DONE and r.source in ("real", "public"):
            label = ws.dataset / "labels" / f"{r.id}.txt"
            img = ws.dataset / "images" / f"{r.id}.jpg"
            if img.exists() and label.exists() and not label.read_text(encoding="utf-8").strip():
                out.append(img)
    return out


def run(ws: Workspace, n: int = 200, seed: int = 0) -> None:
    ws.init()
    rows = ws.load()
    photos = _background_photos(ws, rows)
    if photos:
        print(f"물체 없는 배경 사진 {len(photos)}장을 합성 배경으로 섞어 씁니다.")
    made = 0
    for i in range(n):
        s = seed + i
        fid = f"syn{GEN}_{s:07d}"
        if fid in rows:
            continue
        img, lines = make_scene(s, photos)
        img.save(ws.dataset / "images" / f"{fid}.jpg", "JPEG", quality=random.Random(s).randint(70, 92))
        (ws.dataset / "labels" / f"{fid}.txt").write_text(
            "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        rows[fid] = Row(id=fid, group=f"synth{GEN}_{s // 50}", source="synth", split="train",
                        status=DONE, added_at=dt.datetime.now().isoformat(timespec="seconds"),
                        orig_name="", prelabel="")
        made += 1
    ws.save(rows)
    from .build import write_lists
    write_lists(ws, rows)
    print(f"합성 사진 {made}장을 학습 데이터에 넣었습니다(train 전용, 생성기 {GEN}).")
