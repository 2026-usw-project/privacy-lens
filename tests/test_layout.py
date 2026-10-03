"""글줄 좌표계. 0° 서식을 통째로 돌려도 판정이 같아야 한다."""

import math

import pytest

from pipeline import context, layout
from pipeline.types import Box, Severity, TextSpan

# 0° 송장 서식: (글자, x, y, 너비, 높이). PaddleOCR 처럼 라벨과 값이 따로 온다.
WAYBILL = [
    ("받는분", 20, 80, 57, 26),
    ("박민준", 105, 77, 79, 35),
    ("연락처", 20, 126, 50, 23),
    ("010-5179-2931", 105, 125, 150, 24),
    ("배송지", 20, 170, 53, 26),
    ("경기도 화성시 권선로 242", 105, 168, 250, 28),
    ("121동1655호", 102, 196, 125, 29),
    ("고객센터", 20, 270, 65, 22),
    ("1577-1234", 105, 268, 101, 26),
    ("배송문의는 고객센터로 연락 바랍니다", 230, 270, 260, 22),
]


def rotated(angle: float, cx: float = 300, cy: float = 200) -> list[TextSpan]:
    """서식 전체를 (cx, cy) 기준으로 angle 도 돌린다(화면에서 반시계, PIL rotate 와 같은 쪽).

    외곽선 꼭짓점 순서는 PaddleOCR 처럼 화면 기준 왼쪽 위부터 시계 방향으로 다시 맞춘다.
    그래야 '꼭짓점 순서로 방향을 알아내는' 꼼수 없이 진짜로 축을 구하는지 확인된다.
    """
    t = math.radians(angle)
    c, s = math.cos(t), math.sin(t)

    def rot(x, y):
        dx, dy = x - cx, y - cy
        return (cx + dx * c + dy * s, cy - dx * s + dy * c)

    spans = []
    for text, x, y, w, h in WAYBILL:
        pts = [rot(x, y), rot(x + w, y), rot(x + w, y + h), rot(x, y + h)]
        # 화면 기준 정렬: 무게중심 기준 각도로 시계 방향, 왼쪽 위에서 시작
        mx = sum(p[0] for p in pts) / 4
        my = sum(p[1] for p in pts) / 4
        pts.sort(key=lambda p: math.atan2(p[1] - my, p[0] - mx))
        start = min(range(4), key=lambda k: pts[k][0] + pts[k][1])
        pts = pts[start:] + pts[:start]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        box = Box(int(min(xs)), int(min(ys)), int(max(xs) - min(xs)), int(max(ys) - min(ys)),
                  poly=tuple(pts))
        spans.append(TextSpan(text, box, 0.98))
    return spans


def verdicts(spans):
    fs = context.evaluate(spans)
    by = {f.kind: f for f in fs}
    return {
        "name": by.get("name") and by["name"].evidence_text,
        "mobile": by["mobile"].severity if "mobile" in by else None,
        "address_road": by["address_road"].severity if "address_road" in by else None,
        "address_unit": by["address_unit"].severity if "address_unit" in by else None,
        "service_line": by["service_line"].severity if "service_line" in by else None,
    }


EXPECTED = {
    "name": "박민준",
    "mobile": Severity.COVER,
    "address_road": Severity.COVER,
    "address_unit": Severity.COVER,
    "service_line": Severity.INFO,
}


@pytest.mark.parametrize("angle", [0, 15, 30, 45, 60, 90, 135, 180, 270, -20])
def test_same_verdicts_at_any_angle(angle):
    assert verdicts(rotated(angle)) == EXPECTED


def test_reading_sign_detects_upside_down():
    assert layout.Layout(rotated(0)).sign == 1
    up, down = layout.Layout(rotated(10)), layout.Layout(rotated(190))
    # 축은 같은 쪽으로 맞춰지지만 읽는 방향은 반대여야 한다
    assert up.sign == -down.sign


def test_without_outlines_frame_is_screen_axes():
    spans = [TextSpan(t, Box(x, y, w, h), 0.98) for t, x, y, w, h in WAYBILL]
    lay = layout.Layout(spans)
    assert lay.left_neighbors(1) == [0]          # 박민준 ← 받는분
    assert lay.line_above(6) == 5                 # 동·호수 ↑ 주소
    assert lay.distance(0, 1) == spans[0].box.distance_to(spans[1].box)
    assert verdicts(spans) == EXPECTED
