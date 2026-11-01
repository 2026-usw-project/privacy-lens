"""실사 사진 실패 원인 분류 — 놓친 항목이 어느 단계에서 틀렸는지 나눈다.

  ① 못 찾음    OCR 결과 어디에도 그 글자와 비슷한 조각이 없다    → OCR·검출(YOLO) 문제
  ② 잘못 읽음  비슷한 조각은 있는데 글자가 틀렸다(010 → O1O 등)   → OCR·보정 문제
  ③ 판단 실패  글자는 제대로 읽었는데 등급이 틀렸다               → 판단 규칙 문제

이 비율을 보고 어디에 시간을 쓸지 정한다(docs/MASKING_CRITERIA.md, 우선순위 표).

준비
  1. 팀원이 직접 찍은 사진을 한 폴더에 모은다(번호는 가리거나 가짜로).
  2. 정답 틀 만들기:  python -m eval.failures init <폴더>
     사진마다 <이름>.json 이 생긴다. 사진에 실제로 적힌 글자를 그대로 적는다.
       {"items": [
         {"text": "010-1234-5678", "expect": "cover",  "item": "휴대폰"},
         {"text": "권선로 208",     "expect": "review", "item": "도로명주소"},
         {"text": "1588-1255",     "expect": "none",   "item": "대표번호"}]}
     expect 는 cover(가림) / review(확인 필요) / none(가리면 안 됨). 기준은 가림 기준표.
  3. 실행:  PL_OCR=paddleocr python -m eval.failures run <폴더>

주의: 저장소 규칙대로 결과에는 숫자와 항목 이름만 찍는다. 글자를 보려면
--show-text 를 붙이되, 그 출력은 공유하지 않는다. 사진·정답은 커밋하지 않는다.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.judgment import COVER, NONE, RANK, REVIEW, _key, verdict  # noqa: E402

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic"}
MISREAD_MIN = 0.6   # 정답 글자의 이 비율 이상이 한 조각과 겹치면 '읽긴 했는데 틀림'


def similarity(gold_key: str, span_key: str) -> float:
    """정답 글자 중 OCR 조각과 순서대로 겹치는 글자의 비율(0~1)."""
    if not gold_key:
        return 0.0
    blocks = SequenceMatcher(None, gold_key, span_key, autojunk=False).get_matching_blocks()
    return sum(b.size for b in blocks) / len(gold_key)


def classify(gold: dict, span_texts: list[str], findings) -> tuple[str, str, float]:
    """(원인, 판단 등급, 가장 비슷한 조각과의 유사도). 원인은 맞음/①/②/③."""
    gk = _key(gold["text"])
    keys = [_key(t) for t in span_texts]
    best = max((similarity(gk, k) for k in keys), default=0.0)

    exact = [i for i, k in enumerate(keys) if gk and gk in k]
    got = NONE
    for fd in findings:
        if fd.span_index in exact:
            ek = _key(fd.evidence_text)
            if not ek or ek in gk or gk in ek:
                v = "none" if fd.severity.value == "info" else fd.severity.value
                got = max(got, v, key=lambda x: RANK[x])

    if verdict(gold["expect"], got) == "맞음":
        return "맞음", got, best
    if exact:
        return "③ 판단 실패", got, 1.0
    # 글자를 못 읽었는데 정답이 '가리면 안 됨'이면 결과적으로는 맞다
    if gold["expect"] == NONE:
        return "맞음", got, best
    if best >= MISREAD_MIN:
        return "② 잘못 읽음", got, best
    return "① 못 찾음", got, best


def _images(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXT)


def init(folder: Path) -> None:
    made = 0
    for img in _images(folder):
        js = img.with_suffix(".json")
        if not js.exists():
            js.write_text(json.dumps({"items": [{"text": "", "expect": COVER, "item": ""}]},
                                     ensure_ascii=False, indent=1), encoding="utf-8")
            made += 1
    print(f"정답 틀 {made}개를 만들었습니다. 사진마다 적힌 글자와 등급을 채우세요.")


def _analyze(image):
    """pipeline.analyze 와 같은 순서로 돌리되, 판단에 쓴 OCR 조각 목록도 돌려준다."""
    from pipeline import context, detect, ocr
    backend = ocr.get_backend()
    detector = detect.get_detector()
    spans, _ = ocr.read_with_raw(backend, image)
    dets = detector.detect(image) if detector is not None else []
    if dets:
        spans, _ = detect.reread_documents(image, spans, dets, backend)
    return spans, context.evaluate(spans), backend.name, (detector.name if detector else "없음")


def run(folder: Path, show_text: bool = False) -> None:
    from PIL import Image, ImageOps

    rows, skipped = [], 0
    engine = ""
    for img in _images(folder):
        js = img.with_suffix(".json")
        if not js.exists():
            skipped += 1
            continue
        items = [it for it in json.loads(js.read_text(encoding="utf-8"))["items"] if it.get("text")]
        if not items:
            skipped += 1
            continue
        with Image.open(img) as im:
            image = ImageOps.exif_transpose(im).convert("RGB")
        spans, findings, ocr_name, det_name = _analyze(image)
        engine = f"OCR {ocr_name}, 검출 {det_name}"
        texts = [s.text for s in spans]
        for it in items:
            cause, got, sim = classify(it, texts, findings)
            rows.append({"photo": img.name, "item": it.get("item") or "?", "expect": it["expect"],
                         "got": got, "cause": cause, "sim": round(sim, 2), "text": it["text"]})

    if not rows:
        raise SystemExit("채점할 정답이 없습니다. 먼저 init 으로 틀을 만들고 채우세요.")

    photos = len({r["photo"] for r in rows})
    print(f"사진 {photos}장, 정답 항목 {len(rows)}개 ({engine})" + (f", 정답 없는 사진 {skipped}장 건너뜀" if skipped else ""))
    causes = Counter(r["cause"] for r in rows)
    wrong = len(rows) - causes["맞음"]
    print(f"\n맞음 {causes['맞음']}개, 틀림 {wrong}개")
    for c in ("① 못 찾음", "② 잘못 읽음", "③ 판단 실패"):
        share = f"{100 * causes[c] / wrong:.0f}%" if wrong else "-"
        print(f"  {c:<8} {causes[c]:>3}개  (틀린 것 중 {share})")

    cov = [r for r in rows if r["expect"] == COVER]
    if cov:
        hit = sum(r["got"] == COVER for r in cov)
        weak = sum(r["got"] == REVIEW for r in cov)
        print(f"\n가려야 할 것 {len(cov)}개 → 가림 {hit}개, 확인 필요로만 {weak}개, 놓침 {len(cov) - hit - weak}개")
    neg = [r for r in rows if r["expect"] == NONE]
    if neg:
        print(f"가리면 안 될 것 {len(neg)}개 → 잘못 가림 {sum(r['got'] == COVER for r in neg)}개")

    print("\n항목별 원인")
    by_item = defaultdict(Counter)
    for r in rows:
        by_item[r["item"]][r["cause"]] += 1
    for item, cnt in sorted(by_item.items()):
        print(f"  {item:<10} " + ", ".join(f"{k} {v}" for k, v in cnt.most_common()))

    bad = [r for r in rows if r["cause"] != "맞음"]
    if bad:
        print("\n틀린 항목")
        for r in bad:
            text = f" '{r['text']}'" if show_text else ""
            print(f"  {r['photo']:<20} {r['item']:<10}{text} 정답 {r['expect']} → {r['got']}  "
                  f"{r['cause']} (유사도 {r['sim']})")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m eval.failures")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init").add_argument("folder")
    p = sub.add_parser("run")
    p.add_argument("folder")
    p.add_argument("--show-text", action="store_true", help="틀린 항목의 글자도 찍기(공유 금지)")
    a = ap.parse_args(argv)
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    folder = Path(a.folder)
    if a.cmd == "init":
        init(folder)
    else:
        run(folder, show_text=a.show_text)


if __name__ == "__main__":
    main()
