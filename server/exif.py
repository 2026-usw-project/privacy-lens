"""[D] EXIF 파싱 → ExifInfo  (방향 보정 '전' 원본 바이트 기준)"""
from __future__ import annotations

from datetime import datetime

import piexif

from schema.models import GPS, ExifInfo, Risk, RiskFactors


def _ratio(v) -> float:
    return v[0] / v[1] if v[1] else 0.0


def _dms(vals, ref: bytes) -> float:
    deg = _ratio(vals[0]) + _ratio(vals[1]) / 60 + _ratio(vals[2]) / 3600
    return -deg if ref in (b"S", b"W") else deg


def _s(v) -> str | None:
    if isinstance(v, bytes):
        v = v.decode("utf-8", "ignore")
    v = (v or "").strip("\x00 ").strip()
    return v or None


def parse(raw: bytes) -> ExifInfo:
    try:
        ex = piexif.load(raw)
    except Exception:
        ex = None
    if not ex or not any(ex.get(k) for k in ("0th", "Exif", "GPS")):
        return ExifInfo(present=False, risk=Risk(score=0, level="none", reason="사진 파일에 메타데이터(EXIF)가 없습니다."))

    z, e, g = ex.get("0th", {}), ex.get("Exif", {}), ex.get("GPS", {})
    gps = None
    try:
        if piexif.GPSIFD.GPSLatitude in g and piexif.GPSIFD.GPSLongitude in g:
            lat = _dms(g[piexif.GPSIFD.GPSLatitude], g.get(piexif.GPSIFD.GPSLatitudeRef, b"N"))
            lon = _dms(g[piexif.GPSIFD.GPSLongitude], g.get(piexif.GPSIFD.GPSLongitudeRef, b"E"))
            if (lat, lon) != (0.0, 0.0):
                gps = GPS(lat=round(lat, 6), lon=round(lon, 6))
    except Exception:
        gps = None
    device = " ".join(x for x in (_s(z.get(piexif.ImageIFD.Make)), _s(z.get(piexif.ImageIFD.Model))) if x) or None
    taken = None
    ts = _s(e.get(piexif.ExifIFD.DateTimeOriginal) or z.get(piexif.ImageIFD.DateTime))
    if ts:
        try:
            taken = datetime.strptime(ts, "%Y:%m:%d %H:%M:%S")
        except ValueError:
            pass
    orient = z.get(piexif.ImageIFD.Orientation)

    if gps:
        risk = Risk(score=0.9, level="high", factors=RiskFactors(type_weight=1.0, readability=1.0, area_factor=0.9),
                    reason="사진 파일에 촬영 위치(GPS)가 기록되어 있어 촬영 장소가 드러납니다.")
    elif device or taken:
        risk = Risk(score=0.15, level="low", reason="사진 파일에 촬영 기기·시각 정보가 남아 있습니다.")
    else:
        risk = Risk(score=0, level="none", reason="메타데이터에 위험 정보가 없습니다.")
    return ExifInfo(present=True, gps=gps, device=device, taken_at=taken, software=_s(z.get(piexif.ImageIFD.Software)),
                    orientation=orient if isinstance(orient, int) and 1 <= orient <= 8 else None, risk=risk)
