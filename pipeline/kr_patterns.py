"""한국어 개인정보 패턴과 문맥 어휘.

이 모듈은 "이 문자열이 무슨 형식인가"만 판단한다.
"이게 위험한가"는 context.py 가 주변 문구를 보고 결정한다. 둘을 섞지 않는다.

형식 검증(체크섬)이 있는 항목은 반드시 검증한다. 주민등록번호 13자리를
패턴만으로 잡으면 운송장번호와 계좌번호를 무더기로 오탐한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional

# ---------------------------------------------------------------- 패턴 정의

# 전화번호 계열은 앞뒤가 숫자가 아니어야 한다. 경계가 없으면
# '5301012345678' 같은 운송장번호 한가운데서 휴대폰 번호를 찾아낸다.
_NB, _NA = r"(?<!\d)", r"(?!\d)"

# 휴대폰. OCR이 하이픈을 놓치는 경우가 잦아 구분자를 선택적으로 둔다.
RE_MOBILE = re.compile(_NB + r"01[016789][-.\s]?\d{3,4}[-.\s]?\d{4}" + _NA)

# 지역번호 유선전화
RE_LANDLINE = re.compile(
    _NB + r"0(?:2|3[1-3]|4[1-4]|5[1-5]|6[1-4])[-.\s]?\d{3,4}[-.\s]?\d{4}" + _NA
)

# 대표번호 대역. 개인 연락처가 아니라 기업 공개 번호다.
RE_SERVICE_LINE = re.compile(
    _NB + r"1(?:5(?:88|77|44|66|99|22)|6(?:00|44|66|88))[-.\s]?\d{4}" + _NA
)
RE_TOLLFREE = re.compile(_NB + r"080[-.\s]?\d{3,4}[-.\s]?\d{4}" + _NA)

RE_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# 숫자 덩어리의 경계는 \b 가 아니라 '앞뒤가 숫자가 아님'으로 잡는다.
# 파이썬 \b 는 한글을 단어 글자로 쳐서 '주민번호900101-…', '운송장번호9092…'
# 처럼 라벨에 붙은 숫자를 하나도 못 찾는다. PaddleOCR 는 라벨과 값 사이
# 공백을 자주 빼먹는다.

# 주민등록번호: 생년월일 6자리 + 성별코드 + 6자리
RE_RRN = re.compile(_NB + r"(\d{2})(\d{2})(\d{2})[-\s]?([1-8])(\d{6})" + _NA)

# 사업자등록번호 3-2-5
RE_BRN = re.compile(_NB + r"(\d{3})[-\s]?(\d{2})[-\s]?(\d{5})" + _NA)

# 차량번호판에 실제로 쓰이는 한글은 정해져 있다. 아무 글자나 허용하면
# '121동 1655호' 같은 상세주소를 번호판으로 오탐한다.
PLATE_CHARS = (
    "가나다라마"      # 자가용
    "거너더러머버서어저"  # 영업용
    "고노도로모보소오조"  # 화물
    "구누두루무부수우주"  # 특수
    "바사아자"        # 일반
    "배"              # 택배
    "하허호"          # 렌터카
)
RE_PLATE = re.compile(
    rf"(?:[가-힣]{{2}}\s?)?\d{{2,3}}\s?[{PLATE_CHARS}]\s?\d{{4}}"
    r"(?!\s?(?:호|동|층|번지|원|번))"
)

# 신용카드 4-4-4-4
RE_CARD = re.compile(_NB + r"(?:\d{4}[-\s]?){3}\d{4}" + _NA)

# 도로명주소 핵심 토큰: ○○로 12, ○○길 3-4
# '로'는 조사로도 흔하다. '택배로 3개', '2시로 5분' 을 주소로 잡지 않도록
# 뒤에 단위 명사가 오면 버린다. '으로'는 _road_ok 에서 거른다.
RE_ROAD = re.compile(
    r"[가-힣A-Za-z0-9]{1,12}(?:대?로|길)\s?\d{1,4}(?!\d)(?:-\d{1,4})?(?:번길\s?\d{1,4})?"
    r"(?!\d|\s?(?:개|명|번째|시간|시|분|초|원|일|월|년|회|차|가지|kg|km|%))"
)

# 상세주소. 이게 붙으면 '개인 거주지'일 가능성이 크게 오른다.
RE_UNIT = re.compile(r"\d{1,4}\s?동\s?\d{1,4}\s?호|\d{1,3}\s?층\s?\d{1,4}\s?호")

# 행정구역
RE_REGION = re.compile(
    r"(?:서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)"
    r"(?:특별시|광역시|특별자치시|특별자치도|도)?"
)

# 운송장으로 흔히 쓰이는 자릿수. 그 자체로는 정체를 확정할 수 없다.
# '6123-4567-8901' 처럼 하이픈으로 끊어 찍는 운송장·계좌번호도 받는다.
RE_LONG_DIGITS = re.compile(r"(?<![\d-])\d(?:-?\d){9,13}(?![\d-])")

# 이 라벨 바로 옆의 긴 숫자는 운송장번호로 본다. 라벨이 없으면 단정하지 않는다.
TRACKING_LABELS = ["운송장번호", "송장번호", "운송장", "등기번호", "택배번호"]


# 이름은 형식만으로는 알 수 없다. 이 라벨 바로 뒤에 올 때만 이름 후보로 본다.
NAME_LABELS = [
    "받는분", "받으실분", "수취인", "수하인", "보내는분", "보내시는분",
    "송하인", "발송인", "성명", "이름", "고객명", "예금주", "주문자",
]

# 흔한 성씨. 라벨 뒤의 아무 2~4글자를 이름으로 잡지 않기 위한 두 번째 조건.
SURNAMES = set(
    "김이박최정강조윤장임한오서신권황안송류전홍고문양손배백허유남심노하곽성차주"
    "우구민나진지엄채원천방공현함변염여추도소석선설마길연위표명기반왕금옥육인맹제모탁국어은편용예봉경사"
) | {"남궁", "황보", "제갈", "선우", "독고", "사공", "서문"}

RE_NAME_INLINE = re.compile(
    r"(?:" + "|".join(NAME_LABELS) + r")\s?[:：]?\s?([가-힣]{2,4})(?![가-힣])"
)


# 성씨 글자로 시작하지만 이름이 아닌, 라벨 뒤에 흔히 오는 낱말
NAME_STOPWORDS = {
    "주소", "연락처", "전화", "전화번호", "정보", "확인", "서명", "고객", "본인",
    "기재", "없음", "미상", "주문", "배송", "문의", "안내", "참고", "이름", "성명",
}


def looks_like_name(token: str) -> bool:
    """2~4글자 한글이고 흔한 성씨로 시작하는가. 이름이라는 '확정'은 아니다."""
    if not re.fullmatch(r"[가-힣]{2,4}", token) or token in NAME_STOPWORDS:
        return False
    return token[:2] in SURNAMES or token[0] in SURNAMES


def compact(text: str) -> str:
    """문맥 어휘 비교용. 낱글자로 흩어진 한글('연 락 처')도 잡히게 공백을 전부 뺀다."""
    return re.sub(r"\s+", "", text)


# ------------------------------------------------------------ 문맥 어휘 사전

# 옆에 있으면 '개인의 정보'일 가능성이 오르는 말
CONTEXT_PERSONAL = [
    "수취인", "받는분", "받는 분", "받으실분", "받으실 분", "수하인",
    "보내는분", "보내는 분", "송하인", "발송인",
    "고객명", "성명", "이름", "연락처", "휴대폰", "휴대전화", "전화",
    "배송지", "주소", "도착지", "설치주소", "거주지",
]

# 옆에 있으면 '공개된 정보'일 가능성이 오르는 말
CONTEXT_PUBLIC = [
    "고객센터", "고객상담", "상담센터", "콜센터", "대표번호", "대표전화",
    "문의", "안내", "ARS", "본사", "지사", "지점", "매장", "영업소",
    "사업자", "사업자등록번호", "상호", "법인", "판매자", "가맹점",
    "택배문의", "배송문의", "반품", "교환", "A/S", "AS센터",
]

# 송장·명찰·영수증 같은 '문서'의 존재를 시사하는 말
CONTEXT_DOCUMENT = {
    "waybill": ["운송장", "송장", "택배", "배송", "수취인", "받는분", "등기", "우편"],
    "receipt": ["영수증", "합계", "부가세", "결제", "카드승인", "승인번호", "가맹점", "거래일시"],
    "badge": ["사원증", "명찰", "출입증", "소속", "부서", "팀", "사번"],
    "student": ["학생증", "학번", "학과", "대학교", "고등학교", "중학교", "재학"],
}


@dataclass
class PatternHit:
    kind: str
    text: str
    start: int
    end: int
    base_certainty: float  # 형식만 봤을 때의 신뢰도


# ---------------------------------------------------------- OCR 잡음 정규화

_OCR_DIGIT_FIX = str.maketrans({"O": "0", "o": "0", "l": "1", "I": "1", "|": "1"})


def normalize(text: str) -> str:
    """OCR이 만든 잡음을 걷어낸 뒤에 패턴을 맞춘다.

    Tesseract는 '권선로'를 '권 선 로'로 쪼개 놓는 일이 잦다. 그대로 두면
    도로명주소 정규식이 하나도 안 걸린다. 낱글자로 흩어진 한글을 다시 붙인다.

    "정규식으로 되는 걸 왜 AI라고 하나" 라는 질문의 답이 여기 있다.
    정규식은 깨끗한 문자열에서만 동작한다. 사진에서 나온 문자열은 깨끗하지 않다.
    """
    tokens = text.split()
    out: list[str] = []
    buffer: list[str] = []

    for tok in tokens:
        if len(tok) == 1 and "\uac00" <= tok <= "\ud7a3":
            buffer.append(tok)
            continue
        # '권 선로' 처럼 낱글자 뒤에 짧은 한글 조각이 오면 같은 낱말의 일부로 본다.
        if buffer and len(tok) <= 2 and re.fullmatch(r"[가-힣]+", tok):
            buffer.append(tok)
            out.append("".join(buffer))
            buffer = []
            continue
        if buffer:
            out.append("".join(buffer))
            buffer = []
        out.append(tok)
    if buffer:
        out.append("".join(buffer))

    joined = " ".join(out)
    # 숫자 사이에 낀 글자 오인식만 되돌린다. 전체에 적용하면 한글이 깨진다.
    joined = re.sub(
        r"\d[\dOolI|\-\s]{4,}\d",
        lambda m: m.group(0).translate(_OCR_DIGIT_FIX),
        joined,
    )
    return joined


# ------------------------------------------------------------- 체크섬 검증

def rrn_format_ok(digits: str) -> bool:
    """주민등록번호 형식. 13자리 + 생년월일 유효성. 체크섬은 보지 않는다."""
    d = re.sub(r"\D", "", digits)
    if len(d) != 13:
        return False
    mm, dd = int(d[2:4]), int(d[4:6])
    return 1 <= mm <= 12 and 1 <= dd <= 31


def valid_rrn(digits: str) -> bool:
    """주민등록번호 13자리 검증. 생년월일 유효성 + 가중치 체크섬.

    2020년 10월 이후 발급분은 뒷자리가 임의번호라 체크섬이 맞지 않는다.
    그래서 여기서 False 여도 형식이 맞으면 rrn_unverified 로 남긴다.
    """
    if not rrn_format_ok(digits):
        return False
    d = re.sub(r"\D", "", digits)
    weights = [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5]
    total = sum(int(d[i]) * weights[i] for i in range(12))
    return (11 - total % 11) % 10 == int(d[12])


def valid_brn(digits: str) -> bool:
    """사업자등록번호 10자리 검증."""
    d = re.sub(r"\D", "", digits)
    if len(d) != 10:
        return False
    weights = [1, 3, 7, 1, 3, 7, 1, 3, 5]
    total = sum(int(d[i]) * weights[i] for i in range(9))
    total += (int(d[8]) * 5) // 10
    return (10 - total % 10) % 10 == int(d[9])


def valid_luhn(digits: str) -> bool:
    d = re.sub(r"\D", "", digits)
    if len(d) < 12:
        return False
    total, parity = 0, len(d) % 2
    for i, ch in enumerate(d):
        n = int(ch)
        if i % 2 == parity:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _rrn_unverified(raw: str) -> bool:
    """형식은 맞는데 체크섬이 안 맞는 주민등록번호. 2020.10 이후 발급분.

    체크섬이라는 안전장치가 없으니 'YYMMDD-NNNNNNN' 처럼 구분자가 있을 때만
    받는다. 붙어 있는 13자리는 앞 6자리가 날짜처럼 보이는 운송장번호와
    구분할 수 없다.
    """
    return bool(re.search(r"\d{6}[-\s]\d", raw)) and rrn_format_ok(raw) and not valid_rrn(raw)


def _road_ok(raw: str) -> bool:
    """'으로 3' 같은 조사와 한글 없는 이름을 버린다."""
    name = re.split(r"(?:대?로|길)\s?\d", raw, maxsplit=1)[0]
    if name.endswith("으"):
        return False
    return bool(re.search(r"[가-힣]", name))


# --------------------------------------------------------------- 스캐너

_SPECS: list[tuple[str, re.Pattern, float, Optional[Callable[[str], bool]]]] = [
    ("rrn", RE_RRN, 0.95, valid_rrn),
    # 긴 숫자(0.35)보다는 높게, 검증된 번호보다는 낮게
    ("rrn_unverified", RE_RRN, 0.55, _rrn_unverified),
    ("card", RE_CARD, 0.80, valid_luhn),
    ("brn", RE_BRN, 0.70, valid_brn),
    ("mobile", RE_MOBILE, 0.90, None),
    ("service_line", RE_SERVICE_LINE, 0.90, None),
    ("tollfree", RE_TOLLFREE, 0.85, None),
    ("landline", RE_LANDLINE, 0.75, None),
    ("email", RE_EMAIL, 0.90, None),
    ("plate", RE_PLATE, 0.60, None),
    ("address_unit", RE_UNIT, 0.75, None),
    ("address_road", RE_ROAD, 0.65, _road_ok),
    ("long_digits", RE_LONG_DIGITS, 0.35, None),
]


def scan(text: str) -> list[PatternHit]:
    """문자열에서 개인정보 후보를 찾는다. 겹치는 매치는 신뢰도가 높은 쪽만 남긴다.

    offset 은 정규화된 문자열 기준이다. 원본 좌표가 아니라 겹침 판정용이다.
    """
    text = normalize(text)
    hits: list[PatternHit] = []
    for kind, pattern, base, validator in _SPECS:
        for m in pattern.finditer(text):
            raw = m.group(0)
            if validator is not None and not validator(raw):
                continue
            hits.append(PatternHit(kind, raw, m.start(), m.end(), base))

    hits.sort(key=lambda h: (-h.base_certainty, h.start))
    kept: list[PatternHit] = []
    for h in hits:
        if any(not (h.end <= k.start or h.start >= k.end) for k in kept):
            continue
        kept.append(h)
    return sorted(kept, key=lambda h: h.start)


def document_hint(text: str) -> Optional[str]:
    """텍스트 뭉치가 어떤 문서로 보이는지. 확정이 아니라 힌트다."""
    scores = {
        name: sum(1 for w in words if w in text)
        for name, words in CONTEXT_DOCUMENT.items()
    }
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] >= 2 else None
