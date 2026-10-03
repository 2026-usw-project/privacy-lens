"""
회전 사각형(기울기 맞춤 영역) 계산 도구

좌표 순서는 항상 [좌상, 우상, 우하, 좌하] (시계방향) — schema 의 polygon 규칙과 동일.
"""
from __future__ import annotations

from typing import Iterable, List, Sequence

import cv2
import numpy as np

Quad = List[List[float]]


def order_quad(pts: Sequence[Sequence[float]]) -> Quad:
    """임의 순서의 네 점을 [좌상, 우상, 우하, 좌하] 로 정렬 (기울기 ±45° 이내 가정)"""
    p = np.asarray(pts, dtype=np.float32).reshape(4, 2)
    s, d = p.sum(1), p[:, 1] - p[:, 0]
    return [p[np.argmin(s)].tolist(), p[np.argmin(d)].tolist(), p[np.argmax(s)].tolist(), p[np.argmax(d)].tolist()]


def min_area_quad(points: Iterable[Sequence[float]]) -> Quad:
    """점들을 가장 작게 감싸는 회전 사각형"""
    p = np.asarray(list(points), dtype=np.float32).reshape(-1, 2)
    return order_quad(cv2.boxPoints(cv2.minAreaRect(p)))


def angle_deg(q: Quad) -> float:
    (x0, y0), (x1, y1) = q[0], q[1]
    return float(np.degrees(np.arctan2(y1 - y0, x1 - x0)))


def contains(outer: Sequence[float], quad: Sequence[Sequence[float]], tol: float = 2.0) -> bool:
    """outer = [x_min, x_max, y_min, y_max] 안에 quad 가 (tol 픽셀 오차로) 완전히 들어가는지"""
    x1, x2, y1, y2 = outer
    return all(x1 - tol <= x <= x2 + tol and y1 - tol <= y <= y2 + tol for x, y in quad)


def quad_at_angle(points: Iterable[Sequence[float]], deg: float) -> Quad:
    """주어진 기울기(도)로 점들을 감싸는 최소 사각형"""
    p = np.asarray(list(points), dtype=np.float32).reshape(-1, 2)
    t = np.radians(deg)
    u = np.array([np.cos(t), np.sin(t)], np.float32)        # 글자 진행 방향
    v = np.array([-np.sin(t), np.cos(t)], np.float32)       # 글자 높이 방향
    a, b = p @ u, p @ v
    c = lambda s, r: (u * s + v * r).tolist()
    return [c(a.min(), b.min()), c(a.max(), b.min()), c(a.max(), b.max()), c(a.min(), b.max())]


def size(q: Quad) -> tuple[float, float]:
    w = float(np.hypot(q[1][0] - q[0][0], q[1][1] - q[0][1]))
    h = float(np.hypot(q[3][0] - q[0][0], q[3][1] - q[0][1]))
    return w, h


def center(q: Quad) -> tuple[float, float]:
    return float(sum(p[0] for p in q) / 4), float(sum(p[1] for p in q) / 4)


def smooth_angles(quads: List[Quad], min_aspect: float = 3.0, radius: float = 6.0, tol: float = 1.5) -> List[Quad]:
    """짧은 줄(단어 1~2개)은 기울기 추정이 부정확 → 주변 긴 줄들의 기울기 중앙값으로 다시 감쌈.
    같은 종이 위의 글자는 같은 방향으로 기울어 있다는 가정."""
    info = [(q, *size(q), center(q), angle_deg(q)) for q in quads]
    reliable = [(c, a, h) for q, w, h, c, a in info if h > 0 and w / h >= min_aspect]
    out = []
    for q, w, h, c, a in info:
        near = [ra for rc, ra, rh in reliable if np.hypot(rc[0] - c[0], rc[1] - c[1]) < radius * max(h, rh)]
        if near and (h == 0 or w / h < min_aspect):
            m = float(np.median(near))
            if abs(m - a) > tol:
                q = quad_at_angle(q, m)
        out.append(q)
    return out
