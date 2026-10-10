"""출력 문구 템플릿.

사용자에게 나가는 문장은 **전부 이 파일에서만** 만들어진다.
다른 모듈에서 f-string 으로 메시지를 조립하지 않는다.

이유: "단정하지 않는다"를 내부 원칙으로만 두면 개발 중에 새어나간다.
어미를 코드에 고정해두면 급하게 문구를 추가할 때도 무너지지 않는다.

금지 표현 (assert_safe 가 실제로 막는다):
  - "~입니다" 로 끝나는 신원 단정
  - "확인되었습니다", "확정", "본인의", "당신의 집"
허용 어미:
  - "~로 추정되는", "~가 함께 노출됨", "~가 포함됨", "~를 확인하지 못했습니다"
"""

from __future__ import annotations

BANNED = [
    "당신의 집", "사용자의 집", "거주지입니다", "본인 소유",
    "확정됩니다", "신원이 특정됩니다", "재직 중입니다",
]

KIND_NOUN = {
    "mobile": "휴대전화번호",
    "landline": "유선전화번호",
    "service_line": "대표번호",
    "tollfree": "무료상담번호",
    "email": "이메일 주소",
    "rrn": "주민등록번호 형식의 숫자",
    "rrn_unverified": "주민등록번호 형식의 숫자",
    "name": "이름으로 보이는 문자열",
    "brn": "사업자등록번호 형식의 숫자",
    "card": "카드번호 형식의 숫자",
    "plate": "차량번호 형식의 문자열",
    "address_road": "도로명주소 형식의 문자열",
    "address_unit": "동·호수 형식의 상세주소",
    "long_digits": "긴 자릿수의 숫자",
    "tracking": "운송장번호로 보이는 숫자",
    "qr": "QR코드",
    "barcode": "바코드",
    "gps": "촬영 위치 좌표",
    "document": "문서 영역",
    "face_photo": "증명사진",
}

DOC_NOUN = {
    "waybill": "택배 송장",
    "receipt": "영수증",
    "badge": "명찰 또는 사원증",
    "student": "학생증",
    "id_card": "학생증 또는 카드",
    "screen": "화면",
}


def _has_final(word: str) -> bool:
    """마지막 글자에 받침이 있는가. 한글 유니코드는 28로 나눈 나머지가 종성이다."""
    if not word:
        return False
    ch = word[-1]
    if not ("\uac00" <= ch <= "\ud7a3"):
        return True  # 숫자·영문 뒤에는 받침 있는 쪽 조사를 쓴다
    return (ord(ch) - 0xAC00) % 28 != 0


def josa(word: str, pair: str = "이/가") -> str:
    """'문자열가 인식됨' 같은 문장이 나가지 않게 한다.

    '으로/로'는 ㄹ 받침 뒤에서도 '로'를 쓴다(문자열로, 서울로).
    """
    with_final, without_final = pair.split("/")
    final = _has_final(word)
    if final and with_final == "으로" and _final_is_rieul(word):
        final = False
    return word + (with_final if final else without_final)


def _final_is_rieul(word: str) -> bool:
    ch = word[-1] if word else ""
    return "\uac00" <= ch <= "\ud7a3" and (ord(ch) - 0xAC00) % 28 == 8


def assert_safe(message: str) -> str:
    """단정 표현이 섞여 들어가면 즉시 실패시킨다. 조용히 통과시키지 않는다."""
    for phrase in BANNED:
        if phrase in message:
            raise ValueError(f"단정 표현이 문구에 포함됨: {phrase!r} / {message!r}")
    return message


def found(kind: str, *, near: str | None = None) -> str:
    noun = KIND_NOUN.get(kind, "개인정보 후보")
    if near:
        return assert_safe(f"'{near}' 주변에서 {josa(noun)} 인식됨")
    return assert_safe(f"{josa(noun)} 인식됨")


def found_public(kind: str, *, near: str | None = None) -> str:
    noun = KIND_NOUN.get(kind, "문자열")
    hint = f"'{near}' 주변이라 " if near else ""
    return assert_safe(f"{hint}공개된 {josa(noun, '으로/로')} 보임")


def region_only(doc: str | None = None) -> str:
    noun = DOC_NOUN.get(doc or "", "문서 또는 카드")
    return assert_safe(f"{josa(noun, '으로/로')} 추정되는 영역이 있으나 글자가 흐려 내용을 확인하지 못했습니다")


def qr_decoded(payload_kind: str) -> str:
    mapping = {
        "url": "QR코드에 웹주소가 들어 있음",
        "vcard": "QR코드에 연락처 정보가 들어 있음",
        "wifi": "QR코드에 Wi-Fi 접속정보가 들어 있음",
        "tel": "QR코드에 전화번호가 들어 있음",
        "text": "QR코드가 해독되었으나 내용의 종류를 확정할 수 없음",
    }
    return assert_safe(mapping.get(payload_kind, mapping["text"]))


def qr_contains(nouns: list[str]) -> str:
    """QR 안의 문자열에서 개인정보 형식이 나왔을 때. 값은 보여주지 않는다."""
    return assert_safe(f"QR코드 안에 {josa(', '.join(nouns))} 들어 있음")


def barcode_decoded() -> str:
    return assert_safe("바코드가 해독됨. 운송장번호 등 배송 조회에 쓰이는 번호일 수 있음")


def document_unconfirmed(doc: str | None = None) -> str:
    noun = DOC_NOUN.get(doc or "", "문서 또는 카드")
    return assert_safe(
        f"{josa(noun, '으로/로')} 추정되는 영역에서 일부 글자는 읽었으나 개인정보 항목을 확인하지 못했습니다"
    )


def face_photo_region() -> str:
    return assert_safe("카드나 서류에 인쇄된 증명사진으로 보이는 영역이 있음")


def qr_undecoded() -> str:
    return assert_safe("QR코드 또는 바코드로 보이는 영역이 있으나 해독하지 못했습니다")


def gps_present(lat: float, lon: float) -> str:
    return assert_safe(
        f"사진 파일에 촬영 위치 좌표가 포함됨 ({lat:.5f}, {lon:.5f})"
    )


def combined(doc: str | None, nouns: list[str]) -> str:
    """같은 문서 안에서 함께 발견된 항목 설명.

    '연결할 수 있다'까지만 말하고, 그 대상이 누구인지는 말하지 않는다.
    """
    where = DOC_NOUN.get(doc or "", "같은 영역")
    joined = ", ".join(nouns)
    return assert_safe(
        f"{where} 안에서 {josa(joined)} 함께 노출됨. 서로 연결할 수 있는 상태입니다"
    )


GPS_UNREADABLE = assert_safe("사진 파일에 위치정보 태그가 있으나 좌표를 확인하지 못했습니다")


OCR_UNAVAILABLE = assert_safe("문자 인식 처리에 실패했습니다. 잠시 후 다시 시도해 주세요.")


NO_FINDINGS = "추가로 탐지된 항목이 없습니다"


def all_templates() -> list[str]:
    """테스트용. 이 파일이 만들 수 있는 문장을 종류별로 하나씩 만든다.

    assert_safe 가 실서비스에서 터지기 전에 테스트에서 먼저 터지게 하려는 것.
    """
    out = []
    for kind in KIND_NOUN:
        out += [found(kind), found(kind, near="수취인"),
                found_public(kind), found_public(kind, near="고객센터")]
    for doc in list(DOC_NOUN) + [None]:
        out += [region_only(doc), document_unconfirmed(doc), combined(doc, ["휴대전화번호", "도로명주소"])]
    for kind in ("url", "vcard", "wifi", "tel", "text", "unknown"):
        out.append(qr_decoded(kind))
    out += [qr_undecoded(), face_photo_region(), qr_contains(["휴대전화번호"]), barcode_decoded(),
            gps_present(37.5, 127.0), NO_FINDINGS]
    return out
