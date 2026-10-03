"""핵심 자료형.

설계 원칙 하나: **인식 확실성(Certainty)과 노출 심각도(Severity)는 별개의 축이다.**
흐릿한 학생증은 심각도가 높고 확실성이 낮다. 선명한 고객센터 번호는
확실성이 높고 심각도가 낮다. 두 값을 하나의 점수로 합치면 둘 다 망가진다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Certainty(str, Enum):
    """내용을 얼마나 확실하게 읽었는가."""

    READ = "read"          # 문자열을 읽었고 형식 검증까지 통과
    PARTIAL = "partial"    # 읽었으나 신뢰도가 낮음
    REGION_ONLY = "region" # 영역만 잡힘, 내용 확인 불가

    @property
    def label(self) -> str:
        return {
            Certainty.READ: "내용 확인됨",
            Certainty.PARTIAL: "일부만 인식됨",
            Certainty.REGION_ONLY: "내용 확인 불가",
        }[self]


class Severity(str, Enum):
    """노출됐을 때 얼마나 곤란한가. 위험 '확률'이 아니라 조치 우선순위다."""

    COVER = "cover"      # 가림 권장
    REVIEW = "review"    # 검토 권장
    INFO = "info"        # 참고

    @property
    def label(self) -> str:
        return {
            Severity.COVER: "가림 권장",
            Severity.REVIEW: "검토 권장",
            Severity.INFO: "참고",
        }[self]

    @property
    def rank(self) -> int:
        return {Severity.COVER: 0, Severity.REVIEW: 1, Severity.INFO: 2}[self]


Point = tuple[float, float]


@dataclass(frozen=True)
class Box:
    """이미지 좌표계의 축 정렬 사각형. 단위는 픽셀.

    poly 는 글자의 실제 외곽선(기울어진 사각형 등)이다. PaddleOCR 가 준다.
    거리·군집·겹침 판정은 축 정렬 사각형으로 하고, **가릴 때만** poly 를 쓴다.
    기울어진 줄을 축 정렬 사각형으로 가리면 위아래 줄까지 덮인다.
    """

    x: int
    y: int
    w: int
    h: int
    poly: Optional[tuple[Point, ...]] = None

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    def expanded(self, px: int) -> "Box":
        return Box(self.x - px, self.y - px, self.w + 2 * px, self.h + 2 * px)

    def contains(self, other: "Box") -> bool:
        return (
            self.x <= other.x
            and self.y <= other.y
            and self.x + self.w >= other.x + other.w
            and self.y + self.h >= other.y + other.h
        )

    def intersects(self, other: "Box") -> bool:
        return (
            self.x < other.x + other.w
            and other.x < self.x + self.w
            and self.y < other.y + other.h
            and other.y < self.y + self.h
        )

    def distance_to(self, other: "Box") -> float:
        dx = max(0, max(self.x - (other.x + other.w), other.x - (self.x + self.w)))
        dy = max(0, max(self.y - (other.y + other.h), other.y - (self.y + self.h)))
        return (dx * dx + dy * dy) ** 0.5

    def as_dict(self) -> dict:
        out = {"x": self.x, "y": self.y, "w": self.w, "h": self.h}
        if self.poly:
            out["poly"] = [[round(px, 1), round(py, 1)] for px, py in self.poly]
        return out


@dataclass
class TextSpan:
    """OCR이 뱉은 문자열 한 조각과 그 좌표."""

    text: str
    box: Box
    ocr_confidence: float  # 0.0 ~ 1.0


@dataclass
class Finding:
    """사용자에게 보여줄 탐지 항목 하나.

    `evidence_text`는 절대 추측으로 채우지 않는다. 못 읽었으면 None이고,
    그 경우 certainty 는 REGION_ONLY 가 된다.
    """

    kind: str                       # "phone", "address", "qr", "gps" ...
    box: Optional[Box]              # None 이면 이미지 전체(메타데이터 등)
    certainty: Certainty
    severity: Severity
    message: str                    # 화면에 그대로 나가는 문장
    evidence_text: Optional[str] = None
    group_id: Optional[str] = None  # 같은 문서 인스턴스에 속한 항목끼리 공유
    context_words: list[str] = field(default_factory=list)
    detail: dict = field(default_factory=dict)
    # 이 항목이 나온 OCR 조각의 번호. 문서 군집 소속을 정할 때만 쓰고 내보내지 않는다.
    span_index: Optional[int] = None

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "box": self.box.as_dict() if self.box else None,
            "certainty": self.certainty.value,
            "certainty_label": self.certainty.label,
            "severity": self.severity.value,
            "severity_label": self.severity.label,
            "message": self.message,
            "evidence_text": self.evidence_text,
            "group_id": self.group_id,
            "context_words": self.context_words,
            "detail": self.detail,
        }


@dataclass
class GroupNote:
    """같은 문서 안에서 여러 항목이 함께 발견됐을 때의 설명.

    서로 다른 종이에 있는 정보는 절대 여기서 묶이지 않는다.
    """

    group_id: str
    box: Box
    kinds: list[str]
    message: str
    severity: Severity

    def as_dict(self) -> dict:
        return {
            "group_id": self.group_id,
            "box": self.box.as_dict(),
            "kinds": self.kinds,
            "message": self.message,
            "severity": self.severity.value,
            "severity_label": self.severity.label,
        }


@dataclass
class Report:
    width: int
    height: int
    findings: list[Finding] = field(default_factory=list)
    groups: list[GroupNote] = field(default_factory=list)
    elapsed_ms: int = 0
    ocr_backend: str = ""
    notes: list[str] = field(default_factory=list)

    def sorted_findings(self) -> list[Finding]:
        return sorted(self.findings, key=lambda f: (f.severity.rank, f.kind))

    def as_dict(self) -> dict:
        return {
            "width": self.width,
            "height": self.height,
            "findings": [f.as_dict() for f in self.sorted_findings()],
            "groups": [g.as_dict() for g in self.groups],
            "elapsed_ms": self.elapsed_ms,
            "ocr_backend": self.ocr_backend,
            "notes": self.notes,
        }
