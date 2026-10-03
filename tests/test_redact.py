"""가림, 내보내기, 다시 검사."""

import io

import numpy as np
import pytest
from PIL import Image, ImageDraw

from pipeline import metadata, redact
from pipeline.types import Box, Certainty, Finding, Report, Severity


def jpeg_with_gps() -> bytes:
    exif = Image.Exif()
    exif[0x0112] = 6  # 90도 회전
    exif[0x8825] = {1: "N", 2: (37.0, 30.0, 0.0), 3: "E", 4: (127.0, 0.0, 0.0)}
    buf = io.BytesIO()
    Image.new("RGB", (60, 30), "white").save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def test_export_strips_metadata():
    img = Image.open(io.BytesIO(jpeg_with_gps()))
    assert metadata.check_exif(img)
    out = Image.open(io.BytesIO(redact.export(img)))
    assert not out.getexif()
    assert metadata.check_exif(out) == []


def test_mask_pad_scales_with_box():
    assert redact.pad_for(Box(0, 0, 10, 10)) == redact.PAD_MIN
    assert redact.pad_for(Box(0, 0, 400, 100)) == 18


def test_solid_mask_covers_pixels():
    img = Image.new("RGB", (100, 100), "white")
    out = redact.apply_masks(img, [Box(40, 40, 20, 20)], "solid")
    assert out.getpixel((50, 50)) == redact.FILL
    assert out.getpixel((5, 5)) == (255, 255, 255)
    assert img.getpixel((50, 50)) == (255, 255, 255)  # 원본은 그대로


def _with_text(digits: str, extra: tuple | None = None) -> Image.Image:
    """흰 바탕에 줄무늬 배경, 가운데에 숫자 모양(검은 막대)을 그린다."""
    img = Image.new("RGB", (200, 120), (240, 236, 228))
    d = ImageDraw.Draw(img)
    for y in range(0, 120, 9):
        d.line([(0, y), (200, y)], fill=(200, 190, 180), width=2)
    for i, ch in enumerate(digits):  # 글자마다 다른 막대 = 다른 내용
        h = 6 + int(ch) * 2
        d.rectangle([60 + i * 10, 70 - h, 66 + i * 10, 70], fill=(20, 20, 24))
    if extra:
        d.rectangle(extra, fill=(0, 0, 0))
    return img


def test_blur_keeps_no_information():
    # 같은 자리에 다른 번호 → 결과가 화소 하나까지 같아야 한다.
    # 진짜 블러면 다르게 나오고, 그 차이로 번호를 맞힐 수 있다.
    # (막대는 x 60~156, y 46~70. 상자가 전부 덮어야 한다. 밖으로 삐져나온 부분은
    #  원래 보이는 화소라 테두리 색에 섞이는 게 맞다.)
    box = Box(56, 40, 104, 34)
    a = np.asarray(redact.apply_masks(_with_text("0101112222"), [box]))
    b = np.asarray(redact.apply_masks(_with_text("0109876543"), [box]))
    assert np.array_equal(a, b)


def test_blur_leaves_outside_untouched():
    box = Box(56, 44, 90, 30)
    src = _with_text("0101112222")
    out = np.asarray(redact.apply_masks(src, [box]), dtype=int)
    x0, y0, x1, y1 = redact._rect(box, src.size)
    inside = np.zeros(out.shape[:2], bool)
    inside[y0:y1, x0:x1] = True
    assert np.array_equal(np.asarray(src, dtype=int)[~inside], out[~inside])
    # 그리고 안쪽은 원본과 달라졌다(검은 막대가 남지 않았다)
    assert out[inside].min() > 60


def test_blur_neighbours_do_not_leak_into_each_other():
    # 두 영역이 가까이 있을 때, 한 영역 안의 내용이 다른 영역의 테두리 평균에
    # 섞이면 안 된다. 두 번째 영역 안의 내용만 바꿔도 첫 영역 결과는 같아야 한다.
    first, second = Box(20, 20, 40, 20), Box(66, 20, 40, 20)
    a = redact.apply_masks(_with_text("1", extra=(70, 24, 100, 36)), [first, second])
    b = redact.apply_masks(_with_text("1", extra=(70, 30, 80, 32)), [first, second])
    x0, y0, x1, y1 = redact._rect(first, a.size)
    assert np.array_equal(np.asarray(a)[y0:y1, x0:x1], np.asarray(b)[y0:y1, x0:x1])


def test_unknown_style_rejected():
    with pytest.raises(ValueError):
        redact.apply_masks(Image.new("RGB", (10, 10)), [], "pixelate")


def _finding(box, sev=Severity.COVER, kind="mobile"):
    return Finding(kind=kind, box=box, certainty=Certainty.READ, severity=sev, message="m")


def _fake(findings):
    return lambda _img: Report(width=100, height=100, findings=findings)


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (100, 100)).save(buf, "PNG")
    return buf.getvalue()


def test_verify_fails_when_selected_area_still_detected():
    left = Box(10, 10, 30, 10)
    v = redact.verify([left], _png(), _fake([_finding(left)]), had_gps=False)
    assert not v["passed"] and v["leaked_count"] == 1


def test_verify_passes_and_reports_unselected_leftovers():
    # 1곳만 가렸고 다른 곳에 1건이 남았다. 개수가 줄었다고 통과가 아니라
    # '가린 곳이 깨끗한가'로 판정하고, 남은 건 따로 알려준다.
    v = redact.verify(
        [Box(10, 10, 30, 10)], _png(), _fake([_finding(Box(60, 60, 30, 10))]), had_gps=True
    )
    assert v["passed"]
    assert v["remaining_count"] == 1
    assert v["had_gps"] and v["gps_removed"]


def test_verify_fails_when_gps_remains():
    gps = Finding(kind="gps", box=None, certainty=Certainty.READ,
                  severity=Severity.COVER, message="m")
    v = redact.verify([], _png(), _fake([gps]), had_gps=True)
    assert not v["passed"] and not v["gps_removed"]


# ------------------------------------------------------------ 기울어진 외곽선

def _rotated_quad(cx, cy, length, thick, deg):
    import math
    t = math.radians(deg)
    u = (math.cos(t), math.sin(t))
    v = (-math.sin(t), math.cos(t))
    a, b = length / 2, thick / 2
    return tuple((cx + sx * a * u[0] + sy * b * v[0], cy + sx * a * u[1] + sy * b * v[1])
                 for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)))


def _box_of(quad):
    xs = [p[0] for p in quad]
    ys = [p[1] for p in quad]
    return Box(int(min(xs)), int(min(ys)), int(max(xs) - min(xs)), int(max(ys) - min(ys)), poly=quad)


def test_rotated_mask_follows_outline():
    # 30° 기울어진 줄. 가운데는 가리고, 축 정렬 사각형의 모서리(줄 밖)는 그대로.
    quad = _rotated_quad(100, 60, 140, 16, 30)
    box = _box_of(quad)
    src = Image.new("RGB", (200, 120), (240, 236, 228))
    for style in ("solid", "blur"):
        out = np.asarray(redact.apply_masks(src, [box], style), dtype=int)
        base = np.asarray(src, dtype=int)
        assert not np.array_equal(out[60, 100], base[60, 100])     # 줄 가운데
        corner = (box.y + 2, box.x + 2)                            # 사각형 왼쪽 위 모서리
        assert np.array_equal(out[corner], base[corner])           # 줄 밖이라 그대로
        changed = (out != base).any(axis=2).sum()
        assert changed < 0.5 * box.w * box.h                       # 사각형의 절반도 안 덮는다


def test_rotated_blur_keeps_no_information():
    quad = _rotated_quad(100, 60, 120, 18, 25)
    box = _box_of(quad)

    def with_marks(seed):
        img = Image.new("RGB", (200, 120), (240, 236, 228))
        d = ImageDraw.Draw(img)
        rng = np.random.default_rng(seed)
        for _ in range(12):  # 줄 안쪽에만 서로 다른 점을 찍는다
            t = rng.uniform(-0.4, 0.4)
            x, y = 100 + t * 120 * 0.906, 60 + t * 120 * 0.423
            d.ellipse([x - 2, y - 2, x + 2, y + 2], fill=(0, 0, 0))
        return img

    a = np.asarray(redact.apply_masks(with_marks(1), [box]))
    b = np.asarray(redact.apply_masks(with_marks(2), [box]))
    assert np.array_equal(a, b)


def test_overlap_uses_real_shapes():
    # 기울어진 주소 줄만 가렸을 때, 그 사각형에 걸치는 옆 줄(전화번호)은
    # '가렸는데 남았다'가 아니다.
    addr = _box_of(_rotated_quad(100, 80, 160, 16, 30))
    phone = _box_of(_rotated_quad(80, 50, 100, 16, 30))
    assert addr.intersects(phone)                    # 사각형끼리는 겹친다
    assert redact._overlap(phone, addr) < redact.OVERLAP_RATIO
    assert redact._overlap(addr, addr) > 0.99


def test_box_serializes_outline():
    quad = ((1.04, 2.0), (10.0, 2.0), (10.0, 8.0), (1.0, 8.0))
    d = Box(1, 2, 9, 6, poly=quad).as_dict()
    assert d["poly"] == [[1.0, 2.0], [10.0, 2.0], [10.0, 8.0], [1.0, 8.0]]
    assert "poly" not in Box(1, 2, 9, 6).as_dict()
