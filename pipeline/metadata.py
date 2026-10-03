"""메타데이터와 코드 검사.

두 가지 원칙:

1. QR은 '해독 성공'과 '의미 파악 성공'이 별개다. 해독 결과가 숫자열뿐이면
   운송장번호인지 회원번호인지 확정할 수 없다. 확정하지 않고 그렇게 말한다.
2. QR 안의 링크는 절대 자동으로 열지 않는다. 서버가 임의 URL을 요청하면
   SSRF 통로가 된다. 해독된 문자열만 본다.
"""

from __future__ import annotations

from urllib.parse import urlsplit

import cv2
import numpy as np
from PIL import Image, ExifTags

from . import kr_patterns as kp
from . import wording
from .types import Box, Certainty, Finding, Severity

# 확대 시도에 쓸 최대 화소 수. 12MP 사진을 2.4배로 키우면 7천만 화소,
# 메모리 200MB 가 넘는다. 이 예산을 넘는 배율은 건너뛴다.
MAX_PROBE_PIXELS = 24_000_000

# QR 안의 문자열에서 찾을 개인정보 형식. 운송장번호 같은 긴 숫자는 뺀다.
_SENSITIVE_IN_PAYLOAD = {
    "rrn", "rrn_unverified", "card", "mobile", "landline", "email",
    "address_road", "address_unit",
}

_GPS_TAG = next(k for k, v in ExifTags.TAGS.items() if v == "GPSInfo")


def _to_degrees(value) -> float:
    d, m, s = (float(x) for x in value)
    return d + m / 60.0 + s / 3600.0


def check_exif(image: Image.Image) -> list[Finding]:
    findings: list[Finding] = []
    exif = image.getexif()
    if not exif:
        return findings

    gps = exif.get_ifd(_GPS_TAG)
    if gps:
        try:
            lat = _to_degrees(gps[2])
            lon = _to_degrees(gps[4])
            if gps.get(1) == "S":
                lat = -lat
            if gps.get(3) == "W":
                lon = -lon
        except (KeyError, TypeError, ValueError):
            return findings

        findings.append(
            Finding(
                kind="gps",
                box=None,
                certainty=Certainty.READ,
                severity=Severity.COVER,
                message=wording.gps_present(lat, lon),
                detail={"lat": round(lat, 6), "lon": round(lon, 6)},
            )
        )
    return findings


def _classify_payload(payload: str) -> str:
    """해독된 문자열의 종류. 모르면 'text' 다. 억지로 이름 붙이지 않는다."""
    low = payload.strip().lower()
    if low.startswith(("http://", "https://")):
        return "url"
    if low.startswith("begin:vcard") or low.startswith("mecard:"):
        return "vcard"
    if low.startswith("wifi:"):
        return "wifi"
    if low.startswith("tel:") or low.startswith("smsto:"):
        return "tel"
    return "text"


def _detect_multiscale(arr: np.ndarray) -> tuple[list[str], np.ndarray] | None:
    """여러 배율로 시도한다.

    기울어진 종이 위의 QR은 원본 해상도에서 자주 실패한다. 확대하면 잡히는
    경우가 있어서 배율을 몇 단계 훑는다. 처리 시간이 늘어나므로 첫 성공에서 멈춘다.
    """
    detector = cv2.QRCodeDetector()
    h, w = arr.shape[:2]
    for scale in (1.0, 1.6, 2.4):
        if scale > 1.0 and h * w * scale * scale > MAX_PROBE_PIXELS:
            break
        if scale == 1.0:
            probe = arr
        else:
            probe = cv2.resize(arr, None, fx=scale, fy=scale,
                               interpolation=cv2.INTER_CUBIC)
        try:
            ok, decoded, points, _ = detector.detectAndDecodeMulti(probe)
        except cv2.error:
            continue
        if ok and points is not None and len(points):
            return list(decoded), points / scale
    return None


def check_codes(image: Image.Image) -> list[Finding]:
    """OpenCV 내장 QR 검출기 사용. 별도 시스템 라이브러리가 필요 없다."""
    findings: list[Finding] = []
    arr = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)

    result = _detect_multiscale(arr)
    if result is None:
        return findings
    decoded, points = result

    for payload, quad in zip(decoded, points):
        xs, ys = quad[:, 0], quad[:, 1]
        box = Box(int(xs.min()), int(ys.min()),
                  int(xs.max() - xs.min()), int(ys.max() - ys.min()))

        if not payload:
            findings.append(
                Finding(
                    kind="qr",
                    box=box,
                    certainty=Certainty.REGION_ONLY,
                    severity=Severity.REVIEW,
                    message=wording.qr_undecoded(),
                )
            )
            continue

        payload_kind = _classify_payload(payload)
        severity = {
            "vcard": Severity.COVER,
            "wifi": Severity.COVER,
            "tel": Severity.COVER,
            "url": Severity.REVIEW,
            "text": Severity.REVIEW,
        }[payload_kind]
        message = wording.qr_decoded(payload_kind)

        detail = {"payload_kind": payload_kind, "length": len(payload)}
        # 링크는 열지 않는다. 호스트만 떼어 보여주고 경로는 감춘다.
        # 'user:pass@host' 형태의 계정 정보도 보여주지 않는다.
        scanned = payload
        if payload_kind == "url":
            try:
                parts = urlsplit(payload.strip())
                host = parts.hostname
                # 'user@host' 를 이메일로 오인하지 않게 경로와 쿼리만 본다.
                scanned = f"{parts.path} {parts.query}"
            except ValueError:
                host = None
            if host:
                detail["host"] = host

        # 해독된 문자열 안에 개인정보 형식이 있는지. 값은 내보내지 않고 종류만.
        inner = sorted({h.kind for h in kp.scan(scanned)} & _SENSITIVE_IN_PAYLOAD)
        if inner:
            severity = Severity.COVER
            nouns = list(dict.fromkeys(wording.KIND_NOUN[k] for k in inner))
            message = wording.qr_contains(nouns)
            detail["contains"] = inner

        findings.append(
            Finding(
                kind="qr",
                box=box,
                certainty=Certainty.READ,
                severity=severity,
                message=message,
                detail=detail,
            )
        )

    findings.extend(_check_barcodes(arr))
    return findings


def _check_barcodes(arr: np.ndarray) -> list[Finding]:
    """1차원 바코드. 송장 바코드에는 운송장번호가 들어 있다.

    운송장번호 자체는 신원이 아니지만 배송 조회로 이름·주소에 닿을 수 있다.
    그래서 검토 권장까지만 올리고, 해독한 숫자는 화면에 내보내지 않는다.
    """
    if not hasattr(cv2, "barcode"):
        return []
    try:
        detector = cv2.barcode.BarcodeDetector()
        ok, decoded, _types, points = detector.detectAndDecodeWithType(arr)
    except cv2.error:
        return []
    if not ok or points is None:
        return []

    findings: list[Finding] = []
    for payload, quad in zip(decoded, points):
        xs, ys = quad[:, 0], quad[:, 1]
        box = Box(int(xs.min()), int(ys.min()),
                  int(xs.max() - xs.min()), int(ys.max() - ys.min()))
        if box.w <= 0 or box.h <= 0:
            continue
        findings.append(
            Finding(
                kind="barcode",
                box=box,
                certainty=Certainty.READ if payload else Certainty.REGION_ONLY,
                severity=Severity.REVIEW,
                message=wording.barcode_decoded() if payload else wording.qr_undecoded(),
                detail={"length": len(payload)} if payload else {},
            )
        )
    return findings
