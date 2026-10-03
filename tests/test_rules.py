"""정규식 룰셋 단위 테스트 — 실제 OCR 오인식 사례를 포함 (pytest)"""
from reader.rules import find_pii, mask, normalize_digits, is_address
from schema.models import BBox, OCRLine


def L(text, x1=0, y1=0, x2=500, y2=40, conf=0.9):
    return OCRLine(text=text, conf=conf, bbox=BBox(x1=x1, y1=y1, x2=x2, y2=y2))


def types(lines):
    return sorted(h.type for h in find_pii(lines))


def test_phone_and_name_same_line():
    hits = find_pii([L("운아하   010-0107-2163")])          # 실제 OCR 결과 그대로
    assert {h.type for h in hits} == {"phone", "person_name"}
    assert next(h for h in hits if h.type == "person_name").value == "운아하"


def test_phone_variants():
    for t in ["010 1234 5678", "010.1234.5678", "01012345678", "010~1234-5678"]:
        assert "phone" in types([L(t)]), t


def test_ocr_digit_fix():
    assert normalize_digits("010-12l4-5678") == "010-1214-5678"
    assert "phone" in types([L("010-O123-4567")])


def test_tracking_with_misread_keyword():
    assert "tracking_number" in types([L("운승장번호 5787-1331-5098")])


def test_address_two_lines_merged():
    hits = find_pii([L("경기도 수원시 권선구 월드컵북로 37", y1=0, y2=40), L("29동 165호", y1=50, y2=90)])
    addr = [h for h in hits if h.type == "address"]
    assert len(addr) == 1 and addr[0].value.endswith("29동 165호")


def test_address_negative():
    assert not is_address("파이썬 프로그래밍 개정 3판")
    assert not is_address("품명: 도서")


def test_student_number_same_row():
    lines = [L("학번", x1=0, x2=80), L("20239280", x1=100, x2=300)]
    assert "student_number" in types(lines)
    assert "student_number" in types([L("학번 20239280")])


def test_rrn_and_card_luhn():
    assert "rrn" in types([L("주민번호 900101-1234567")])
    assert "card_number" in types([L("4111 1111 1111 1111")])
    assert "card_number" not in types([L("1234 5678 9012 3456")])   # Luhn 실패


def test_plate():
    assert "plate_number" in types([L("12가 3456")])
    assert "plate_number" not in types([L("12쀍 3456")])


def test_book_cover_no_pii():
    assert types([L("파이씬 프로그래망"), L("개정 3판")]) == []


def test_masks():
    assert mask("phone", "010-0107-2163") == "010-****-2163"
    assert mask("person_name", "윤아하") == "윤*하"
    assert mask("rrn", "900101-1234567") == "900101-*******"
    assert mask("address", "경기도 수원시 권선구 와우안길 17") == "경기도 수원시 권선구 ****"
    assert mask("url", "https://track.example.com/p/123") == "https://track.example.com/****"


def test_address_detail_with_label_between_tilted():
    """기울어진 송장: '배송지' 라벨이 주소 줄과 동·호 줄 사이 순서로 끼어도 연결돼야 함"""
    lines = sorted([L("서울특별시 강남구 선릉로 77", x1=150, y1=0, x2=700, y2=40),
                    L("배송지", x1=0, y1=8, x2=90, y2=48),
                    L("130동 1343호", x1=150, y1=52, x2=360, y2=90)],
                   key=lambda l: (l.bbox.y1, l.bbox.x1))
    hits = find_pii(lines)
    addr = [h for h in hits if h.type == "address"]
    det = [h for h in hits if h.type == "address_detail"]
    assert len(addr) == 1 and addr[0].value.endswith("130동 1343호")
    assert len(det) == 1 and det[0].link == addr[0].line_idx


def test_address_detail_far_away_not_linked():
    """멀리 떨어진 '101호' 같은 글자는 주소에 붙이지 않음"""
    hits = find_pii([L("경기도 수원시 권선구 와우안길 17", y1=0, y2=40), L("3동 101호", y1=400, y2=440)])
    assert not [h for h in hits if h.type == "address_detail"]


def test_tilted_address_fragments_all_masked():
    """8° 기울어진 송장의 실제 OCR 좌표 — 조각난 주소 줄과 동·호 줄이 모두 가림 범위에 들어가야 함"""
    from reader.judge import build_findings
    raw = [((1947, 1488, 2128, 1582), "조민준"), ((1744, 1520, 1881, 1607), "밭는분"),
           ((1956, 1547, 2368, 1671), "010-0482-5242"), ((2358, 1607, 2587, 1700), "선통로 77"),
           ((1760, 1615, 1890, 1695), "연락처"), ((2209, 1629, 2380, 1728), "강남구"),
           ((1968, 1653, 2236, 1758), "서울특별시 ="), ((1770, 1701, 1908, 1782), "배송지"),
           ((2122, 1716, 2303, 1804), "1343호"), ((1980, 1741, 2136, 1827), "130동"),
           ((1979, 1903, 2200, 1983), "1577-1234")]
    lines = sorted([L(t, *b) for b, t in raw], key=lambda l: (l.bbox.y1, l.bbox.x1))
    f = build_findings(4032, 3024, lines, [])
    boxes = [p.bbox for x in f for p in x.pii if p.bbox]

    def covered(x1, y1, x2, y2):
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        return any(b.x1 <= cx <= b.x2 and b.y1 <= cy <= b.y2 for b in boxes)

    for b, t in raw:
        if t in ("서울특별시 =", "강남구", "선통로 77", "130동", "1343호", "010-0482-5242", "조민준"):
            assert covered(*b), f"{t} 가 가림 범위 밖"
    assert not covered(1979, 1903, 2200, 1983), "고객센터 번호까지 가리면 안 됨"


def test_address_detail_linked_when_boxes_overlap_4deg():
    """4° 기울기 실제 좌표: 두 줄의 축 정렬 박스가 겹쳐도(gap<0) 둘째 줄로 연결"""
    lines = sorted([L("서클별시강남구 선물로7", 1939, 1561, 2621, 1733), L("배송지", 1753, 1652, 1888, 1718),
                    L("1343호", 2106, 1685, 2293, 1769), L("130동", 1954, 1689, 2128, 1787)],
                   key=lambda l: (l.bbox.y1, l.bbox.x1))
    hits = find_pii(lines)
    assert any(h.type == "address_detail" for h in hits)


def test_same_row_on_same_line_not_detail():
    """같은 줄 높이에 있는 '101호' 는 둘째 줄이 아님 (중심이 아래가 아니면 연결 안 함)"""
    hits = find_pii([L("경기도 수원시 권선구 와우안길 17", x1=0, x2=500, y1=0, y2=40), L("101호", x1=520, x2=600, y1=2, y2=40)])
    assert not [h for h in hits if h.type == "address_detail"]
