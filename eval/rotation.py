"""회전 실험. 송장이 기울어져도 판정이 같은가.

같은 합성 송장(3종 × 원본/책상)을 여러 각도로 돌려서 세 가지를 센다.

  가림 권장   가려야 할 항목(전화·주소·동호수)을 가림 권장으로 올렸는가
  이름        '받는분' 옆 이름을 잡았는가
  오경고      고객센터 번호·운송장번호를 가림 권장으로 올렸는가

OCR 이 아예 못 읽은 것은 규칙 탓이 아니므로 'OCR 이 읽은 정답'을 따로 보여준다.
PaddleOCR 로 돌린다(기울어진 외곽선이 필요하다). Tesseract 는 외곽선이 없어
가로 기준으로만 판단한다.

사용법:
    PL_OCR=paddleocr python -m eval.rotation
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import analyze, ocr  # noqa: E402
from pipeline.types import Severity  # noqa: E402
from samples.make_sample import make_waybill, place_on_desk  # noqa: E402

ANGLES = (0, 15, 30, 45, 60, 90, 180, 270)


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def main() -> None:
    backend = ocr.get_backend()
    cases = []
    for seed in range(3):
        wb, labels = make_waybill(seed)
        for base in (wb, place_on_desk(wb, seed)):
            cases.append((base, labels))

    print(f"OCR 백엔드: {backend.name}   사진 {len(cases)}장 × 각도 {len(ANGLES)}\n")
    print(f"{'각도':>5}{'OCR읽음':>9}{'가림권장':>9}{'이름':>7}{'오경고':>7}")
    print("-" * 40)
    totals = [0, 0, 0, 0]
    for angle in ANGLES:
        read = cover = names = alarms = 0
        for base, labels in cases:
            img = base.rotate(angle, expand=True, fillcolor=(96, 84, 72), resample=Image.BICUBIC)
            spans = backend.read(img)
            rep = analyze.analyze(img, backend=ocr.ScriptedBackend(spans))
            seen = [_digits(s.text) for s in spans]
            covered = {_digits(f.evidence_text) for f in rep.findings
                       if f.severity is Severity.COVER and f.evidence_text}
            truths = [_digits(t) for t in labels["truth_cover"]]
            read += sum(1 for t in truths if any(t in s for s in seen if s))
            cover += sum(1 for t in truths if t in covered)
            names += any(f.kind == "name" and f.evidence_text == labels["name"]
                         for f in rep.findings)
            alarms += sum(1 for t in labels["truth_not_pii"] if _digits(t) in covered)
        n = len(cases)
        print(f"{angle:>4}°{read:>6}/{3 * n}{cover:>6}/{3 * n}{names:>4}/{n}{alarms:>7}")
        for k, v in enumerate((read, cover, names, alarms)):
            totals[k] += v
    n = len(cases) * len(ANGLES)
    print("-" * 40)
    print(f"{'합계':>4} {totals[0]:>5}/{3 * n}{totals[1]:>5}/{3 * n}"
          f"{totals[2]:>4}/{n}{totals[3]:>7}")


if __name__ == "__main__":
    main()
