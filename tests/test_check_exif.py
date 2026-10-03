"""EXIF 잔존 검사 테스트 — 캔버스 재인코딩처럼 새로 저장하면 깨끗해야 함"""
import io

import piexif
from PIL import Image

from data.check_exif import leftover


def _jpeg(exif: bytes | None = None) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(buf, "JPEG", **({"exif": exif} if exif else {}))
    return buf.getvalue()


def test_gps_left_is_reported():
    gps = {piexif.GPSIFD.GPSLatitudeRef: b"N", piexif.GPSIFD.GPSLatitude: ((37, 1), (12, 1), (0, 1)),
           piexif.GPSIFD.GPSLongitudeRef: b"E", piexif.GPSIFD.GPSLongitude: ((126, 1), (57, 1), (0, 1))}
    assert "GPS" in leftover(_jpeg(piexif.dump({"0th": {}, "Exif": {}, "GPS": gps})))


def test_reencoded_image_is_clean():
    src = _jpeg(piexif.dump({"0th": {piexif.ImageIFD.Make: b"Cam"}, "Exif": {}, "GPS": {}}))
    assert leftover(src) is not None
    out = io.BytesIO()
    Image.open(io.BytesIO(src)).save(out, "JPEG")          # exif= 를 주지 않고 다시 저장
    assert leftover(out.getvalue()) is None
