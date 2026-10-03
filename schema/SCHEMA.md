# Privacy Lens 데이터 스키마 v0.2.0

기준 파일은 `schema/models.py` 하나입니다. JSON Schema와 TS 타입은 여기서 자동으로 생성합니다.

## 1. 데이터 흐름과 담당

```
업로드 ─▶ [D] EXIF 파싱 + 방향 보정 ─▶ ExifInfo
            │
            ▼ image (RGB ndarray, 원본 해상도)
        [A] detect(image) ─────────────▶ list[Detection]
            │
            ▼
        [B] read_and_judge(image, dets) ▶ list[Finding]
            │
            ▼
        [D] AnalyzeResponse 조립 ──────▶ React
```

| 필드 | 채우는 사람 |
|---|---|
| `id`, `label`, `bbox`, `det_conf`, `polygon`, `code` | A |
| `ocr`, `pii[]`, `risk` | B |
| `exif`, `image`, `summary`, `timing`, `models`, `request_id` | D |

함수 시그니처는 `schema/interfaces.py`를 따릅니다.

## 2. 반드시 지킬 규칙 5가지

1. **좌표는 방향 보정 후 원본 픽셀 기준입니다.** 서버는 맨 처음 `ImageOps.exif_transpose()`를 적용합니다. 이를 빼먹으면 세로로 찍은 폰 사진에서 박스가 엉뚱한 곳에 그려집니다.
2. **bbox는 `{x1,y1,x2,y2}` 객체입니다.** YOLO의 xywh 형식이나 정규화 좌표(0~1)를 넘기지 마세요. SAHI 결과와 크롭 OCR 줄 좌표도 원본 좌표로 환산해서 넘깁니다.
3. **PII 값은 마스킹해서만 응답합니다** (`value_masked`). 원문은 서버 메모리 안에서만 쓰고 DB에 기록하지 않습니다. DB에는 label, type, score, timing만 남깁니다.
4. **`ocr` 필드는 debug 모드에서만 채웁니다.** OCR 원문에 개인정보가 들어 있기 때문입니다.
5. **정의되지 않은 필드는 에러가 납니다** (`extra="forbid"`). 필드가 필요하면 models.py에 먼저 추가하고 PR로 공유하세요.

## 3. 검출 클래스 9종 (순서 = YOLO 클래스 인덱스)

| idx | label | 대상 |
|---|---|---|
| 0 | parcel_label | 택배 송장 |
| 1 | name_tag | 명찰 · 사원증 |
| 2 | student_id | 학생증 |
| 3 | payment_card | 카드 |
| 4 | screen | 모니터 · 노트북 · 휴대폰 화면 |
| 5 | license_plate | 차량 번호판 |
| 6 | receipt | 영수증 · 결제 화면 |
| 7 | document | 문서 · 우편물 · 고지서 |
| 8 | qr_barcode | QR · 바코드 |

YOLO `data.yaml`의 `names`는 `schema/classes.txt`를 그대로 사용합니다. C의 합성 데이터 생성기도 이 인덱스로 라벨을 출력합니다.

## 4. 위험 등급 (B가 튜닝할 초기값)

| level | score |
|---|---|
| none | 0 |
| low | < 0.3 |
| medium | 0.3 ~ 0.6 |
| high | ≥ 0.6 |

`summary.level`은 findings와 exif 가운데 가장 높은 등급입니다.

## 5. API

| 메서드 | 경로 | 응답 |
|---|---|---|
| GET | `/api/v1/health` | `{status}` |
| POST | `/api/v1/analyze` (multipart `file`) | `AnalyzeResponse` / 오류 시 `ErrorResponse` |

마스킹과 EXIF 제거본 저장은 브라우저 Canvas에서 처리합니다(PPT 설계 기준). Canvas로 다시 인코딩하면 EXIF는 자동으로 빠집니다.

## 6. 명령어

```bash
python -m schema.generate                       # JSON Schema · classes.txt 생성 + 예시 검증
npx json-schema-to-typescript -i schema/analyze_response.schema.json -o web/src/types.gen.ts
uvicorn server.mock_app:app --reload --port 8000  # 목업 API
```

## 7. 변경 이력
- 0.2.0 (2026-10-03) `OCRLine.polygon`, `PIIItem.polygon` 추가 (선택 항목, 하위 호환).
  기울어진 글자를 가리기 위한 회전 사각형 [좌상, 우상, 우하, 좌하], 원본 픽셀 좌표.
  있으면 프론트는 bbox 대신 이 모양으로 가리고, 없으면 기존처럼 bbox 를 씁니다.
- 0.1.0 (2026-09-30) 초안
