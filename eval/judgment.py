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
    python -m eval.judgment --check         # 기준선보다 나빠진 항목이 있으면 실패(CI 가 돌린다)
    python -m eval.judgment --update        # 판단 규칙을 고쳐 좋아졌으면 기준선을 새로 저장
    python -m eval.judgment --dump out.jsonl  # 장면·정답을 파일로(NER 비교 실험용)

기준선(eval/baselines/judgment.json)은 '지금 규칙이 맞히는 개수'다. 규칙을 고친 PR 은
--check 를 통과해야 하고(아무 항목도 나빠지지 않음), 좋아졌으면 --update 결과를 같이 올린다.
"""

from __future__ import annotations

import argparse
import json
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


# 가상 정보 생성기는 촬영 소품(samples.props)과 같이 쓴다
from samples.fake import (BANKS, CITIES, COMPANIES, GIVEN, NAME_LIKE_WORDS, ROADS,  # noqa: E402,F401
                          SCHOOLS, SURN, Fake)


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
    menu = f.pick(NAME_LIKE_WORDS)
    lines = [["누리마트 수원점"], _lv("대표", tel, split), _lv("사업자", brn, split),
             [menu, "4,500"], _lv("카드번호", masked, split), ["카드승인 합계 12,500원"]]
    gold = [Gold(tel, NONE, "유선전화"), Gold(brn, NONE, "사업자번호"), Gold(masked, NONE, "카드번호"),
            Gold(menu, NONE, "이름 같은 낱말")]
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


def ocr_noise(f: Fake, split: bool):
    """라벨에 기호가 끼고 번호 맨 앞 0 이 O 로 읽힌 송장(PaddleOCR·Tesseract 에서 실제로 나온 모양)."""
    n, a, u = f.name(), f.road(), f.unit()
    p = "O" + f.mobile()[1:]
    lines = [_lv("받-는분", n, split), _lv("연락·처", p, split), _lv("배송‧지", f"{a} {u}", split)]
    gold = [Gold(n, COVER, "이름"), Gold(p, COVER, "휴대폰"), Gold(a, COVER, "도로명주소"),
            Gold(u, COVER, "상세주소")]
    return lines, gold


def settings_screen(f: Fake, split: bool):
    """비밀번호·번호 낱말은 있지만 값이 없는 화면. 새 규칙의 오탐 시험용."""
    member = f.tracking()
    lines = [["계정 설정"], ["비밀번호 변경"], ["비밀번호를 입력하세요"], _lv("회원번호", member, split),
             ["우리 집 와이파이 이름 NURI_5G"], ["문의 help@example.org"]]
    gold = [Gold(member, NONE, "긴 숫자"), Gold("help@example.org", NONE, "이메일"),
            Gold("NURI_5G", NONE, "와이파이 이름")]
    return lines, gold


def card_split(f: Fake, split: bool):
    """카드 번호가 4자리씩 따로 읽힌 사진(실물 학생증 겸 체크카드에서 실제로 나온 모양)."""
    c = f.card()
    groups = c.split("-")
    lines = [["NURI CARD", "Check&Debit"], groups, ["VALID", "THRU", f"0{f.r.randint(1, 9)}/2{f.r.randint(6, 9)}"]]
    return lines, [Gold(" ".join(groups), COVER, "카드번호")]


def digit_groups(f: Fake, split: bool):
    """4자리 숫자가 한 줄에 여럿 있지만 카드가 아닌 것(시간표·주문표). Luhn 이 안 맞는 16자리."""
    while True:
        d = "".join(str(f.r.randint(0, 9)) for _ in range(16))
        if not kp.valid_luhn(d):
            break
    groups = [d[i:i + 4] for i in range(0, 16, 4)]
    lines = [["주문 내역"], groups, ["합계 12,500원"]]
    return lines, [Gold(" ".join(groups), NONE, "숫자 묶음")]


def _exp(f: Fake) -> str:
    return f"0{f.r.randint(1, 9)}/2{f.r.randint(6, 9)}"


def card_misread(f: Fake, split: bool):
    """OCR 이 한 자리를 잘못 읽어 Luhn 이 안 맞는 카드 번호. 카드 앞면 단서(VALID THRU)가 옆에 있다."""
    d = list(f.card().replace("-", ""))
    k = f.r.randint(4, 15)
    d[k] = str((int(d[k]) + f.r.randint(1, 8)) % 10)
    groups = ["".join(d[i:i + 4]) for i in range(0, 16, 4)]
    num = groups if split else [" ".join(groups)]
    lines = [["NURI CARD"], num, ["VALID THRU", _exp(f)]]
    return lines, [Gold(" ".join(groups), COVER, "카드번호")]


def card_vertical(f: Fake, split: bool):
    """세로형 카드: 번호가 4자리씩 네 줄, 또는 8자리씩 두 줄로 쌓여 있다."""
    groups = f.card().split("-")
    rows = [[g] for g in groups] if split else [[groups[0], groups[1]], [groups[2], groups[3]]]
    lines = [["NURI", "check"], *rows, ["VALID THRU " + _exp(f)]]
    return lines, [Gold(" ".join(groups), COVER, "카드번호")]


def card_15(f: Fake, split: bool):
    """15자리(4-6-5) 카드 번호."""
    digits = [9] + [f.r.randint(0, 9) for _ in range(13)]
    d = next("".join(map(str, digits + [last])) for last in range(10) if kp.valid_luhn("".join(map(str, digits + [last]))))
    c = f"{d[:4]} {d[4:10]} {d[10:]}"
    lines = [["NURI CARD"], [c], ["VALID THRU", _exp(f)]]
    return lines, [Gold(c, COVER, "카드번호")]


def card_lookalike(f: Fake, split: bool):
    """숫자 몇 개가 닮은 글자로 읽힌 카드 번호(0→O, 1→l, 5→S, 8→B)."""
    c = f.card().replace("-", " ")
    swaps, out, used = {"0": "O", "1": "l", "5": "S", "8": "B"}, [], 0
    for ch in c:
        if ch in swaps and used < 2 and f.r.random() < 0.5:
            out.append(swaps[ch]); used += 1
        else:
            out.append(ch)
    c2 = "".join(out)
    lines = [["NURI CARD"], [c2], ["VALID THRU", _exp(f)]]
    return lines, [Gold(c2, COVER, "카드번호")]


def not_card_numbers(f: Fake, split: bool):
    """카드가 아닌 숫자: 세로로 쌓인 4자리 숫자(Luhn 이 우연히 맞음), '카드승인' 옆 Luhn 안 맞는 주문번호."""
    while True:
        col = [str(f.r.randint(1000, 9999)) for _ in range(4)]
        if kp.valid_luhn("".join(col)):
            break
    while True:
        o = "".join(str(f.r.randint(0, 9)) for _ in range(16))
        if not kp.valid_luhn(o):
            break
    order = " ".join(o[i:i + 4] for i in range(0, 16, 4))
    lines = [["재고 수량"], *[[c] for c in col], _lv("주문번호", order, split), ["카드승인 합계 12,500원"]]
    return lines, [Gold(" ".join(col), NONE, "숫자 묶음"), Gold(order, NONE, "숫자 묶음")]


def student_id_other(f: Fake, split: bool):
    """학교마다 학번 모양이 다르다. 연도로 시작하지 않는 8자리(실물 학생증에서 나온 모양)."""
    n, s = f.name(), f.pick(SCHOOLS)
    sid = f"{f.r.randint(1, 9)}{f.r.choice(['1', '2'])}{f.r.randint(0, 2)}{f.r.randint(10000, 99999)}"
    if sid.startswith(("19", "20")):
        sid = "3" + sid[1:]
    lines = [[s], ["학생증"], [f.pick(["ICT융합대학", "경영대학", "공과대학"])], [n], [sid]]
    return lines, [Gold(n, COVER, "이름"), Gold(sid, REVIEW, "학번")]


HANJA = ["韓瑞潾", "金民秀", "李道敏", "朴志訓", "崔智度", "鄭恩敏", ""]   # "" = OCR 이 한자를 못 읽고 남긴 빈 괄호


def id_card_hanja(f: Fake, split: bool):
    """신분증의 이름 옆에 한자가 괄호로 붙은 모양."""
    n, r, a = f.name(), f.rrn(), f.road()
    h = f.pick(HANJA)
    lines = [["주민등록증"], [f"{n} ({h})" if h else f"{n}()"], [r], [a]]
    return lines, [Gold(n, COVER, "이름"), Gold(r, COVER, "주민번호"), Gold(a, COVER, "도로명주소")]


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
    "OCR 잡음": ocr_noise,
    "설정 화면": settings_screen,
    "카드(번호 나뉨)": card_split,
    "숫자 묶음": digit_groups,
    "학생증(학번 모양 다름)": student_id_other,
    "신분증(한자 이름)": id_card_hanja,
    "카드(한 자리 잘못 읽힘)": card_misread,
    "카드(세로로 쌓임)": card_vertical,
    "카드(15자리)": card_15,
    "카드(닮은 글자)": card_lookalike,
    "카드 아닌 숫자": not_card_numbers,
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
            if fd.span_index is None:
                continue
            parts = fd.detail.get("span_indices") or [fd.span_index]
            if gk not in _key("".join(spans[k].text for k in parts)):
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


def run(scenes: list[Scene], unlabeled_names: str = "context") -> list[dict]:
    """unlabeled_names 는 환경변수와 상관없이 고정한다. 기준선이 실행 환경에 따라 달라지면 안 된다."""
    rows = []
    for sc in scenes:
        spans = sc.spans()
        findings = context.evaluate(spans, unlabeled_names=unlabeled_names)
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


BASELINE = Path(__file__).resolve().parent / "baselines" / "judgment.json"


def snapshot(rows: list[dict]) -> dict:
    """기준선에 저장할 것: 항목·등급별 (맞음, 전체)와 잘못 가림 수. 문자열은 저장하지 않는다."""
    table: dict[str, list[int]] = {}
    for r in rows:
        key = f"{r['expect']}|{r['item']}"
        ok, total = table.get(key, [0, 0])
        table[key] = [ok + (r["verdict"] == "맞음"), total + 1]
    return {
        "items": dict(sorted(table.items())),
        "false_cover": sum(r["expect"] == NONE and r["got"] == COVER for r in rows),
        "summary": summarize(rows),
    }


def check(rows: list[dict], baseline_path: Path = BASELINE) -> list[str]:
    """기준선보다 나빠진 점. 빈 목록이면 통과."""
    if not baseline_path.exists():
        return [f"기준선 파일이 없습니다: {baseline_path} (python -m eval.judgment --update)"]
    base = json.loads(baseline_path.read_text(encoding="utf-8"))
    now = snapshot(rows)
    problems = []
    if set(base["items"]) != set(now["items"]) or any(
            base["items"][k][1] != now["items"][k][1] for k in now["items"] if k in base["items"]):
        problems.append("정답 세트가 기준선과 다릅니다. 장면 틀이나 정답을 일부러 바꿨다면 --update 로 기준선을 새로 저장하세요.")
        return problems
    for k, (ok, total) in now["items"].items():
        was = base["items"][k][0]
        if ok < was:
            expect, item = k.split("|", 1)
            problems.append(f"[{expect}] {item}: 맞음 {was} → {ok} (전체 {total})")
    if now["false_cover"] > base["false_cover"]:
        problems.append(f"잘못 가림 {base['false_cover']} → {now['false_cover']}")
    return problems


def improvements(rows: list[dict], baseline_path: Path = BASELINE) -> list[str]:
    if not baseline_path.exists():
        return []
    base = json.loads(baseline_path.read_text(encoding="utf-8"))["items"]
    out = []
    for k, (ok, total) in snapshot(rows)["items"].items():
        if k in base and ok > base[k][0]:
            expect, item = k.split("|", 1)
            out.append(f"[{expect}] {item}: 맞음 {base[k][0]} → {ok} (전체 {total})")
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m eval.judgment")
    ap.add_argument("--all", action="store_true", help="틀린 사례 전부 보기")
    ap.add_argument("--dump", help="장면·정답을 JSONL 로 저장")
    ap.add_argument("--json", help="채점 결과를 JSON 으로 저장")
    ap.add_argument("--check", action="store_true", help="기준선보다 나빠지면 종료 코드 1")
    ap.add_argument("--update", action="store_true", help="지금 결과를 기준선으로 저장")
    ap.add_argument("--quiet", action="store_true", help="요약 표 없이 검사 결과만")
    ap.add_argument("--unlabeled-names", default="context", choices=["off", "context", "all"],
                    help="라벨 없는 이름 판단(D-12 비교용). 기준선은 context 로만 잰다")
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
    if a.unlabeled_names != "context" and (a.check or a.update):
        raise SystemExit("기준선은 --unlabeled-names context 로만 잽니다.")
    rows = run(scenes, a.unlabeled_names)
    if not a.quiet:
        report(rows, show_all=a.all)
    if a.json:
        Path(a.json).write_text(json.dumps({"summary": summarize(rows), "rows": rows},
                                           ensure_ascii=False, indent=1), encoding="utf-8")
    if a.update:
        BASELINE.parent.mkdir(exist_ok=True)
        BASELINE.write_text(json.dumps(snapshot(rows), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"\n기준선을 저장했습니다: {BASELINE.relative_to(BASELINE.parents[2])}")
    elif a.check:
        problems = check(rows)
        better = improvements(rows)
        print("\n── 기준선 비교")
        for line in better:
            print(f"  좋아짐  {line}")
        for line in problems:
            print(f"  나빠짐  {line}")
        if problems:
            print("판단 규칙이 기준선보다 나빠졌습니다. 의도한 변경이면 이유를 PR 에 쓰고 --update 하세요.")
            raise SystemExit(1)
        print("  통과" + (" — 좋아진 항목이 있으니 --update 로 기준선을 올려 주세요." if better else " (변화 없음)"))


if __name__ == "__main__":
    main()
