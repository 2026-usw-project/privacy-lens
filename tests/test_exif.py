"""EXIF 파서 테스트 — 합성 생성기의 GPS 삽입과 왕복 확인"""
import io
import random

import piexif
from PIL import Image

from data.synth.compose import gps_exif
from server.exif import parse


def _jpeg(exif: bytes | None = None) -> bytes:
    buf = io.BytesIO()
    kw = {"exif": exif} if exif else {}
    Image.new("RGB", (64, 48), "white").save(buf, "JPEG", **kw)
    return buf.getvalue()


def test_gps_detected_high():
    info = parse(_jpeg(gps_exif(random.Random(1))))
    assert info.present and info.gps is not None
    assert 37.2 <= info.gps.lat <= 37.3 and 126.95 <= info.gps.lon <= 127.05
    assert info.risk.level == "high"
    assert info.device == "DemoPhone PL-1"


def test_no_exif():
    info = parse(_jpeg())
    assert not info.present and info.risk.level == "none"


def test_device_only_low():
    ex = piexif.dump({"0th": {piexif.ImageIFD.Make: b"Cam"}, "Exif": {}, "GPS": {}})
    info = parse(_jpeg(ex))
    assert info.gps is None and info.risk.level == "low"


def test_png_does_not_crash():
    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, "PNG")
    assert parse(buf.getvalue()).present is False
