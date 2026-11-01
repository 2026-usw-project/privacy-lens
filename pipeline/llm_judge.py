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
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable

from . import wording
from .context import _certainty_from_ocr, _region_only
from .types import Certainty, Finding, Severity, TextSpan

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

TIMEOUT_S = 90
MAX_SPANS = 400          # 한 번에 보낼 조각 수 상한. 넘는 조각은 보내지 않고 판단도 하지 않는다
MAX_SPAN_CHARS = 200
MAX_FIELD = 500

SYSTEM_PROMPT = """너는 사진 속 개인정보를 가려 주는 서비스의 판단기다.
OCR 이 사진에서 읽은 글자 조각 목록을 받는다. 각 조각은 번호(i), 글자(text), 원본 픽셀 상자(x, y, w, h), OCR 신뢰도(conf)를 가진다.
상자 위치로 같은 줄·바로 왼쪽·바로 윗줄을 판단해 라벨과 값을 연결한다.

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
{"findings":[{"i":조각번호,"kind":"종류","severity":"cover|review|info","text":"조각 안의 해당 값 그대로","near":"근거가 된 옆 라벨(없으면 빈 문자열)"}]}
개인정보가 아닌 조각은 넣지 않는다. text 는 조각 글자에 실제로 있는 부분만 그대로 옮기고, 고치거나 지어내지 않는다."""


class LlmJudgeError(Exception):
    """화면에 그대로 보여도 되는 문구만 담는다. 키·원문·응답 본문은 넣지 않는다."""


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


def parse_config(raw: str | None) -> JudgeConfig | None:
    """화면이 보낸 판단 설정(JSON). 비었거나 provider 가 rules 면 None(규칙 기반)."""
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
    if not model:
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


def _http_post(url: str, headers: dict, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", **headers},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # 응답 본문에 보낸 원문이 되돌아올 수 있어 상태 코드만 쓴다
        if exc.code in (401, 403):
            raise LlmJudgeError(wording.LLM_AUTH_FAILED) from None
        if exc.code == 429:
            raise LlmJudgeError(wording.LLM_RATE_LIMITED) from None
        raise LlmJudgeError(wording.llm_http_failed(exc.code)) from None
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


# ------------------------------------------------------------------ 판단

def _user_message(spans: list[TextSpan], width: int, height: int) -> str:
    items = [{"i": i, "text": s.text[:MAX_SPAN_CHARS], "x": s.box.x, "y": s.box.y, "w": s.box.w, "h": s.box.h,
              "conf": round(s.ocr_confidence, 2)}
             for i, s in enumerate(spans[:MAX_SPANS])]
    return json.dumps({"image": {"width": width, "height": height}, "spans": items}, ensure_ascii=False)


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _evidence(claimed: str, span_text: str) -> str:
    """LLM 이 준 값이 조각 안에 있으면 그 부분, 아니면 조각 원문. 지어낸 글자는 내보내지 않는다."""
    claimed = claimed.strip()
    return claimed if claimed and claimed in span_text else span_text


def _near(word: str, spans: list[TextSpan]) -> str | None:
    """근거 라벨은 사진에 실제로 있는 글자일 때만 쓴다."""
    word = (word or "").strip()[:20]
    if not word or not any(_squash(word) in _squash(s.text) for s in spans):
        return None
    return word


def to_findings(data: dict, spans: list[TextSpan]) -> list[Finding]:
    items = data.get("findings")
    if not isinstance(items, list):
        raise LlmJudgeError(wording.LLM_BAD_RESPONSE)
    out: list[Finding] = []
    seen: set[tuple] = set()
    for item in items[:600]:
        if not isinstance(item, dict):
            continue
        i, kind = item.get("i"), str(item.get("kind") or "").strip()
        sev = SEVERITIES.get(str(item.get("severity") or "").strip().lower())
        if not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < min(len(spans), MAX_SPANS):
            continue
        if kind not in KINDS or sev is None:
            continue
        span = spans[i]
        certainty = _certainty_from_ocr(span.ocr_confidence)
        if certainty is Certainty.REGION_ONLY:
            key = (i, kind, None)
            if key not in seen:
                seen.add(key)
                out.append(_region_only(kind, span, i))
            continue
        evidence = _evidence(str(item.get("text") or ""), span.text)
        key = (i, kind, evidence)
        if key in seen:
            continue
        seen.add(key)
        near = _near(str(item.get("near") or ""), spans)
        message = wording.found_public(kind, near=near) if sev is Severity.INFO else wording.found(kind, near=near)
        out.append(Finding(kind=kind, box=span.box, certainty=certainty, severity=sev, message=message,
                           evidence_text=evidence, context_words=[near] if near else [], span_index=i,
                           detail={"judge": "llm"}))
    return out


def evaluate(spans: list[TextSpan], cfg: JudgeConfig, *, width: int, height: int,
             transport: Transport | None = None) -> list[Finding]:
    """OCR 조각 → LLM → 탐지 항목. 조각이 없으면 부르지 않는다."""
    if not spans:
        return []
    url, headers, body = _request(cfg, SYSTEM_PROMPT, _user_message(spans, width, height))
    data = (transport or _http_post)(url, headers, body, TIMEOUT_S)
    if not isinstance(data, dict):
        raise LlmJudgeError(wording.LLM_BAD_RESPONSE)
    return to_findings(_parse_json(_reply_text(cfg.provider, data)), spans)
