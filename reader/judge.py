"""
[B] OCR 줄 + QR 검출 → Finding 목록

데모 단계에서는 YOLO 대신 '개인정보가 나온 줄들을 가까운 것끼리 묶은 범위'를 영역으로 사용합니다.
YOLO 도입 후에는 build_findings() 대신 read_and_judge(image, detections) 가
YOLO 박스 안의 줄만 모아 같은 판정 함수(_judge_group)를 호출하면 됩니다.
"""
from __future__ import annotations

import statistics
from typing import Dict, List, Sequence

from schema.models import BBox, Detection, Finding, OCRLine, OCRResult, PIIItem, Risk, RiskFactors

from . import rules

TYPE_WEIGHT = {
    "rrn": 1.0, "card_number": 1.0, "account_number": 1.0,
    "phone": 0.9, "address": 0.9, "email": 0.7, "student_number": 0.7,
    "person_name": 0.6, "plate_number": 0.6, "tracking_number": 0.5, "url": 0.5,
    "affiliation": 0.3,
}
TYPE_KO = {
    "person_name": "이름", "address": "주소", "phone": "전화번호", "tracking_number": "송장번호",
    "student_number": "학번", "affiliation": "소속 학교", "url": "링크", "rrn": "주민등록번호",
    "card_number": "카드번호", "plate_number": "차량번호", "email": "이메일",
}
LABEL_KO = {
    "parcel_label": "택배 송장", "student_id": "학생증", "name_tag": "명찰", "payment_card": "카드",
    "screen": "화면", "license_plate": "번호판", "receipt": "영수증", "document": "문서", "qr_barcode": "QR코드",
}
POS_KO = [["왼쪽 위", "위쪽 가운데", "오른쪽 위"], ["왼쪽", "가운데", "오른쪽"], ["왼쪽 아래", "아래쪽 가운데", "오른쪽 아래"]]
ORDER = ["rrn", "card_number", "person_name", "address", "phone", "email", "student_number",
         "tracking_number", "plate_number", "affiliation", "url"]


def level_of(score: float) -> str:
    if score <= 0:
        return "none"
    return "low" if score < 0.3 else "medium" if score < 0.6 else "high"


def _josa(word: str, a: str = "이", b: str = "가") -> str:
    ch = word[-1]
    if "가" <= ch <= "힣":
        return a if (ord(ch) - 0xAC00) % 28 else b
    return a if ch in "013678" else b      # 숫자/영문 끝: 대략적 처리


def position(b: BBox, W: int, H: int) -> str:
    cx, cy = (b.x1 + b.x2) / 2 / W, (b.y1 + b.y2) / 2 / H
    return POS_KO[min(int(cy * 3), 2)][min(int(cx * 3), 2)]


def _union(boxes: Sequence[BBox]) -> BBox:
    return BBox(x1=min(b.x1 for b in boxes), y1=min(b.y1 for b in boxes),
                x2=max(b.x2 for b in boxes), y2=max(b.y2 for b in boxes))


def _gap(a: BBox, b: BBox) -> float:
    dx = max(0, max(a.x1, b.x1) - min(a.x2, b.x2))
    dy = max(0, max(a.y1, b.y1) - min(a.y2, b.y2))
    return (dx * dx + dy * dy) ** 0.5


def _cluster(idxs: List[int], lines: List[OCRLine], k: float = 3.5) -> List[List[int]]:
    parent = {i: i for i in idxs}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a in idxs:
        for b in idxs:
            if a < b:
                la, lb = lines[a].bbox, lines[b].bbox
                h = min(la.y2 - la.y1, lb.y2 - lb.y1)
                if _gap(la, lb) < k * h:
                    parent[find(a)] = find(b)
    groups: Dict[int, List[int]] = {}
    for i in idxs:
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def _reason(label: str, pos: str, types: List[str], readability: float) -> str:
    names = [TYPE_KO[t] for t in ORDER if t in types]
    items = ", ".join(names)
    verb = "읽힙니다" if readability >= 0.5 else "읽힐 수 있습니다"
    return f"{pos} {LABEL_KO[label]}에서 {items}{_josa(names[-1])} {verb}."


def _judge(label: str, bbox: BBox, hits: List[rules.Hit], member_lines: List[OCRLine],
           W: int, H: int) -> Risk:
    types = {h.type for h in hits}
    tw = max(TYPE_WEIGHT.get(t, 0.3) for t in types)
    if "person_name" in types and types & {"phone", "address"}:
        tw = min(1.0, tw + 0.1)                     # 이름 + 연락처/주소 조합 → 특정인 식별 가능
    conf = statistics.mean(h.conf for h in hits)
    readability = min(1.0, 0.4 + 0.6 * conf)
    med_h = statistics.median(l.bbox.y2 - l.bbox.y1 for l in member_lines)
    area_factor = max(0.5, min(1.0, med_h / 18))
    score = round(tw * readability * area_factor, 3)
    return Risk(score=score, level=level_of(score),
                factors=RiskFactors(type_weight=round(tw, 3), readability=round(readability, 3),
                                    area_factor=round(area_factor, 3)),
                reason=_reason(label, position(bbox, W, H), sorted(types), readability))


def build_findings(W: int, H: int, lines: List[OCRLine], qr_dets: List[Detection],
                   debug: bool = False, ocr_engine: str = "") -> List[Finding]:
    hits = rules.find_pii(lines)
    by_line: Dict[int, List[rules.Hit]] = {}
    for h in hits:
        by_line.setdefault(h.line_idx, []).append(h)
    # 키워드만 있는 줄(받는분, 운송장번호, 학생증 …)도 묶음의 다리 역할로 포함
    kw_lines = [i for i, l in enumerate(lines)
                if rules.KW_PARCEL.search(l.text) or rules.KW_STUDENT.search(l.text) or rules.KW_RECIPIENT.search(l.text)]
    nodes = sorted(set(by_line) | set(kw_lines))
    findings: List[Finding] = []

    groups = _cluster(nodes, lines)
    # 약한 묶음(학교 이름 · 키워드만)은 가까운(줄 높이 15배 이내) 강한 묶음에 합침 — 학생증 머리글과 본문 사이 사진 공간 대응
    weak_types = {"affiliation", "address_detail"}
    def strong(g):
        return any(h.type not in weak_types for i in g for h in by_line.get(i, []))
    strong_g = [g for g in groups if strong(g)]
    for g in [g for g in groups if not strong(g)]:
        ub = _union([lines[i].bbox for i in g])
        h = min(lines[i].bbox.y2 - lines[i].bbox.y1 for i in g)
        best = min(strong_g, key=lambda s: _gap(ub, _union([lines[i].bbox for i in s])), default=None)
        if best is not None and _gap(ub, _union([lines[i].bbox for i in best])) < 15 * h:
            best.extend(g)
        else:
            strong_g.append(g)

    for grp in strong_g:
        g_hits = [h for i in grp for h in by_line.get(i, [])]
        real = [h for h in g_hits if h.type != "address_detail"]
        if not real:
            continue
        if {h.type for h in real} == {"affiliation"} and len(grp) == 1:
            continue                                   # 학교 이름 한 줄만 단독 → 노출 아님
        member = [lines[i] for i in grp]
        pad = int(statistics.median(l.bbox.y2 - l.bbox.y1 for l in member) * 0.6)
        u = _union([l.bbox for l in member])
        bbox = BBox(x1=max(0, u.x1 - pad), y1=max(0, u.y1 - pad), x2=min(W, u.x2 + pad), y2=min(H, u.y2 + pad))
        inside = [l.text for l in lines if l.bbox.x1 >= bbox.x1 and l.bbox.x2 <= bbox.x2
                  and l.bbox.y1 >= bbox.y1 and l.bbox.y2 <= bbox.y2]
        label = rules.infer_label(inside, {h.type for h in real})

        items: List[PIIItem] = []
        for h in real:
            b = h.bbox
            if h.type == "address":   # 주소 둘째 줄(동·호)까지 마스킹 범위에 포함
                extra = [d.bbox for d in g_hits if d.type == "address_detail" and d.line_idx == h.line_idx + 1]
                b = _union([b] + extra)
            items.append(PIIItem(type=h.type, value_masked=rules.mask(h.type, h.value),
                                 method="regex" if h.method == "regex" else "rule",
                                 conf=round(h.conf, 3), bbox=b))
        ocr = None
        if debug:
            ocr = OCRResult(engine=ocr_engine, text="\n".join(l.text for l in member),
                            conf=round(statistics.mean(l.conf for l in member), 3), lines=member)
        findings.append(Finding(id=0, label=label, bbox=bbox, det_conf=round(statistics.mean(l.conf for l in member), 3),
                                ocr=ocr, pii=items, risk=_judge(label, bbox, real, member, W, H)))

    for q in qr_dets:
        url = q.code.payload if q.code else None
        pii = [PIIItem(type="url", value_masked=rules.mask("url", url), method="code", conf=1.0)] if url else []
        score = 0.45 if url else 0.1
        reason = (f"{position(q.bbox, W, H)} QR코드를 스캔하면 링크가 열립니다. 예약·주문 정보일 수 있습니다."
                  if url else f"{position(q.bbox, W, H)}에 QR코드가 있습니다.")
        code = q.code.model_copy(update={"payload": rules.mask("url", url) if url else None}) if q.code else None
        findings.append(Finding(id=0, label="qr_barcode", bbox=q.bbox, det_conf=q.det_conf, code=code, pii=pii,
                                risk=Risk(score=score, level=level_of(score),
                                          factors=RiskFactors(type_weight=0.5 if url else 0.1, readability=1.0, area_factor=0.9),
                                          reason=reason)))

    findings.sort(key=lambda f: f.risk.score, reverse=True)
    for i, f in enumerate(findings):
        f.id = i
    return findings
