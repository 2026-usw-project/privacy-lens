"""실사 사진 평가: AI 허브 데이터로 지금 서비스(OCR + 규칙)를 잰다.

합성 샘플(eval.compare)이 아니라 실제로 찍힌 사진에서 두 가지를 본다.
  personal  사진 속 개인정보 글자를 알리는가    — AI 허브 '미디어 콘텐츠 비식별처리' 텍스트정보
  signs     개인정보가 아닌 글자에 잘못 경고하는가 — 같은 데이터의 간판·현수막·광고판 + '야외 실제 촬영 한글' 간판

두 단계로 나눈다. AI 허브 데이터가 있는 곳과 PaddleOCR 가 도는 곳이 다르기 때문이다.

  prep  (데이터를 받은 PC)  필요한 사진과 정답 박스만 골라 평가 묶음(zip) 하나로 만든다
        python -m eval.realtext prep ~/aihub ~/aihub-eval
  run   (PaddleOCR 가 있는 곳, 예: Colab)
        PL_OCR=paddleocr python -m eval.realtext run /content/aihub-eval [--limit 50]

센 것. OCR 은 사진마다 한 번 돌리고 세 조건(정규식만 / +심각도표 / +문맥·결합)에 같은 결과를 넣는다.
  personal  개인정보 글자 영역마다
              OCR 이 읽음  겹치는 OCR 글자 조각이 있음(규칙과 무관한 상한)
              알림        겹치는 가림·검토 권장 항목이 있음, 그중 가림 권장
            라벨 밖 경고  어느 영역과도 안 겹치는 가림·검토 권장 항목(라벨이 빠뜨린 것일 수도 있다)
  signs     가림 권장이 하나라도 나온 사진 비율, 사진당 가림·검토 권장 수, 가림 권장 항목 종류

주의
  - AI 허브 데이터는 승인받은 본인만 쓴다. 평가 묶음을 팀 공유 폴더·저장소에 올리지 않고
    개인 드라이브에서 돌린다. 결과에는 숫자와 항목 종류만 찍고 OCR 원문은 찍지 않는다.
  - AI 허브 정책 문구가 '학습용으로만' 이라, 이 숫자를 발표에 쓰기 전에 AI 허브에 확인한다.
  - '개인정보 텍스트'의 범위는 AI 허브 라벨 기준이라 우리 기준(가림 권장)과 다를 수 있다.
  - PL_YOLO_WEIGHTS 를 지정하지 않으면 지금 배포된 서비스와 같은 조건이다.
"""

from __future__ import annotations

import argparse
import collections
import json
import random
import shutil
import sys
import time
from pathlib import Path

from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import analyze, ocr  # noqa: E402
from pipeline.types import Box, Severity  # noqa: E402

CONDITIONS = {
    "정규식만": analyze.naive_regex,
    "+심각도표": analyze.baseline,
    "+문맥·결합": analyze.analyze,
}


# ------------------------------------------------------------------ prep

def prep(aihub: str, out: str, n_signs: int = 200, n_media_each: int = 50, seed: int = 0) -> Path:
    """AI 허브 폴더에서 평가 묶음을 만든다. 캡션·촬영 정보는 버리고 박스만 남긴다."""
    root, dst = Path(aihub).expanduser(), Path(out).expanduser()
    if dst.exists():
        shutil.rmtree(dst)
    rng = random.Random(seed)

    # personal: 미디어 콘텐츠 비식별처리 텍스트정보. bbox 는 [x1, y1, x2, y2]
    images = {p.name: p for p in root.glob("07.*/**/VS_*텍스트정보/**/*.jpg")}
    truth = {}
    (dst / "personal" / "images").mkdir(parents=True)
    for f in sorted(root.glob("07.*/**/VL_*텍스트정보/**/*.json")):
        d = json.loads(f.read_text(encoding="utf-8-sig"))
        src = images.get(d["image"]["file_name"])
        boxes = [[x1, y1, x2 - x1, y2 - y1] for x1, y1, x2, y2 in (o["bbox"] for o in d["objects"])]
        if src and boxes:
            shutil.copy2(src, dst / "personal" / "images" / src.name)
            truth[src.name] = boxes
    (dst / "personal" / "truth.json").write_text(json.dumps(truth, ensure_ascii=False), encoding="utf-8")

    # signs: 같은 데이터의 간판·현수막·광고판 + 야외 한글 간판. 정답은 필요 없다(전부 비개인정보)
    (dst / "signs" / "images").mkdir(parents=True)
    picks = []
    for cat in ("간판", "현수막", "광고판"):
        pool = sorted(root.glob(f"07.*/**/VS_*{cat}/**/*.jpg"))
        picks += [("media", p) for p in rng.sample(pool, min(n_media_each, len(pool)))]
    pool = sorted(root.glob("030.*/**/VS1/**/*.jpg"))
    picks += [("outdoor", p) for p in rng.sample(pool, min(n_signs, len(pool)))]
    for tag, p in picks:
        shutil.copy2(p, dst / "signs" / "images" / f"{tag}_{p.name}")

    archive = shutil.make_archive(str(dst), "zip", dst.parent, dst.name)
    print(f"personal {len(truth)}장(영역 {sum(map(len, truth.values()))}개) · signs {len(picks)}장")
    print(f"평가 묶음: {archive}  ← 개인 드라이브에만 올리세요(팀 공유 폴더 X)")
    return Path(archive)


# ------------------------------------------------------------------ 채점

def _overlap(a: Box, b: Box) -> float:
    """겹친 넓이 / 작은 쪽 넓이."""
    ix = max(0, min(a.x + a.w, b.x + b.w) - max(a.x, b.x))
    iy = max(0, min(a.y + a.h, b.y + b.h) - max(a.y, b.y))
    return ix * iy / max(1, min(a.w * a.h, b.w * b.h))


def _serious(report):
    return [f for f in report.findings if f.box is not None and f.severity is not Severity.INFO]


def score_personal(spans, report, truth: list[Box]) -> dict:
    serious = _serious(report)
    hit = [[f for f in serious if _overlap(f.box, t) >= 0.3] for t in truth]
    return {
        "read": sum(any(_overlap(s.box, t) >= 0.3 for s in spans) for t in truth),
        "alert": sum(bool(h) for h in hit),
        "cover": sum(any(f.severity is Severity.COVER for f in h) for h in hit),
        "outside": sum(1 for f in serious if not any(_overlap(f.box, t) >= 0.3 for t in truth)),
    }


def score_signs(report) -> dict:
    serious = _serious(report)
    cover = [f.kind for f in serious if f.severity is Severity.COVER]
    return {"cover": len(cover), "review": len(serious) - len(cover), "kinds": cover}


# ------------------------------------------------------------------ run

def _open(p: Path) -> Image.Image:
    with Image.open(p) as raw:
        return ImageOps.exif_transpose(raw).convert("RGB")


def run(folder: str, backend=None, limit: int | None = None) -> dict:
    folder = Path(folder)
    backend = backend or ocr.get_backend()
    res = {"backend": backend.name, "ocr_ms": [],
           "personal": {c: collections.Counter() for c in CONDITIONS},
           "signs": {c: {"images": 0, "with_cover": 0, "cover": 0, "review": 0,
                         "kinds": collections.Counter()} for c in CONDITIONS}}

    def conditions(img):
        t0 = time.perf_counter()
        spans = backend.read(img)
        res["ocr_ms"].append((time.perf_counter() - t0) * 1000)
        fixed = ocr.ScriptedBackend(spans)
        return spans, {c: fn(img, backend=fixed) for c, fn in CONDITIONS.items()}

    truth = json.loads((folder / "personal" / "truth.json").read_text(encoding="utf-8"))
    for name in sorted(truth)[:limit]:
        boxes = [Box(*b) for b in truth[name]]
        spans, reports = conditions(_open(folder / "personal" / "images" / name))
        for c, rep in reports.items():
            res["personal"][c].update(score_personal(spans, rep, boxes))
            res["personal"][c]["regions"] += len(boxes)
            res["personal"][c]["images"] += 1

    for p in sorted((folder / "signs" / "images").glob("*.jpg"))[:limit]:
        _, reports = conditions(_open(p))
        for c, rep in reports.items():
            s, r = score_signs(rep), res["signs"][c]
            r["images"] += 1
            r["with_cover"] += s["cover"] > 0
            r["cover"] += s["cover"]
            r["review"] += s["review"]
            r["kinds"].update(s["kinds"])
    return res


def _pct(a: int, b: int) -> str:
    return f"{a}/{b} ({a / b:.0%})" if b else "0/0"


def report_text(res: dict) -> str:
    ms = res["ocr_ms"]
    lines = [f"OCR {res['backend']} · 사진 {len(ms)}장 · OCR 평균 {sum(ms) / max(1, len(ms)):.0f} ms", ""]
    lines.append("[개인정보 글자 — 알리는가]")
    lines.append(f"{'조건':<10}{'OCR 이 읽음':>16}{'알림':>16}{'가림 권장':>16}{'라벨 밖 경고':>10}")
    for c, x in res["personal"].items():
        n = x["regions"]
        lines.append(f"{c:<10}{_pct(x['read'], n):>16}{_pct(x['alert'], n):>16}{_pct(x['cover'], n):>16}{x['outside']:>10}")
    lines += ["", "[개인정보가 아닌 글자 — 잘못 경고하는가]"]
    lines.append(f"{'조건':<10}{'가림 권장 나온 사진':>20}{'사진당 가림':>10}{'사진당 검토':>10}  가림 권장 종류")
    for c, x in res["signs"].items():
        n = max(1, x["images"])
        kinds = ", ".join(f"{k} {v}" for k, v in x["kinds"].most_common(5)) or "-"
        lines.append(f"{c:<10}{_pct(x['with_cover'], x['images']):>20}{x['cover'] / n:>10.2f}{x['review'] / n:>10.2f}  {kinds}")
    lines += ["",
              "OCR 이 읽음 = 규칙과 무관하게 그 영역 글자를 OCR 이 찾았는지(알림의 상한)",
              "※ AI 허브 데이터는 '학습용' 조건이라 발표에 쓰기 전에 AI 허브에 확인할 것."]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m eval.realtext")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prep", help="AI 허브 폴더 → 평가 묶음(zip)")
    p.add_argument("aihub")
    p.add_argument("out")
    p.add_argument("--signs", type=int, default=200, help="야외 한글 간판 사진 수")
    p.add_argument("--media", type=int, default=50, help="간판·현수막·광고판 종류별 사진 수")
    p = sub.add_parser("run", help="평가 묶음을 돌려 숫자를 낸다(OCR 필요)")
    p.add_argument("folder")
    p.add_argument("--limit", type=int, help="세트마다 앞에서부터 이만큼만(시간 줄이기)")
    a = ap.parse_args(argv)
    if a.cmd == "prep":
        prep(a.aihub, a.out, n_signs=a.signs, n_media_each=a.media)
    else:
        print(report_text(run(a.folder, limit=a.limit)))


if __name__ == "__main__":
    main()
