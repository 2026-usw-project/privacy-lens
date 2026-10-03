"""
[C] 평가 스크립트 — 합성 · 실사 테스트셋 공용

  python -m data.eval --dir data/demo            (truth.json 필요)

측정 항목 (PPT 성공 기준과 같은 이름)
  - PII 항목 재현율 : 정답 개인정보 중 탐지된 비율 (유형별)
  - 문서 검출률     : 정답 문서 박스와 IoU ≥ 0.3 로 겹치는 finding 이 있는 비율
  - 오탐            : 개인정보 없는 사진에서 medium 이상이 뜬 비율
  - GPS 검출        : GPS 가 있는 사진에서 exif.gps 를 찾은 비율
  - 평균 / 최대 응답 시간
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import warnings
from collections import defaultdict
from pathlib import Path

warnings.filterwarnings("ignore")


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


def main():
    from server.pipeline import analyze

    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/demo")
    a = ap.parse_args()
    d = Path(a.dir)
    truths = json.loads((d / "truth.json").read_text(encoding="utf-8"))

    rec = defaultdict(lambda: [0, 0])            # type → [찾음, 전체]
    doc_hit = doc_all = neg_fp = neg_all = gps_hit = gps_all = 0
    times = []
    rows = []
    for t in truths:
        r = analyze((d / t["file"]).read_bytes()).model_dump(mode="json")
        times.append(r["timing"]["total_ms"])
        fs = r["findings"]
        if t["negative"]:
            neg_all += 1
            neg_fp += any(f["risk"]["level"] in ("medium", "high") for f in fs)
        if t["has_gps"]:
            gps_all += 1
            gps_hit += r["exif"].get("gps") is not None
        for o in t["objects"]:
            doc_all += 1
            near = [f for f in fs if _iou(f["bbox"], o["bbox"]) >= 0.3 or _inside(f["bbox"], o["bbox"])]
            doc_hit += bool(near)
            found_types = defaultdict(int)
            for f in fs:
                if _inside(f["bbox"], o["bbox"], margin=0.15) or f in near:
                    for p in f.get("pii", []):
                        found_types[p["type"]] += 1
            want = defaultdict(int)
            for p in o["pii"]:
                want[p["type"]] += 1
            for tp, n in want.items():
                rec[tp][0] += min(n, found_types.get(tp, 0))
                rec[tp][1] += n
        rows.append(f"{t['file']}  {r['summary']['level']:<6} {r['timing']['total_ms']:>6}ms  {r['summary']['headline']}")

    print("\n".join(rows))
    print("\n── PII 항목 재현율 ─────────────")
    tot_f = tot_n = 0
    for tp, (f, n) in sorted(rec.items()):
        print(f"  {tp:<16} {f:>3}/{n:<3} {f / n:.0%}")
        tot_f += f; tot_n += n
    print(f"  {'전체':<15} {tot_f:>3}/{tot_n:<3} {tot_f / max(tot_n, 1):.0%}   (목표 85%)")
    print(f"문서 검출률        {doc_hit}/{doc_all}  {doc_hit / max(doc_all, 1):.0%}")
    print(f"오탐 (비위험 사진) {neg_fp}/{neg_all}  {neg_fp / max(neg_all, 1):.0%}   (목표 15% 이하)")
    print(f"GPS 검출           {gps_hit}/{gps_all}")
    print(f"응답 시간          평균 {statistics.mean(times) / 1000:.1f}s · 최대 {max(times) / 1000:.1f}s")


if __name__ == "__main__":
    main()
