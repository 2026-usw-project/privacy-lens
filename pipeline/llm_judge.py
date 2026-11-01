"""LLM 판단(개발자 모드). 규칙 기반 판단(context.evaluate) 대신 쓴다.

OCR 이 읽은 조각과 좌표를 LLM 에 보내고, '몇 번 조각이 어떤 개인정보인지'만 받는다.
LLM 을 고르면 정규식·체크섬·문맥 규칙은 돌리지 않는다. 위치정보(EXIF)·QR·YOLO 영역
경고는 글자 판단이 아니라서 그대로 둔다.

지키는 것
  - **OCR 원문이 외부로 나간다.** 클라우드 공급자(ChatGPT·Gemini·Claude·OpenRouter)를
    고르면 사진 속 글자가 그 회사 서버로 간다. 개발자 모드에서만 쓰고 실사 개인정보
    사진에는 쓰지 않는다(DECISIONS D-15).
  - 키는 요청마다 화면에서 받아 쓰고 저장하지 않는다. 오류 문구·로그에 키와 원문을 넣지 않는다.
  - 화면에 나가는 문장은 wording 이 만든다. LLM 이 쓴 설명은 내보내지 않는다.
  - 근거 문자열은 LLM 이 준 값이 그 조각 안에 실제로 있을 때만 쓴다. 없으면 조각 원문을 쓴다.
    못 읽은 글자(OCR 신뢰도 낮음)는 지금처럼 내용 없이 영역으로만 낸다.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable

from . import wording
from .context import CONTEXT_RADIUS_EM, _certainty_from_ocr, _region_only
from .grouping import _cluster
from .layout import layout
from .types import Box, Certainty, Finding, Severity, TextSpan

PROVIDERS = {
    "openai": "ChatGPT",
    "gemini": "Gemini",
    "anthropic": "Claude",
    "openrouter": "OpenRouter",
    "ollama": "Ollama",
    "custom": "Custom API",
}
# 사진 속 글자가 이 컴퓨터 밖으로 나가는 공급자
CLOUD = {"openai", "gemini", "anthropic", "openrouter"}
NEEDS_KEY = CLOUD
NEEDS_URL = {"custom"}
DEFAULT_URL = {"ollama": "http://127.0.0.1:11434"}

# LLM 이 고를 수 있는 종류. 글자에서 나오는 것만(gps·qr·문서 영역은 다른 단계가 낸다)
KINDS = [
    "name", "mobile", "landline", "service_line", "tollfree", "email", "rrn", "rrn_unverified",
    "card", "account", "password", "student_id", "address_road", "address_unit", "plate",
    "tracking", "brn", "long_digits", "other",
]
SEVERITIES = {"cover": Severity.COVER, "review": Severity.REVIEW, "info": Severity.INFO}
# basis=document 일 때 받는 문서 종류(wording.DOC_NOUN 의 키)
DOCS = {"waybill", "student", "id_card", "badge", "receipt", "screen"}
MAX_PARTS = 8            # 한 값으로 묶을 수 있는 조각 수(4자리씩 끊긴 카드번호 등)
LABEL_MAX = 12           # 라벨로 인정할 최대 글자 수(공백 빼고). 'VALID THRU' 같은 영문 라벨까지
_WORSE = [Certainty.READ, Certainty.PARTIAL, Certainty.REGION_ONLY]

TIMEOUT_S = 90
MAX_SPANS = 400          # 한 번에 보낼 조각 수 상한. 넘는 조각은 보내지 않고 판단도 하지 않는다
MAX_SPAN_CHARS = 200
MAX_FIELD = 500

SYSTEM_PROMPT = """너는 사진 속 개인정보를 가려 주는 서비스의 판단기다.
OCR 이 사진에서 읽은 글자 조각 목록을 받는다. 각 조각:
- i: 번호, text: 글자, conf: OCR 신뢰도, box: 원본 픽셀 상자 [x, y, w, h]
- line: 몇 번째 글줄인지, order: 그 줄에서 몇 번째인지(기울어진 사진도 글줄 방향 기준)
- left: 같은 줄 바로 왼쪽(앞) 조각 번호, above: 바로 윗줄에 줄머리를 맞춘 조각 번호(없으면 null)
- doc: 같은 종이(문서)로 묶인 묶음 번호. 다른 묶음의 정보는 서로의 근거로 쓰지 않는다
라벨과 값은 left·above 로 연결한다. 좌표를 직접 계산하기보다 이 관계를 먼저 본다.

등급
- cover: 혼자서 또는 옆 정보와 합쳐 특정 개인을 알아볼 수 있다(가림 권장)
- review: 개인정보일 수 있으나 문맥이 부족하다(검토 권장)
- info: 가게·기업이 일부러 공개한 정보다(참고)
원칙: 놓침이 오탐보다 나쁘다. 애매하면 review. 공개 정보(고객센터·대표번호·매장 주소·사업자번호)는 info.

종류(kind): name, mobile, landline, service_line(15xx·16xx 대표번호), tollfree(080), email,
rrn(주민등록번호), rrn_unverified(체크섬 불확실한 주민번호 형식), card, account(계좌), password(비밀번호·PIN),
student_id(학번·사번), address_road(도로명·지번 주소), address_unit(동·호수), plate(차량번호),
tracking(운송장번호), brn(사업자등록번호), long_digits(정체 모를 긴 숫자), other(그 밖의 개인정보)

기준 예
- '받는분 홍길동', '연락처 010-…', '배송지 …' 옆 값은 cover. 동·호수는 cover.
- 이름은 라벨, 명찰·학생증 단서, 같은 묶음의 연락처·주소가 있으면 cover. 호칭(…님)만 있으면 review. 상호·지명·일반 낱말은 이름이 아니다.
- 비밀번호는 '비밀번호·비번·PW' 라벨 뒤 값만. 라벨이 없는 문자열은 고르지 않는다.
- 라벨 없는 긴 숫자는 계좌인지 주문번호인지 알 수 없으므로 info(long_digits).

출력: JSON 객체 하나만. 설명·코드블록 없이.
{"findings":[{"i":[조각번호,...],"kind":"종류","severity":"cover|review|info","text":"조각 안의 해당 값 그대로",
  "basis":"label|document|linked|honorific|format","label_i":라벨 조각번호,"doc":"문서 종류","with":[함께 있는 개인정보의 조각번호,...]}]}
- i: 한 값이 여러 조각으로 나뉘었으면(예: 4자리씩 끊긴 카드번호) 모두 넣는다. 한 조각이면 [번호].
- 좌표·상자는 출력하지 않는다. 서버가 조각 번호로 OCR 좌표를 쓴다.
- basis: 판단 근거의 종류 하나.
  label: 옆 라벨이 근거('연락처', '받는분', 'VALID THRU' 등). label_i 에 그 라벨 조각 번호(보통 left 나 above). 다른 개인정보 값은 라벨이 아니다.
  document: 문서 종류가 근거. doc 은 waybill(송장)·student(학생증)·id_card(신분증·카드)·badge(명찰·사원증)·receipt(영수증)·screen(화면) 중 하나.
  linked: 같은 묶음의 다른 개인정보와 함께 있는 것이 근거. with 에 그 개인정보의 조각 번호(이 출력에 함께 넣은 것만).
  honorific: '…님'·'…씨' 같은 호칭이 근거.
  format: 형식만 보고 판단(주민번호 체크섬, 카드번호 16자리 등).
- 공개 정보(info)는 공개를 알려 주는 라벨('고객센터' 등)을 label 로 준다.
개인정보가 아닌 조각은 넣지 않는다. text 는 조각 글자에 실제로 있는 부분만 그대로 옮기고, 고치거나 지어내지 않는다."""


class LlmJudgeError(Exception):
    """화면에 그대로 보여도 되는 문구만 담는다. 키·원문·응답 본문은 넣지 않는다.

    status·provider_body 는 개발자 콘솔(llm_trace)에만 쓴다. 서버 로그와 detail 에는 넣지 않는다.
    """

    def __init__(self, message: str, *, status: int | None = None, provider_body: str | None = None):
        super().__init__(message)
        self.status = status
        self.provider_body = provider_body
        self.trace: list[dict] = []


@dataclass(frozen=True)
class JudgeConfig:
    provider: str
    model: str
    api_key: str = ""
    base_url: str = ""

    @property
    def label(self) -> str:
        return f"{PROVIDERS[self.provider]} · {self.model}"

    @property
    def sends_outside(self) -> bool:
        return self.provider in CLOUD


def parse_config(raw: str | None, *, need_model: bool = True) -> JudgeConfig | None:
    """화면이 보낸 판단 설정(JSON). 비었거나 provider 가 rules 면 None(규칙 기반).

    need_model=False 는 모델 목록을 물을 때다(아직 모델을 고르기 전).
    """
    if raw is None or not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError(wording.LLM_CONFIG_INVALID)
    if not isinstance(data, dict):
        raise ValueError(wording.LLM_CONFIG_INVALID)
    provider = str(data.get("provider") or "rules").strip().lower()
    if provider == "rules":
        return None
    if provider not in PROVIDERS:
        raise ValueError(wording.LLM_CONFIG_INVALID)

    def field(name: str) -> str:
        value = data.get(name) or ""
        if not isinstance(value, str) or len(value) > MAX_FIELD:
            raise ValueError(wording.LLM_CONFIG_INVALID)
        return value.strip()

    model, key, url = field("model"), field("api_key"), field("base_url")
    if not model and need_model:
        raise ValueError(wording.LLM_MODEL_MISSING)
    if provider in NEEDS_KEY and not key:
        raise ValueError(wording.LLM_KEY_MISSING)
    url = url or DEFAULT_URL.get(provider, "")
    if provider in NEEDS_URL and not url:
        raise ValueError(wording.LLM_URL_MISSING)
    if url:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError(wording.LLM_URL_MISSING)
        url = url.rstrip("/")
    return JudgeConfig(provider, model, key, url)


# ------------------------------------------------------------------ 요청

Transport = Callable[[str, dict, dict, float], dict]
GetTransport = Callable[[str, dict, float], dict]


def _http_post(url: str, headers: dict, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", **headers},
    )
    return _send(req, timeout)


def _http_get(url: str, headers: dict, timeout: float) -> dict:
    return _send(urllib.request.Request(url, method="GET", headers=headers), timeout)


def _send(req: urllib.request.Request, timeout: float) -> dict:
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # 응답 본문에 보낸 원문이 되돌아올 수 있어 화면 문구에는 상태 코드만 쓴다.
        # 본문은 개발자 콘솔(llm_trace)로만 넘긴다.
        try:
            body = exc.read().decode("utf-8", "replace")[:TRACE_BODY_CHARS]
        except Exception:
            body = None
        message = {401: wording.LLM_AUTH_FAILED, 403: wording.LLM_AUTH_FAILED, 404: wording.LLM_MODEL_NOT_FOUND,
                   429: wording.LLM_RATE_LIMITED}.get(exc.code) or wording.llm_http_failed(exc.code)
        raise LlmJudgeError(message, status=exc.code, provider_body=body) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise LlmJudgeError(wording.LLM_UNREACHABLE) from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise LlmJudgeError(wording.LLM_BAD_RESPONSE) from None


def _openai_style(url: str, cfg: JudgeConfig, system: str, user: str, *, json_mode: bool) -> tuple:
    headers = {"Authorization": f"Bearer {cfg.api_key}"} if cfg.api_key else {}
    body = {"model": cfg.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    return url, headers, body


def _request(cfg: JudgeConfig, system: str, user: str) -> tuple[str, dict, dict]:
    p = cfg.provider
    if p == "openai":
        return _openai_style("https://api.openai.com/v1/chat/completions", cfg, system, user, json_mode=True)
    if p == "openrouter":
        return _openai_style("https://openrouter.ai/api/v1/chat/completions", cfg, system, user, json_mode=False)
    if p == "custom":
        return _openai_style(cfg.base_url + "/chat/completions", cfg, system, user, json_mode=False)
    if p == "anthropic":
        return ("https://api.anthropic.com/v1/messages",
                {"x-api-key": cfg.api_key, "anthropic-version": "2023-06-01"},
                {"model": cfg.model, "max_tokens": 8192, "system": system,
                 "messages": [{"role": "user", "content": user}]})
    if p == "gemini":
        # 키는 주소(쿼리)가 아니라 헤더로 보낸다
        model = urllib.parse.quote(cfg.model, safe="")
        return (f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                {"x-goog-api-key": cfg.api_key},
                {"systemInstruction": {"parts": [{"text": system}]},
                 "contents": [{"role": "user", "parts": [{"text": user}]}],
                 "generationConfig": {"responseMimeType": "application/json", "temperature": 0}})
    if p == "ollama":
        return (cfg.base_url + "/api/chat", {},
                {"model": cfg.model, "stream": False, "format": "json", "options": {"temperature": 0},
                 "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
    raise LlmJudgeError(wording.LLM_CONFIG_INVALID)


def _reply_text(provider: str, data: dict) -> str:
    """공급자별 응답에서 모델이 쓴 글만 꺼낸다."""
    try:
        if provider == "anthropic":
            return "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
        if provider == "gemini":
            return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
        if provider == "ollama":
            return data["message"]["content"]
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError, AttributeError):
        raise LlmJudgeError(wording.LLM_BAD_RESPONSE) from None


def _parse_json(text: str) -> dict:
    """코드블록·앞뒤 설명이 붙어 와도 첫 JSON 객체를 찾는다."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        out = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise LlmJudgeError(wording.LLM_BAD_RESPONSE) from None
        try:
            out = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            raise LlmJudgeError(wording.LLM_BAD_RESPONSE) from None
    if isinstance(out, list):
        out = {"findings": out}
    if not isinstance(out, dict):
        raise LlmJudgeError(wording.LLM_BAD_RESPONSE)
    return out


# ------------------------------------------------------------------ 개발자 콘솔 기록

TRACE_BODY_CHARS = 20_000
_SECRET_HEADERS = {"authorization", "x-api-key", "x-goog-api-key"}


def _mask_headers(headers: dict) -> dict:
    """키는 끝 4글자만 남긴다. 콘솔에 키 전체가 찍히지 않게."""
    out = {}
    for k, v in headers.items():
        if k.lower() in _SECRET_HEADERS and isinstance(v, str):
            prefix = "Bearer " if v.startswith("Bearer ") else ""
            secret = v[len(prefix):]
            out[k] = f"{prefix}…{secret[-4:]}" if len(secret) > 8 else f"{prefix}…"
        else:
            out[k] = v
    return out


def _traced(trace: list | None, kind: str, cfg: JudgeConfig, method: str, url: str, headers: dict,
            body: dict | None, call: Callable[[], dict]) -> dict:
    """공급자 요청 한 번. trace 가 있으면 요청·응답(키 가림)을 남긴다. 실패해도 남기고 예외에 붙인다."""
    entry = {"kind": kind, "provider": cfg.provider, "model": cfg.model, "method": method, "url": url,
             "headers": _mask_headers(headers), "request": body}
    started = time.perf_counter()
    try:
        data = call()
    except LlmJudgeError as exc:
        if trace is not None:
            entry.update(ok=False, elapsed_ms=int((time.perf_counter() - started) * 1000), status=exc.status,
                         error=str(exc), response=exc.provider_body)
            trace.append(entry)
            exc.trace = trace
        raise
    if trace is not None:
        entry.update(ok=True, elapsed_ms=int((time.perf_counter() - started) * 1000), status=200, response=data)
        trace.append(entry)
    return data


def _fail(trace: list | None, message: str) -> LlmJudgeError:
    """응답은 왔지만 해석하지 못했을 때. 이미 남긴 요청·응답 기록을 예외에 붙인다."""
    exc = LlmJudgeError(message)
    if trace:
        trace[-1].update(ok=False, error=message)
        exc.trace = trace
    return exc


# ------------------------------------------------------------------ 판단

def _hull(boxes: list[Box]) -> Box:
    """여러 조각을 덮는 상자. 한 조각이면 외곽선(poly)까지 그대로."""
    if len(boxes) == 1:
        return boxes[0]
    x0, y0 = min(b.x for b in boxes), min(b.y for b in boxes)
    x1, y1 = max(b.x + b.w for b in boxes), max(b.y + b.h for b in boxes)
    return Box(x0, y0, x1 - x0, y1 - y0)


def _relations(spans: list[TextSpan]) -> list[dict]:
    """조각마다 글줄 번호·순서·바로 왼쪽·바로 윗줄·문서 묶음. 규칙 판단과 같은 글줄 좌표계(layout)로 잰다.

    LLM 은 숫자 좌표로 '같은 줄인지'를 계산하는 데 약하다(기울어진 사진에서 특히). 관계를 미리 풀어 준다.
    """
    lay = layout(spans)
    n = len(spans)
    left = [next(iter(lay.left_neighbors(i)), None) for i in range(n)]
    above = [lay.line_above(i) for i in range(n)]

    # 같은 줄: 바로 왼쪽으로 이어지는 조각끼리 묶는다
    parent = list(range(n))

    def find(k: int) -> int:
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    for i, j in enumerate(left):
        if j is not None:
            parent[find(i)] = find(j)
    # 글줄 좌표계에서의 위치(줄 순서·줄 안 순서). 첫 조각의 좌표계를 기준으로 쓴다
    ext = [lay.pair(0, k)[1] for k in range(n)]
    lines: dict[int, list[int]] = {}
    for k in range(n):
        lines.setdefault(find(k), []).append(k)
    ordered = sorted(lines.values(), key=lambda ks: sum(ext[k].mid_c for k in ks) / len(ks))
    line_of, order_of = [0] * n, [0] * n
    for li, ks in enumerate(ordered):
        for oi, k in enumerate(sorted(ks, key=lambda k: ext[k].a0)):
            line_of[k], order_of[k] = li, oi

    doc_of = [0] * n
    for di, ks in enumerate(_cluster(spans)):
        for k in ks:
            doc_of[k] = di
    return [{"line": line_of[k], "order": order_of[k], "left": left[k], "above": above[k], "doc": doc_of[k]}
            for k in range(n)]


def _user_message(spans: list[TextSpan], width: int, height: int) -> str:
    sent = spans[:MAX_SPANS]
    rel = _relations(sent)
    items = [{"i": i, "text": s.text[:MAX_SPAN_CHARS], "conf": round(s.ocr_confidence, 2),
              "box": [s.box.x, s.box.y, s.box.w, s.box.h], **rel[i]}
             for i, s in enumerate(sent)]
    return json.dumps({"image": {"width": width, "height": height}, "spans": items}, ensure_ascii=False)


def _evidence(claimed: str, span_text: str) -> str:
    """LLM 이 준 값이 조각 안에 있으면 그 부분, 아니면 조각 원문. 지어낸 글자는 내보내지 않는다."""
    claimed = claimed.strip()
    return claimed if claimed and claimed in span_text else span_text


def _indices(raw, limit: int) -> list[int]:
    """i 는 번호 하나 또는 번호 목록. 범위 밖·중복·불리언은 버린다."""
    items = raw if isinstance(raw, list) else [raw]
    out: list[int] = []
    for v in items[:MAX_PARTS]:
        if isinstance(v, int) and not isinstance(v, bool) and 0 <= v < limit and v not in out:
            out.append(v)
    return out


def _clean_label(text: str) -> str | None:
    text = re.sub(r"\s+", " ", text).strip().strip(":：-").strip()
    return text if text and len(text.replace(" ", "")) <= LABEL_MAX else None


def _label_ok(label_i, value_idx: list[int], spans: list[TextSpan], value_spans: set[int],
              evidence: str) -> str | None:
    """라벨 근거를 위치로 확인한다. 같은 줄 바로 앞, 바로 윗줄, 또는 문맥 반경 안이어야 하고,
    다른 개인정보 값이 아니며, 라벨이라 부를 만큼 짧아야 한다. 통과하면 라벨 글자, 아니면 None.

    '연락처 010-…' 처럼 라벨과 값이 한 조각이면 label_i 가 값 조각이어도 된다. 그때는 값 앞부분이 라벨이다.
    """
    if not isinstance(label_i, int) or isinstance(label_i, bool) or not 0 <= label_i < len(spans):
        return None
    if label_i in value_idx:
        own = spans[label_i].text
        cut = own.find(evidence) if evidence and evidence != own else -1
        return _clean_label(own[:cut]) if cut > 0 else None
    if label_i in value_spans:
        return None
    text = _clean_label(spans[label_i].text)
    if not text:
        return None
    lay = layout(spans)
    first = value_idx[0]
    close = (label_i in lay.left_neighbors(first)[:2] or lay.line_above(first) == label_i
             or lay.distance(first, label_i) <= max(lay.thickness(first), 12) * CONTEXT_RADIUS_EM)
    return text if close else None


def to_findings(data: dict, spans: list[TextSpan]) -> list[Finding]:
    """LLM 출력 → 탐지 항목. 근거(basis)는 서버가 위치·목록으로 확인하고, 확인되지 않으면 '형식' 근거로 내린다.

    화면 문구에 들어가는 것은 라벨 조각 글자, 문서 종류, 함께 있는 항목의 '종류'뿐이다. 다른 개인정보 값은 넣지 않는다.
    """
    items = data.get("findings")
    if not isinstance(items, list):
        raise LlmJudgeError(wording.LLM_BAD_RESPONSE)
    limit = min(len(spans), MAX_SPANS)

    # 1차: 값과 조각만 확정한다. 근거 확인에 '어떤 조각이 개인정보 값인지'가 필요하다.
    picked: list[tuple[list[int], str, Severity, dict]] = []
    seen: set[tuple] = set()
    for item in items[:600]:
        if not isinstance(item, dict):
            continue
        idx = _indices(item.get("i"), limit)
        kind = str(item.get("kind") or "").strip()
        sev = SEVERITIES.get(str(item.get("severity") or "").strip().lower())
        if not idx or kind not in KINDS or sev is None:
            continue
        key = (tuple(idx), kind)
        if key in seen:
            continue
        seen.add(key)
        picked.append((idx, kind, sev, item))
    kind_at = {k: kind for idx, kind, sev, _ in picked if sev is not Severity.INFO for k in idx}

    out: list[Finding] = []
    for idx, kind, sev, item in picked:
        parts = [spans[k] for k in idx]
        box = _hull([s.box for s in parts])
        certainty = max((_certainty_from_ocr(s.ocr_confidence) for s in parts), key=_WORSE.index)  # 가장 못 읽은 조각 기준
        if certainty is Certainty.REGION_ONLY:
            f = _region_only(kind, parts[0], idx[0])
            f.box = box
            out.append(f)
            continue
        joined = " ".join(s.text for s in parts)
        evidence = _evidence(str(item.get("text") or ""), joined)

        basis = str(item.get("basis") or "").strip().lower()
        detail: dict = {"judge": "llm", "basis": "format"}
        context: list[str] = []
        message = None
        if basis == "label":
            label = _label_ok(item.get("label_i"), idx, spans, set(kind_at), evidence)
            if label:
                detail.update(basis="label", basis_box=spans[item["label_i"]].box.as_dict())
                context = [label]
                message = (wording.found_public(kind, near=label) if sev is Severity.INFO
                           else wording.found(kind, near=label))
        elif basis == "document" and item.get("doc") in DOCS:
            detail.update(basis="document", document_hint=item["doc"])
            context = [wording.DOC_NOUN[item["doc"]]]
            message = wording.found_in_document(kind, item["doc"])
        elif basis == "linked":
            others = [kind_at[k] for k in _indices(item.get("with"), limit) if k in kind_at and k not in idx]
            if others:
                detail.update(basis="linked", linked_kinds=sorted(set(others)))
                message = wording.found_linked(kind, others[0])
        elif basis == "honorific" and kind == "name":
            detail.update(basis="honorific")
            message = wording.found_honorific(kind)
        if message is None:  # 근거가 없거나 확인되지 않음 → 형식 근거
            message = wording.found_public(kind) if sev is Severity.INFO else wording.found(kind)
        if len(idx) > 1:
            detail["parts"] = len(idx)
        out.append(Finding(kind=kind, box=box, certainty=certainty, severity=sev, message=message,
                           evidence_text=evidence, context_words=context, span_index=idx[0], detail=detail))
    return out


def evaluate(spans: list[TextSpan], cfg: JudgeConfig, *, width: int, height: int,
             transport: Transport | None = None, trace: list | None = None) -> list[Finding]:
    """OCR 조각 → LLM → 탐지 항목. 조각이 없으면 부르지 않는다.

    trace 에 리스트를 주면 공급자와 주고받은 요청·응답을 남긴다(개발자 콘솔용, 키는 가림).
    """
    if not spans:
        return []
    url, headers, body = _request(cfg, SYSTEM_PROMPT, _user_message(spans, width, height))
    post = transport or _http_post
    data = _traced(trace, "judge", cfg, "POST", url, headers, body,
                   lambda: post(url, headers, body, TIMEOUT_S))
    try:
        if not isinstance(data, dict):
            raise LlmJudgeError(wording.LLM_BAD_RESPONSE)
        return to_findings(_parse_json(_reply_text(cfg.provider, data)), spans)
    except LlmJudgeError as exc:
        raise _fail(trace, str(exc)) from None


# ------------------------------------------------------------------ 모델 목록

MAX_MODELS = 2000
MAX_PAGES = 5


def _model_request(cfg: JudgeConfig, page: str | None) -> tuple[str, dict]:
    """공급자별 '쓸 수 있는 모델 목록' 요청. 키는 헤더로만."""
    p = cfg.provider
    bearer = {"Authorization": f"Bearer {cfg.api_key}"} if cfg.api_key else {}
    if p == "openai":
        return "https://api.openai.com/v1/models", bearer
    if p == "openrouter":
        return "https://openrouter.ai/api/v1/models", bearer
    if p == "custom":
        return cfg.base_url + "/models", bearer
    if p == "ollama":
        return cfg.base_url + "/api/tags", {}
    if p == "anthropic":
        q = {"limit": "1000", **({"after_id": page} if page else {})}
        return ("https://api.anthropic.com/v1/models?" + urllib.parse.urlencode(q),
                {"x-api-key": cfg.api_key, "anthropic-version": "2023-06-01"})
    if p == "gemini":
        q = {"pageSize": "1000", **({"pageToken": page} if page else {})}
        return ("https://generativelanguage.googleapis.com/v1beta/models?" + urllib.parse.urlencode(q),
                {"x-goog-api-key": cfg.api_key})
    raise LlmJudgeError(wording.LLM_CONFIG_INVALID)


def _model_page(provider: str, data: dict) -> tuple[list[str], str | None]:
    """응답에서 모델 이름과 다음 쪽 표시를 꺼낸다."""
    try:
        if provider == "ollama":
            return [m["name"] for m in data["models"]], None
        if provider == "gemini":
            # 판단에 쓰는 generateContent 를 지원하는 모델만. 이름 앞의 'models/' 는 뗀다
            names = [m["name"].removeprefix("models/") for m in data.get("models", [])
                     if "generateContent" in m.get("supportedGenerationMethods", ["generateContent"])]
            return names, data.get("nextPageToken") or None
        names = [m["id"] for m in data["data"]]
        if provider == "anthropic" and data.get("has_more") and data.get("last_id"):
            return names, data["last_id"]
        return names, None
    except (KeyError, TypeError, AttributeError):
        raise LlmJudgeError(wording.LLM_BAD_RESPONSE) from None


def list_models(cfg: JudgeConfig, *, transport: GetTransport | None = None,
                trace: list | None = None) -> list[str]:
    """공급자가 이 키로 쓸 수 있다고 알려 주는 모델 이름. 정렬하고 중복을 뺀다."""
    get = transport or _http_get
    names: list[str] = []
    page: str | None = None
    for _ in range(MAX_PAGES):
        url, headers = _model_request(cfg, page)
        data = _traced(trace, "models", cfg, "GET", url, headers, None, lambda: get(url, headers, 30))
        try:
            if not isinstance(data, dict):
                raise LlmJudgeError(wording.LLM_BAD_RESPONSE)
            got, page = _model_page(cfg.provider, data)
        except LlmJudgeError as exc:
            raise _fail(trace, str(exc)) from None
        names += [n for n in got if isinstance(n, str) and 0 < len(n) <= MAX_FIELD]
        if not page or len(names) >= MAX_MODELS:
            break
    return sorted(set(names))[:MAX_MODELS]
