"""
[B] 정규식 · 키워드 기반 PII 판정

OCR 오인식을 견디도록
  - 숫자 사이의 O/o/l/I 를 0/1 로 보정
  - 키워드는 비슷한 글자 변형까지 허용 (예: 받는분 ↔ 반는분 · 밭는분)
처리합니다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

from schema.models import BBox, OCRLine

# ── 키워드 (OCR 오인식 변형 포함) ───────────────────────
KW_RECIPIENT = re.compile(r"[받반밭발][는눈][분문]|수[령렁]인|보[내너][는눈][분문]|성[명영]|이름|주문자")
KW_TRACKING = re.compile(r"운?[송승]장|송장|운송장번호|tracking", re.I)
KW_STUDENT = re.compile(r"학[생셍][증중종]|STUDENT|학[번빈]|대학교", re.I)
KW_STUDENT_NO = re.compile(r"학[번빈]|사[번빈]")
KW_PARCEL = re.compile(r"택배|익스프레스|로지스|[받반밭][는눈][분문]|보[내너][는눈][분문]|[송승]장|품[명영]")
KW_RECEIPT = re.compile(r"영수증|합계|승인번호|카드번호|결제")

SURNAMES = set("김이박최정강조윤장임한오서신권황안송류홍전고문양손배백허유남심노하곽성차주우구민진나지엄채원천방공현함변염여추도소석선설마길연위표명기반왕금옥육인맹제모탁국어은편용예봉경")

# ── 정규식 ─────────────────────────────────────────────
SEP = r"[-–—~.\s]?"
RE_PHONE = re.compile(rf"(?<!\d)(01[016789]){SEP}(\d{{3,4}}){SEP}(\d{{4}})(?!\d)")
RE_TEL = re.compile(rf"(?<!\d)(0(?:2|[3-6][1-5])){SEP}(\d{{3,4}}){SEP}(\d{{4}})(?!\d)")
RE_RRN = re.compile(r"(?<!\d)(\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01]))\s?[-–]\s?([1-4]\d{6})(?!\d)")
RE_CARD = re.compile(r"(?<!\d)(\d{4})[-\s](\d{4})[-\s](\d{4})[-\s](\d{4})(?!\d)")
RE_PLATE = re.compile(r"(?<!\d)(\d{2,3})\s?([가-힣])\s?(\d{4})(?!\d)")
RE_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
RE_URL = re.compile(r"https?://\S+|www\.\S+", re.I)
RE_DIGITS_LONG = re.compile(r"(?<!\d)(\d[\d-]{8,16}\d)(?!\d)")
RE_STUDENT_NO = re.compile(r"(?<!\d)(\d{8,10})(?!\d)")
RE_ADDR_REGION = re.compile(r"(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충청|충북|충남|전라|전북|전남|경상|경북|경남|제주)\S*")
RE_ADDR_UNIT = re.compile(r"\S+(?:시|군|구)\s")
RE_ADDR_ROAD = re.compile(r"\S+(?:로|길)\s?\d+")
RE_ADDR_DONG_HO = re.compile(r"\d+\s?동\s?\d+\s?호|\d+\s?호(?!\S)")
RE_SCHOOL = re.compile(r"\S+대학교")
PLATE_CHARS = set("가나다라마거너더러머버서어저고노도로모보소오조구누두루무부수우주하허호배")


@dataclass
class Hit:
    type: str
    value: str
    method: str
    conf: float
    line_idx: int
    bbox: BBox
    link: Optional[int] = None      # address_detail 이 이어지는 주소 줄의 line_idx


def normalize_digits(t: str) -> str:
    """숫자 문맥 속 O/o/l/I/| 오인식 보정"""
    t = re.sub(r"(?<=\d)[Oo](?=[\d\s-])|(?<=[\d\s-])[Oo](?=\d)", "0", t)
    t = re.sub(r"(?<=\d)[lI|](?=[\d\s-])|(?<=[\d\s-])[lI|](?=\d)", "1", t)
    return t


def _luhn(num: str) -> bool:
    s, alt = 0, False
    for ch in reversed(num):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d > 4 else d * 2
        s += d
        alt = not alt
    return s % 10 == 0


def _name_tokens(text: str, strict: bool = True) -> List[str]:
    """strict=False: 전화번호 바로 앞처럼 문맥이 강할 때 — OCR이 성씨를 잘못 읽어도(윤→운) 허용"""
    return [t for t in re.findall(r"[가-힣]{2,4}", text)
            if (not strict or t[0] in SURNAMES) and not KW_RECIPIENT.search(t) and not KW_PARCEL.search(t)]


def _same_row(a: BBox, b: BBox) -> bool:
    ov = min(a.y2, b.y2) - max(a.y1, b.y1)
    return ov > 0.5 * min(a.y2 - a.y1, b.y2 - b.y1) and b.x1 >= a.x1


def is_address(text: str) -> bool:
    score = 0
    score += bool(RE_ADDR_REGION.search(text))
    score += bool(RE_ADDR_UNIT.search(text + " "))
    score += bool(RE_ADDR_ROAD.search(text))
    return score >= 2


def find_pii(lines: List[OCRLine]) -> List[Hit]:
    hits: List[Hit] = []
    texts = [normalize_digits(l.text) for l in lines]
    detail_cands: List[int] = []

    for i, (ln, t) in enumerate(zip(lines, texts)):
        def add(tp, val, method="regex", conf=None):
            hits.append(Hit(tp, val.strip(), method, ln.conf if conf is None else conf, i, ln.bbox))

        consumed = t
        for m in RE_RRN.finditer(t):
            add("rrn", m.group(0)); consumed = consumed.replace(m.group(0), " ")
        for m in RE_CARD.finditer(consumed):
            if _luhn("".join(m.groups())):
                add("card_number", m.group(0)); consumed = consumed.replace(m.group(0), " ")
        for m in RE_PHONE.finditer(consumed):
            add("phone", m.group(0)); consumed = consumed.replace(m.group(0), " ")
        for m in RE_TEL.finditer(consumed):
            add("phone", m.group(0)); consumed = consumed.replace(m.group(0), " ")
        for m in RE_EMAIL.finditer(consumed):
            add("email", m.group(0))
        for m in RE_URL.finditer(consumed):
            add("url", m.group(0))
        for m in RE_PLATE.finditer(consumed):
            if m.group(2) in PLATE_CHARS:
                add("plate_number", m.group(0))

        # 송장번호: 키워드가 있는 줄의 긴 숫자열
        if KW_TRACKING.search(t):
            for m in RE_DIGITS_LONG.finditer(consumed):
                if 10 <= len(re.sub(r"\D", "", m.group(1))) <= 14:
                    add("tracking_number", m.group(1))
        # 학번: 키워드가 있는 줄 또는 같은 행 오른쪽 줄
        if KW_STUDENT_NO.search(t):
            cand = [(i, t)] + [(j, texts[j]) for j in range(len(lines)) if j != i and _same_row(ln.bbox, lines[j].bbox)]
            for j, tj in cand:
                m = RE_STUDENT_NO.search(tj)
                if m:
                    hits.append(Hit("student_number", m.group(1), "rule", lines[j].conf, j, lines[j].bbox))
                    break
        # 주소
        if is_address(t):
            add("address", t, method="rule")
        elif RE_ADDR_DONG_HO.search(t) and len(t) < 20:
            detail_cands.append(i)          # 주소 둘째 줄 후보 — 아래에서 위치로 연결
        # 소속(학교)
        for m in RE_SCHOOL.finditer(t):
            add("affiliation", m.group(0), method="rule")

    # 주소 둘째 줄('29동 165호') 연결: 줄 순서가 아니라 위치로 판단
    # 송장이 기울면 '배송지' 같은 라벨 박스가 두 줄 사이 순서로 끼어들기 때문 (2026-10-03 실사 데모에서 발견)
    for i in detail_cands:
        b = lines[i].bbox
        h = b.y2 - b.y1
        best = None
        for a in (x for x in hits if x.type == "address"):
            ab = a.bbox
            gap = b.y1 - ab.y2                                  # 주소 줄 아래쪽과의 세로 간격 (기울면 음수 가능)
            overlap = min(ab.x2, b.x2) - max(ab.x1, b.x1)       # 가로로 겹치는 폭
            below = (b.y1 + b.y2) / 2 > (ab.y1 + ab.y2) / 2 + 0.3 * h   # 중심이 주소 줄보다 아래
            if below and gap <= 2.0 * h and overlap > 0 and (best is None or gap < best[0]):
                best = (gap, a)
        if best:
            a = best[1]
            a.value = f"{a.value}, {texts[i]}"
            hits.append(Hit("address_detail", texts[i], "rule", lines[i].conf, i, b, link=a.line_idx))

    # 성명: (a) 전화번호가 있는 줄의 앞쪽 2~4글자  (b) 키워드 줄 · 같은 행
    phone_lines = {h.line_idx for h in hits if h.type == "phone"}
    named = set()
    for i, (ln, t) in enumerate(zip(lines, texts)):
        cands = []
        if i in phone_lines:
            head = RE_PHONE.split(t)[0]
            cands += _name_tokens(head, strict=False)
        if KW_RECIPIENT.search(t):
            after = KW_RECIPIENT.split(t, maxsplit=1)[-1]
            cands += _name_tokens(after)
            if not cands:
                for j, l2 in enumerate(lines):
                    if j != i and _same_row(ln.bbox, l2.bbox):
                        cands += _name_tokens(RE_PHONE.split(texts[j])[0], strict=j not in phone_lines)
                        if cands:
                            hits.append(Hit("person_name", cands[0], "rule", l2.conf, j, l2.bbox))
                            named.add(j)
                            cands = []
                            break
        if cands and i not in named:
            hits.append(Hit("person_name", cands[0], "rule", ln.conf, i, ln.bbox))
            named.add(i)
    # 같은 줄에서 같은 값이 두 규칙으로 중복 검출된 경우 하나만 남김
    seen, uniq = set(), []
    for h in hits:
        key = (h.type, h.line_idx, h.value)
        if key not in seen:
            seen.add(key)
            uniq.append(h)
    return uniq


# ── 마스킹 표시값 ──────────────────────────────────────
def mask(tp: str, v: str) -> str:
    d = re.sub(r"\D", "", v)
    if tp == "phone":
        return f"{d[:3]}-****-{d[-4:]}" if len(d) >= 10 else "***-****-" + d[-4:]
    if tp == "rrn":
        return d[:6] + "-*******"
    if tp == "card_number":
        return f"{d[:4]}-****-****-{d[-4:]}"
    if tp in ("tracking_number", "student_number"):
        return d[:4] + "*" * max(len(d) - 4, 4)
    if tp == "person_name":
        return v[0] + "*" * (len(v) - 2) + v[-1] if len(v) >= 3 else v[0] + "*"
    if tp == "address":
        toks = v.split()
        keep = [t for t in toks[:3] if not re.search(r"\d", t)]
        return " ".join(keep) + " ****"
    if tp == "plate_number":
        m = RE_PLATE.search(v)
        return f"{m.group(1)}{m.group(2)} ****" if m else "****"
    if tp == "email":
        u, _, dom = v.partition("@")
        return u[:1] + "***@" + dom
    if tp == "url":
        m = re.match(r"(https?://)?([^/]+)", v)
        return (m.group(1) or "") + m.group(2) + "/****" if m else "****"
    if tp == "affiliation":
        return v
    return "****"


def infer_label(texts: List[str], types: set) -> Optional[str]:
    joined = " ".join(texts)
    if KW_PARCEL.search(joined) or "tracking_number" in types:
        return "parcel_label"
    if KW_STUDENT.search(joined) or "student_number" in types:
        return "student_id"
    if KW_RECEIPT.search(joined) or "card_number" in types:
        return "receipt"
    if types == {"plate_number"}:
        return "license_plate"
    return "document"
