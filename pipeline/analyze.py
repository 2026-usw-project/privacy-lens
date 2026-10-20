"""파이프라인 조립.

`use_context=False` 로 부르면 OCR + 정규식만 쓰는 베이스라인이 된다.
같은 코드 경로, 같은 OCR, 규칙만 다르게. 비교 실험의 대조군이 여기서 나온다.

원본 이미지와 추출한 문자열은 어디에도 기록하지 않는다. 로그에 남기지 않고,
디스크에 쓰지 않고, 함수가 끝나면 메모리에서만 사라진다.
"""

from __future__ import annotations

import time

from PIL import Image

from . import context, detect, grouping, metadata, ocr
from .types import Report

_AUTO = object()


def analyze(
    image: Image.Image,
    *,
    backend=None,
    use_context: bool = True,
    naive: bool = False,
    check_codes: bool = True,
    check_meta: bool = True,
    detector=_AUTO,
) -> Report:
    """detector 를 안 주면 PL_YOLO_WEIGHTS 로 만든 검출기를 쓰고, 없으면 검출 없이 돈다.
    None 을 주면 검출을 끈다(비교 실험의 대조군)."""
    started = time.perf_counter()

    backend = backend or ocr.get_backend()
    if detector is _AUTO:
        detector = detect.get_detector()

    spans = backend.read(image)

    # 문서 검출 → 작게 찍힌 문서는 잘라 확대해서 다시 읽는다
    dets = detector.detect(image) if detector is not None else []
    if dets:
        spans, _ = detect.reread_documents(image, spans, dets, backend)

    findings = context.evaluate(spans, use_context=use_context, naive=naive)

    if check_meta:
        findings.extend(metadata.check_exif(image))
    if check_codes:
        findings.extend(metadata.check_codes(image))
    if dets:
        # 다시 읽어도 못 읽은 문서, 증명사진, 해독 못 한 코드는 영역으로 알린다
        findings.extend(detect.region_findings(dets, spans, findings))

    groups = grouping.assign_groups(spans, findings) if use_context else []
    if dets:
        detect.tag_documents(dets, findings)

    report = Report(
        width=image.width,
        height=image.height,
        findings=findings,
        groups=groups,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        ocr_backend=backend.name,
        detector=detector.name if detector is not None else "",
    )

    if not findings:
        from . import wording
        report.notes.append(wording.NO_FINDINGS)

    return report


def naive_regex(image: Image.Image, *, backend=None) -> Report:
    """가장 소박한 대조군: 패턴에 걸리면 전부 가림 권장."""
    return analyze(image, backend=backend, use_context=False, naive=True,
                   check_codes=False, check_meta=False, detector=None)


def baseline(image: Image.Image, *, backend=None) -> Report:
    """중간 대조군: 심각도 표는 쓰되 주변 문구는 보지 않는다."""
    return analyze(image, backend=backend, use_context=False,
                   check_codes=False, check_meta=False, detector=None)
