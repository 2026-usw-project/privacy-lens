"""문맥 판단과 문서 군집. ScriptedBackend 대신 TextSpan 을 직접 넣는다."""

from pipeline import context, grouping
from pipeline.types import Box, Certainty, Severity, TextSpan


def span(text, x, y, w=200, h=20, conf=0.95):
    return TextSpan(text, Box(x, y, w, h), conf)


def by_kind(findings, kind):
    return [f for f in findings if f.kind == kind]


# ------------------------------------------------------------ 같은 줄 라벨

def test_label_on_same_line_counts():
    fs = context.evaluate([span("받는분 010-1234-5678", 0, 0, 300)])
    [m] = by_kind(fs, "mobile")
    assert m.severity is Severity.COVER


def test_spaced_label_counts():
    # Tesseract 는 '연락처'를 '연 락 처'로 준다
    fs = context.evaluate([span("연 락 처", 0, 0, 60), span("010-1234-5678", 80, 0)])
    [m] = by_kind(fs, "mobile")
    assert m.severity is Severity.COVER
    assert "연락처" in m.context_words


def test_public_word_does_not_count_as_personal():
    # '대표전화' 안의 '전화'를 개인 신호로 세지 않는다
    fs = context.evaluate([span("대표전화", 0, 0, 80), span("010-1234-5678", 90, 0)])
    [m] = by_kind(fs, "mobile")
    assert m.severity is Severity.INFO


def test_same_line_left_label_wins():
    # 1번 규칙: 바로 왼쪽 라벨이 정한다. 아래쪽 '고객센터'는 보지 않는다.
    fs = context.evaluate([
        span("연락처", 0, 0, 60), span("010-1234-5678", 80, 0),
        span("고객센터", 0, 100, 80), span("1588-0011", 100, 100, 100),
    ])
    [m] = by_kind(fs, "mobile")
    assert m.severity is Severity.COVER and "연락처" in m.message
    # 공개 쪽 라벨도 마찬가지다
    fs = context.evaluate([span("고객센터", 0, 0, 80), span("010-1234-5678", 100, 0),
                           span("수취인", 0, 60, 60)])
    [m] = by_kind(fs, "mobile")
    assert m.severity is Severity.INFO


def test_left_label_inside_merged_line():
    # Tesseract 가 라벨과 값을 한 조각으로 합친 경우. '대표전화' 는 '전화' 로도 끝나지만 공개 쪽.
    [m] = by_kind(context.evaluate([span("대표전화 010-1234-5678", 0, 0, 300),
                                    span("수취인", 0, 40, 60)]), "mobile")
    assert m.severity is Severity.INFO


def test_clearly_closer_side_wins():
    # 2번 규칙: 같은 줄 라벨은 없고 둘 다 반경 안. 개인 쪽이 절반 이하 거리.
    fs = context.evaluate([
        span("010-1234-5678", 0, 50),
        span("수취인", 150, 20, 60),   # 위로 10px. 왼쪽 정렬이 아니라 윗줄 라벨은 아니다
        span("고객센터", 150, 100, 80),  # 아래로 30px
    ])
    [m] = by_kind(fs, "mobile")
    assert m.severity is Severity.COVER


def test_similar_distance_stays_review():
    # 거리가 비슷하면 단정하지 않는다
    fs = context.evaluate([
        span("010-1234-5678", 0, 50),
        span("수취인", 150, 20, 60),   # 위로 10px
        span("고객센터", 150, 84, 80),  # 아래로 14px
    ])
    [m] = by_kind(fs, "mobile")
    assert m.severity is Severity.REVIEW


def test_low_confidence_never_exposes_text():
    fs = context.evaluate([span("010-1234-5678", 0, 0, conf=0.2)])
    [m] = fs
    assert m.certainty is Certainty.REGION_ONLY
    assert m.evidence_text is None


def test_naive_and_baseline_modes():
    spans = [span("고객센터 010-1234-5678", 0, 0, 300)]
    assert context.evaluate(spans, naive=True)[0].severity is Severity.COVER
    assert context.evaluate(spans, use_context=False)[0].severity is Severity.REVIEW


# ------------------------------------------------------------ 이름

def test_name_after_label_on_left():
    fs = context.evaluate([span("받 는 분", 0, 0, 60), span("조 예 준", 80, 0, 60)])
    [n] = by_kind(fs, "name")
    assert n.evidence_text == "조예준"
    assert n.severity is Severity.COVER


def test_name_inline():
    fs = context.evaluate([span("성명: 홍길동", 0, 0)])
    assert [n.evidence_text for n in by_kind(fs, "name")] == ["홍길동"]


def test_no_name_without_label():
    fs = context.evaluate([span("한 진 택 배", 0, 0, 80), span("김 민 준", 0, 400, 60)])
    assert by_kind(fs, "name") == []


def test_no_name_in_naive_mode():
    fs = context.evaluate([span("성명: 홍길동", 0, 0)], naive=True)
    assert by_kind(fs, "name") == []


# ------------------------------------------------------------ 군집

def test_groups_do_not_cross_documents_with_overlapping_hulls():
    # 종이 A: 글자 조각이 'ㄱ'자로 이어진다(위쪽 가로줄 + 오른쪽 세로줄).
    # 종이 B 의 휴대폰 번호는 A 의 외곽 사각형 안에 들어오지만
    # A 의 어떤 조각과도 멀다. 사각형 포함으로 소속을 정하면 섞인다.
    a = [span("배송지 권선로 208", 0, 0, 200)]
    a += [span("송장", x, 0, 40) for x in range(240, 1200, 60)]
    a += [span("운송장", 1160, y, 40) for y in range(40, 800, 40)]
    a.append(span("연락처 010-1111-2222", 960, 800, 200))
    b = [span("받는분 010-3333-4444", 200, 600, 200)]
    spans = a + b
    fs = context.evaluate(spans)
    notes = grouping.assign_groups(spans, fs)

    b_phone = next(f for f in fs if f.evidence_text == "010-3333-4444")
    a_addr = next(f for f in fs if f.kind == "address_road")
    assert b_phone.group_id != a_addr.group_id
    for n in notes:
        assert not ({"mobile", "address_road"} <= set(n.kinds) and n.group_id == b_phone.group_id)


def test_group_note_lists_all_matched_kinds_in_order():
    spans = [
        span("받 는 분", 0, 0, 60), span("홍 길 동", 80, 0, 60),
        span("연락처 010-1234-5678", 0, 30, 300),
        span("배송지 권선로 208", 0, 60, 300),
    ]
    fs = context.evaluate(spans)
    [note] = grouping.assign_groups(spans, fs)
    assert note.kinds == ["name", "mobile", "address_road"]
    assert "서로 연결할 수 있는" in note.message


# ------------------------------------------------------------ 운송장번호

def test_tracking_number_needs_label():
    for spans in (
        [span("운송장번호 909266858784", 0, 0, 300)],
        [span("운송장번호909266858784", 0, 0, 300)],
        [span("운송장번호", 0, 0, 80), span("909266858784", 100, 0)],
        [span("운송장 No. 6123-4567-8901", 0, 0, 300)],
    ):
        [f] = context.evaluate(spans)
        assert (f.kind, f.severity) == ("tracking", Severity.REVIEW), spans

    # 라벨이 없거나 다른 라벨이면 정체를 단정하지 않는다
    for text in ("909266858784", "회원번호 909266858784"):
        [f] = context.evaluate([span(text, 0, 0, 300)])
        assert (f.kind, f.severity) == ("long_digits", Severity.INFO)


# ------------------------------------------------------------ 윗줄 라벨 이어받기

def test_unit_line_inherits_label_from_line_above():
    # PaddleOCR 서식: 라벨이 따로, 주소 두 줄, 아래에 고객센터
    spans = [
        span("배송지", 0, 0, 50, 26),
        span("서울특별시 강남구 권선로 208", 80, 0, 250, 28),
        span("130동1343호", 77, 28, 125, 29),
        span("고객센터", 0, 84, 65, 22), span("1577-1234", 80, 84, 100, 26),
    ]
    [u] = by_kind(context.evaluate(spans), "address_unit")
    assert u.severity is Severity.COVER and "배송지" in u.message


def test_inherits_from_merged_line_and_label_above():
    # Tesseract 가 '배송지 …' 를 한 줄로 합친 경우
    [u] = by_kind(context.evaluate([
        span("배송지 권선로 208", 0, 0, 250), span("121동 1655호", 4, 26, 120),
    ]), "address_unit")
    assert u.severity is Severity.COVER
    # 라벨이 값 위에 있는 서식
    [m] = by_kind(context.evaluate([span("연락처", 0, 0, 60), span("010-1234-5678", 2, 24)]),
                  "mobile")
    assert m.severity is Severity.COVER


def test_three_line_chain():
    spans = [
        span("배송지", 0, 0, 50), span("경기도 수원시 영통구", 70, 0, 200),
        span("권선로 208", 70, 24, 120), span("101동 202호", 70, 48, 120),
    ]
    fs = context.evaluate(spans)
    assert by_kind(fs, "address_unit")[0].severity is Severity.COVER


def test_no_inheritance_when_far_or_misaligned():
    far = [span("배송지 권선로 208", 0, 0, 250), span("121동 1655호", 4, 80, 120)]
    shifted = [span("배송지 권선로 208", 0, 0, 250), span("121동 1655호", 140, 26, 120)]
    for spans in (far, shifted):
        # 너무 멀거나 왼쪽 정렬이 아니면 윗줄 라벨을 이어받지 않는다
        assert context._inherited_label(1, spans) is None


def test_own_label_beats_inherited():
    # 윗줄이 개인 쪽이어도 자기 줄 왼쪽에 공개 라벨이 있으면 그쪽
    spans = [span("수취인 홍길동", 0, 0, 200), span("대표번호 1588-0011", 0, 24, 200),
             span("고객센터", 0, 48, 80), span("010-1234-5678", 100, 48)]
    [m] = by_kind(context.evaluate(spans), "mobile")
    assert m.severity is Severity.INFO
