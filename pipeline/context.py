"""주변 문구를 보고 심각도를 정한다.

같은 '010-1234-5678' 이라도 '수취인' 옆에 있으면 개인 연락처이고
'고객센터' 옆에 있으면 공개 번호다. 정규식만으로는 이 둘을 구분할 수 없고,
구분하지 못하면 오탐이 쌓여 사용자가 사진 세 장 만에 서비스를 끈다.

Presidio 가 독일 우편번호를 다루는 방식이 같은 발상이다. 패턴만으로는
오탐 위험이 커서 주소 문맥 단어가 함께 있을 때만 신뢰하고, 기본 신뢰도를
아주 낮게 둔다.
"""

from __future__ import annotations

from . import kr_patterns as kp
from . import wording
from .layout import layout
from .types import Certainty, Finding, Severity, TextSpan

# 주변 문구를 찾을 반경. 글자 높이의 배수로 잡아야 해상도에 안 휘둘린다.
CONTEXT_RADIUS_EM = 6.0

# 개인 쪽·공개 쪽 단어가 둘 다 반경 안에 있을 때, 한쪽이 다른 쪽 거리의
# 이 비율 이하로 가까우면 그쪽으로 판정한다. 비슷하면 검토 권장으로 남긴다.
CLEARLY_CLOSER = 0.5

# 문맥이 전혀 없을 때의 기본 심각도
DEFAULT_SEVERITY = {
    "rrn": Severity.COVER,
    # 체크섬이 안 맞는 주민번호 형식. 2020.10 이후 발급분일 수 있어 버리지 않되
    # 운송장번호일 수도 있으니 문맥 없이는 검토 권장에 둔다.
    "rrn_unverified": Severity.REVIEW,
    "card": Severity.COVER,
    "mobile": Severity.REVIEW,
    "landline": Severity.REVIEW,
    "email": Severity.REVIEW,
    "address_road": Severity.REVIEW,
    "address_unit": Severity.COVER,
    "plate": Severity.REVIEW,
    # 공개 번호 대역은 문맥과 무관하게 개인정보가 아니다
    "service_line": Severity.INFO,
    "tollfree": Severity.INFO,
    # 사업자등록번호는 공개 정보다
    "brn": Severity.INFO,
    # 정체를 확정할 수 없는 숫자. 절대 올려 잡지 않는다
    "long_digits": Severity.INFO,
}

# 문맥과 무관하게 심각도를 고정할 항목
CONTEXT_IMMUNE = {"service_line", "tollfree", "brn", "long_digits", "rrn", "card"}


# '같은 줄', '왼쪽', '윗줄', 거리는 전부 글줄 좌표계(layout.py)로 잰다.
# 송장이 기울어도 0° 와 같은 기준이 되게. 외곽선이 없으면 화면 가로·세로 그대로다.

def _nearby(index: int, spans: list[TextSpan]) -> list[tuple[int, float]]:
    """반경 안의 (조각 번호, 거리)."""
    lay = layout(spans)
    radius = max(lay.thickness(index), 12) * CONTEXT_RADIUS_EM
    out = []
    for j in range(len(spans)):
        if j != index:
            d = lay.distance(index, j)
            if d <= radius:
                out.append((j, d))
    return out


def _words_in(text: str) -> tuple[list[str], list[str]]:
    """한 조각 안의 (개인 쪽 단어, 공개 쪽 단어).

    - 공백을 다 빼고 비교한다. Tesseract 는 '연락처'를 '연 락 처'로 준다.
    - 공개 쪽 단어 안에 들어 있는 개인 쪽 단어('대표전화' 속 '전화')는
      개인 신호로 세지 않는다.
    """
    blob = kp.compact(kp.normalize(text))
    public = [w for w in kp.CONTEXT_PUBLIC if kp.compact(w) in blob]
    rest = blob
    for w in sorted(public, key=len, reverse=True):
        rest = rest.replace(kp.compact(w), "|")
    personal = [w for w in kp.CONTEXT_PERSONAL if kp.compact(w) in rest]
    return personal, public


def _context_words(
    index: int, spans: list[TextSpan], hit_text: str
) -> tuple[dict[str, float], dict[str, float]]:
    """반경 안의 (개인 쪽 단어 → 거리, 공개 쪽 단어 → 거리). 거리는 가장 가까운 것.

    자기 조각도 본다(거리 0). 다만 탐지된 문자열 자체는 빼고 본다.
    """
    own = kp.normalize(spans[index].text).replace(hit_text, " ", 1)
    sources = [(own, 0.0)] + [(spans[j].text, d) for j, d in _nearby(index, spans)]

    personal: dict[str, float] = {}
    public: dict[str, float] = {}
    for text, dist in sources:
        found_personal, found_public = _words_in(text)
        for w in found_personal:
            personal[w] = min(dist, personal.get(w, dist))
        for w in found_public:
            public[w] = min(dist, public.get(w, dist))
    return personal, public


def _ends_with_context_word(text: str) -> tuple[str, str] | None:
    """조각이 문맥 어휘로 끝나는가. ('연락처', 'personal') / ('고객센터', 'public').

    겹치면 긴 쪽이 이긴다. '대표전화'는 '전화'로도 끝나지만 공개 쪽이다.
    """
    flat = kp.compact(kp.normalize(text)).rstrip(":：.#")
    hits = [(kp.compact(w), w, "personal") for w in kp.CONTEXT_PERSONAL]
    hits += [(kp.compact(w), w, "public") for w in kp.CONTEXT_PUBLIC]
    matched = [(len(c), w, side) for c, w, side in hits if flat.endswith(c)]
    if not matched:
        return None
    _, word, side = max(matched)
    return word, side


def _line_label(index: int, spans: list[TextSpan], hit_text: str) -> tuple[str, str] | None:
    """같은 줄 바로 왼쪽의 라벨. 서류는 거의 '라벨: 값' 꼴이라 가장 강한 신호다.

    같은 조각 안에서 값 바로 앞(Tesseract 가 '받는분 010-…' 을 한 줄로 합칠 때),
    또는 같은 줄 왼쪽의 가장 가까운 조각(PaddleOCR 가 따로 줄 때).
    """
    own = kp.normalize(spans[index].text)
    cut = own.find(hit_text)
    if cut > 0:
        label = _ends_with_context_word(own[:cut])
        if label:
            return label
    for j in _left_neighbors(index, spans):
        label = _ends_with_context_word(spans[j].text)
        if label:
            return label
        break  # 바로 왼쪽 조각이 라벨이 아니면 더 멀리 가지 않는다
    return None


def _starts_with_context_word(text: str) -> tuple[str, str] | None:
    """조각이 문맥 어휘로 시작하는가. Tesseract 가 '배송지 서울…' 을 한 줄로 합친 경우,
    또는 조각 자체가 라벨('받 는 분')인 경우."""
    flat = kp.compact(kp.normalize(text))
    hits = [(kp.compact(w), w, "personal") for w in kp.CONTEXT_PERSONAL]
    hits += [(kp.compact(w), w, "public") for w in kp.CONTEXT_PUBLIC]
    matched = [(len(c), w, side) for c, w, side in hits if flat.startswith(c)]
    if not matched:
        return None
    _, word, side = max(matched)
    return word, side


def _line_above(index: int, spans: list[TextSpan]) -> int | None:
    """바로 윗줄에 왼쪽 정렬로 붙어 있는 조각. 여러 줄로 이어지는 값의 윗줄이다.

    '배송지  서울특별시 강남구 권선로 208
            130동 1343호'          ← 이 줄의 윗줄
    """
    return layout(spans).line_above(index)


def _inherited_label(index: int, spans: list[TextSpan], depth: int = 0) -> tuple[str, str] | None:
    """윗줄의 라벨을 이어받는다. 주소 둘째 줄(동·호수)처럼 자기 라벨이 없는 줄.

    윗줄이 라벨로 시작하거나('배송지 서울…', 조각 자체가 '받는분'), 윗줄의 같은 줄
    왼쪽에 라벨이 있으면 그것. 윗줄도 이어지는 줄이면 세 줄까지 거슬러 올라간다.
    """
    j = _line_above(index, spans)
    if j is None:
        return None
    label = _starts_with_context_word(spans[j].text)
    if label:
        return label
    for k in _left_neighbors(j, spans):
        label = _ends_with_context_word(spans[k].text)
        if label:
            return label
        break
    if depth < 2:
        return _inherited_label(j, spans, depth + 1)
    return None


def _left_neighbors(index: int, spans: list[TextSpan]) -> list[int]:
    """같은 줄, 읽는 방향으로 바로 앞(왼쪽)에 있는 조각 번호. 가까운 것부터."""
    return layout(spans).left_neighbors(index)


def _dedupe(words: list[str]) -> list[str]:
    """'받는분'과 '받는 분'처럼 공백만 다른 어휘는 하나로."""
    seen, out = set(), []
    for w in words:
        key = kp.compact(w)
        if key not in seen:
            seen.add(key)
            out.append(w)
    return out


def _certainty_from_ocr(conf: float) -> Certainty:
    if conf >= 0.75:
        return Certainty.READ
    if conf >= 0.45:
        return Certainty.PARTIAL
    return Certainty.REGION_ONLY


def _region_only(kind: str, span: TextSpan, index: int) -> Finding:
    """못 읽은 글자는 절대 내용으로 내보내지 않는다."""
    return Finding(
        kind=kind,
        box=span.box,
        certainty=Certainty.REGION_ONLY,
        severity=Severity.REVIEW,
        message=wording.region_only(None),
        evidence_text=None,
        span_index=index,
    )


# ------------------------------------------------------------------ 이름

def _label_at_end(text: str, labels: list[str] | None = None) -> str | None:
    """조각이 라벨로 끝나는가. '받 는 분 :', '운송장 No.' 같은 형태도 받는다."""
    flat = kp.compact(kp.normalize(text)).rstrip(":：.#")
    if flat.lower().endswith("no"):
        flat = flat[:-2].rstrip(":：.#")
    return next((w for w in (labels or kp.NAME_LABELS) if flat.endswith(w)), None)


def _left_label(
    index: int, spans: list[TextSpan], labels: list[str] | None = None
) -> str | None:
    """같은 줄 왼쪽 가까이에 라벨 조각이 있는가."""
    for j in _left_neighbors(index, spans):
        label = _label_at_end(spans[j].text, labels)
        if label:
            return label
    return None


def _tracking_label(index: int, spans: list[TextSpan], hit_text: str) -> str | None:
    """긴 숫자 바로 앞(같은 조각 또는 같은 줄 왼쪽 조각)에 운송장 라벨이 있는가.

    '운송장번호909266858784' 처럼 붙어 나오는 일이 흔하다(PaddleOCR).
    라벨이 없으면 운송장번호라고 부르지 않는다. 회원번호·계좌번호일 수 있다.
    """
    own = kp.normalize(spans[index].text)
    cut = own.find(hit_text)
    if cut > 0:
        label = _label_at_end(own[:cut], kp.TRACKING_LABELS)
        if label:
            return label
    return _left_label(index, spans, kp.TRACKING_LABELS)


def _judge(
    index: int, spans: list[TextSpan], hit_text: str, kind: str, default: Severity
) -> tuple[Severity, str, list[str], list[str]]:
    """문맥으로 심각도를 정한다. (심각도, 문구, 개인 쪽 단어, 공개 쪽 단어)

    1. 같은 줄 바로 왼쪽 라벨이 있으면 그것으로 정한다.
       '연락처 010-…' → 가림 권장, '고객센터 1588-…' → 참고.
       멀리 있는 다른 단어는 보지 않는다.
       자기 라벨이 없는 줄은 바로 윗줄(왼쪽 정렬)의 라벨을 이어받는다.
       주소 둘째 줄(동·호수), 라벨이 값 위에 있는 서식('받는 분' 아래 이름).
    2. 없으면 반경 안의 단어를 본다.
       한쪽만 있으면 그쪽, 둘 다 있으면 확실히 가까운 쪽(CLEARLY_CLOSER),
       거리가 비슷하면 검토 권장. 단정하지 않는다.
    """
    line = _line_label(index, spans, hit_text) or _inherited_label(index, spans)
    if line:
        word, side = line
        if side == "personal":
            return Severity.COVER, wording.found(kind, near=word), [word], []
        return Severity.INFO, wording.found_public(kind, near=word), [], [word]

    personal, public = _context_words(index, spans, hit_text)
    by_dist = lambda d: sorted(d, key=lambda w: (d[w], -len(w)))  # noqa: E731
    near_p, near_q = by_dist(personal), by_dist(public)
    words_p, words_q = _dedupe(near_p), near_q

    if public and not personal:
        return Severity.INFO, wording.found_public(kind, near=near_q[0]), words_p, words_q
    if personal and not public:
        return Severity.COVER, wording.found(kind, near=near_p[0]), words_p, words_q
    if personal and public:
        dp, dq = personal[near_p[0]], public[near_q[0]]
        if dp < dq and dp <= CLEARLY_CLOSER * dq:
            return Severity.COVER, wording.found(kind, near=near_p[0]), words_p, words_q
        if dq < dp and dq <= CLEARLY_CLOSER * dp:
            return Severity.INFO, wording.found_public(kind, near=near_q[0]), words_p, words_q
        # 양쪽 신호가 비슷하게 가까우면 올려 잡되 단정하지 않는다.
        return Severity.REVIEW, wording.found(kind, near=near_p[0]), words_p, words_q
    return default, wording.found(kind), [], []


def find_names(spans: list[TextSpan]) -> list[Finding]:
    """이름 라벨 바로 뒤의 2~4글자 한글 중 흔한 성씨로 시작하는 것.

    라벨 없이 아무 한글 낱말을 이름으로 잡으면 오탐만 쌓인다.
    """
    findings: list[Finding] = []
    for i, span in enumerate(spans):
        text = kp.normalize(span.text)
        token, label = None, None

        m = kp.RE_NAME_INLINE.search(text)
        if m and kp.looks_like_name(m.group(1)):
            token = m.group(1)
            label = next(w for w in kp.NAME_LABELS if w in m.group(0))
        else:
            flat = kp.compact(text)
            if kp.looks_like_name(flat):
                label = _left_label(i, spans)
                token = flat if label else None

        if not token:
            continue

        certainty = _certainty_from_ocr(span.ocr_confidence)
        if certainty is Certainty.REGION_ONLY:
            findings.append(_region_only("name", span, i))
            continue
        findings.append(
            Finding(
                kind="name",
                box=span.box,
                certainty=certainty,
                severity=Severity.COVER,
                message=wording.found("name", near=label),
                evidence_text=token,
                context_words=[label],
                span_index=i,
            )
        )
    return findings


# ------------------------------------------------------------------ 평가

def evaluate(
    spans: list[TextSpan],
    *,
    use_context: bool = True,
    naive: bool = False,
) -> list[Finding]:
    """OCR 결과에서 탐지 항목을 만든다.

    조건이 세 가지다. 비교 실험에서 같은 코드 경로로 전부 돌린다.

      naive=True          : 패턴에 걸리면 전부 가림 권장. 가장 소박한 정규식 구현.
      use_context=False   : 심각도 표는 쓰되 주변 문구는 보지 않음.
      기본값               : 주변 문구까지 본다. 라벨 뒤 이름도 찾는다.
    """
    findings: list[Finding] = []

    for i, span in enumerate(spans):
        for hit in kp.scan(span.text):
            certainty = _certainty_from_ocr(span.ocr_confidence)

            # 못 읽은 글자는 절대 내용으로 내보내지 않는다.
            if certainty is Certainty.REGION_ONLY:
                findings.append(_region_only(hit.kind, span, i))
                continue

            kind = hit.kind
            if naive:
                severity = Severity.COVER
            else:
                severity = DEFAULT_SEVERITY.get(kind, Severity.REVIEW)
            personal: list[str] = []
            public: list[str] = []
            message = wording.found(kind)

            # 운송장 라벨이 바로 옆에 있는 긴 숫자. 신원은 아니지만 송장 조회로
            # 이름·주소(일부 가림)에 닿을 수 있다. 같은 번호가 든 바코드·QR 과
            # 맞춰 검토 권장으로 둔다. 가림 권장까지는 올리지 않는다.
            label = None
            if use_context and not naive and kind == "long_digits":
                label = _tracking_label(i, spans, hit.text)
            if label:
                kind = "tracking"
                severity = Severity.REVIEW
                message = wording.found(kind, near=label)
                personal = [label]

            elif use_context and not naive and kind not in CONTEXT_IMMUNE:
                severity, message, personal, public = _judge(i, spans, hit.text, kind, severity)

            findings.append(
                Finding(
                    kind=kind,
                    box=span.box,
                    certainty=certainty,
                    severity=severity,
                    message=message,
                    evidence_text=hit.text,
                    context_words=(personal + public)[:4],
                    span_index=i,
                )
            )

    if use_context and not naive:
        findings.extend(find_names(spans))

    return findings
