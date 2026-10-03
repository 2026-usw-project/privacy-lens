"""가림과 검증.

가리는 방식은 두 가지다. 어느 쪽이든 **가린 자리에 원본 화소의 정보가 남지 않는다.**

- solid: 단색으로 덮는다.
- blur(기본): 흐린 유리처럼 보이게 덮는다. 다만 글자 위에 블러를 거는 게 아니다.

진짜 블러(글자에 가우시안을 거는 것)는 되돌릴 수 있다. 전화번호·운송장번호는
글꼴과 형식이 정해져 있어서, 후보 번호를 전부 같은 글꼴로 그려 같은 블러를 건 뒤
비교하면 맞춰진다. 모자이크도 마찬가지다(Depix 류). 개인정보 서비스가 쓸 방법이 아니다.

그래서 blur 는 이렇게 만든다.
  1. 가릴 자리를 **주변 테두리의 평균색**으로 채운다. 이 순간 원본 글자는 사라진다.
  2. 그 상태에서 블러를 걸어 주변과 부드럽게 이어 붙이고, 옅은 결(노이즈)을 얹는다.
결과는 가린 자리 바깥 화소로만 만들어진다. 같은 자리에 다른 번호가 있었어도
결과는 똑같다(테스트가 이것을 확인한다).

그리고 가린 뒤에 **다시 검사한다**. 캔버스에 박스만 그려놓고 원본을 그대로
내보내는 사고가 흔하다. 내려받은 파일을 실제로 다시 읽어서 확인해야 한다.
"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .types import Box

FILL = (24, 24, 27)
STYLES = ("blur", "solid")
DEFAULT_STYLE = "blur"

# 흐린 유리 결. 너무 세면 지저분하고, 없으면 평평한 색면이 티가 난다.
GRAIN = 5.0
# 살짝 밝게. 가렸다는 게 보여야 한다. 주변과 완전히 같으면 사진을 받은 사람이
# '원래 아무것도 없었다'고 오해할 수 있다.
FROST = 0.14

# 여백은 상자 높이에 비례해서 준다. 3px 고정이면 4000px 사진에서
# OCR 상자 밖으로 삐져나온 글자 끝(받침, 아래 획)이 남는다.
PAD_MIN = 3
PAD_RATIO = 0.18

# 다시 검사한 항목이 선택 영역과 이만큼 겹치면 '가렸는데 남은 것'으로 본다.
OVERLAP_RATIO = 0.4


def pad_for(b: Box) -> int:
    return max(PAD_MIN, round(min(b.w, b.h) * PAD_RATIO))


def _rect(b: Box, size: tuple[int, int]) -> tuple[int, int, int, int] | None:
    """축 정렬 상자에 여백을 붙이고 이미지 안으로 자른 (x0, y0, x1, y1). 비면 None."""
    pad = pad_for(b)
    x0, y0 = max(0, b.x - pad), max(0, b.y - pad)
    x1, y1 = min(size[0], b.x + b.w + pad), min(size[1], b.y + b.h + pad)
    return (x0, y0, x1, y1) if x1 > x0 and y1 > y0 else None


# ---------------------------------------------------------------- 외곽선

def _quad_frame(poly):
    """네 꼭짓점 외곽선을 (중심, 긴 축 단위벡터, 짧은 축 단위벡터, 반길이, 반폭)으로.

    PaddleOCR 외곽선은 거의 직사각형이지만 꼭 직각은 아니다. 마주 보는 변을
    평균 내서 축을 잡는다. 찌그러져 축을 못 잡으면 None.
    """
    p = np.asarray(poly, dtype=np.float64)
    u = ((p[1] - p[0]) + (p[2] - p[3])) / 2
    v = ((p[3] - p[0]) + (p[2] - p[1])) / 2
    lu, lv = np.linalg.norm(u), np.linalg.norm(v)
    if lu < 1 or lv < 1:
        return None
    return p.mean(axis=0), u / lu, v / lv, lu / 2, lv / 2


def _outline(b: Box, extra: float = 0.0) -> tuple[list[tuple[float, float]], float]:
    """가릴 외곽선(여백 + extra 만큼 바깥으로 넓힌 것)과 글자 두께.

    - 기울어진 외곽선(poly 네 점)이 있으면 그 축을 따라 넓힌다.
    - 없으면 축 정렬 상자. 꼭짓점을 (x1-1, y1-1) 로 잡아 채운 화소가 _rect 와 똑같다.
    """
    if b.poly and len(b.poly) == 4:
        frame = _quad_frame(b.poly)
        if frame is not None:
            c, u, v, hu, hv = frame
            thick = 2 * min(hu, hv)
            grow = max(PAD_MIN, round(thick * PAD_RATIO)) + extra
            a, d = hu + grow, hv + grow
            pts = [c - u * a - v * d, c + u * a - v * d, c + u * a + v * d, c - u * a + v * d]
            return [(float(x), float(y)) for x, y in pts], float(thick)
    grow = pad_for(b) + extra
    x0, y0 = b.x - grow, b.y - grow
    x1, y1 = b.x + b.w + grow, b.y + b.h + grow
    return [(x0, y0), (x1 - 1, y0), (x1 - 1, y1 - 1), (x0, y1 - 1)], float(min(b.w, b.h))


def _shape(b: Box) -> list[tuple[float, float]]:
    """여백 없는 실제 모양. 다시 검사할 때 겹침 판정용."""
    if b.poly and len(b.poly) >= 3:
        return [tuple(map(float, pt)) for pt in b.poly]
    return [(b.x, b.y), (b.x + b.w - 1, b.y), (b.x + b.w - 1, b.y + b.h - 1), (b.x, b.y + b.h - 1)]


def _bounds(pts, size) -> tuple[int, int, int, int] | None:
    """외곽선을 감싸는 정수 범위 (x0, y0, x1, y1), 이미지 안으로 자름. x1, y1 은 미포함."""
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x0, y0 = max(0, int(np.floor(min(xs)))), max(0, int(np.floor(min(ys))))
    x1, y1 = min(size[0], int(np.ceil(max(xs))) + 1), min(size[1], int(np.ceil(max(ys))) + 1)
    return (x0, y0, x1, y1) if x1 > x0 and y1 > y0 else None


def _raster(pts, bounds) -> np.ndarray:
    """외곽선 안쪽 화소를 bounds 크기의 참/거짓 배열로."""
    x0, y0, x1, y1 = bounds
    canvas = Image.new("L", (x1 - x0, y1 - y0), 0)
    ImageDraw.Draw(canvas).polygon([(x - x0, y - y0) for x, y in pts], fill=255)
    return np.asarray(canvas) > 0


def _seed(bounds) -> int:
    """결(노이즈)은 자리마다 고정한다. 같은 입력이면 같은 결과가 나와야 검증이 된다."""
    x0, y0, x1, y1 = bounds
    return (x0 * 73856093 ^ y0 * 19349663 ^ x1 * 83492791 ^ y1 * 2654435761) & 0xFFFFFFFF


# ---------------------------------------------------------------- 가리기

def apply_masks(
    image: Image.Image, boxes: list[Box], style: str = DEFAULT_STYLE
) -> Image.Image:
    """선택된 영역을 가린다. 원본은 건드리지 않는다.

    기울어진 외곽선이 있으면 그 모양 그대로 가린다. 축 정렬 사각형으로 가리면
    30° 기울어진 송장에서 가리는 넓이가 글자의 2~6배가 되고 위아래 줄까지 덮인다.
    """
    if style not in STYLES:
        raise ValueError(f"알 수 없는 가림 방식: {style!r}")
    out = image.convert("RGB").copy()

    regions = []
    for b in boxes:
        pts, thick = _outline(b)
        bounds = _bounds(pts, out.size)
        if bounds:
            regions.append((b, pts, thick, bounds, _raster(pts, bounds)))

    if style == "solid":
        draw = ImageDraw.Draw(out)
        for _, pts, _, _, _ in regions:
            draw.polygon(pts, fill=FILL)
        return out

    # 가릴 자리 전체. 테두리 평균에서 빼야 하고, 블러 전에 전부 지워져 있어야 한다.
    union = np.zeros((out.height, out.width), dtype=bool)
    for _, _, _, (x0, y0, x1, y1), mask in regions:
        union[y0:y1, x0:x1] |= mask

    # 1. 모든 자리를 테두리 평균색으로 채운다. 여기서 원본 글자가 사라진다.
    #    평균은 채우기 전 화소로 재되, 다른 가릴 자리 안의 화소는 세지 않는다.
    #    다른 영역의 글자가 평균에 섞이면 그만큼 정보가 샌다.
    arr = np.asarray(out, dtype=np.float32)
    filled = arr.copy()
    for b, pts, thick, (x0, y0, x1, y1), mask in regions:
        ring_pts, _ = _outline(b, extra=max(4.0, thick / 3))
        rb = _bounds(ring_pts, out.size)
        rx0, ry0, rx1, ry1 = rb
        ring = _raster(ring_pts, rb) & ~union[ry0:ry1, rx0:rx1]
        pixels = arr[ry0:ry1, rx0:rx1][ring]
        color = pixels.mean(axis=0) if pixels.size else np.array([128.0, 128.0, 128.0])
        filled[y0:y1, x0:x1][mask] = color
    base = Image.fromarray(np.clip(filled, 0, 255).astype(np.uint8))

    # 2. 채운 그림을 흐리게 해서 주변과 잇고, 가린 자리 안에만 붙인다.
    #    입력에 원본 글자가 없으니 블러를 아무리 되돌려도 나오는 건 평균색과 주변뿐이다.
    result = np.asarray(base, dtype=np.float32).copy()
    for _, _, thick, bounds, mask in regions:
        x0, y0, x1, y1 = bounds
        radius = max(4.0, thick * 0.6)
        m = int(radius * 3)
        cx0, cy0 = max(0, x0 - m), max(0, y0 - m)
        cx1, cy1 = min(base.width, x1 + m), min(base.height, y1 + m)
        soft = base.crop((cx0, cy0, cx1, cy1)).filter(ImageFilter.GaussianBlur(radius))
        patch = np.asarray(soft, dtype=np.float32)[y0 - cy0:y1 - cy0, x0 - cx0:x1 - cx0]
        patch = patch * (1 - FROST) + 255.0 * FROST
        grain = np.random.default_rng(_seed(bounds)).normal(0, GRAIN, patch.shape[:2])
        local = result[y0:y1, x0:x1]
        local[mask] = (patch + grain[..., None])[mask]

    return Image.fromarray(np.clip(result, 0, 255).astype(np.uint8))


def export(image: Image.Image, *, quality: int = 92) -> bytes:
    """메타데이터를 떼고 다시 인코딩한다.

    Pillow 는 save 시 exif 를 넘기지 않으면 기본적으로 싣지 않는다.
    다만 그것에 기대지 않고 화소만 새 이미지로 옮겨 확실히 끊는다.
    (getdata() 를 리스트로 옮기면 12MP 사진에서 튜플 1,200만 개가 생긴다.
    바이트로 옮긴다.)
    """
    rgb = image.convert("RGB")
    clean = Image.frombytes("RGB", rgb.size, rgb.tobytes())

    buf = io.BytesIO()
    clean.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def _overlap(finding_box: Box, mask: Box) -> float:
    """다시 찾은 항목의 실제 모양 중 가린 모양(여백 포함)과 겹치는 비율.

    축 정렬 사각형끼리 재면, 기울어진 주소 줄만 가렸을 때 그 사각형에 걸치는
    옆 줄(가리지 않은 전화번호)까지 '가렸는데 남았다'로 잘못 센다.
    """
    f_pts = _shape(finding_box)
    m_pts, _ = _outline(mask)
    xs = [p[0] for p in f_pts + m_pts]
    ys = [p[1] for p in f_pts + m_pts]
    bounds = (int(np.floor(min(xs))), int(np.floor(min(ys))),
              int(np.ceil(max(xs))) + 1, int(np.ceil(max(ys))) + 1)
    f = _raster(f_pts, bounds)
    return float((f & _raster(m_pts, bounds)).sum()) / max(1, int(f.sum()))


def verify(selected: list[Box], masked_bytes: bytes, analyze_fn, *, had_gps: bool) -> dict:
    """내려보낼 파일을 실제로 다시 읽어 검사한다.

    통과 조건은 '개수가 줄었다'가 아니다. 10곳 중 1곳만 가려도 개수는 준다.
    **선택한 영역 하나하나**에서 다시 탐지되는 것이 없어야 하고,
    위치정보가 남아 있지 않아야 한다.

    선택하지 않은 곳에 남은 항목은 실패로 치지 않는다. 사용자가 일부러
    남긴 것일 수 있다. 다만 개수는 알려준다.

    analyze_fn 은 analyze.analyze 를 그대로 받는다. 순환 임포트를 피하려고
    인자로 주입한다.
    """
    masked = Image.open(io.BytesIO(masked_bytes))
    after = analyze_fn(masked)

    serious = [
        f for f in after.findings
        if f.severity.value in ("cover", "review") and f.box is not None
    ]
    leaked = [
        f for f in serious
        if any(_overlap(f.box, b) >= OVERLAP_RATIO for b in selected)
    ]
    elsewhere = [f for f in serious if f not in leaked]
    has_gps = any(f.kind == "gps" for f in after.findings)

    return {
        "selected_count": len(selected),
        "leaked_count": len(leaked),
        "remaining_count": len(elsewhere),
        "had_gps": had_gps,
        "gps_removed": not has_gps,
        "leaked": [f.as_dict() for f in leaked],
        "remaining": [f.as_dict() for f in elsewhere],
        "passed": not leaked and not has_gps,
    }
