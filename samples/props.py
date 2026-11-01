"""촬영용 소품 — 가상 개인정보를 인쇄해 실제로 찍는다.

실사 평가 사진에 진짜 개인정보를 쓰지 않으려면 두 가지 방법이 있다.
  1. 팀원 본인 물건을 찍고 번호를 포스트잇으로 가린다(문서 모양이 진짜)
  2. 이 소품을 인쇄해 찍는다(글자가 전부 가짜라 가릴 필요가 없고, 정답이 미리 정해져 있다)

이 파일은 2번이다. A4 에 실제 크기로 소품을 배치한 인쇄용 PDF 와, 소품마다 무엇이 적혀
있고 어떻게 판정해야 하는지를 담은 'props.json' 을 만든다. 정답 입력 도구
(eval/gold_tool.html)는 같은 폴더의 props.json 을 읽어 소품 번호만 고르면 정답을 채운다.

    python -m samples.props <출력 폴더> [--sets 2] [--seed 1]

주의
  - 소품은 실제 신분증·카드처럼 보이지 않게 일부러 단순하게 그리고 '견본' 표시를 넣는다.
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


# ------------------------------------------------------------------ 소품 종류

def waybill(pid: str, f: Fake) -> Prop:
    p = Prop(pid, "송장", (100, 70))
    c = Canvas(p)
    c.rect(0, 0, 100, 10, fill=(236, 234, 228))
    c.text(3, 2.5, f.pick(["가온택배", "누리익스프레스", "한빛로지스"]), 4, True)
    c.text(52, 3.2, "운송장번호", 2.2, fill=LABEL)
    c.text(67, 2.6, p.add(f.tracking(), "운송장번호", "review"), 3, True)
    c.text(3, 14, "받는분", 2.4, fill=LABEL); c.text(18, 13, p.add(f.name(), "이름", "cover"), 3.6, True)
    c.text(3, 22, "연락처", 2.4, fill=LABEL); c.text(18, 21.5, p.add(f.mobile(), "휴대폰", "cover"), 3.2)
    c.text(3, 30, "배송지", 2.4, fill=LABEL); c.text(18, 29.5, p.add(f.road(), "도로명주소", "cover"), 3)
    c.text(18, 35, p.add(f.unit(), "상세주소", "cover"), 3)
    c.line(3, 45, 97, 45)
    c.text(3, 48, "보내는분", 2.4, fill=LABEL); c.text(18, 47.5, p.add(f.name(), "이름", "cover"), 3)
    c.text(3, 56, "고객센터", 2.4, fill=LABEL); c.text(18, 55.5, p.add("1588-1255", "대표번호", "none"), 3)
    c.text(45, 56.3, "배송 문의는 고객센터로 연락 바랍니다", 2.1, fill=LABEL)
    c.finish()
    return p


def waybill_unlabeled(pid: str, f: Fake) -> Prop:
    """편의점 반값택배처럼 라벨 없이 값만 찍힌 작은 송장."""
    p = Prop(pid, "송장(라벨 없음)", (80, 45))
    c = Canvas(p, bg=(255, 255, 255))
    c.text(3, 4, p.add(f.name(), "이름", "cover"), 3.4, True)
    c.text(3, 11, p.add(f.mobile(), "휴대폰", "cover"), 3)
    c.text(3, 18, p.add(f.road(), "도로명주소", "review"), 2.7)
    c.text(3, 24, p.add(f.unit(), "상세주소", "cover"), 2.7)
    c.text(3, 33, "GS25 " + f.pick(["수원역점", "기흥점", "동탄점"]), 2.2, fill=LABEL)
    c.finish()
    return p


def student_card(pid: str, f: Fake) -> Prop:
    p = Prop(pid, "학생증", (85.6, 54))
    c = Canvas(p, bg=(244, 247, 252))
    c.rect(0, 0, 85.6, 11, fill=(40, 70, 130))
    c.text(4, 2.6, f.pick(SCHOOLS), 3.6, True, (255, 255, 255))
    c.text(58, 3.4, "학생증", 2.8, True, (255, 255, 255))
    c.rect(4, 15, 26, 44, fill=(205, 208, 214))
    c.text(10, 28, "사진", 2.4, fill=(120, 124, 130))
    labeled = int(pid[1:]) % 2 == 0
    sid = f"20{f.r.randint(19, 25)}{f.r.randint(1000, 9999)}"
    if labeled:
        c.text(30, 17, "성명", 2.4, fill=LABEL)
        c.text(30, 25, "학번", 2.4, fill=LABEL)
        c.text(30, 33, "학과", 2.4, fill=LABEL)
        x = 42
    else:
        x = 30
    c.text(x, 16, p.add(f.name(), "이름", "cover"), 3.6, True)
    c.text(x, 24.5, p.add(sid, "학번·사번", "cover"), 3)
    c.text(x, 32.5, f.pick(["정보보호학과", "컴퓨터학과", "경영학과"]), 2.8)
    c.finish(sample_mark=True)
    return p


def name_tag(pid: str, f: Fake) -> Prop:
    p = Prop(pid, "명찰·사원증", (90, 55))
    c = Canvas(p, bg=(255, 255, 255))
    c.rect(0, 0, 90, 4, fill=(196, 80, 29))
    c.text(5, 8, f"{f.pick(COMPANIES)} {f.pick(['영업팀', '개발팀', '고객지원팀'])}", 3, fill=(80, 80, 85))
    c.text(5, 20, p.add(f.name(), "이름", "cover"), 7, True)
    c.text(5, 38, f.pick(["매니저", "선임", "책임", "인턴"]), 3, fill=(80, 80, 85))
    c.finish()
    return p


def business_card(pid: str, f: Fake) -> Prop:
    p = Prop(pid, "명함", (90, 50))
    c = Canvas(p, bg=(255, 255, 255))
    company = f.pick(COMPANIES)
    c.text(5, 5, company, 3.2, True, (40, 70, 130))
    c.text(5, 15, p.add(f.name(), "이름", "cover"), 4.4, True)
    c.text(5, 23, f.pick(["대리", "과장", "연구원"]), 2.6, fill=(90, 90, 95))
    c.text(5, 31, "M. " + p.add(f.mobile(), "휴대폰", "cover"), 2.6)
    c.text(5, 36.5, "T. " + p.add(f.landline(), "유선전화", "review"), 2.6)
    c.text(5, 42, "E. " + p.add(f.email(), "이메일", "cover"), 2.6)
    c.finish()
    return p


def memo(pid: str, f: Fake) -> Prop:
    p = Prop(pid, "메모·포스트잇", (76, 76))
    c = Canvas(p, bg=(255, 240, 150))
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
    p = Prop(pid, "영수증", (70, 120))
    c = Canvas(p, bg=(255, 255, 255))
    c.text(5, 5, f"누리마트 {f.pick(['수원점', '기흥점', '동탄점'])}", 3.6, True)
    c.text(5, 14, "대표 " + p.add(f.landline(), "유선전화", "none"), 2.6)
    c.text(5, 20, "사업자 " + p.add(f.brn(), "사업자번호", "none"), 2.6)
    c.line(5, 27, 65, 27)
    y = 31
    for name, price in [("생수 2L", "1,200"), ("라면 5입", "4,500"), ("우유 900ml", "2,800")]:
        c.text(5, y, name, 2.6); c.text(48, y, price, 2.6); y += 6
    c.line(5, y + 1, 65, y + 1)
    c.text(5, y + 4, "합계", 3, True); c.text(46, y + 4, "8,500원", 3, True)
    masked = f"9410-12**-****-{f.r.randint(1000, 9999)}"
    c.text(5, y + 14, "카드번호 " + p.add(masked, "카드번호", "none"), 2.4)
    c.text(5, y + 20, f"승인번호 {f.r.randint(10000000, 99999999)}", 2.4)
    c.finish()
    return p


def flyer(pid: str, f: Fake) -> Prop:
    """개인정보가 아닌 글자만 있는 전단. 이름처럼 생긴 상호가 함정이다."""
    p = Prop(pid, "간판·전단", (120, 80))
    c = Canvas(p, bg=(255, 250, 240))
    w1, w2 = f.r.sample(NAME_LIKE_WORDS, 2)
    c.text(6, 6, p.add(w1, "상호·간판", "none"), 8, True, (190, 50, 40))
    c.text(6, 26, "오늘의 메뉴  김치찌개 8,000원  제육볶음 9,000원", 3)
    c.text(6, 38, "예약문의 " + p.add(f.landline(), "유선전화", "none"), 3.4)
    c.text(6, 47, "배달문의 " + p.add(f.mobile(), "휴대폰", "none"), 3.4)
    c.text(6, 60, p.add(w2, "상호·간판", "none") + " 2호점 오픈", 4, True)
    c.finish()
    return p


def id_card(pid: str, f: Fake) -> Prop:
    """주민번호가 적힌 가상 신분증. 실제 신분증 디자인을 흉내 내지 않는다."""
    p = Prop(pid, "학생증·신분증", (85.6, 54))
    c = Canvas(p, bg=(250, 250, 250))
    c.text(4, 3, "신분 확인용 카드 (가상)", 3, True)
    c.rect(60, 12, 80, 38, fill=(210, 210, 214))
    c.text(4, 13, p.add(f.name(), "이름", "cover"), 4, True)
    c.text(4, 22, p.add(f.rrn(), "주민번호", "cover"), 3.2)
    c.text(4, 30, p.add(f.road(), "도로명주소", "cover"), 2.6)
    c.finish(sample_mark=True)
    return p


def card(pid: str, f: Fake) -> Prop:
    p = Prop(pid, "카드", (85.6, 54))
    c = Canvas(p, bg=(60, 64, 80))
    white = (240, 240, 245)
    c.text(5, 5, "NURI CARD", 3.6, True, white)
    c.rect(5, 15, 16, 23, fill=(200, 180, 110))
    c.text(5, 28, p.add(f.card(), "카드번호", "cover"), 3.8, True, white)
    c.text(5, 40, p.add(f.name(), "이름", "cover"), 3, False, white)
    c.finish(sample_mark=True)
    return p


MAKERS = [waybill, waybill_unlabeled, student_card, name_tag, business_card, memo,
          receipt, flyer, id_card, card]


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
