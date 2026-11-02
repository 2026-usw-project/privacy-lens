"""파이프라인 조립.

`use_context=False` 로 부르면 OCR + 정규식만 쓰는 베이스라인이 된다.
같은 코드 경로, 같은 OCR, 규칙만 다르게. 비교 실험의 대조군이 여기서 나온다.
서버와 화면은 '문맥·결합'(기본값)만 쓴다. 대조군은 eval 에서만 부른다.

`judge` 에 LLM 설정(llm_judge.JudgeConfig)을 주면 글자 판단을 규칙 대신 LLM 이 한다
(개발자 모드). 이때 OCR 원문이 그 공급자에게 전송된다.

원본 이미지와 추출한 문자열은 어디에도 기록하지 않는다. 로그에 남기지 않고,
디스크에 쓰지 않고, 함수가 끝나면 메모리에서만 사라진다.

`on_stage` 를 주면 처리 단계(OCR·YOLO·판단 …)가 시작하고 끝날 때마다 알린다. 서버가
단계별 걸린 시간을 재고 남은 시간을 추정하는 데 쓴다(timing.py). 단계 이름과 크기
(메가픽셀·조각 수)만 넘기고 내용은 넘기지 않는다.
"""

from __future__ import annotations

import time

from PIL import Image

from . import context, detect, grouping, llm_judge, metadata, ocr
from .types import Report

_AUTO = object()


def ocr_key(backend) -> str:
    """OCR 단계 키. 엔진 종류만(버전·모델 이름은 빼서 기록이 흩어지지 않게)."""
    name = str(getattr(backend, "name", "") or "ocr").split()[0].lower()
    return "ocr:" + name


def judge_key(judge: llm_judge.JudgeConfig | None) -> str:
    """판단 단계 키. 넓은 키로 빌려 쓸 수 있게 공급자 → 모델 순."""
    if judge is None:
        return "judge:rules"
    return f"judge:llm:{judge.provider}:{judge.model}"


def megapixels(image: Image.Image) -> float:
    return image.width * image.height / 1_000_000


class _Stage:
    """with _Stage(on_stage, 이름, 크기): … — 시작·끝을 알린다. 실패한 단계는 끝을 알리지 않는다."""

    def __init__(self, on_stage, name: str, units: float):
        self.on_stage, self.name, self.units = on_stage, name, units

    def _emit(self, *args) -> None:
        if self.on_stage is None:
            return
        try:
            self.on_stage(*args)
        except Exception:
            pass  # 시간 기록이 분석을 망치면 안 된다

    def __enter__(self) -> "_Stage":
        self._emit("start", self.name, self.units, None)
        self.started = time.perf_counter()
        return self

    def __exit__(self, exc_type, *_):
        if exc_type is None:
            self._emit("end", self.name, self.units, time.perf_counter() - self.started)
        return False


def analyze(
    image: Image.Image,
    *,
    backend=None,
    use_context: bool = True,
    naive: bool = False,
    check_codes: bool = True,
    check_meta: bool = True,
    detector=_AUTO,
    judge: llm_judge.JudgeConfig | None = None,
    llm_transport=None,
    llm_trace: list | None = None,
    on_stage=None,
) -> Report:
    """detector 를 안 주면 PL_YOLO_WEIGHTS 로 만든 검출기를 쓰고, 없으면 검출 없이 돈다.
    None 을 주면 검출을 끈다(비교 실험의 대조군)."""
    started = time.perf_counter()

    backend = backend or ocr.get_backend()
    if detector is _AUTO:
        detector = detect.get_detector()

    # 위치정보(EXIF)는 원본에서, 글자·문서·코드는 RGB 로 바꾼 사본에서 본다(CMYK·16비트·투명 PNG)
    pixels = ocr.ocr_ready(image)
    mp = megapixels(pixels)
    with _Stage(on_stage, ocr_key(backend), mp):
        spans, raw_ocr = ocr.read_with_raw(backend, pixels)

    # 문서 검출 → 작게 찍힌 문서는 잘라 확대해서 다시 읽는다
    dets = []
    if detector is not None:
        with _Stage(on_stage, "detect", mp):
            dets = detector.detect(pixels)
    if dets:
        with _Stage(on_stage, "reread", 0) as st:
            spans, st.units = detect.reread_documents(pixels, spans, dets, backend, raw_ocr=raw_ocr)

    with _Stage(on_stage, judge_key(judge), len(spans)):
        if judge is not None:
            findings = llm_judge.evaluate(spans, judge, width=image.width, height=image.height,
                                          transport=llm_transport, trace=llm_trace)
        else:
            findings = context.evaluate(spans, use_context=use_context, naive=naive)

    if check_meta:
        findings.extend(metadata.check_exif(image))
    if check_codes:
        with _Stage(on_stage, "codes", mp):
            findings.extend(metadata.check_codes(pixels))
    if dets:
        # 다시 읽어도 못 읽은 문서, 증명사진, 해독 못 한 코드는 영역으로 알린다
        findings.extend(detect.region_findings(dets, spans, findings))

    groups = grouping.assign_groups(spans, findings) if use_context else []
    if dets:
        detect.tag_documents(dets, findings)

    report = Report(
        width=image.width,
        height=image.height,
        raw_ocr=raw_ocr,
        findings=findings,
        groups=groups,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        ocr_backend=backend.name,
        detector=detector.name if detector is not None else "",
        detector_device=getattr(detector, "device", "") if detector is not None else "",
        judge=judge.label if judge is not None else "규칙 기반",
        judge_provider=judge.provider if judge is not None else "rules",
        llm_trace=llm_trace or [],
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
