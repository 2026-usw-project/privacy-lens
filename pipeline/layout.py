"""글줄 좌표계.

문맥 판단은 '같은 줄', '바로 왼쪽', '바로 윗줄', '가까운 정도'를 묻는다. 이것을
화면의 가로·세로로 재면 송장이 기울었을 때 틀린다. 30° 기울어진 송장에서는 같은
줄이라도 오른쪽으로 갈수록 위로 올라가서, '받는분' 옆의 이름이 48px 위에 찍히고
'다른 줄'로 판정됐다.

그래서 **글줄 방향**을 기준으로 잰다. PaddleOCR 가 주는 글자 외곽선의 긴 축이
글줄 방향이다.

  r  읽는 방향(글줄을 따라 오른쪽)   along  = r 방향 좌표
  n  다음 줄 방향(글줄의 아래쪽)      across = n 방향 좌표

외곽선이 없으면(Tesseract) r = 화면 오른쪽, n = 화면 아래다. 이때 모든 계산이
예전 가로·세로 계산과 정확히 같다.

방향 두 가지 모호함을 이렇게 푼다.

1. 축의 앞뒤. 긴 축만으로는 오른쪽인지 왼쪽인지 모른다. 문서 전체의 주된 축을
   먼저 구하고 각 줄의 축을 그쪽으로 맞춘다(89°와 91°가 반대로 뒤집히지 않게).
2. 뒤집힌 문서(180°). 축이 같아도 읽는 방향이 반대다. 라벨('받는분', '연락처' …)은
   값보다 **앞에** 온다. 라벨 바로 옆 값이 축의 어느 쪽에 있는지 투표해서 정한다.
   라벨이 없으면 뒤집히지 않았다고 본다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from . import kr_patterns as kp
from .types import Box, TextSpan

Vec = tuple[float, float]

# 긴 변이 짧은 변의 이 배수보다 짧으면 방향을 모른다고 본다(낱글자 '권', '호').
MIN_ASPECT = 1.3
# 라벨로 볼 조각의 최대 길이(공백 뺀 글자 수). '배송문의는 고객센터로 …' 같은 문장은 라벨이 아니다.
LABEL_MAX_CHARS = 8


def _axis(box: Box) -> Vec | None:
    """외곽선의 긴 축 단위벡터. 방향을 모르면 None."""
    if not box.poly or len(box.poly) != 4:
        return None
    p = box.poly
    u = ((p[1][0] - p[0][0] + p[2][0] - p[3][0]) / 2, (p[1][1] - p[0][1] + p[2][1] - p[3][1]) / 2)
    v = ((p[3][0] - p[0][0] + p[2][0] - p[1][0]) / 2, (p[3][1] - p[0][1] + p[2][1] - p[1][1]) / 2)
    lu, lv = math.hypot(*u), math.hypot(*v)
    if min(lu, lv) < 1:
        return None
    (long, ll), sl = ((u, lu), lv) if lu >= lv else ((v, lv), lu)
    if ll / sl < MIN_ASPECT:
        return None
    return (long[0] / ll, long[1] / ll)


def _dominant(axes: list[tuple[Vec, float]]) -> Vec | None:
    """축들의 주된 방향. 각도를 두 배로 해서 평균 낸다(앞뒤가 없는 방향의 평균)."""
    sx = sum(w * math.cos(2 * math.atan2(a[1], a[0])) for a, w in axes)
    sy = sum(w * math.sin(2 * math.atan2(a[1], a[0])) for a, w in axes)
    if math.hypot(sx, sy) < 1e-6:
        return None
    t = math.atan2(sy, sx) / 2
    return (math.cos(t), math.sin(t))


def _corners(box: Box) -> list[Vec]:
    if box.poly and len(box.poly) >= 3:
        return list(box.poly)
    return [(box.x, box.y), (box.x + box.w, box.y),
            (box.x + box.w, box.y + box.h), (box.x, box.y + box.h)]


@dataclass(frozen=True)
class Extent:
    """조각이 글줄 좌표계에서 차지하는 범위. a 는 along, c 는 across."""

    a0: float
    a1: float
    c0: float
    c1: float

    @property
    def mid_c(self) -> float:
        return (self.c0 + self.c1) / 2

    @property
    def thick(self) -> float:
        return self.c1 - self.c0


def _is_label(text: str) -> bool:
    flat = kp.compact(kp.normalize(text)).rstrip(":：.#")
    if not flat or len(flat) > LABEL_MAX_CHARS:
        return False
    words = kp.CONTEXT_PERSONAL + kp.CONTEXT_PUBLIC + kp.NAME_LABELS + kp.TRACKING_LABELS
    return any(flat.endswith(kp.compact(w)) for w in words)


class Layout:
    """한 장의 OCR 결과에 대한 글줄 기하. 같은 spans 로 여러 번 물어도 한 번만 만든다."""

    def __init__(self, spans: list[TextSpan]):
        self.spans = spans
        raw = [_axis(s.box) for s in spans]
        weighted = [(a, s.box.w + s.box.h) for a, s in zip(raw, spans) if a]
        ref = _dominant(weighted) if weighted else None
        # 각 줄의 축을 문서의 주된 방향 쪽으로 맞춘다
        self._axes: list[Vec | None] = []
        for a in raw:
            if a and ref and a[0] * ref[0] + a[1] * ref[1] < 0:
                a = (-a[0], -a[1])
            self._axes.append(a)
        self.sign = self._reading_sign()

    # ------------------------------------------------------------ 좌표계

    def _frame(self, i: int, j: int) -> tuple[Vec, Vec]:
        a = self._axes[i] or self._axes[j]
        if a is None:
            return (1.0, 0.0), (0.0, 1.0)  # 외곽선 없음: 화면 가로·세로
        r = (a[0] * self.sign, a[1] * self.sign)
        return r, (-r[1], r[0])  # 화면 좌표(y 아래)에서 r 을 시계 방향 90° 돌린 것이 '아래'

    def _extent(self, k: int, r: Vec, n: Vec) -> Extent:
        pts = _corners(self.spans[k].box)
        along = [p[0] * r[0] + p[1] * r[1] for p in pts]
        across = [p[0] * n[0] + p[1] * n[1] for p in pts]
        return Extent(min(along), max(along), min(across), max(across))

    def pair(self, i: int, j: int) -> tuple[Extent, Extent]:
        r, n = self._frame(i, j)
        return self._extent(i, r, n), self._extent(j, r, n)

    # ------------------------------------------------------------ 질문들

    def thickness(self, i: int) -> float:
        me, _ = self.pair(i, i)
        return me.thick

    def distance(self, i: int, j: int) -> float:
        """두 조각 가장자리 사이 거리(글줄 좌표계)."""
        me, ot = self.pair(i, j)
        ga = max(0.0, ot.a0 - me.a1, me.a0 - ot.a1)
        gc = max(0.0, ot.c0 - me.c1, me.c0 - ot.c1)
        return math.hypot(ga, gc)

    def left_neighbors(self, i: int) -> list[int]:
        """같은 줄, 읽는 방향으로 바로 앞(왼쪽)에 있는 조각. 가까운 것부터."""
        out = []
        for j in range(len(self.spans)):
            if j == i:
                continue
            me, ot = self.pair(i, j)
            same_line = abs(ot.mid_c - me.mid_c) <= min(ot.thick, me.thick) * 0.8
            gap = me.a0 - ot.a1
            if same_line and -4 <= gap <= max(ot.thick, me.thick) * 4:
                out.append((gap, j))
        return [j for _, j in sorted(out)]

    def line_above(self, i: int) -> int | None:
        """바로 윗줄에 줄 머리를 맞춰 붙어 있는 조각."""
        best = None
        for j in range(len(self.spans)):
            if j == i:
                continue
            me, ot = self.pair(i, j)
            h = min(ot.thick, me.thick)
            gap = me.c0 - ot.c1
            above = ot.mid_c < me.mid_c - 0.5 * h
            aligned = abs(ot.a0 - me.a0) <= 1.5 * h
            if above and aligned and -0.35 * h <= gap <= 0.9 * h:
                if best is None or gap < best[0]:
                    best = (gap, j)
        return best[1] if best else None

    # ------------------------------------------------------------ 뒤집힘

    def _reading_sign(self) -> int:
        """라벨 바로 옆 값이 축의 앞쪽에 있으면 +1, 뒤쪽이면 -1(뒤집힌 문서)."""
        votes = 0
        for i, s in enumerate(self.spans):
            a = self._axes[i]
            if a is None or not _is_label(s.text):
                continue
            n = (-a[1], a[0])
            me = self._extent(i, a, n)
            best = None
            for j in range(len(self.spans)):
                if j == i:
                    continue
                ot = self._extent(j, a, n)
                if abs(ot.mid_c - me.mid_c) > min(ot.thick, me.thick) * 0.8:
                    continue
                after, before = ot.a0 - me.a1, me.a0 - ot.a1
                gap = max(after, before)
                if -4 <= gap <= max(ot.thick, me.thick) * 4 and (best is None or gap < best[0]):
                    best = (gap, 1 if after >= before else -1)
            if best:
                votes += best[1]
        return 1 if votes >= 0 else -1


_last: tuple[list[TextSpan] | None, Layout | None] = (None, None)


def layout(spans: list[TextSpan]) -> Layout:
    """같은 spans 목록이면 만들어 둔 것을 쓴다. 문맥 판단은 한 장에 수백 번 묻는다."""
    global _last
    cached_spans, cached = _last
    if cached_spans is spans and cached is not None:
        return cached
    lay = Layout(spans)
    _last = (spans, lay)
    return lay
