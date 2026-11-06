"""촬영용 소품 — 가상 개인정보를 인쇄해 실제로 찍는다.

실사 평가 사진에 진짜 개인정보를 쓰지 않으려면 두 가지 방법이 있다.
  1. 팀원 본인 물건을 찍고 번호를 포스트잇으로 가린다(문서 모양이 진짜)
  2. 이 소품을 인쇄해 찍는다(글자가 전부 가짜라 가릴 필요가 없고, 정답이 미리 정해져 있다)

이 파일은 2번이다. A4 에 실제 크기로 소품을 배치한 인쇄용 PDF 와, 소품마다 무엇이 적혀
있고 어떻게 판정해야 하는지를 담은 'props.json' 을 만든다. 정답 입력 도구
(eval/gold_tool.html)는 같은 폴더의 props.json 을 읽어 소품 번호만 고르면 정답을 채운다.

    python -m samples.props <출력 폴더> [--sets 2] [--seed 1]

주의
  - 배치는 국내 실물(대형 택배사 송장, 체크카드 겸용 학생증, POS 영수증, 배달 주문서,
    창봉투 우편물)을 따르되 상호·로고는 전부 가상이다. 카드·학생증에는 '견본' 표시를 넣는다.
  - 주민등록증·운전면허증·여권은 흉내 내지 않는다(공문서 모양 재현은 하지 않는다).
  - 대형 택배사 송장은 이름 가운데 글자·전화 가운데 자리를 가려 찍는다(홍*동, 010-****-1234).
    이 가린 값의 등급은 기준표에 없어 '이름=확인 필요, 전화=가리지 않음'으로 임시로 둔다.
  - 정답 등급은 docs/MASKING_CRITERIA.md 를 따른다. 기준이 바뀌면 여기도 바꾼다.
  - 인쇄물은 실제 송장(감열지)·카드(플라스틱)와 질감이 다르다. 그래서 1번 사진도 함께 찍는다.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from samples.fake import BANKS, COMPANIES, NAME_LIKE_WORDS, SCHOOLS, Fake  # noqa: E402
from samples.fonts import find_korean_font  # noqa: E402

DPI = 200
MM = DPI / 25.4                     # 1mm 당 픽셀
A4 = (round(210 * MM), round(297 * MM))
MARGIN = round(10 * MM)
GAP = round(6 * MM)

FONT_REGULAR, FONT_BOLD = find_korean_font()
_FONTS: dict[tuple[float, bool], ImageFont.FreeTypeFont] = {}


def font(mm: float, bold: bool = False) -> ImageFont.FreeTypeFont:
    """글자 높이를 mm 로. 실제 문서의 글자 크기에 맞춰 찍혀야 OCR 난이도가 현실과 같다."""
    key = (mm, bold)
    if key not in _FONTS:
        _FONTS[key] = ImageFont.truetype((FONT_BOLD or FONT_REGULAR) if bold else FONT_REGULAR, round(mm * MM * 1.35))
    return _FONTS[key]


@dataclass
class Prop:
    pid: str
    kind: str
    size_mm: tuple[float, float]
    items: list[dict] = field(default_factory=list)   # {"text", "item", "expect"}
    image: Image.Image | None = None

    def add(self, text: str, item: str, expect: str) -> str:
        self.items.append({"text": text, "item": item, "expect": expect})
        return text


class Canvas:
    """mm 좌표로 그리는 작은 도화지."""

    def __init__(self, prop: Prop, bg=(252, 251, 247)):
        self.prop = prop
        w, h = prop.size_mm
        self.img = Image.new("RGB", (round(w * MM), round(h * MM)), bg)
        self.d = ImageDraw.Draw(self.img)

    def text(self, x, y, s, mm=3.0, bold=False, fill=(25, 25, 28)):
        self.d.text((x * MM, y * MM), s, font=font(mm, bold), fill=fill)

    def rect(self, x0, y0, x1, y1, fill=None, outline=None, width=1):
        self.d.rectangle([x0 * MM, y0 * MM, x1 * MM, y1 * MM], fill=fill, outline=outline, width=width)

    def line(self, x0, y0, x1, y1, fill=(190, 188, 182), width=2):
        self.d.line([(x0 * MM, y0 * MM), (x1 * MM, y1 * MM)], fill=fill, width=width)

    def finish(self, sample_mark: bool = False) -> Image.Image:
        w, h = self.prop.size_mm
        if sample_mark:  # 실제 카드·신분증으로 오해받지 않게
            mark = "견본 SAMPLE"
            tw = self.d.textlength(mark, font=font(2.2, True)) / MM
            self.text(w - tw - 2.5, h - 5.5, mark, 2.2, True, (200, 60, 50))
        self.d.text((1.2 * MM, 0.6 * MM), self.prop.pid, font=font(1.6), fill=(170, 168, 160))
        self.prop.image = self.img
        return self.img


LABEL = (120, 120, 125)
INK = (25, 25, 28)


def mono(mm: float, bold: bool = False) -> ImageFont.FreeTypeFont:
    """영수증·주문서용 고정폭 글꼴. 없으면 일반 글꼴."""
    key = (mm, bold, "mono")
    if key not in _FONTS:
        size = round(mm * MM * 1.35)
        for path, index in [("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else
                             "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 6),
                            (r"C:\Windows\Fonts\gulim.ttc", 1)]:
            try:
                _FONTS[key] = ImageFont.truetype(path, size, index=index)
                break
            except OSError:
                continue
        else:
            _FONTS[key] = font(mm, bold)
    return _FONTS[key]


class Draw(Canvas):
    """국내 실물 모양을 흉내 내는 데 필요한 것들: 바코드, QR 비슷한 무늬, 점선, 칩."""

    def mtext(self, x, y, s, mm=2.6, bold=False, fill=INK):
        self.d.text((x * MM, y * MM), s, font=mono(mm, bold), fill=fill)

    def rtext(self, xr, y, s, mm=2.6, bold=False, fill=INK, use_mono=False):
        f = mono(mm, bold) if use_mono else font(mm, bold)
        self.d.text((xr * MM - self.d.textlength(s, font=f), y * MM), s, font=f, fill=fill)

    def dashed(self, x0, x1, y, fill=(120, 120, 120)):
        x = x0
        while x < x1:
            self.line(x, y, min(x + 1.2, x1), y, fill, 2)
            x += 2.0

    def barcode(self, x, y, w, h, r):
        """1차원 바코드처럼 보이는 줄무늬(읽히지 않는다)."""
        cx = x
        while cx < x + w:
            bw = r.choice([0.25, 0.25, 0.5, 0.75])
            if r.random() < 0.55:
                self.rect(cx, y, min(cx + bw, x + w), y + h, fill=INK)
            cx += bw

    def qr(self, x, y, size, r, n=25):
        """QR 코드처럼 보이는 무늬. 위치 표시 세 개 + 무작위 칸(읽히지 않는다)."""
        cell = size / n
        for i in range(n):
            for j in range(n):
                if r.random() < 0.48:
                    self.rect(x + i * cell, y + j * cell, x + (i + 1) * cell, y + (j + 1) * cell, fill=INK)
        for fx, fy in [(0, 0), (n - 7, 0), (0, n - 7)]:
            X, Y = x + fx * cell, y + fy * cell
            self.rect(X, Y, X + 7 * cell, Y + 7 * cell, fill=(255, 255, 255))
            self.rect(X, Y, X + 7 * cell, Y + 7 * cell, outline=INK, width=max(1, round(cell * MM)))
            self.rect(X + 2 * cell, Y + 2 * cell, X + 5 * cell, Y + 5 * cell, fill=INK)

    def chip(self, x, y):
        self.d.rounded_rectangle([x * MM, y * MM, (x + 11) * MM, (y + 8.5) * MM], radius=1.2 * MM,
                                 fill=(212, 186, 118), outline=(150, 128, 70), width=2)
        for yy in (y + 2.8, y + 5.7):
            self.line(x, yy, x + 11, yy, (150, 128, 70), 2)
        self.line(x + 5.5, y, x + 5.5, y + 8.5, (150, 128, 70), 2)

    def contactless(self, x, y, fill):
        for k in range(4):
            r_ = (1.2 + k * 1.1) * MM
            self.d.arc([x * MM - r_, y * MM - r_, x * MM + r_, y * MM + r_], -50, 50, fill=fill, width=3)

    def photo(self, x0, y0, x1, y1):
        """증명사진 자리: 회색 바탕에 머리·어깨 실루엣(실제 얼굴 아님)."""
        self.rect(x0, y0, x1, y1, fill=(214, 218, 224))
        w, h = x1 - x0, y1 - y0
        cx = x0 + w / 2
        self.d.ellipse([(cx - w * .2) * MM, (y0 + h * .18) * MM, (cx + w * .2) * MM, (y0 + h * .55) * MM], fill=(168, 174, 184))
        self.d.ellipse([(x0 + w * .08) * MM, (y0 + h * .6) * MM, (x1 - w * .08) * MM, (y1 + h * .35) * MM], fill=(168, 174, 184))
        self.rect(x0, y1, x1, y1 + h * .4, fill=(255, 255, 255))  # 아래로 삐져나온 어깨 자르기


ROMAN_SURN = ["KIM", "LEE", "PARK", "CHOI", "JUNG", "KANG", "YOON", "HAN"]
ROMAN_GIVEN = ["MINJUN", "SEOYEON", "JIHO", "HAEUN", "DOYUN", "YEJIN", "SUAH", "JIWON"]
SHOPS = ["누리상회", "가온스토어", "한빛몰", "다온리빙"]
COURIERS = ["한빛로지스", "가온택배", "누리익스프레스"]


def mask_name(n: str) -> str:
    return n[0] + "*" + n[2:] if len(n) >= 3 else n[0] + "*"


def mask_mobile(m: str) -> str:
    a, _, c = m.split("-")
    return f"{a}-****-{c}"


def roman(f: Fake) -> str:
    return f"{f.pick(ROMAN_SURN)} {f.pick(ROMAN_GIVEN)}"


# ------------------------------------------------------------------ 소품 종류

def waybill(pid: str, f: Fake) -> Prop:
    """대형 택배사형 감열지 송장. 큰 분류 코드, 바코드, 가려진 이름·전화, 굵은 동·호수, 왼쪽 아래 QR."""
    p = Prop(pid, "송장", (123, 100))
    c = Draw(p, bg=(255, 255, 255))
    c.text(3, 2, "운송장번호", 2.2, fill=LABEL)
    t = f.tracking()
    c.text(3, 5.2, p.add(f"{t[:4]}-{t[4:8]}-{t[8:]}", "운송장번호", "review"), 3.4, True)
    c.rtext(120, 2.4, f.pick(COURIERS), 3.4, True)
    c.rtext(120, 7.2, f"{f.r.randint(2026, 2026)}.{f.r.randint(10, 11):02d}.{f.r.randint(1, 28):02d}  1/1", 2.2, fill=LABEL)
    c.barcode(3, 11.5, 70, 9, f.r)
    c.rect(78, 10.5, 120, 23, fill=INK)
    c.text(81, 10.4, f"{f.r.randint(1, 9)}{f.pick('ABCDE')}{f.r.randint(10, 99)}", 6.8, True, (255, 255, 255))
    c.text(3, 23.5, f"{f.pick(['기흥', '동탄', '분당', '팔달'])}{f.pick('ABC')}  {f.r.randint(10, 99)}-{f.r.randint(1, 9)}",
           6, True)
    c.line(3, 34, 120, 34, INK, 3)
    c.rect(3, 36, 15, 41, fill=INK); c.text(4.2, 36.6, "받는분", 2.6, True, (255, 255, 255))
    name, mob = f.name(), f.mobile()
    c.text(18, 35.6, p.add(mask_name(name), "이름", "review"), 4.2, True)
    c.text(52, 36.4, p.add(mask_mobile(mob), "휴대폰", "none"), 3.4)
    c.text(3, 44, p.add(f.road(), "도로명주소", "cover"), 3.4)
    c.text(3, 50, p.add(f"누리아파트 {f.unit()}", "상세주소", "cover"), 5, True)
    c.line(3, 58.5, 120, 58.5)
    c.text(3, 60, "보내는분", 2.4, fill=LABEL)
    c.text(18, 59.6, p.add(f.pick(SHOPS), "상호·간판", "none"), 3)
    c.text(52, 60, p.add(f"1588-{f.r.randint(1000, 9999)}", "대표번호", "none"), 2.8)
    c.line(3, 65.5, 120, 65.5)
    c.text(3, 67, "품목", 2.4, fill=LABEL); c.text(14, 66.6, f.pick(["무선 이어폰 케이스 외 1건", "주방 수납용기 3P", "겨울 니트 머플러"]), 2.8)
    c.text(84, 67, "수량 1   운임 신용", 2.6)
    c.text(3, 72.5, "배송메세지", 2.4, fill=LABEL)
    c.text(19, 72, f.pick(["문 앞에 놓아주세요", "부재 시 경비실에 맡겨주세요", "배송 전 연락 바랍니다"]), 2.8)
    c.qr(3, 78.5, 19, f.r)
    c.barcode(26, 80, 60, 7, f.r)
    c.text(26, 89.5, "개인정보 보호를 위해 운송장은 떼어서 폐기해 주세요.", 2.2, fill=LABEL)
    c.text(26, 93.5, "모든 정보는 촬영용 가상 정보입니다", 2.0, fill=(170, 170, 170))
    c.finish()
    return p


def waybill_small(pid: str, f: Fake) -> Prop:
    """편의점·소규모 판매자 송장. 이름·전화가 가려지지 않고 그대로 찍힌다."""
    p = Prop(pid, "송장", (100, 70))
    c = Draw(p, bg=(255, 255, 255))
    c.rect(0, 0, 100, 8, fill=(236, 236, 236))
    c.text(3, 1.6, f"{f.pick(['누리25', '가온마트'])} 편의점택배", 3.2, True)
    t = f.tracking()
    c.rtext(97, 2.2, p.add(t, "운송장번호", "review"), 3, True)
    c.barcode(3, 10, 55, 7, f.r)
    c.text(62, 10.4, f"{f.r.randint(100, 999)}-{f.r.randint(10, 99)}", 6, True)
    c.text(3, 20, "받는분", 2.4, fill=LABEL); c.text(16, 19.4, p.add(f.name(), "이름", "cover"), 3.6, True)
    c.text(50, 20, "연락처", 2.4, fill=LABEL); c.text(61, 19.8, p.add(f.mobile(), "휴대폰", "cover"), 3)
    c.text(3, 27.5, "주소", 2.4, fill=LABEL); c.text(16, 27, p.add(f.road(), "도로명주소", "cover"), 3)
    c.text(16, 33, p.add(f.unit(), "상세주소", "cover"), 3.4, True)
    c.line(3, 40, 97, 40)
    c.text(3, 42, "보내는분", 2.4, fill=LABEL); c.text(16, 41.6, p.add(f.name(), "이름", "cover"), 3)
    c.text(50, 42, "연락처", 2.4, fill=LABEL); c.text(61, 41.8, p.add(f.mobile(), "휴대폰", "cover"), 2.8)
    c.text(3, 49, "물품 의류   수량 1   선불", 2.6)
    c.text(3, 56, "점포 " + f.pick(["수원역점", "기흥구청점", "동탄호수점"]) + "   접수 " + f"{f.r.randint(10, 11)}/{f.r.randint(1, 28)}", 2.3, fill=LABEL)
    c.finish()
    return p


def waybill_unlabeled(pid: str, f: Fake) -> Prop:
    """라벨 없이 값만 찍힌 작은 주소 스티커."""
    p = Prop(pid, "송장(라벨 없음)", (80, 45))
    c = Draw(p, bg=(255, 255, 255))
    c.text(3, 4, p.add(f.name(), "이름", "cover"), 3.4, True)
    c.text(3, 11, p.add(f.mobile(), "휴대폰", "cover"), 3)
    c.text(3, 18, p.add(f.road(), "도로명주소", "review"), 2.7)
    c.text(3, 24, p.add(f.unit(), "상세주소", "cover"), 2.7)
    c.barcode(3, 32, 45, 6, f.r)
    c.finish()
    return p


def _school_head(c: Draw, school: str, w: float, color):
    c.rect(0, 0, w, 12, fill=color)
    c.d.ellipse([2.5 * MM, 2 * MM, 10.5 * MM, 10 * MM], outline=(255, 255, 255), width=3)
    c.text(4.6, 3.6, school[0], 3.4, True, (255, 255, 255))
    c.text(13, 1.8, school, 3.6, True, (255, 255, 255))
    c.text(13, 7.2, {"한빛대학교": "HANBIT UNIVERSITY", "누리대학교": "NURI UNIVERSITY",
                     "다온대학교": "DAON UNIVERSITY"}.get(school, "UNIVERSITY"), 2.0, False, (225, 232, 245))


def student_card(pid: str, f: Fake) -> Prop:
    """가로형 체크카드 겸용 학생증. 사진 왼쪽, 성명·학번·학과 오른쪽, 아래 IC칩·은행명."""
    p = Prop(pid, "학생증", (85.6, 54))
    c = Draw(p, bg=(246, 248, 252))
    color = f.pick([(30, 62, 120), (0, 98, 80), (120, 30, 50)])
    school = f.pick(SCHOOLS)
    _school_head(c, school, 85.6, color)
    c.rtext(83, 3.6, "STUDENT ID", 2.6, True, (255, 255, 255))
    c.photo(4, 15, 24, 41)
    labeled = int(pid[1:]) % 2 == 0
    sid = f"20{f.r.randint(19, 25)}{f.r.randint(1000, 9999)}"
    x = 28
    if labeled:
        for yy, lab in [(15.5, "성명"), (23.5, "학번"), (30, "학과")]:
            c.text(28, yy + 0.5, lab, 2.2, fill=LABEL)
        x = 37
    c.text(x, 14.6, p.add(f.name(), "이름", "cover"), 4.2, True)
    c.text(x, 23, p.add(sid, "학번·사번", "cover"), 3.2)
    c.text(x, 29.6, f.pick(["정보보호학과", "컴퓨터학부", "경영학과", "디자인학부"]), 2.8)
    c.text(28, 35.6, roman(f), 2.2, fill=LABEL)
    c.chip(4, 43.5)
    c.text(18, 46.5, "누리은행 체크", 2.4, True, color)
    c.contactless(45, 48, color)
    c.finish(sample_mark=True)
    return p


def student_card_vertical(pid: str, f: Fake) -> Prop:
    """세로형 학생증. 위에 학교, 가운데 사진, 아래 이름·학과·학번, 맨 아래 바코드."""
    p = Prop(pid, "학생증(세로)", (54, 85.6))
    c = Draw(p, bg=(255, 255, 255))
    color = f.pick([(30, 62, 120), (0, 98, 80), (90, 40, 120)])
    school = f.pick(SCHOOLS)
    _school_head(c, school, 54, color)
    c.photo(15, 16, 39, 44)
    name = f.name()
    c.text(27 - c.d.textlength(name, font=font(4.6, True)) / MM / 2, 47, p.add(name, "이름", "cover"), 4.6, True)
    c.text(10, 55, f.pick(["정보보호학과", "컴퓨터학부", "경영학과"]), 2.8, fill=(70, 70, 75))
    sid = f"{f.r.randint(19, 25)}{f.r.randint(100000, 999999)}"
    c.text(10, 60.5, "학번 " + p.add(sid, "학번·사번", "cover"), 2.8)
    c.barcode(8, 67, 38, 7, f.r)
    c.rect(0, 80, 54, 85.6, fill=color)
    c.finish(sample_mark=True)
    return p


def name_tag(pid: str, f: Fake) -> Prop:
    """목걸이형 사원증. 줄 구멍, 회사명, 사진, 큰 이름, 부서, 사번."""
    p = Prop(pid, "명찰·사원증", (54, 85.6))
    c = Draw(p, bg=(255, 255, 255))
    color = f.pick([(196, 80, 29), (20, 90, 160), (40, 40, 45)])
    c.rect(0, 0, 54, 16, fill=color)
    c.d.rounded_rectangle([20 * MM, 2.5 * MM, 34 * MM, 5 * MM], radius=1.2 * MM, fill=(255, 255, 255))
    c.text(5, 8.4, f.pick(COMPANIES), 3.6, True, (255, 255, 255))
    c.photo(15, 20, 39, 48)
    name = f.name()
    c.text(27 - c.d.textlength(name, font=font(5.8, True)) / MM / 2, 51, p.add(name, "이름", "cover"), 5.8, True)
    c.text(8, 61.5, f"{f.pick(['영업팀', '개발팀', '고객지원팀'])}  {f.pick(['매니저', '선임', '책임'])}", 2.8, fill=(80, 80, 85))
    c.text(8, 67, "사번 " + p.add(f"N{f.r.randint(10000, 99999)}", "학번·사번", "cover"), 2.6, fill=(80, 80, 85))
    c.barcode(8, 74, 38, 6, f.r)
    c.finish()
    return p


def business_card(pid: str, f: Fake) -> Prop:
    """국내 흔한 명함: 왼쪽 위 로고·회사, 이름 옆 직함, 아래 주소·전화·메일."""
    p = Prop(pid, "명함", (90, 50))
    c = Draw(p, bg=(255, 255, 255))
    color = f.pick([(40, 70, 130), (0, 110, 90), (170, 50, 40)])
    c.rect(6, 5, 12, 11, fill=color)
    c.text(14, 5.4, f.pick(COMPANIES), 3.2, True, color)
    name = f.name()
    c.text(6, 17, p.add(name, "이름", "cover"), 5, True)
    c.text(6 + c.d.textlength(name, font=font(5, True)) / MM + 2, 19, f.pick(["대리", "과장", "책임연구원"]), 2.8, fill=(90, 90, 95))
    c.text(6, 25.5, f.pick(["플랫폼개발팀", "전략기획팀", "B2B영업팀"]), 2.4, fill=(110, 110, 115))
    c.line(6, 30, 84, 30, color, 2)
    c.text(6, 32, p.add(f"{f.road()} 누리타워 {f.r.randint(3, 15)}층", "도로명주소", "none"), 2.2)
    c.text(6, 36.4, "T " + p.add(f.landline(), "유선전화", "review"), 2.3)
    c.text(46, 36.4, "M " + p.add(f.mobile(), "휴대폰", "cover"), 2.3)
    c.text(6, 40.8, "E " + p.add(f.email(), "이메일", "cover"), 2.3)
    c.text(46, 40.8, "F " + f.landline(), 2.3)
    c.finish()
    return p


def memo(pid: str, f: Fake) -> Prop:
    p = Prop(pid, "메모·포스트잇", (76, 76))
    c = Draw(p, bg=(255, 240, 150))
    ink = (40, 40, 90)
    c.text(5, 6, "현관 비밀번호 " + p.add(f"{f.r.randint(1000, 9999)}*", "비밀번호", "cover"), 3.4, fill=ink)
    c.text(5, 17, "와이파이 비번", 3.4, fill=ink)
    c.text(5, 24, p.add(f"nuri{f.r.randint(1000, 9999)}!", "비밀번호", "cover"), 3.4, fill=ink)
    c.text(5, 37, f"월세 {f.pick(BANKS)}", 3.4, fill=ink)
    c.text(5, 44, p.add(f.account(), "계좌번호", "cover"), 3.4, fill=ink)
    c.text(5, 54, "예금주 " + p.add(f.name(), "이름", "cover"), 3.4, fill=ink)
    c.finish()
    return p


def receipt(pid: str, f: Fake) -> Prop:
    """POS 감열지 영수증(폭 80mm). 가게 정보, 품목 표, 부가세, 카드 승인 정보(9~12번째 자리 가림), 바코드."""
    p = Prop(pid, "영수증", (80, 150))
    c = Draw(p, bg=(255, 255, 255))
    c.text(28, 3, "[영 수 증]", 3.4, True)
    shop = f"누리마트 {f.pick(['수원점', '기흥점', '동탄점'])}"
    c.mtext(4, 11, shop, 3.2, True)
    c.mtext(4, 17, "사업자 " + p.add(f.brn(), "사업자번호", "none"), 2.4)
    c.mtext(4, 21.5, "대표자 " + p.add(f.name(), "이름", "none"), 2.4)
    c.mtext(4, 26, p.add(f.road(), "도로명주소", "none"), 2.4)
    c.mtext(4, 30.5, "TEL " + p.add(f.landline(), "유선전화", "none"), 2.4)
    c.mtext(4, 35, f"2026-{f.r.randint(10, 11):02d}-{f.r.randint(1, 28):02d} {f.r.randint(9, 21):02d}:{f.r.randint(0, 59):02d}  POS:01-{f.r.randint(1000, 9999)}", 2.3)
    c.dashed(4, 76, 40)
    c.mtext(4, 41.5, "상품명          단가  수량    금액", 2.3)
    c.dashed(4, 76, 46)
    y = 48
    items = f.r.sample([("생수 2L", 1200), ("신라면 5입", 4500), ("서울우유 900ml", 2980), ("햇반 210g", 1500),
                        ("바나나", 3990), ("휴지 30롤", 12900)], 4)
    total = 0
    for nm, price in items:
        q = f.r.randint(1, 2)
        total += price * q
        c.mtext(4, y, nm, 2.3)
        c.rtext(50, y, f"{price:,}", 2.3, use_mono=True)
        c.rtext(57, y, str(q), 2.3, use_mono=True)
        c.rtext(76, y, f"{price * q:,}", 2.3, use_mono=True)
        y += 4.6
    c.dashed(4, 76, y + 1)
    supply = round(total / 1.1)
    for lab, val in [("과세물품가액", supply), ("부   가   세", total - supply)]:
        c.mtext(4, y + 3, lab, 2.3); c.rtext(76, y + 3, f"{val:,}", 2.3, use_mono=True); y += 4.4
    c.mtext(4, y + 4, "합계금액", 3.4, True); c.rtext(76, y + 4, f"{total:,}", 3.4, True, use_mono=True)
    y += 11
    c.dashed(4, 76, y)
    c.mtext(4, y + 2, "[신용승인정보]", 2.4, True)
    d = f.card().replace("-", "")
    masked = f"{d[:4]}-{d[4:8]}-****-{d[12:]}"
    rows = [("카드종류", "누리카드"), ("카드번호", p.add(masked, "카드번호", "none")), ("할부개월", "일시불"),
            ("승인번호", str(f.r.randint(10000000, 99999999))), ("가맹점번호", str(f.r.randint(100000000, 999999999)))]
    for lab, val in rows:
        c.mtext(4, y + 6.5, lab, 2.3); c.mtext(26, y + 6.5, val, 2.3); y += 4.4
    c.barcode(10, y + 9, 60, 8, f.r)
    c.mtext(9, y + 19, "교환·환불은 영수증 지참 7일 이내", 2.2, fill=(90, 90, 90))
    c.finish()
    return p


def delivery_slip(pid: str, f: Fake) -> Prop:
    """배달 봉투에 붙는 주문서 스티커. 주문번호, 메뉴, 요청사항, 배달주소(동·호수), 안심번호."""
    p = Prop(pid, "배달 주문서", (80, 110))
    c = Draw(p, bg=(255, 255, 255))
    c.rect(0, 0, 80, 9, fill=INK)
    c.text(3, 1.8, "배달 주문", 3.6, True, (255, 255, 255))
    c.rtext(77, 2.2, f"{f.r.randint(1, 99):02d}번", 3.4, True, (255, 255, 255))
    c.mtext(3, 12, "주문번호 " + f"B{f.r.randint(1, 9)}{f.pick('KXQ')}{f.r.randint(10000000, 99999999)}", 2.4)
    c.mtext(3, 16.4, f"주문일시 2026-{f.r.randint(10, 11):02d}-{f.r.randint(1, 28):02d} {f.r.randint(11, 22):02d}:{f.r.randint(0, 59):02d}", 2.4)
    shop = f.pick(["정성식당 기흥점", "한우리분식", "다온치킨 동탄점"])
    c.mtext(3, 21, p.add(shop, "상호·간판", "none"), 3, True)
    c.dashed(3, 77, 26.5)
    y = 28.5
    for nm in f.r.sample(["김치볶음밥 x1", "참치김밥 x2", "떡볶이(보통맛) x1", "후라이드 반마리 x1", "콜라 1.25L x1"], 3):
        c.mtext(3, y, nm, 2.6); y += 4.8
    c.dashed(3, 77, y + 0.5)
    c.mtext(3, y + 2.5, "[요청사항]", 2.4, True)
    c.mtext(3, y + 6.8, f.pick(["문 앞에 두고 벨 눌러주세요", "수저·포크 안 주셔도 돼요", "아기가 자요, 노크해주세요"]), 2.5)
    y += 13
    c.line(3, y, 77, y, INK, 3)
    c.mtext(3, y + 2, "[배달주소]", 2.4, True)
    c.mtext(3, y + 6.6, p.add(f.road(), "도로명주소", "cover"), 2.6)
    c.mtext(3, y + 11.4, p.add(f"누리빌 {f.unit()}", "상세주소", "cover"), 3.8, True)
    c.mtext(3, y + 18.6, "연락처(안심번호)", 2.3, fill=LABEL)
    c.mtext(3, y + 22.4, p.add(f"0507-{f.r.randint(1000, 9999)}-{f.r.randint(1000, 9999)}", "기타", "review"), 3, True)
    c.mtext(3, y + 30, "결제 완료 · 카드", 2.3, fill=(90, 90, 90))
    c.finish()
    return p


def envelope(pid: str, f: Fake) -> Prop:
    """창봉투 우편물(고지서). 보내는 곳, 요금별납 표시, 창 안의 우편번호·주소·이름 '님 귀하', 등기번호."""
    p = Prop(pid, "우편물", (180, 95))
    c = Draw(p, bg=(250, 248, 240))
    c.text(8, 7, p.add(f"누리아파트 관리사무소", "상호·간판", "none"), 3.4, True)
    c.text(8, 13, f.road() + " 관리동 1층", 2.4, fill=(90, 90, 90))
    c.rect(140, 6, 172, 22, outline=INK, width=2)
    c.text(144, 8.5, "요금별납", 3.2, True); c.text(145, 15, "기흥우체국", 2.6)
    c.rect(60, 34, 165, 74, fill=(255, 255, 255), outline=(200, 200, 200), width=2)
    zipc = f"{f.r.randint(10000, 18999)}"
    for k, ch in enumerate(zipc):
        c.rect(66 + k * 6, 38, 71.5 + k * 6, 44, outline=(200, 40, 40), width=2)
        c.text(67.3 + k * 6, 38.6, ch, 3.6)
    c.text(66, 48, p.add(f.road(), "도로명주소", "cover"), 3.4)
    c.text(66, 55, p.add(f"누리아파트 {f.unit()}", "상세주소", "cover"), 3.6, True)
    name = f.name()
    c.text(110, 63, p.add(name, "이름", "cover"), 4.4, True)
    c.text(110 + c.d.textlength(name, font=font(4.4, True)) / MM + 1, 64.4, "님 귀하", 3, False)
    c.text(8, 80, "등기번호", 2.4, fill=LABEL)
    reg = "".join(str(f.r.randint(0, 9)) for _ in range(13))
    c.text(22, 79.6, p.add(reg, "기타", "review"), 2.8)
    c.barcode(60, 79, 60, 7, f.r)
    c.text(8, 88, "2026년 10월분 관리비 고지서", 2.4, fill=(90, 90, 90))
    c.finish()
    return p


def flyer(pid: str, f: Fake) -> Prop:
    """개인정보가 아닌 글자만 있는 전단. 이름처럼 생긴 상호가 함정이다."""
    p = Prop(pid, "간판·전단", (120, 80))
    c = Draw(p, bg=(255, 250, 240))
    w1, w2 = f.r.sample(NAME_LIKE_WORDS, 2)
    c.text(6, 6, p.add(w1, "상호·간판", "none"), 8, True, (190, 50, 40))
    c.text(6, 26, "오늘의 메뉴  김치찌개 8,000원  제육볶음 9,000원", 3)
    c.text(6, 38, "예약문의 " + p.add(f.landline(), "유선전화", "none"), 3.4)
    c.text(6, 47, "배달문의 " + p.add(f.mobile(), "휴대폰", "none"), 3.4)
    c.text(6, 60, p.add(w2, "상호·간판", "none") + " 2호점 오픈", 4, True)
    c.finish()
    return p


def id_card(pid: str, f: Fake) -> Prop:
    """주민번호가 적힌 가상 회원 확인 카드. 주민등록증·면허증 디자인은 흉내 내지 않는다."""
    p = Prop(pid, "학생증·신분증", (85.6, 54))
    c = Draw(p, bg=(250, 250, 250))
    c.text(4, 3, "신분 확인용 카드 (가상)", 3, True)
    c.photo(60, 12, 80, 38)
    c.text(4, 13, p.add(f.name(), "이름", "cover"), 4, True)
    c.text(4, 22, p.add(f.rrn(), "주민번호", "cover"), 3.2)
    c.text(4, 30, p.add(f.road(), "도로명주소", "cover"), 2.6)
    c.finish(sample_mark=True)
    return p


def _card_face(c: Draw, f: Fake, dark):
    c.rect(0, 0, 85.6, 54, fill=dark)
    for k in range(6):  # 은은한 사선 무늬
        c.line(40 + k * 9, 0, 70 + k * 9, 54, tuple(min(255, v + 12) for v in dark), 6)


def card(pid: str, f: Fake) -> Prop:
    """체크카드 앞면. 발급사, IC칩, 비접촉 표시, 카드번호, 영문 이름, 유효기간."""
    p = Prop(pid, "카드", (85.6, 54))
    dark = f.pick([(44, 52, 74), (20, 20, 24), (0, 82, 120), (120, 30, 60)])
    c = Draw(p, bg=dark)
    _card_face(c, f, dark)
    white = (240, 240, 245)
    c.text(5, 4.5, "누리카드", 3.4, True, white)
    c.rtext(81, 5.2, "check", 2.6, False, white)
    c.chip(7, 17)
    c.contactless(23, 21.2, white)
    c.text(6, 30.5, p.add(f.card().replace("-", " "), "카드번호", "cover"), 4, True, white)
    c.text(40, 38.5, "VALID THRU " + p.add(f"{f.r.randint(1, 12):02d}/{f.r.randint(28, 31)}", "기타", "cover"), 2.2, False, white)
    c.text(6, 44.5, p.add(roman(f), "이름", "cover"), 2.8, False, white)
    c.finish(sample_mark=True)
    return p


def card_back(pid: str, f: Fake) -> Prop:
    """카드 뒷면. 요즘 국내 카드는 번호·CVC 가 뒷면에만 있는 경우가 많다."""
    p = Prop(pid, "카드(뒷면)", (85.6, 54))
    c = Draw(p, bg=(236, 236, 240))
    c.rect(0, 5, 85.6, 15, fill=(20, 20, 22))
    c.rect(5, 19, 58, 26, fill=(255, 255, 255))
    for k in range(9):
        c.line(5, 19.8 + k * 0.7, 58, 19.8 + k * 0.7, (225, 220, 235), 1)
    c.text(5, 26.6, "AUTHORIZED SIGNATURE", 1.6, fill=LABEL)
    c.rect(60, 19, 72, 26, fill=(255, 255, 255))
    c.text(61.5, 20.4, p.add(f"{f.r.randint(100, 999)}", "기타", "cover"), 3, True)
    c.text(73, 21, "CVC", 1.8, fill=LABEL)
    c.text(5, 31, p.add(f.card(), "카드번호", "cover"), 3.6, True)
    c.text(5, 37.5, "VALID THRU " + p.add(f"{f.r.randint(1, 12):02d}/{f.r.randint(28, 31)}", "기타", "cover"), 2.4)
    c.text(5, 42.5, "고객센터 " + p.add(f"1588-{f.r.randint(1000, 9999)}", "대표번호", "none"), 2.2)
    c.text(5, 46.5, "이 카드는 누리카드 회원만 사용할 수 있습니다.", 1.8, fill=LABEL)
    c.finish(sample_mark=True)
    return p


MAKERS = [waybill, waybill_small, waybill_unlabeled, student_card, student_card_vertical, name_tag,
          business_card, memo, receipt, delivery_slip, envelope, flyer, id_card, card, card_back]


# ------------------------------------------------------------------ 배치·출력

def make_props(sets: int = 2, seed: int = 1) -> list[Prop]:
    props, n = [], 0
    for s in range(sets):
        for k, make in enumerate(MAKERS):
            n += 1
            props.append(make(f"P{n:02d}", Fake(seed * 10_000 + s * 100 + k)))
    return props


def layout(props: list[Prop]) -> list[Image.Image]:
    """A4 에 실제 크기로 줄지어 놓는다. 자를 수 있게 테두리를 그린다.

    키 큰 것부터 줄을 채워(선반 배치) 종이를 아낀다. 소품 번호가 붙어 있어 순서는 상관없다.
    """
    props = sorted(props, key=lambda p: (-p.image.size[1], p.pid))
    pages, page, x, y, row_h = [], None, MARGIN, MARGIN, 0

    def new_page():
        img = Image.new("RGB", A4, (255, 255, 255))
        ImageDraw.Draw(img).text((MARGIN, A4[1] - MARGIN + 4), "Privacy Lens 촬영용 소품 — 모든 정보는 가짜입니다",
                                 font=font(2.2), fill=(150, 150, 150))
        pages.append(img)
        return img

    page = new_page()
    for p in props:
        w, h = p.image.size
        if x + w > A4[0] - MARGIN:
            x, y, row_h = MARGIN, y + row_h + GAP, 0
        if y + h > A4[1] - MARGIN - 20:
            page, x, y, row_h = new_page(), MARGIN, MARGIN, 0
        page.paste(p.image, (x, y))
        ImageDraw.Draw(page).rectangle([x - 1, y - 1, x + w, y + h], outline=(150, 150, 150), width=1)
        x += w + GAP
        row_h = max(row_h, h)
    return pages


def write(out: Path, sets: int = 2, seed: int = 1) -> tuple[Path, Path]:
    out.mkdir(parents=True, exist_ok=True)
    props = make_props(sets, seed)
    pages = layout(props)
    pdf = out / "소품_인쇄용.pdf"
    pages[0].save(pdf, save_all=True, append_images=pages[1:], resolution=DPI)
    manifest = out / "props.json"
    manifest.write_text(json.dumps({
        "note": "samples.props 가 만든 가상 소품. 등급은 docs/MASKING_CRITERIA.md 초안 기준",
        "seed": seed,
        "props": {p.pid: {"kind": p.kind, "items": p.items} for p in props},
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return pdf, manifest


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m samples.props", description="촬영용 가상 소품 인쇄물과 정답 만들기")
    ap.add_argument("out", help="출력 폴더(실사 평가 사진 폴더에 바로 만들어도 된다)")
    ap.add_argument("--sets", type=int, default=2, help="종류별 몇 벌(기본 2 → 소품 20개)")
    ap.add_argument("--seed", type=int, default=1, help="같은 숫자면 같은 소품이 나온다")
    a = ap.parse_args(argv)
    pdf, manifest = write(Path(a.out), a.sets, a.seed)
    n = len(json.loads(manifest.read_text(encoding="utf-8"))["props"])
    print(f"소품 {n}개: {pdf}\n정답: {manifest}\n"
          "A4 로 '실제 크기(100%)'로 인쇄해 테두리대로 자르세요. 소품 번호(P01…)는 왼쪽 위 작은 글씨입니다.")


if __name__ == "__main__":
    main()
