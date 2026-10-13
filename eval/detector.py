"""문서 검출(YOLO) 전후 비교.

같은 사진, 같은 OCR 결과로 '검출 없음'(지금 서비스)과 '검출 있음'을 돌려
**문서 단위**로 센다. 정답은 vision 라벨(YOLO 형식)의 문서 박스(송장·학생증·명찰·화면)다.
라벨에는 이름·번호 같은 항목 정답이 없으므로 항목 단위 재현율은 재지 않는다.

센 것
  - 알린 문서   : 정답 문서 안에 가림·검토 권장 항목이 하나라도 있음(내용을 읽었든 영역 경고든).
                  참고(info) 항목만 있으면 알리지 않은 것으로 본다
  - 그중 내용 읽음: 그 항목 중 '내용 확인 불가'가 아닌 것이 있음(확대 재판독의 효과)
  - 크기별      : 문서 긴 변 / 사진 짧은 변 이 0.15 미만 작음, 0.4 미만 중간, 그 이상 큼
  - 엉뚱한 경고 : 어느 정답 문서에도 속하지 않는 가림·검토 권장 항목(위치 없는 GPS 는 뺌)
  - 처리 시간   : 전체 OCR 시간 + 조건별 나머지 시간(재판독·검출·규칙)

전체 사진 OCR 은 한 번만 돌리고 두 조건에 같은 결과를 넣는다(eval.compare 와 같은 방식).
검출 조건에서 잘라 다시 읽는 조각만 진짜 OCR 로 읽는다.

사용법:
    PL_OCR=paddleocr python -m eval.detector <폴더> --weights <best.pt>
    PL_OCR=paddleocr python -m eval.detector <작업폴더>/dataset --list test.txt --weights …

<폴더>에는 images/ 와 labels/ 가 있어야 한다. 최종 시험 묶음은 학습 작업 폴더와 다른
작업 폴더(예: PrivacyLens-YOLO/최종시험)에서 ingest·검수·build 해서 그 dataset 을 넣는다.

주의: 학습·검수에 쓴 사진으로 재면 '검출 있음'이 부풀려진다. 발표 숫자는 봉인한 시험 묶음으로.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import analyze, detect, ocr  # noqa: E402
from pipeline.types import Box, Certainty, Severity  # noqa: E402
from vision.classes import NAMES  # noqa: E402

DOC_CLASSES = ("waybill", "id_card", "name_tag", "screen")
SIZES = ("작음", "중간", "큼")
CONDITIONS = ("검출 없음", "검출 있음")


def load_docs(label_path: Path, W: int, H: int) -> list[tuple[str, Box]]:
    """YOLO 라벨에서 문서 클래스 박스만 원본 픽셀 좌표로."""
    out = []
    if not label_path.exists():
        return out
    for line in label_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        c, cx, cy, w, h = line.split()
        name = NAMES.get(int(c))
        if name in DOC_CLASSES:
            cx, cy, w, h = float(cx) * W, float(cy) * H, float(w) * W, float(h) * H
            out.append((name, Box(int(cx - w / 2), int(cy - h / 2), max(1, int(w)), max(1, int(h)))))
    return out


def size_of(doc: Box, W: int, H: int) -> str:
    r = max(doc.w, doc.h) / min(W, H)
    return SIZES[0] if r < 0.15 else SIZES[1] if r < 0.4 else SIZES[2]


def _inside(b: Box, doc: Box) -> bool:
    return doc.x <= b.cx <= doc.x + doc.w and doc.y <= b.cy <= doc.y + doc.h


def score(report, docs: list[tuple[str, Box]]) -> tuple[list[tuple[str, bool, bool]], int]:
    """문서마다 (문서 이름, 알렸나, 내용까지 읽었나)와 엉뚱한 경고 수."""
    serious = [f for f in report.findings if f.box is not None and f.severity is not Severity.INFO]
    per_doc = []
    for name, d in docs:
        hits = [f for f in serious if _inside(f.box, d)]
        per_doc.append((name, bool(hits), any(f.certainty is not Certainty.REGION_ONLY for f in hits)))
    stray = sum(1 for f in serious if not any(_inside(f.box, d) for _, d in docs))
    return per_doc, stray


class _Reuse:
    """전체 사진은 미리 읽은 결과를 돌려주고, 잘라낸 조각만 진짜 OCR 로 읽는다."""

    def __init__(self, backend, size, spans):
        self.backend, self.size, self.spans, self.name = backend, size, spans, backend.name

    def read(self, image):
        return list(self.spans) if image.size == self.size else self.backend.read(image)


def evaluate(items, backend, detector) -> dict:
    """items: (이름, 사진, 문서 정답) 반복. 조건별 집계를 돌려준다."""
    res = {c: {"found": {s: 0 for s in SIZES}, "read": {s: 0 for s in SIZES},
               "stray": 0, "ms": [], "missed": []} for c in CONDITIONS}
    total = {s: 0 for s in SIZES}
    n = 0
    for name, img, docs in items:
        n += 1
        W, H = img.size
        sizes = [size_of(d, W, H) for _, d in docs]
        for s in sizes:
            total[s] += 1
        t0 = time.perf_counter()
        spans = backend.read(img)
        ocr_ms = (time.perf_counter() - t0) * 1000
        reuse = _Reuse(backend, img.size, spans)
        for cond, det in zip(CONDITIONS, (None, detector)):
            t0 = time.perf_counter()
            report = analyze.analyze(img, backend=reuse, detector=det)
            r = res[cond]
            r["ms"].append(ocr_ms + (time.perf_counter() - t0) * 1000)
            per_doc, stray = score(report, docs)
            r["stray"] += stray
            for s, (doc, found, read) in zip(sizes, per_doc):
                r["found"][s] += found
                r["read"][s] += read
                if not found:
                    r["missed"].append(f"{name}:{doc}({s})")
    return {"images": n, "total": total, **res}


def _items(folder: Path, names: list[str] | None):
    images = folder / "images"
    paths = [images / Path(n).name for n in names] if names else sorted(images.glob("*.jpg"))
    for p in paths:
        with Image.open(p) as raw:
            img = ImageOps.exif_transpose(raw).convert("RGB")
        yield p.stem, img, load_docs(folder / "labels" / f"{p.stem}.txt", *img.size)


def _rate(a: int, b: int) -> str:
    return f"{a}/{b}" + (f" ({a / b:.0%})" if b else "")


def report_text(r: dict) -> str:
    t = r["total"]
    lines = [f"사진 {r['images']}장 · 정답 문서 {sum(t.values())}개 "
             f"(작음 {t['작음']} · 중간 {t['중간']} · 큼 {t['큼']})", ""]
    for c in CONDITIONS:
        x = r[c]
        found, read = sum(x["found"].values()), sum(x["read"].values())
        ms = sorted(x["ms"])
        lines += [
            f"[{c}]",
            "  알린 문서    " + "  ".join(f"{s} {_rate(x['found'][s], t[s])}" for s in SIZES)
            + f"  전체 {_rate(found, sum(t.values()))}",
            "  내용 읽음    " + "  ".join(f"{s} {_rate(x['read'][s], t[s])}" for s in SIZES)
            + f"  전체 {_rate(read, sum(t.values()))}",
            f"  엉뚱한 경고  {x['stray']}건",
            f"  처리 시간    평균 {sum(ms) / len(ms):.0f} ms · 느린 10% {ms[int(len(ms) * 0.9)]:.0f} ms" if ms else "",
        ]
        if x["missed"]:
            lines.append("  놓친 문서    " + ", ".join(x["missed"][:10]) + (" …" if len(x["missed"]) > 10 else ""))
        lines.append("")
    lines.append("※ 학습·검수에 쓴 사진이면 '검출 있음'이 부풀려집니다. 발표 숫자는 봉인한 시험 묶음으로.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m eval.detector", description="문서 검출 전후 비교")
    ap.add_argument("folder", help="images/ 와 labels/ 가 있는 폴더")
    ap.add_argument("--weights", required=True, help="YOLO 가중치(best.pt)")
    ap.add_argument("--list", help="폴더 안의 목록 파일(예: test.txt). 없으면 images/ 전부")
    ap.add_argument("--conf", type=float, help="검출 기준값(기본 PL_YOLO_CONF 또는 0.35)")
    a = ap.parse_args(argv)

    folder = Path(a.folder)
    names = None
    if a.list:
        names = [l.strip() for l in (folder / a.list).read_text(encoding="utf-8").splitlines() if l.strip()]
    backend = ocr.get_backend()
    detector = detect.YoloDetector(a.weights, conf=a.conf)
    print(f"OCR {backend.name} · 검출 {detector.name}\n")
    print(report_text(evaluate(_items(folder, names), backend, detector)))


if __name__ == "__main__":
    main()
