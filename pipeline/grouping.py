"""문서 인스턴스 단위로 묶기.

책상 위에 내 영수증과 룸메이트 택배 송장이 같이 있을 때, 이름과 주소를
잘못 연결하면 존재하지 않는 사람의 프로필을 만들어내는 셈이 된다.

그래서 결합 설명은 **같은 문서 안에서만** 한다. 판정 근거는 공간적 근접성이다.
단일 연결(single-linkage) 군집화로 텍스트 조각을 뭉치고, 그 뭉치 안에
문서 힌트 어휘가 있으면 문서 인스턴스로 본다.
"""

from __future__ import annotations

from . import kr_patterns as kp
from . import wording
from .types import Box, Finding, GroupNote, Severity, TextSpan

# 이 배수 안쪽이면 같은 종이로 본다. 글자 높이 기준.
LINK_DISTANCE_EM = 2.5

# 결합 설명을 붙일 가치가 있는 조합
COMBINABLE = {
    frozenset({"mobile", "address_road"}),
    frozenset({"mobile", "address_unit"}),
    frozenset({"landline", "address_road"}),
    frozenset({"address_road", "address_unit"}),
    frozenset({"mobile", "email"}),
    frozenset({"name", "mobile"}),
    frozenset({"name", "address_road"}),
    frozenset({"name", "address_unit"}),
}

# 결합 설명에 나올 때의 순서. 집합 순회 순서에 기대지 않는다.
_ORDER = ["name", "mobile", "landline", "email", "address_road", "address_unit"]


def _cluster(spans: list[TextSpan]) -> list[list[int]]:
    n = len(spans)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i in range(n):
        for j in range(i + 1, n):
            bi, bj = spans[i].box, spans[j].box
            threshold = max(bi.h, bj.h, 10) * LINK_DISTANCE_EM
            if bi.distance_to(bj) <= threshold:
                union(i, j)

    buckets: dict[int, list[int]] = {}
    for i in range(n):
        buckets.setdefault(find(i), []).append(i)
    return list(buckets.values())


def _hull(boxes: list[Box]) -> Box:
    x0 = min(b.x for b in boxes)
    y0 = min(b.y for b in boxes)
    x1 = max(b.x + b.w for b in boxes)
    y1 = max(b.y + b.h for b in boxes)
    return Box(x0, y0, x1 - x0, y1 - y0)


def assign_groups(
    spans: list[TextSpan],
    findings: list[Finding],
) -> list[GroupNote]:
    """findings 에 group_id 를 채우고, 결합 설명을 만들어 돌려준다.

    소속은 **조각 번호**로 정한다. 군집 외곽 사각형에 들어가는지로 정하면
    비스듬히 겹쳐 놓인 두 종이의 사각형이 서로를 덮어서, A 종이의 항목이
    B 종이 그룹에 들어간다. 다른 사람의 정보를 묶는 사고가 거기서 난다.
    """
    if not spans:
        return []

    clusters = _cluster(spans)
    cluster_of = {i: idx for idx, ids in enumerate(clusters) for i in ids}
    hulls = [_hull([spans[i].box for i in ids]) for ids in clusters]

    def owner(f: Finding) -> int | None:
        if f.span_index is not None:
            return cluster_of.get(f.span_index)
        if f.box is None:
            return None
        # QR 처럼 OCR 조각에서 나오지 않은 항목. 딱 한 군집 안에 있을 때만 붙인다.
        holders = [k for k, h in enumerate(hulls) if h.expanded(4).contains(f.box)]
        return holders[0] if len(holders) == 1 else None

    members: dict[int, list[Finding]] = {}
    for f in findings:
        k = owner(f)
        if k is not None:
            members.setdefault(k, []).append(f)

    notes: list[GroupNote] = []
    for idx, member_ids in enumerate(clusters):
        group_id = f"g{idx}"
        blob = " ".join(spans[i].text for i in member_ids)
        doc = kp.document_hint(kp.compact(kp.normalize(blob)))

        inside = members.get(idx, [])
        for f in inside:
            f.group_id = group_id
            if doc:
                f.detail["document_hint"] = doc

        # 가릴 필요가 있다고 본 항목끼리만 결합 설명 대상으로 삼는다.
        significant = [f for f in inside if f.severity is not Severity.INFO]
        kinds = {f.kind for f in significant}

        matched: set[str] = set()
        for combo in COMBINABLE:
            if combo <= kinds:
                matched |= combo
        if not matched:
            continue

        ordered = [k for k in _ORDER if k in matched]
        nouns = [wording.KIND_NOUN.get(k, k) for k in ordered]
        notes.append(
            GroupNote(
                group_id=group_id,
                box=_hull([f.box for f in significant if f.kind in matched]),
                kinds=ordered,
                message=wording.combined(doc, nouns),
                severity=Severity.COVER,
            )
        )

    return notes
