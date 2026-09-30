/* 자동 생성 파일 — 직접 수정 금지. schema/models.py 수정 후 재생성 */

export type SchemaVersion = string;
export type RequestId = string;
/**
 * 방향 보정 후 가로 픽셀
 */
export type Width = number;
/**
 * 방향 보정 후 세로 픽셀
 */
export type Height = number;
export type Format = "jpeg" | "png" | "webp" | "heic";
/**
 * EXIF 존재 여부
 */
export type Present = boolean;
export type Lat = number;
export type Lon = number;
/**
 * Make + Model
 */
export type Device = string | null;
export type TakenAt = string | null;
export type Software = string | null;
/**
 * 원본 Orientation 태그값
 */
export type Orientation = number | null;
export type Score = number;
export type RiskLevel = "none" | "low" | "medium" | "high";
/**
 * 발견된 PII 유형 가중치 중 최댓값
 */
export type TypeWeight = number;
/**
 * 판독가능성 (OCR conf · 글자 높이 기반)
 */
export type Readability = number;
/**
 * 이미지 대비 영역 크기 보정값
 */
export type AreaFactor = number;
/**
 * 사용자에게 보여줄 근거 문장
 */
export type Reason = string;
/**
 * 이미지 내 고유 번호 (A가 0부터 부여)
 */
export type Id = number;
/**
 * 검출 클래스 9종 (YOLO 클래스 인덱스 순서와 동일하게 유지)
 */
export type ObjectLabel =
  | "parcel_label"
  | "name_tag"
  | "student_id"
  | "payment_card"
  | "screen"
  | "license_plate"
  | "receipt"
  | "document"
  | "qr_barcode";
export type X1 = number;
export type Y1 = number;
export type X2 = number;
export type Y2 = number;
/**
 * YOLO confidence
 */
export type DetConf = number;
/**
 * 원근 보정용 네 꼭짓점 (시계방향, 좌상단부터). 없으면 bbox 사용
 */
export type Polygon = [Point, Point, Point, Point] | null;
export type X = number;
export type Y = number;
export type Decoded = boolean;
/**
 * QR_CODE, EAN_13, CODE_128 ...
 */
export type Format1 = string | null;
/**
 * 디코딩 원문. 응답 직전에 B가 마스킹 처리
 */
export type Payload = string | null;
/**
 * paddleocr-korean / clova / tesseract ...
 */
export type Engine = string;
/**
 * 줄을 \n 으로 이어붙인 전체 텍스트
 */
export type Text = string;
/**
 * 줄 conf 의 평균
 */
export type Conf = number;
export type Text1 = string;
export type Conf1 = number;
export type Lines = OCRLine[];
/**
 * 판정 단위(항목) — B 모듈이 채움
 */
export type PIIType =
  | "person_name"
  | "address"
  | "phone"
  | "rrn"
  | "card_number"
  | "account_number"
  | "student_number"
  | "tracking_number"
  | "plate_number"
  | "email"
  | "affiliation"
  | "url"
  | "gps"
  | "device"
  | "other";
/**
 * 화면 표시용 마스킹 값. 예: 010-****-5678
 */
export type ValueMasked = string;
export type Method = "regex" | "ner" | "rule" | "exif" | "code";
export type Conf2 = number;
export type Pii = PIIItem[];
export type Findings = Finding[];
/**
 * findings · exif 중 가장 높은 등급
 */
export type RiskLevel1 = "none" | "low" | "medium" | "high";
export type FindingCount = number;
/**
 * 결과 화면 최상단 문장
 */
export type Headline = string;
export type TotalMs = number;
export type ExifMs = number;
export type DetectMs = number;
export type OcrMs = number;
export type JudgeMs = number;
/**
 * 예: yolov8s-pl-v1 + sahi640
 */
export type Detector = string;
export type Ocr = string;
export type Ner = string | null;

export interface AnalyzeResponse {
  schema_version?: SchemaVersion;
  request_id: RequestId;
  image: ImageInfo;
  exif: ExifInfo;
  findings: Findings;
  summary: Summary;
  timing: Timing;
  models: ModelVersions;
}
export interface ImageInfo {
  width: Width;
  height: Height;
  format: Format;
}
export interface ExifInfo {
  present: Present;
  gps?: GPS | null;
  device?: Device;
  taken_at?: TakenAt;
  software?: Software;
  orientation?: Orientation;
  risk: Risk;
}
export interface GPS {
  lat: Lat;
  lon: Lon;
}
export interface Risk {
  score: Score;
  level: RiskLevel;
  factors?: RiskFactors | null;
  reason: Reason;
}
/**
 * 위험도 = type_weight × readability × area_factor (산식은 B가 확정)
 */
export interface RiskFactors {
  type_weight: TypeWeight;
  readability: Readability;
  area_factor: AreaFactor;
}
/**
 * Detection 에 판독 · 판정 결과를 덧붙인 것 = 최종 결과 한 건
 */
export interface Finding {
  id: Id;
  label: ObjectLabel;
  bbox: BBox;
  det_conf: DetConf;
  polygon?: Polygon;
  code?: CodeDecode | null;
  /**
   * debug=true 일 때만 응답에 포함
   */
  ocr?: OCRResult | null;
  pii?: Pii;
  risk: Risk;
}
/**
 * 원본 이미지 픽셀 좌표, 좌상단~우하단
 */
export interface BBox {
  x1: X1;
  y1: Y1;
  x2: X2;
  y2: Y2;
}
export interface Point {
  x: X;
  y: Y;
}
/**
 * QR · 바코드 디코딩 결과 (label == qr_barcode 일 때만)
 */
export interface CodeDecode {
  decoded: Decoded;
  format?: Format1;
  payload?: Payload;
}
export interface OCRResult {
  engine: Engine;
  text: Text;
  conf: Conf;
  lines?: Lines;
}
export interface OCRLine {
  text: Text1;
  conf: Conf1;
  bbox: BBox;
}
export interface PIIItem {
  type: PIIType;
  value_masked: ValueMasked;
  method: Method;
  conf: Conf2;
  /**
   * 항목이 발견된 줄 위치 → 부분 마스킹에 사용
   */
  bbox?: BBox | null;
}
export interface Summary {
  level: RiskLevel1;
  finding_count: FindingCount;
  headline: Headline;
}
/**
 * 단계별 소요 시간(ms) — 성공 기준 '5초 이내' 측정용
 */
export interface Timing {
  total_ms: TotalMs;
  exif_ms: ExifMs;
  detect_ms: DetectMs;
  ocr_ms: OcrMs;
  judge_ms: JudgeMs;
}
export interface ModelVersions {
  detector: Detector;
  ocr: Ocr;
  ner?: Ner;
}
