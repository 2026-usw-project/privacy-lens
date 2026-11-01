"""실사 사진 실패 원인 분류 — 놓친 항목이 어느 단계에서 틀렸는지 나눈다.

  ① 못 찾음    OCR 결과 어디에도 그 글자와 비슷한 조각이 없다    → OCR·검출(YOLO) 문제
  ② 잘못 읽음  비슷한 조각은 있는데 글자가 틀렸다(010 → O1O 등)   → OCR·보정 문제
  ③ 판단 실패  글자는 제대로 읽었는데 등급이 틀렸다               → 판단 규칙 문제

이 비율을 보고 어디에 시간을 쓸지 정한다(docs/MASKING_CRITERIA.md, 우선순위 표).

준비
  1. 팀원이 직접 찍은 사진을 한 폴더에 모은다(번호는 가리거나 가짜로).
     공유 폴더에 올리기 전에 위치정보를 지운다:  python -m eval.failures strip <폴더>
  2. 정답 틀 만들기:  python -m eval.failures init <폴더>
     사진마다 <이름>.json 이 생긴다. 사진에 실제로 적힌 글자를 그대로 적는다.
       {"items": [
         {"text": "010-1234-5678", "expect": "cover",  "item": "휴대폰"},
         {"text": "권선로 208",     "expect": "review", "item": "도로명주소"},
         {"text": "1588-1255",     "expect": "none",   "item": "대표번호"}]}
     expect 는 cover(가림) / review(확인 필요) / none(가리면 안 됨). 기준은 가림 기준표.
  3. 실행:  PL_OCR=paddleocr python -m eval.failures run <폴더>
     실행할 때마다 <폴더>/평가기록.csv 에 숫자가 한 줄씩 쌓인다(코드 버전·OCR·검출 모델과 함께).
     규칙을 고치기 전과 후에 한 번씩 돌리면 그대로 '개선 전/후' 표가 된다.
     정답은 eval/gold_tool.html 로 브라우저에서 입력할 수 있다.

주의: 저장소 규칙대로 결과에는 숫자와 항목 이름만 찍는다. 글자를 보려면
--show-text 를 붙이되, 그 출력은 공유하지 않는다. 사진·정답은 커밋하지 않는다.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import subprocess
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


TOOL_NAME = "정답입력도구.html"


def _heif() -> None:
    """아이폰 HEIC 를 열 수 있게. pillow-heif 가 없으면 HEIC 만 못 연다."""
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:
        pass


def strip(folder: Path) -> int:
    """사진의 위치정보·기기정보(EXIF)를 지운다. 해상도는 그대로 둔다.

    팀원 휴대폰 사진에는 집 위치가 들어 있을 수 있다. 공유 폴더에 올리기 전에 지운다.
    방향(회전)은 픽셀에 반영한 뒤 지운다. HEIC 는 JPEG 로 바꾼다(정답 파일 이름은 그대로 맞는다).
    """
    from PIL import Image, ImageOps
    _heif()
    n = 0
    for img in _images(folder):
        with Image.open(img) as im:
            if not im.getexif() and img.suffix.lower() != ".heic":
                continue
            clean = ImageOps.exif_transpose(im).convert("RGB")
        out = img.with_suffix(".jpg") if img.suffix.lower() == ".heic" else img
        if out.suffix.lower() in (".jpg", ".jpeg"):
            clean.save(out, quality=95)
        else:
            clean.save(out)
        if out != img:
            img.unlink()
        n += 1
    return n


def init(folder: Path) -> None:
    """정답 틀과 정답 입력 도구를 폴더에 넣는다. 이미 있는 정답은 건드리지 않는다."""
    import shutil
    if not folder.is_dir():
        raise SystemExit(f"폴더가 없습니다: {folder}")
    shutil.copy2(Path(__file__).with_name("gold_tool.html"), folder / TOOL_NAME)
    made = 0
    for img in _images(folder):
        js = img.with_suffix(".json")
        if not js.exists():
            js.write_text(json.dumps({"items": [{"text": "", "expect": COVER, "item": ""}]},
                                     ensure_ascii=False, indent=1), encoding="utf-8")
            made += 1
    print(f"정답 틀 {made}개를 만들었습니다. 사진마다 적힌 글자와 등급을 채우세요.\n"
          f"브라우저(크롬·엣지)로 {folder / TOOL_NAME} 을 열고 '폴더 열기'로 이 폴더를 고르면 편합니다.")


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


HISTORY = "평가기록.csv"
HISTORY_FIELDS = ["시각", "코드", "OCR", "검출", "사진", "항목", "맞음", "못찾음", "잘못읽음", "판단실패",
                  "가림정답", "가림", "확인필요로만", "놓침", "무시정답", "잘못가림", "정답밖가림", "메모"]


def _git_version() -> str:
    root = Path(__file__).resolve().parents[1]
    try:
        rev = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
                               capture_output=True, text=True, timeout=5).stdout.strip()
        return (rev + ("+수정중" if dirty else "")) if rev else "?"
    except Exception:
        return "?"


def load_gold(path: Path) -> list[dict] | None:
    """채점에 쓸 정답 항목. 덜 끝난 정답(checked=false)이나 빈 틀은 None.

    정답 입력 도구는 '가릴 것이 없는 사진'을 items=[], checked=true 로 저장한다.
    이런 사진은 정답 항목은 없지만 '정답 밖 가림'(오탐 후보)을 세는 데 쓴다.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    items = [it for it in data.get("items", []) if (it.get("text") or "").strip()]
    if data.get("checked") is False:
        return None
    if not items and data.get("checked") is not True:
        return None  # init 이 만든 빈 틀
    return items


def extra_covers(items: list[dict], span_texts: list[str], findings) -> int:
    """정답 어디에도 없는데 가림으로 올라온 항목 수. 오탐이거나 정답에서 빠뜨린 것이다."""
    keys = [_key(it["text"]) for it in items]
    n = 0
    for fd in findings:
        if fd.severity.value != COVER:
            continue
        ek = _key(fd.evidence_text)
        st = _key(span_texts[fd.span_index]) if fd.span_index is not None else ""
        if not any(k and (k in st or (ek and (ek in k or k in ek))) for k in keys):
            n += 1
    return n


def summary_row(rows: list[dict], engine: tuple[str, str], note: str = "", extra: int = 0,
                photos: int | None = None) -> dict:
    causes = Counter(r["cause"] for r in rows)
    cov = [r for r in rows if r["expect"] == COVER]
    neg = [r for r in rows if r["expect"] == NONE]
    hit = sum(r["got"] == COVER for r in cov)
    weak = sum(r["got"] == REVIEW for r in cov)
    return {
        "시각": dt.datetime.now().isoformat(timespec="minutes"), "코드": _git_version(),
        "OCR": engine[0], "검출": engine[1],
        "사진": photos if photos is not None else len({r["photo"] for r in rows}), "항목": len(rows), "맞음": causes["맞음"],
        "못찾음": causes["① 못 찾음"], "잘못읽음": causes["② 잘못 읽음"], "판단실패": causes["③ 판단 실패"],
        "가림정답": len(cov), "가림": hit, "확인필요로만": weak, "놓침": len(cov) - hit - weak,
        "무시정답": len(neg), "잘못가림": sum(r["got"] == COVER for r in neg), "정답밖가림": extra, "메모": note,
    }


def append_history(folder: Path, row: dict) -> Path:
    path = folder / HISTORY
    new = not path.exists()
    with path.open("a", encoding="utf-8-sig", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=HISTORY_FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)
    return path


def run(folder: Path, show_text: bool = False, note: str = "", record: bool = True,
        json_out: str | None = None) -> None:
    from PIL import Image, ImageOps
    _heif()

    rows, skipped, extra, scored = [], 0, Counter(), []
    engine = ("?", "?")
    for img in _images(folder):
        js = img.with_suffix(".json")
        items = load_gold(js) if js.exists() else None
        if items is None:
            skipped += 1
            continue
        with Image.open(img) as im:
            image = ImageOps.exif_transpose(im).convert("RGB")
        spans, findings, ocr_name, det_name = _analyze(image)
        engine = (ocr_name, det_name)
        texts = [s.text for s in spans]
        scored.append(img.name)
        extra[img.name] = extra_covers(items, texts, findings)
        for it in items:
            cause, got, sim = classify(it, texts, findings)
            rows.append({"photo": img.name, "item": it.get("item") or "?", "expect": it["expect"],
                         "got": got, "cause": cause, "sim": round(sim, 2), "text": it["text"]})

    if not scored:
        raise SystemExit("채점할 정답이 없습니다. 먼저 init 으로 틀을 만들거나 gold_tool.html 로 정답을 입력하세요.")

    photos = len(scored)
    print(f"사진 {photos}장, 정답 항목 {len(rows)}개 (OCR {engine[0]}, 검출 {engine[1]})"
          + (f", 정답이 없거나 덜 된 사진 {skipped}장 건너뜀" if skipped else ""))
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
    n_extra = sum(extra.values())
    print(f"정답 밖 가림 {n_extra}개 (사진 {sum(1 for v in extra.values() if v)}장) — 오탐이거나 정답에서 빠뜨린 것. 사진을 다시 확인하세요")

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

    if json_out:  # 글자는 넣지 않는다
        Path(json_out).write_text(json.dumps([{k: v for k, v in r.items() if k != "text"} for r in rows],
                                             ensure_ascii=False, indent=1), encoding="utf-8")
    if record:
        path = append_history(folder, summary_row(rows, engine, note, extra=n_extra, photos=photos))
        print(f"\n기록을 남겼습니다: {path}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m eval.failures")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init").add_argument("folder")
    sub.add_parser("strip", help="사진의 위치정보(EXIF) 지우기").add_argument("folder")
    p = sub.add_parser("run")
    p.add_argument("folder")
    p.add_argument("--show-text", action="store_true", help="틀린 항목의 글자도 찍기(공유 금지)")
    p.add_argument("--note", default="", help="평가기록.csv 에 남길 메모(예: '이름 규칙 보강 후')")
    p.add_argument("--no-record", action="store_true", help="평가기록.csv 에 남기지 않기")
    p.add_argument("--json", help="항목별 결과를 JSON 으로 저장(글자 제외)")
    a = ap.parse_args(argv)
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    folder = Path(a.folder)
    if a.cmd == "init":
        init(folder)
    elif a.cmd == "strip":
        print(f"위치정보·기기정보를 지운 사진 {strip(folder)}장")
    else:
        run(folder, show_text=a.show_text, note=a.note, record=not a.no_record, json_out=a.json)


if __name__ == "__main__":
    main()
