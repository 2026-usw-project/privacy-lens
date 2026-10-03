"""비교 실험.

주장 대신 측정한다. 같은 사진, 같은 OCR 엔진, 규칙만 바꿔서 돌린다.

  대조군: OCR + 정규식
  실험군: OCR + 정규식 + 문맥 판단 + 결합 설명

측정 항목 세 가지
  - 놓친 개인정보 수  : 가려야 할 항목을 가림 권장으로 올리지 못한 횟수
  - 불필요한 경고 수  : 가리면 안 될 항목을 가림 권장으로 올린 횟수
  - 사진 한 장 처리 시간

주의: 여기 쓰는 합성 샘플은 파이프라인이 도는지 확인하는 용도다.
발표에 낼 숫자는 **개발에 쓰지 않은 실사 사진**으로 다시 뽑아야 한다.
그리고 베이스라인은 가급적 PaddleOCR + Presidio 같은 공개 구현으로 잡아라.
직접 만든 대조군은 "일부러 약하게 잡은 것 아니냐"는 반박을 부른다.

사용법:
    python3 -m eval.compare samples/out

OCR 엔진·모델 비교는 환경변수만 바꿔 두 번 돌린다. 규칙은 같다.
    PL_OCR=paddleocr python -m eval.compare samples/out
    PL_OCR=paddleocr PL_PADDLE_DET=PP-OCRv6_medium_det python -m eval.compare samples/out

OCR 은 사진마다 **한 번만** 돌리고, 그 결과를 세 조건에 똑같이 넣는다.
조건마다 OCR 을 다시 돌리면 시간이 세 배가 되고, 규칙 시간에 OCR 시간이 섞인다.
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import analyze, ocr  # noqa: E402
from pipeline.types import Severity  # noqa: E402
from samples.make_sample import make_waybill  # noqa: E402


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _covered(report) -> list[str]:
    """가림 권장으로 올라온 항목의 숫자만 추린다.

    OCR이 공백을 흩뿌리기 때문에 문자열 그대로 비교하면 전부 불일치가 난다.
    숫자만 남겨 비교하는 게 현실적이다. 숫자가 하나도 없는 항목(이메일, 이름)은
    여기서 뺀다. 빈 문자열이 남으면 `"" in target` 이 항상 참이 돼서
    그 사진의 정답이 전부 '잡음'으로 셈해진다.
    """
    out = []
    for f in report.findings:
        if f.severity is Severity.COVER and f.evidence_text:
            digits = _digits(f.evidence_text)
            if digits:
                out.append(digits)
    return out


def score(report, labels: dict) -> tuple[int, int]:
    """놓침과 오경고를 **같은 기준**(숫자열 완전 일치)으로 센다.

    한쪽만 부분 일치로 느슨하게 세면 조건 사이 비교가 기울어진다.
    """
    covered = set(_covered(report))

    missed = sum(
        1 for truth in labels["truth_cover"]
        if _digits(truth) and _digits(truth) not in covered
    )
    false_alarms = sum(
        1 for safe in labels["truth_not_pii"]
        if _digits(safe) and _digits(safe) in covered
    )
    return missed, false_alarms


def ocr_recall(spans, labels: dict) -> int:
    """규칙과 무관하게, OCR 이 정답 숫자열을 읽어내긴 했는가.

    놓침이 OCR 탓인지 규칙 탓인지 가르려고 따로 센다. 주소는 번지 숫자만
    보므로 도로명을 깨뜨려 읽어도 '읽음'으로 잡힌다. 느슨한 상한이다.
    """
    seen = [_digits(s.text) for s in spans]
    return sum(
        1 for truth in labels["truth_cover"]
        if _digits(truth) and any(_digits(truth) in d for d in seen)
    )


def main(sample_dir: str = "samples/out", n: int = 3) -> None:
    backend = ocr.get_backend()
    rows = []
    ocr_ms: list[int] = []
    read_hits = total_truth = 0

    for seed in range(n):
        path = Path(sample_dir) / f"waybill_{seed}_desk.png"
        if not path.exists():
            print(f"샘플 없음: {path}. 먼저 samples/make_sample.py 를 실행하세요.")
            return
        img = Image.open(path)
        _, labels = make_waybill(seed)

        started = time.perf_counter()
        spans = backend.read(img)
        ocr_ms.append(int((time.perf_counter() - started) * 1000))
        read_hits += ocr_recall(spans, labels)
        total_truth += len(labels["truth_cover"])

        fixed = ocr.ScriptedBackend(spans)
        conditions = {
            "정규식만": analyze.naive_regex(img, backend=fixed),
            "+심각도표": analyze.baseline(img, backend=fixed),
            "+문맥·결합": analyze.analyze(img, backend=fixed),
        }
        rows.append((seed, {k: (score(v, labels), v.elapsed_ms)
                            for k, v in conditions.items()}))

    names = list(rows[0][1].keys())
    print(f"OCR 백엔드: {backend.name}   샘플 {n}장")
    print(f"OCR 평균 {sum(ocr_ms) // len(ocr_ms)} ms · "
          f"OCR 이 읽어낸 정답 {read_hits}/{total_truth}\n")
    print(f"{'조건':<12}{'놓침':>8}{'오경고':>9}{'규칙 ms':>10}")
    print("-" * 40)

    for name in names:
        missed = sum(r[1][name][0][0] for r in rows)
        alarms = sum(r[1][name][0][1] for r in rows)
        ms = sum(r[1][name][1] for r in rows) // len(rows)
        print(f"{name:<12}{missed:>8}{alarms:>9}{ms:>10}")

    print("-" * 40)
    print("놓침   = 가려야 할 항목을 가림 권장으로 못 올린 횟수")
    print("오경고 = 고객센터 번호·운송장번호를 가림 권장으로 올린 횟수")
    print("규칙 ms = OCR 을 뺀 나머지(규칙·QR·바코드·EXIF) 시간")
    print("\n※ 합성 샘플 기준. 발표용 숫자는 개발에 쓰지 않은 실사 사진으로 다시 뽑을 것.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "samples/out")
