"""
Privacy Lens — 모듈 간 데이터 스키마 (Single Source of Truth)

이 파일이 기준입니다. 필드를 바꾸면
  1) SCHEMA_VERSION 올리기
  2) python schema/generate.py 실행 → JSON Schema / 예시 재검증
  3) web 쪽 types.ts 재생성
순서로 반영하세요.

데이터 흐름
  [D] 업로드 수신 → EXIF 방향 보정 → ExifInfo
  [A] 이미지 → list[Detection]                  (검출 · QR 디코딩)
  [B] 이미지 + list[Detection] → list[Finding]   (크롭 OCR · PII 판정 · 위험도)
  [D] ExifInfo + list[Finding] → AnalyzeResponse (프론트로 반환)

좌표 규칙 (중요)
  - 모든 좌표는 "EXIF 방향 보정 후" 원본 해상도 기준 픽셀 좌표입니다.
  - 리사이즈 · 타일 좌표로 넘기지 말 것. SAHI 결과도 원본 좌표로 환산해서 넘깁니다.
  - BBox 는 좌상단(x1, y1) ~ 우하단(x2, y2). xywh 아님.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "0.1.0"


class _Base(BaseModel):
    # 정의되지 않은 필드가 들어오면 에러 → 오타·스키마 불일치를 바로 발견
    model_config = ConfigDict(extra="forbid", use_enum_values=True)


# ─────────────────────────────────────────────
# 열거형
# ─────────────────────────────────────────────
class ObjectLabel(str, Enum):
    """검출 클래스 9종 (YOLO 클래스 인덱스 순서와 동일하게 유지)"""
    PARCEL_LABEL = "parcel_label"    # 0 택배 송장
    NAME_TAG = "name_tag"            # 1 명찰 · 사원증
    STUDENT_ID = "student_id"        # 2 학생증
    PAYMENT_CARD = "payment_card"    # 3 카드
    SCREEN = "screen"                # 4 모니터 · 노트북 · 휴대폰 화면
    LICENSE_PLATE = "license_plate"  # 5 차량 번호판
    RECEIPT = "receipt"              # 6 영수증 · 결제 화면
    DOCUMENT = "document"            # 7 문서 · 우편물 · 고지서
    QR_BARCODE = "qr_barcode"        # 8 QR · 바코드


class PIIType(str, Enum):
    """판정 단위(항목) — B 모듈이 채움"""
    PERSON_NAME = "person_name"          # 성명            (NER)
    ADDRESS = "address"                  # 주소            (NER + 정규식)
    PHONE = "phone"                      # 전화번호        (정규식)
    RRN = "rrn"                          # 주민등록번호    (정규식)
    CARD_NUMBER = "card_number"          # 카드번호        (정규식 + Luhn)
    ACCOUNT_NUMBER = "account_number"    # 계좌번호        (정규식)
    STUDENT_NUMBER = "student_number"    # 학번 · 사번     (정규식)
    TRACKING_NUMBER = "tracking_number"  # 송장번호        (정규식)
    PLATE_NUMBER = "plate_number"        # 차량번호        (정규식)
    EMAIL = "email"                      # 이메일          (정규식)
    AFFILIATION = "affiliation"          # 소속 · 학교 · 회사 (NER)
    URL = "url"                          # QR 등에서 나온 링크
    GPS = "gps"                          # EXIF 위치
    DEVICE = "device"                    # EXIF 촬영 기기
    OTHER = "other"


class RiskLevel(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# ─────────────────────────────────────────────
# 공통 도형
# ─────────────────────────────────────────────
class BBox(_Base):
    """원본 이미지 픽셀 좌표, 좌상단~우하단"""
    x1: int = Field(ge=0)
    y1: int = Field(ge=0)
    x2: int = Field(ge=0)
    y2: int = Field(ge=0)

    @model_validator(mode="after")
    def _check_order(self) -> "BBox":
        if self.x2 <= self.x1 or self.y2 <= self.y1:
            raise ValueError("bbox 는 x2>x1, y2>y1 이어야 합니다")
        return self


class Point(_Base):
    x: float
    y: float


# ─────────────────────────────────────────────
# [A] 비전 검출 모듈 출력
# ─────────────────────────────────────────────
class CodeDecode(_Base):
    """QR · 바코드 디코딩 결과 (label == qr_barcode 일 때만)"""
    decoded: bool
    format: Optional[str] = Field(None, description="QR_CODE, EAN_13, CODE_128 ...")
    payload: Optional[str] = Field(None, description="디코딩 원문. 응답 직전에 B가 마스킹 처리")


class Detection(_Base):
    id: int = Field(ge=0, description="이미지 내 고유 번호 (A가 0부터 부여)")
    label: ObjectLabel
    bbox: BBox
    det_conf: float = Field(ge=0, le=1, description="YOLO confidence")
    polygon: Optional[List[Point]] = Field(
        None, min_length=4, max_length=4,
        description="원근 보정용 네 꼭짓점 (시계방향, 좌상단부터). 없으면 bbox 사용",
    )
    code: Optional[CodeDecode] = None


# ─────────────────────────────────────────────
# [B] 판독 · 판정 모듈 출력
# ─────────────────────────────────────────────
class OCRLine(_Base):
    text: str
    conf: float = Field(ge=0, le=1)
    bbox: BBox  # 원본 이미지 좌표로 환산해서 기록 (크롭 좌표 아님)


class OCRResult(_Base):
    engine: str = Field(description="paddleocr-korean / clova / tesseract ...")
    text: str = Field(description="줄을 \\n 으로 이어붙인 전체 텍스트")
    conf: float = Field(ge=0, le=1, description="줄 conf 의 평균")
    lines: List[OCRLine] = []


class PIIItem(_Base):
    type: PIIType
    value_masked: str = Field(description="화면 표시용 마스킹 값. 예: 010-****-5678")
    method: Literal["regex", "ner", "rule", "exif", "code"]
    conf: float = Field(ge=0, le=1)
    bbox: Optional[BBox] = Field(None, description="항목이 발견된 줄 위치 → 부분 마스킹에 사용")


class RiskFactors(_Base):
    """위험도 = type_weight × readability × area_factor (산식은 B가 확정)"""
    type_weight: float = Field(ge=0, le=1, description="발견된 PII 유형 가중치 중 최댓값")
    readability: float = Field(ge=0, le=1, description="판독가능성 (OCR conf · 글자 높이 기반)")
    area_factor: float = Field(ge=0, le=1, description="이미지 대비 영역 크기 보정값")


class Risk(_Base):
    score: float = Field(ge=0, le=1)
    level: RiskLevel
    factors: Optional[RiskFactors] = None
    reason: str = Field(description="사용자에게 보여줄 근거 문장")


class Finding(Detection):
    """Detection 에 판독 · 판정 결과를 덧붙인 것 = 최종 결과 한 건"""
    ocr: Optional[OCRResult] = Field(None, description="debug=true 일 때만 응답에 포함")
    pii: List[PIIItem] = []
    risk: Risk


# ─────────────────────────────────────────────
# [D] EXIF 모듈 출력
# ─────────────────────────────────────────────
class GPS(_Base):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class ExifInfo(_Base):
    present: bool = Field(description="EXIF 존재 여부")
    gps: Optional[GPS] = None
    device: Optional[str] = Field(None, description="Make + Model")
    taken_at: Optional[datetime] = None
    software: Optional[str] = None
    orientation: Optional[int] = Field(None, ge=1, le=8, description="원본 Orientation 태그값")
    risk: Risk


# ─────────────────────────────────────────────
# 최종 API 응답  POST /api/v1/analyze
# ─────────────────────────────────────────────
class ImageInfo(_Base):
    width: int = Field(gt=0, description="방향 보정 후 가로 픽셀")
    height: int = Field(gt=0, description="방향 보정 후 세로 픽셀")
    format: Literal["jpeg", "png", "webp", "heic"]


class Summary(_Base):
    level: RiskLevel = Field(description="findings · exif 중 가장 높은 등급")
    finding_count: int = Field(ge=0)
    headline: str = Field(description="결과 화면 최상단 문장")


class Timing(_Base):
    """단계별 소요 시간(ms) — 성공 기준 '5초 이내' 측정용"""
    total_ms: int = Field(ge=0)
    exif_ms: int = Field(ge=0)
    detect_ms: int = Field(ge=0)
    ocr_ms: int = Field(ge=0)
    judge_ms: int = Field(ge=0)


class ModelVersions(_Base):
    detector: str = Field(description="예: yolov8s-pl-v1 + sahi640")
    ocr: str
    ner: Optional[str] = None


class AnalyzeResponse(_Base):
    schema_version: str = SCHEMA_VERSION
    request_id: UUID
    image: ImageInfo
    exif: ExifInfo
    findings: List[Finding]
    summary: Summary
    timing: Timing
    models: ModelVersions


class ErrorCode(str, Enum):
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    DECODE_FAILED = "DECODE_FAILED"
    TIMEOUT = "TIMEOUT"
    INTERNAL = "INTERNAL"


class ErrorBody(_Base):
    code: ErrorCode
    message: str


class ErrorResponse(_Base):
    schema_version: str = SCHEMA_VERSION
    request_id: Optional[UUID] = None
    error: ErrorBody
