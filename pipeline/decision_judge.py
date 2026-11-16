"""Gemini Decision 판단(판단 모델 창의 'Gemini Decision', D-23).

LLM 판단(llm_judge)처럼 글을 받아 해석하지 않는다. Gemini Decisions API(`gemini-decision-1`)에
조각마다 정해 둔 질문(등급·종류·라벨인지)을 묻고, 확률이 붙은 답을 코드에서 조합한다.
글을 만들지 않으므로 출력 토큰이 0 이고, 답이 늘 정해 둔 보기 안에서 온다(JSON 해석이 없다).

지키는 것(llm_judge 와 같다)
  - **OCR 원문이 Google 로 나간다.** 판단 모델 창에서만 쓰고 실사 개인정보 사진에는 쓰지 않는다(D-15).
  - 키는 헤더로만 보내고, 오류 문구·로그에 키와 원문을 넣지 않는다.
  - 화면 문구는 wording 이 만든다. 근거 문자열은 OCR 조각 글자 그대로다(모델이 글자를 쓰지 않는다).
  - 못 읽은 글자(OCR 신뢰도 낮음)는 내용 없이 영역으로만 낸다.

판단 방법(2026-11-16 가상 장면·소품 사진으로 맞춘 v3, 수치는 DECISIONS D-23)
  - 조각마다 질문 셋: 등급(cover/review/public/none), 종류(llm_judge.KINDS), '라벨·제목만 있는 조각인가'.
  - 라벨·제목만 있는 조각(확률 0.7 이상)은 값으로 보지 않는다.
  - 여러 조각에 걸친 카드번호 묶기는 모델에 묻지 않고 규칙 코드(context.find_cards)의 묶음을 쓴다.
  - OCR 신뢰도 0.45~0.75 조각은 모델 확신 0.7 이상일 때만, 0.45 미만은 '가림' 확신 0.9 이상일 때만
    영역으로 낸다. 읽다 만 쓰레기 조각을 개인정보로 올리지 않기 위해서다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import context, wording
from .context import _certainty_from_ocr, _region_only
from .types import Certainty, Finding, Severity, TextSpan

if TYPE_CHECKING:
    from .llm_judge import JudgeConfig, Transport

URL = "https://generativelanguage.googleapis.com/v1beta/decisions"
DEFAULT_MODEL = "gemini-decision-1"
TIMEOUT_S = 60
# 한 요청의 질문은 1,000개까지다(조각마다 질문 3개). 넘으면 같은 입력으로 나눠 묻는다.
SPANS_PER_CALL = 300
LABEL_ONLY = 0.7          # '라벨·제목만 있는 조각' 확률이 이 이상이면 값이 아니다
PARTIAL_MIN_CONF = 0.7    # 일부만 읽힌 조각(OCR 0.45~0.75)에 요구하는 모델 확신
UNREAD_MIN_CONF = 0.9     # 못 읽은 조각(OCR 0.45 미만)은 '가림' 확신이 이만큼일 때만 영역으로

SEVERITY = {"cover": Severity.COVER, "review": Severity.REVIEW, "public": Severity.INFO}
_RANK = {"cover": 3, "review": 2, "public": 1, "none": 0}

RUBRIC = """너는 사진 속 개인정보를 가려 주는 서비스의 판단기다. 아래 spans 는 OCR 이 사진에서 읽은 글자 조각 목록이다.
OCR 은 글자를 자주 잘못 읽는다(예: '성명'→'세임', '전화'→'진호', '받는분'→'받는 누분', 0→O). 잘못 읽힌 라벨도 뜻으로 알아본다.
각 조각: i(번호), text(글자), conf(OCR 신뢰도), box(픽셀 상자), line(글줄 번호), order(줄 안 순서),
left(같은 줄 바로 앞 조각), above(바로 윗줄 조각), doc(같은 종이 묶음). 다른 묶음의 정보는 서로의 근거로 쓰지 않는다.

등급
- cover(가림): 혼자서 또는 옆 정보와 합쳐 특정 개인을 알아볼 수 있다.
- review(확인 필요): 개인정보일 수 있으나 문맥이 부족하다.
- public(공개): 가게·기업·기관이 일부러 알리는 정보.
- none(아님): 개인정보가 아니다.
원칙: 놓침이 오탐보다 나쁘다. 애매하면 review. 단 cover 로 단정하지는 않는다.

항목별 기준
- 주민등록번호: 형식이 맞으면 cover. 뒷자리 일부가 *로 가려진 것은 review.
- 카드번호: 16자리(4자리씩 나뉘거나 위아래 줄로 쌓여도 같다)·15자리, 또는 카드 앞면 단서(VALID THRU·VISA·유효기간) 옆 번호는 cover. 일부가 *로 가려진 영수증 표기, 단서 없는 4자리 묶음(주문표·재고표)은 none.
- 계좌번호: '계좌'·'예금주'·은행명 옆 긴 숫자는 cover. 라벨 없는 긴 숫자, 회원번호·주문번호는 none.
- 휴대폰·전화: 개인 라벨(받는분·보내는분·연락처·전화·휴대폰) 옆이나 이름 옆이면 cover, 문맥이 없으면 review.
  가게·병원·기관 라벨(대표·문의·예약·배달·Tel·고객센터) 옆이면 public. 15xx·16xx·080 은 public.
- 주소: 개인 라벨(받는분·주소·배송지) 옆이나 이름 옆이면 cover, 라벨 없이 주소만 있으면 review. 가게·병원·본사·기관 주소는 public.
- 상세주소(동·호수, 아파트·건물 이름이 든 괄호): 항상 cover.
- 이름: 이름 라벨(받는분·보내는분·성명·이름·환자명·수진자·예금주) 옆, 명찰·학생증·신분증 위, 같은 묶음에 연락처·주소가 있으면 cover. '…님'·'…씨' 호칭만 있으면 review.
  상호·지명·학교·병원·회사 이름, 일반 낱말, 의사·발급 기관장 직함은 이름이 아니다.
- 생년월일: '생년월일·출생일·생일' 라벨 옆 날짜가 이름(cover)과 같은 묶음이면 cover, 이름이 없으면 review. 진료일·처방일·유효기간·가입일 같은 다른 라벨의 날짜는 none.
- 비밀번호·PIN: '비밀번호·비번·PW·도어락' 라벨 바로 뒤나 아래의 값은 cover(와이파이 비번 포함). 값 없는 문구('비밀번호 변경')는 none.
- 학번·사번: 라벨 + 학생증·사원증 단서면 cover. 학생증 위 라벨 없는 8~10자리 숫자는 review.
- 운송장번호: 송장 위 번호는 review. 사업자등록번호는 public.
- 이메일: 개인 라벨이나 이름 옆이면 cover. help@·cs@·info@ 같은 기업 대표 메일은 public.

none 으로 보는 것
- 라벨·항목 이름·제목·양식 문구 자체('이름', '주민등록번호', '주민등', '록번호', '환자명', '받는분', '연락처', '주민등록증', '운송장', '처방전'). 라벨과 값이 한 조각이면 값으로 판단한다.
- 발급 기관·발급일('○○시장 2024.05.15 발급', '○○구청장'), 날짜·시각, 가격, 수량, 무게, 상품·약 이름, 메뉴·버튼·키보드 글자.
- 성별·나이만 있는 조각('여', '24세').
- 와이파이 이름(SSID, 예: 'NURI_5G'), 기기·모델 이름. 와이파이 '비밀번호'만 개인정보다.
- 회원번호·주문번호·고객번호·접수번호처럼 라벨이 개인 식별용이 아닌 번호.
"""

SEV_CRITERIA = {
    "cover": "가림: 기준표의 가림 항목. 혼자서 또는 옆 정보와 합쳐 특정 개인을 알아볼 수 있는 값(라벨 옆 이름·연락처·주소, 동·호수, 주민번호, 카드번호, 비밀번호, 이름 옆 생년월일 등).",
    "review": "확인 필요: 개인정보일 수 있으나 문맥이 부족한 값(호칭만 붙은 이름, 라벨 없는 주소·전화, 운송장번호, 이름 없는 생년월일, 일부 가려진 주민번호).",
    "public": "공개: 가게·병원·기업·기관이 일부러 알리는 번호·주소·메일·사업자번호.",
    "none": "아님: 개인 값이 없는 조각. 라벨·제목·양식 문구, 발급 기관·발급일, 날짜, 가격, 수량, 상품명, 성별·나이만 있는 조각, 일반 낱말.",
}

KIND_CRITERIA = {
    "name": "A person's name", "mobile": "Mobile phone number (010...)", "landline": "Landline phone number",
    "service_line": "15xx/16xx representative number", "tollfree": "080 toll-free number", "email": "Email address",
    "rrn": "Korean resident registration number", "rrn_unverified": "Resident-number-shaped value with uncertain checksum",
    "card": "Payment card number", "account": "Bank account number", "password": "Password or PIN after a password label",
    "student_id": "Student or employee ID number", "address_road": "Road or lot address",
    "address_unit": "Building/unit (dong/ho) detail", "plate": "Vehicle plate number", "tracking": "Parcel tracking number",
    "brn": "Business registration number", "long_digits": "Unidentified long number",
    "birth_date": "Date of birth next to a birth-date label", "other": "Other personal info",
    "not_personal": "Not personal information at all",
}


def _head(i: int, text: str) -> str:
    return (f"spans 의 i={i} 조각(글자: \"{text}\")만 판단한다. 이 조각에 라벨과 값이 함께 있으면 값으로 판단한다. "
            f"이 조각이 여러 조각으로 나뉜 한 값의 일부이면(4자리씩 끊긴 카드번호 등) 합친 값으로 판단한다.")


def questions(spans: list[TextSpan], indices: range) -> dict:
    qs: dict = {}
    for i in indices:
        text = spans[i].text[:200]
        qs[f"sev_{i}"] = {"type": "choice", "criteria": SEV_CRITERIA,
                          "instructions": _head(i, text) + " 이 조각 안의 값은 기준표의 어느 등급인가?"}
        qs[f"kind_{i}"] = {"type": "choice", "criteria": KIND_CRITERIA,
                           "instructions": _head(i, text) + " 이 조각 안의 값은 어떤 종류의 정보인가?"}
        qs[f"label_{i}"] = {"type": "noul", "instructions":
                            f"spans 의 i={i} 조각(글자: \"{text}\")이 개인 값 없이 라벨·항목 이름·제목·양식 문구·발급 기관·날짜·"
                            f"성별·나이·버튼이나 키보드 글자만으로 이루어져 있는가? 라벨 뒤에 이름·번호·주소 같은 값이 같은 조각에 붙어 있으면 아니다."}
    return qs


def _answers(data, keys) -> dict:
    """응답에서 물은 질문의 답만 꺼낸다. 형식이 다르면 해석 실패."""
    from .llm_judge import LlmJudgeError

    answers = data.get("answers") if isinstance(data, dict) else None
    if not isinstance(answers, dict):
        raise LlmJudgeError(wording.LLM_BAD_RESPONSE)
    out = {}
    for k in keys:
        a = answers.get(k)
        if not isinstance(a, dict) or not isinstance(a.get("confidence"), (int, float)):
            raise LlmJudgeError(wording.LLM_BAD_RESPONSE)
        if k.startswith("label_"):
            if not isinstance(a.get("noul"), (int, float)):
                raise LlmJudgeError(wording.LLM_BAD_RESPONSE)
        elif not isinstance(a.get("choice"), str):
            raise LlmJudgeError(wording.LLM_BAD_RESPONSE)
        out[k] = a
    return out


def _card_groups(spans: list[TextSpan]) -> list[list[int]]:
    """여러 조각에 걸친 카드번호 묶음. 모델에 묻지 않고 규칙 코드가 찾은 묶음을 쓴다."""
    return [f.detail["span_indices"] for f in context.find_cards(spans, [])
            if len(f.detail.get("span_indices") or []) > 1]


def to_findings(ans: dict, spans: list[TextSpan]) -> list[Finding]:
    """답 → 탐지 항목. 화면 문구는 wording, 근거 글자는 OCR 조각 글자 그대로."""
    from .llm_judge import KINDS, _hull

    n = len(spans)
    label_only = {i for i in range(n) if ans[f"label_{i}"]["noul"] >= LABEL_ONLY}
    parent = list(range(n))

    def find(k: int) -> int:
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    for group in _card_groups(spans):
        for k in group[1:]:
            parent[find(k)] = find(group[0])
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    out: list[Finding] = []
    for idx in groups.values():
        best, conf = "none", 0.0
        for k in idx:
            if k in label_only and len(idx) == 1:
                continue
            a = ans[f"sev_{k}"]
            top, c = a["choice"], float(a["confidence"])
            if top not in _RANK:
                continue
            ocr_conf = spans[k].ocr_confidence
            if ocr_conf < 0.45 and not (top == "cover" and c >= UNREAD_MIN_CONF):
                continue
            if ocr_conf < 0.75 and c < PARTIAL_MIN_CONF:
                continue
            if _RANK[top] > _RANK[best]:
                best, conf = top, c
        if best == "none":
            continue
        kinds = [ans[f"kind_{k}"]["choice"] for k in idx]
        kind = next((x for x in kinds if x in KINDS), "other")
        sev = SEVERITY[best]
        parts = [spans[k] for k in idx]
        certainty = min((_certainty_from_ocr(s.ocr_confidence) for s in parts),
                        key=[Certainty.REGION_ONLY, Certainty.PARTIAL, Certainty.READ].index)
        if certainty is Certainty.REGION_ONLY:
            f = _region_only(kind, parts[0], idx[0])
            f.box = _hull([s.box for s in parts])
            f.detail = {"judge": "decision", "confidence": round(conf, 3)}
            out.append(f)
            continue
        detail: dict = {"judge": "decision", "basis": "format", "confidence": round(conf, 3)}
        if len(idx) > 1:
            detail.update(span_indices=sorted(idx), parts=len(idx))
        message = wording.found_public(kind) if sev is Severity.INFO else wording.found(kind)
        out.append(Finding(kind=kind, box=_hull([s.box for s in parts]), certainty=certainty, severity=sev,
                           message=message, evidence_text=" ".join(s.text for s in parts),
                           span_index=min(idx), detail=detail))
    return out


def evaluate(spans: list[TextSpan], cfg: "JudgeConfig", *, width: int, height: int,
             transport: "Transport | None" = None, trace: list | None = None) -> list[Finding]:
    """OCR 조각 → Decisions API → 탐지 항목. 조각이 없으면 부르지 않는다.

    입력(기준표 + 조각 목록)은 한 번 만들고, 질문이 1,000개를 넘으면 같은 입력으로 나눠 묻는다.
    """
    from .llm_judge import MAX_SPANS, LlmJudgeError, _fail, _http_post, _traced, _user_message

    if not spans:
        return []
    sent = spans[:MAX_SPANS]
    shared = RUBRIC + "\n" + _user_message(sent, width, height)
    post = transport or _http_post
    headers = {"x-goog-api-key": cfg.api_key}
    ans: dict = {}
    for start in range(0, len(sent), SPANS_PER_CALL):
        qs = questions(sent, range(start, min(start + SPANS_PER_CALL, len(sent))))
        body = {"model": cfg.model or DEFAULT_MODEL, "input": shared, "questions": qs}
        data = _traced(trace, "judge", cfg, "POST", URL, headers, body,
                       lambda body=body: post(URL, headers, body, TIMEOUT_S))
        try:
            ans.update(_answers(data, qs.keys()))
        except LlmJudgeError as exc:
            raise _fail(trace, str(exc)) from None
    return to_findings(ans, sent)
