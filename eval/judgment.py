"""판단 평가 — OCR 이 글자를 **완벽하게 읽었다고 가정**하고, 판단만 잰다.

사진 실험은 '못 읽음'과 '잘못 판단함'이 섞여서 어디를 고쳐야 할지 모른다.
여기서는 OCR 결과처럼 생긴 가상 텍스트 장면을 만들어 판단 코드에 바로 넣는다.
그래서 여기서 나온 실패는 전부 **판단 실패**다.

  - 정답 기준: docs/MASKING_CRITERIA.md (팀 합의 전 초안)
  - 데이터: 전부 가상. 이름은 흔한 성씨 + 이름 글자를 섞고, 번호는 무작위,
    메일은 example.com, 카드는 실제 카드사에 없는 9로 시작하는 번호다.
  - 주의: 이 숫자는 "판단 규칙이 어디서 막히는지" 보는 용도다. 장면은 사람이
    만든 틀이라 실사 OCR 결과보다 깨끗하다. 발표 숫자는 실사로 다시 잰다.

사용법:
    python -m eval.judgment                 # 요약 + 실패 사례
    python -m eval.judgment --all           # 실패 사례 전부
    python -m eval.judgment --dump out.jsonl  # 장면·정답을 파일로(NER 비교 실험용)
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import context  # noqa: E402
from pipeline import kr_patterns as kp  # noqa: E402
from pipeline.types import Box, Severity, TextSpan  # noqa: E402

COVER, REVIEW, NONE = "cover", "review", "none"
RANK = {NONE: 0, "info": 0, REVIEW: 1, COVER: 2}


@dataclass
class Gold:
    text: str        # 장면 안의 문자열 그대로
    expect: str      # cover / review / none
    item: str        # 기준표의 항목 이름(이름, 휴대폰, 계좌 ...)


@dataclass
class Scene:
    sid: str
    category: str
    lines: list[list[str]]        # 줄마다 OCR 조각들
    gold: list[Gold] = field(default_factory=list)

    def spans(self) -> list[TextSpan]:
        out = []
        for row, parts in enumerate(self.lines):
            x = 40
            for text in parts:
                w = max(22 * len(text), 30)
                out.append(TextSpan(text, Box(x, 40 + 60 * row, w, 30), 0.95))
                x += w + 40
        return out


# ------------------------------------------------------------- 가상 정보

SURN = "김이박최정강조윤장임한오서신권황안송"
GIVEN = "민서지현우준수연하은도윤예성진유아원호영"
ROADS = ["가온로", "누리로", "한빛로", "새솔길", "다온로", "푸른숲길", "별빛로", "이음로"]
CITIES = [("수원시", "팔달구"), ("용인시", "기흥구"), ("화성시", "동탄구"), ("성남시", "분당구"),
          ("서울특별시", "마포구"), ("안양시", "동안구")]
SCHOOLS = ["한빛대학교", "누리대학교", "다온대학교"]
COMPANIES = ["누리전자", "가온물산", "한빛시스템"]
BANKS = ["국민", "신한", "우리", "하나", "농협"]
# 이름처럼 생긴(흔한 성씨로 시작하는 2~4글자) 일반 낱말. 오탐 시험용
NAME_LIKE_WORDS = ["김밥나라", "정성식당", "조은약국", "한우리", "강남역", "박하사탕", "이마트",
                   "최고급", "장보기", "임대문의", "오늘특가", "신상품"]


class Fake:
    def __init__(self, seed: int):
        self.r = random.Random(seed)

    def name(self) -> str:
        return self.r.choice(SURN) + self.r.choice(GIVEN) + self.r.choice(GIVEN)

    def mobile(self) -> str:
        return f"010-{self.r.randint(2000, 9999)}-{self.r.randint(1000, 9999)}"

    def landline(self) -> str:
        return f"031-{self.r.randint(200, 999)}-{self.r.randint(1000, 9999)}"

    def road(self) -> str:
        city, gu = self.r.choice(CITIES)
        return f"{city} {gu} {self.r.choice(ROADS)} {self.r.randint(3, 280)}"

    def unit(self) -> str:
        return f"{self.r.randint(101, 115)}동 {self.r.randint(1, 25)}{self.r.randint(1, 4):02d}호"

    def rrn(self) -> str:
        while True:
            yy, mm, dd = self.r.randint(80, 99), self.r.randint(1, 12), self.r.randint(1, 28)
            body = f"{yy:02d}{mm:02d}{dd:02d}{self.r.choice('12')}{self.r.randint(0, 99999):05d}"
            w = [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5]
            check = (11 - sum(int(body[i]) * w[i] for i in range(12)) % 11) % 10
            full = body + str(check)
            if kp.valid_rrn(full):
                return f"{full[:6]}-{full[6:]}"

    def card(self) -> str:
        digits = [9] + [self.r.randint(0, 9) for _ in range(14)]
        for last in range(10):
            d = "".join(map(str, digits + [last]))
            if kp.valid_luhn(d):
                return "-".join(d[i:i + 4] for i in range(0, 16, 4))
        raise AssertionError

    def account(self) -> str:
        return f"{self.r.randint(100, 999)}-{self.r.randint(100000, 999999)}-{self.r.randint(10, 99)}-{self.r.randint(100, 999)}"

    def tracking(self) -> str:
        return "".join(str(self.r.randint(0, 9)) for _ in range(12))

    def brn(self) -> str:
        while True:
            d = "".join(str(self.r.randint(0, 9)) for _ in range(10))
            if kp.valid_brn(d):
                return f"{d[:3]}-{d[3:5]}-{d[5:]}"

    def email(self) -> str:
        return f"{self.r.choice(['minsu', 'jiyoon', 'hana', 'dohyun'])}{self.r.randint(10, 99)}@example.com"

    def pick(self, seq):
        return self.r.choice(seq)


# ------------------------------------------------------------- 장면 틀
# 각 틀은 (줄 목록, 정답 목록) 을 만든다. split=True 면 '라벨 | 값' 을 다른 조각으로
# (PaddleOCR 처럼), False 면 한 조각으로(Tesseract 처럼) 둔다.

def _lv(label: str, value: str, split: bool) -> list[str]:
    return [label, value] if split else [f"{label} {value}"]


def waybill_labeled(f: Fake, split: bool):
    n, p, a, u, t = f.name(), f.mobile(), f.road(), f.unit(), f.tracking()
    lines = [_lv("받는분", n, split), _lv("연락처", p, split), _lv("주소", f"{a} {u}", split),
             _lv("운송장번호", t, split), ["고객센터 1588-1255"]]
    gold = [Gold(n, COVER, "이름"), Gold(p, COVER, "휴대폰"), Gold(a, COVER, "도로명주소"),
            Gold(u, COVER, "상세주소"), Gold(t, REVIEW, "운송장번호"), Gold("1588-1255", NONE, "대표번호")]
    return lines, gold


def waybill_unlabeled(f: Fake, split: bool):
    """라벨 칸이 찢기거나 접혀서 값만 보이는 송장."""
    n, p, a, u = f.name(), f.mobile(), f.road(), f.unit()
    lines = [[n], [p], [a], [u]]
    gold = [Gold(n, COVER, "이름"), Gold(p, COVER, "휴대폰"), Gold(a, REVIEW, "도로명주소"),
            Gold(u, COVER, "상세주소")]
    return lines, gold


def name_tag(f: Fake, split: bool):
    n, c = f.name(), f.pick(COMPANIES)
    lines = [[f"{c} 영업팀"], [n]]
    return lines, [Gold(n, COVER, "이름")]


def student_id(f: Fake, split: bool):
    n, s = f.name(), f.pick(SCHOOLS)
    sid = f"20{f.r.randint(19, 25)}{f.r.randint(1000, 9999)}"
    if split:
        lines = [[s], ["학생증"], [n], [f"학번 {sid}"]]
    else:
        lines = [[s], ["학생증"], ["성명", n], ["학번", sid]]
    return lines, [Gold(n, COVER, "이름"), Gold(sid, COVER, "학번")]


def messenger(f: Fake, split: bool):
    n, p, a, u = f.name(), f.mobile(), f.road(), f.unit()
    lines = [[f"{n}님 택배 경비실에 맡겨두었습니다"], [f"제 번호 {p}로 연락주세요"],
             [f"주소는 {a} {u}입니다"], ["오후 3:12"]]
    gold = [Gold(n, REVIEW, "이름"), Gold(p, COVER, "휴대폰"), Gold(a, COVER, "도로명주소"),
            Gold(u, COVER, "상세주소")]
    return lines, gold


def memo(f: Fake, split: bool):
    n, acc, bank = f.name(), f.account(), f.pick(BANKS)
    pin = f"{f.r.randint(1000, 9999)}*"
    pw = f"nuri{f.r.randint(1000, 9999)}!"
    lines = [_lv("현관 비밀번호", pin, split), _lv("와이파이 비번", pw, split),
             [f"월세 {bank} {acc}"], _lv("예금주", n, split)]
    gold = [Gold(pin, COVER, "비밀번호"), Gold(pw, COVER, "비밀번호"), Gold(acc, COVER, "계좌번호"),
            Gold(n, COVER, "이름")]
    return lines, gold


def receipt(f: Fake, split: bool):
    tel, brn = f.landline(), f.brn()
    masked = f"9410-12**-****-{f.r.randint(1000, 9999)}"
    lines = [["누리마트 수원점"], _lv("대표", tel, split), _lv("사업자", brn, split),
             _lv("카드번호", masked, split), ["합계 12,500원"]]
    gold = [Gold(tel, NONE, "유선전화"), Gold(brn, NONE, "사업자번호"), Gold(masked, NONE, "카드번호")]
    return lines, gold


def store_sign(f: Fake, split: bool):
    w1, w2 = f.r.sample(NAME_LIKE_WORDS, 2)
    tel, mob = f.landline(), f.mobile()
    lines = [[w1], _lv("예약문의", tel, split), [w2], _lv("배달문의", mob, split)]
    gold = [Gold(w1, NONE, "이름 같은 낱말"), Gold(tel, NONE, "유선전화"),
            Gold(w2, NONE, "이름 같은 낱말"), Gold(mob, NONE, "휴대폰")]
    return lines, gold


def mail_screen(f: Fake, split: bool):
    n, e = f.name(), f.email()
    lines = [_lv("보낸사람", n, split), [e], ["고객센터 help@example.org"], ["제목: 견적 요청드립니다"]]
    gold = [Gold(n, COVER, "이름"), Gold(e, COVER, "이메일"), Gold("help@example.org", NONE, "이메일")]
    return lines, gold


def id_card(f: Fake, split: bool):
    n, r, a = f.name(), f.rrn(), f.road()
    lines = [["주민등록증"], [n], [r], [a], ["수원시장"]]
    gold = [Gold(n, COVER, "이름"), Gold(r, COVER, "주민번호"), Gold(a, COVER, "도로명주소")]
    return lines, gold


def card_photo(f: Fake, split: bool):
    c, n = f.card(), f.name()
    lines = [["NURI CARD"], [c], [n]]
    return lines, [Gold(c, COVER, "카드번호"), Gold(n, COVER, "이름")]


TEMPLATES = {
    "송장(라벨 있음)": waybill_labeled,
    "송장(라벨 없음)": waybill_unlabeled,
    "명찰": name_tag,
    "학생증": student_id,
    "메신저 캡처": messenger,
    "메모·포스트잇": memo,
    "영수증": receipt,
    "간판·전단": store_sign,
    "메일 화면": mail_screen,
    "신분증": id_card,
    "카드": card_photo,
}


def build(per_template: int = 14, seed: int = 20261101) -> list[Scene]:
    scenes = []
    for t_i, (cat, fn) in enumerate(TEMPLATES.items()):
        for k in range(per_template):
            f = Fake(seed + t_i * 1000 + k)
            lines, gold = fn(f, split=bool(k % 2))
            scenes.append(Scene(f"{t_i:02d}-{k:02d}", cat, lines, gold))
    return scenes


# ------------------------------------------------------------- 채점

def _key(s: str) -> str:
    return re.sub(r"[\s\-]", "", kp.normalize(s or ""))


def predict(scene: Scene, spans: list[TextSpan], findings) -> list[tuple[Gold, str, list]]:
    """정답 항목마다 판단 코드가 준 가장 높은 등급과, 그 근거가 된 탐지들."""
    out = []
    for g in scene.gold:
        gk = _key(g.text)
        hits = []
        for fd in findings:
            if fd.span_index is None or gk not in _key(spans[fd.span_index].text):
                continue
            ek = _key(fd.evidence_text)
            if not ek or ek in gk or gk in ek:
                hits.append(fd)
        sev = max((fd.severity.value for fd in hits), key=lambda v: RANK[v], default=NONE)
        out.append((g, NONE if sev == "info" else sev, hits))
    return out


def verdict(expect: str, got: str) -> str:
    if expect == COVER:
        return {COVER: "맞음", REVIEW: "약함(확인 필요로만)", NONE: "놓침"}[got]
    if expect == REVIEW:
        return {COVER: "과함(가림까지)", REVIEW: "맞음", NONE: "놓침"}[got]
    return {COVER: "오탐(가림)", REVIEW: "오탐(확인 필요)", NONE: "맞음"}[got]


def run(scenes: list[Scene]) -> list[dict]:
    rows = []
    for sc in scenes:
        spans = sc.spans()
        findings = context.evaluate(spans)
        for g, got, hits in predict(sc, spans, findings):
            rows.append({
                "scene": sc.sid, "category": sc.category, "item": g.item, "text": g.text,
                "expect": g.expect, "got": got, "verdict": verdict(g.expect, got),
                "kinds": sorted({h.kind for h in hits}),
            })
    return rows


def summarize(rows: list[dict]) -> dict:
    """놓침률·오탐률. 가림 정답 중 가림으로 못 올린 비율, 무시 정답 중 올린 비율."""
    cov = [r for r in rows if r["expect"] == COVER]
    rev = [r for r in rows if r["expect"] == REVIEW]
    neg = [r for r in rows if r["expect"] == NONE]
    pct = lambda a, b: round(100 * a / b, 1) if b else 0.0  # noqa: E731
    return {
        "items": len(rows),
        "cover_total": len(cov),
        "cover_hit": pct(sum(r["got"] == COVER for r in cov), len(cov)),
        "cover_weak": pct(sum(r["got"] == REVIEW for r in cov), len(cov)),
        "cover_miss": pct(sum(r["got"] == NONE for r in cov), len(cov)),
        "review_total": len(rev),
        "review_ok": pct(sum(r["got"] != NONE for r in rev), len(rev)),
        "none_total": len(neg),
        "false_cover": pct(sum(r["got"] == COVER for r in neg), len(neg)),
        "false_review": pct(sum(r["got"] == REVIEW for r in neg), len(neg)),
    }


def report(rows: list[dict], show_all: bool = False) -> None:
    s = summarize(rows)
    print(f"장면 {len({r['scene'] for r in rows})}개, 정답 항목 {s['items']}개 (가상 데이터, OCR 은 완벽하다고 가정)\n")
    print(f"가려야 할 것 {s['cover_total']}개 → 가림 {s['cover_hit']}%  "
          f"확인 필요로만 {s['cover_weak']}%  놓침 {s['cover_miss']}%")
    print(f"확인 필요 정답 {s['review_total']}개 → 잡음 {s['review_ok']}%")
    print(f"가리면 안 될 것 {s['none_total']}개 → 잘못 가림 {s['false_cover']}%  "
          f"잘못 확인 요청 {s['false_review']}%\n")

    print("항목별 (맞음 / 전체, 틀린 이유)")
    by_item = defaultdict(list)
    for r in rows:
        by_item[(r["item"], r["expect"])].append(r)
    for (item, expect), rs in sorted(by_item.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        ok = sum(r["verdict"] == "맞음" for r in rs)
        bad = Counter(r["verdict"] for r in rs if r["verdict"] != "맞음")
        why = ", ".join(f"{k} {v}" for k, v in bad.most_common())
        print(f"  [{expect:<6}] {item:<10} {ok:>3}/{len(rs):<3} {why}")

    print("\n장면 종류별 (맞음 / 전체)")
    by_cat = defaultdict(list)
    for r in rows:
        by_cat[r["category"]].append(r)
    for cat, rs in by_cat.items():
        print(f"  {cat:<12} {sum(r['verdict'] == '맞음' for r in rs):>3}/{len(rs)}")

    bad = [r for r in rows if r["verdict"] != "맞음"]
    seen, shown = set(), []
    for r in bad:  # 같은 (항목, 장면 종류, 판정)은 한 번만
        key = (r["item"], r["category"], r["verdict"])
        if show_all or key not in seen:
            seen.add(key)
            shown.append(r)
    print(f"\n틀린 사례 {len(bad)}개 중 {'전부' if show_all else '유형별 1개씩'}")
    for r in shown:
        print(f"  {r['category']:<12} {r['item']:<10} '{r['text']}' 정답 {r['expect']} → "
              f"{r['got']} ({r['verdict']}) {r['kinds'] or ''}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m eval.judgment")
    ap.add_argument("--all", action="store_true", help="틀린 사례 전부 보기")
    ap.add_argument("--dump", help="장면·정답을 JSONL 로 저장")
    ap.add_argument("--json", help="채점 결과를 JSON 으로 저장")
    a = ap.parse_args(argv)
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    scenes = build()
    if a.dump:
        with open(a.dump, "w", encoding="utf-8") as fp:
            for sc in scenes:
                fp.write(json.dumps({"id": sc.sid, "category": sc.category, "lines": sc.lines,
                                     "gold": [g.__dict__ for g in sc.gold]}, ensure_ascii=False) + "\n")
    rows = run(scenes)
    report(rows, show_all=a.all)
    if a.json:
        Path(a.json).write_text(json.dumps({"summary": summarize(rows), "rows": rows},
                                           ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
