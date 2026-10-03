"""
[C] 평가 스크립트 — 합성 · 실사 테스트셋 공용

  python -m data.eval --dir data/demo                 (truth.json 필요)
  python -m data.eval --dir data/test --out 결과.json   (결과 + 실행 환경을 JSON 으로 저장)

측정 항목
  - 항목 재현율 · 정밀도 : 정답 개인정보 '값'과 예측 값을 1:1 로 짝지어 비교 (유형별)
        정확   숫자류는 숫자만 같으면, 글자류는 공백·쉼표·따옴표를 뺀 문자열이 같으면 일치
        허용   글자류(이름·주소·소속)는 글자 20% 이내(최소 1자) 오인식을 허용
        유형만 같은 유형이 하나라도 있으면 인정 — 값을 안 보던 이전 방식, 비교용
  - 문서 검출률   : 정답 문서 박스와 IoU ≥ 0.3 이거나 안에 들어가는 finding 이 있는 비율
  - 오탐(사진 단위): 개인정보 없는 사진에서 medium 이상이 뜬 비율 (어려운 비위험은 따로 집계)
  - QR 링크 · GPS 검출 · 응답 시간(모델 로딩 제외)

주의: 규칙을 고칠 때 본 사진 세트로 평가하면 개발셋 점수입니다. 최종 수치는 규칙을 고치는 데 쓰지 않은
세트(다른 --seed 나 실사)로 재세요.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import statistics
import subprocess
import warnings
from collections import defaultdict
from datetime import datetime
from importlib import metadata
from pathlib import Path

warnings.filterwarnings("ignore")

NUM_TYPES = {"phone", "tracking_number", "student_number", "rrn", "card_number", "account_number"}
MODES = ("strict", "lenient", "type")
SKIP = {"url", "address_detail"}      # url 은 QR 경로로 따로 셈, address_detail 은 address 값에 합쳐져 있음


# ── 값 비교 ────────────────────────────────────────────
def _edit(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _norm(tp: str, v: str) -> str:
    return re.sub(r"\D", "", v) if tp in NUM_TYPES else re.sub(r"[\s,'\"`]", "", v)


def same(tp: str, gt: str, pred: str, lenient: bool = False) -> bool:
    a, b = _norm(tp, gt), _norm(tp, pred)
    if a == b:
        return True
    return lenient and tp not in NUM_TYPES and _edit(a, b) <= max(1, round(len(a) * 0.2))


def pair(gt, pred, mode: str = "strict"):
    """정답·예측 [(유형, 값)] 을 1:1 로 짝지어 (못 찾은 정답, 정답과 안 맞은 예측) 목록을 돌려줌"""
    used, fn = set(), []
    for tp, v in gt:
        k = next((i for i, (pt, pv) in enumerate(pred)
                  if i not in used and pt == tp and (mode == "type" or same(tp, v, pv, mode == "lenient"))), None)
        if k is None:
            fn.append((tp, v))
        else:
            used.add(k)
    return fn, [p for i, p in enumerate(pred) if i not in used]


def match(gt, pred, mode: str = "strict"):
    """유형별 [TP, FN, FP] — 값이 한두 글자 틀린 예측은 정확 모드에서 FN 이자 FP 로 함께 셈"""
    fn, fp = pair(gt, pred, mode)
    out = defaultdict(lambda: [0, 0, 0])
    for tp, _ in gt:
        out[tp][0] += 1
    for tp, _ in fn:
        out[tp][0] -= 1
        out[tp][1] += 1
    for tp, _ in fp:
        out[tp][2] += 1
    return out


# ── 위치 비교 (문서 단위) ───────────────────────────────
def _iou(a, b) -> float:
    ix = max(0, min(a["x2"], b["x2"]) - max(a["x1"], b["x1"]))
    iy = max(0, min(a["y2"], b["y2"]) - max(a["y1"], b["y1"]))
    inter = ix * iy
    ua = (a["x2"] - a["x1"]) * (a["y2"] - a["y1"]) + (b["x2"] - b["x1"]) * (b["y2"] - b["y1"]) - inter
    return inter / ua if ua else 0.0


def _inside(p, box, margin=0.05) -> bool:
    w, h = box["x2"] - box["x1"], box["y2"] - box["y1"]
    cx, cy = (p["x1"] + p["x2"]) / 2, (p["y1"] + p["y2"]) / 2
    return box["x1"] - w * margin <= cx <= box["x2"] + w * margin and box["y1"] - h * margin <= cy <= box["y2"] + h * margin


# ── 실행 환경 기록 (같은 데이터 · 같은 버전이면 같은 결과인지 확인하려고) ──
def _env() -> dict:
    def ver(pkg):
        try:
            return metadata.version(pkg)
        except metadata.PackageNotFoundError:
            return None
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:  # noqa: BLE001
        commit = ""
    return {"python": platform.python_version(), "os": platform.platform(), "commit": commit,
            **{p: ver(p) for p in ("easyocr", "torch", "opencv-contrib-python-headless", "numpy", "Pillow")}}


def _pct(a, b) -> str:
    return f"{a / b:.0%}" if b else "-"


def main():
    from reader import rules
    from server.pipeline import analyze
    from vision import ocr

    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/demo")
    ap.add_argument("--out", default=None, help="결과 JSON 경로 (기본: <dir>/eval_result.json)")
    ap.add_argument("--show", action="store_true",
                    help="틀린 항목의 원문 값을 화면에 출력 (JSON 에는 저장 안 함). 실제 개인정보가 든 실사 세트에는 쓰지 말 것")
    a = ap.parse_args()
    d = Path(a.dir)
    truth_raw = (d / "truth.json").read_bytes()
    truths = json.loads(truth_raw.decode("utf-8"))

    ocr.warmup()                                     # 모델 로딩 시간이 첫 사진 응답 시간에 섞이지 않도록
    cap, orig = {}, ocr.read_lines

    def spy(img):                                    # ponytail: 서버 코드를 안 고치고 마스킹 전 원문 줄을 얻기 위한 가로채기
        cap["lines"] = orig(img)
        return cap["lines"]

    ocr.read_lines = spy

    tot = {m: defaultdict(lambda: [0, 0, 0]) for m in MODES}
    doc_hit = doc_all = neg_fp = neg_all = hard_fp = hard_all = gps_hit = gps_all = qr_hit = qr_all = 0
    times, rows = [], []
    for t in truths:
        r = analyze((d / t["file"]).read_bytes()).model_dump(mode="json")
        times.append(r["timing"]["total_ms"])
        fs = r["findings"]
        gt = [(p["type"], p["value"]) for o in t["objects"] for p in o["pii"] if p["type"] not in SKIP]
        pred = [(h.type, h.value) for h in rules.find_pii(cap["lines"]) if h.type not in SKIP]
        for m in MODES:
            for tp, (x, y, z) in match(gt, pred, m).items():
                v = tot[m][tp]
                v[0] += x; v[1] += y; v[2] += z
        if t["negative"]:
            fp = any(f["risk"]["level"] in ("medium", "high") for f in fs)
            neg_all += 1; neg_fp += fp
            if t.get("hard"):
                hard_all += 1; hard_fp += fp
        if t["has_gps"]:
            gps_all += 1
            gps_hit += r["exif"].get("gps") is not None
        want_qr = sum(p["type"] == "url" for o in t["objects"] for p in o["pii"])
        got_qr = sum(f["label"] == "qr_barcode" and any(p["type"] == "url" for p in f.get("pii", [])) for f in fs)
        qr_all += want_qr; qr_hit += min(want_qr, got_qr)
        for o in t["objects"]:
            doc_all += 1
            doc_hit += any(_iou(f["bbox"], o["bbox"]) >= 0.3 or _inside(f["bbox"], o["bbox"]) for f in fs)
        fn_items, fp_items = pair(gt, pred, "strict")
        s = {"tp": len(gt) - len(fn_items), "fn": len(fn_items), "fp": len(fp_items)}
        rows.append({"file": t["file"], "level": r["summary"]["level"], "ms": r["timing"]["total_ms"],
                     "negative": t["negative"], "hard": bool(t.get("hard")), **s,
                     "fp_types": sorted({tp for tp, _ in fp_items})})      # 유형만 저장 — 원문 값은 저장하지 않음
        print(f"{t['file']}  {r['summary']['level']:<6} {r['timing']['total_ms']:>6}ms  TP{s['tp']:>2} FN{s['fn']:>2} FP{s['fp']:>2}  {r['summary']['headline']}")
        if a.show:
            for tp, v in fn_items:
                print(f"      놓침  {tp:<16} {v}")
            for tp, v in fp_items:
                print(f"      오탐  {tp:<16} {v}")

    def sums(m, i):
        return sum(v[i] for v in tot[m].values())

    print("\n── 항목 재현율 (정답 값과 비교) ─────────────────────")
    print(f"  {'유형':<16}{'정답':>5}{'정확':>6}{'허용':>6}{'유형만':>7}")
    for tp in sorted(tot["type"]):
        n = tot["type"][tp][0] + tot["type"][tp][1]
        if n:
            print(f"  {tp:<16}{n:>5}{tot['strict'][tp][0]:>6}{tot['lenient'][tp][0]:>6}{tot['type'][tp][0]:>7}")
    n_gt = sums("type", 0) + sums("type", 1)
    summary = {"gt_items": n_gt}
    for m, label in (("strict", "정확"), ("lenient", "허용"), ("type", "유형만")):
        summary[f"recall_{m}"] = sums(m, 0) / n_gt if n_gt else 0
    for m in ("strict", "lenient"):
        tp_, fp_ = sums(m, 0), sums(m, 2)
        summary[f"precision_{m}"] = tp_ / (tp_ + fp_) if tp_ + fp_ else 0
    print(f"  재현율  정확 {summary['recall_strict']:.0%} · 허용 {summary['recall_lenient']:.0%} · 유형만(이전 방식) {summary['recall_type']:.0%}   (목표 85%)")
    print(f"  정밀도  정확 {summary['precision_strict']:.0%} · 허용 {summary['precision_lenient']:.0%}   (오탐 항목 {sums('strict', 2)}개)")
    fp_by = {tp: v[2] for tp, v in tot["strict"].items() if v[2]}
    if fp_by:
        print("  오탐 항목(정확 기준) 유형별:", ", ".join(f"{k} {v}" for k, v in sorted(fp_by.items())))
    print(f"문서 검출률        {doc_hit}/{doc_all}  {_pct(doc_hit, doc_all)}")
    print(f"오탐 (비위험 사진) {neg_fp}/{neg_all}  {_pct(neg_fp, neg_all)}   (목표 15% 이하)  · 그중 어려운 비위험 {hard_fp}/{hard_all}")
    print(f"QR 링크            {qr_hit}/{qr_all}")
    print(f"GPS 검출           {gps_hit}/{gps_all}")
    print(f"응답 시간(모델 로딩 제외)  평균 {statistics.mean(times) / 1000:.1f}s · 최대 {max(times) / 1000:.1f}s")

    summary.update(doc=[doc_hit, doc_all], neg_fp=[neg_fp, neg_all], hard_fp=[hard_fp, hard_all],
                   qr=[qr_hit, qr_all], gps=[gps_hit, gps_all],
                   ms_mean=statistics.mean(times), ms_max=max(times),
                   per_type={m: dict(tot[m]) for m in MODES})
    out = Path(a.out) if a.out else d / "eval_result.json"
    out.write_text(json.dumps({"when": datetime.now().isoformat(timespec="seconds"), "dir": str(d),
                               "truth_sha1": hashlib.sha1(truth_raw).hexdigest()[:10], "env": _env(),
                               "summary": summary, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("결과 저장:", out)


if __name__ == "__main__":
    main()
