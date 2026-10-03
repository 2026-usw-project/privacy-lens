# Privacy Lens · 팀 서버 연동 제안 v1.0

> **미채택 데모 전용 제안입니다. 현재 팀 API 계약이 아닙니다.**
> 저장소의 기준은 `schema/models.py`, `schema/SCHEMA.md`입니다.
> 팀 API는 `/api/v1/analyze` + `file`, 좌표는 `{x1,y1,x2,y2}`를 사용합니다.
> 아래 `/api/analyze`, `image`, xywh 형식으로 팀 서버에 직접 연결하지 마세요.
> [INTEGRATION_NOTES.md](INTEGRATION_NOTES.md)에 차이와 후속 합의 사항을 기록했습니다.

현재 프론트엔드 구현과 일치하는 **제안 규격**입니다. 실제 백엔드는 포함되지 않습니다.
담당자와 합의 후 바꾸려면 dist/api.js와 dist/core.js, 계약 검사를 함께 수정하세요.

## 연결

1. 화면 상단 **데모 · 서버 미연결** → 팀 서버 모드 선택.
2. 기본 URL 입력. 예: http://127.0.0.1:8000 또는 https://privacy.example.org
3. 서버 전송 안내 확인 후 설정 적용.
4. 실제 테스트 사진 선택 → 서버 분석 → 영역 수정 → 저장.

HTTPS 또는 HTTP 루프백만 허용합니다. 주소에 계정·비밀번호·쿼리·해시는 넣지 않습니다.
경로 접두사는 가능합니다. 기본 URL이 https://example.org/lens이면
https://example.org/lens/api/analyze로 요청합니다.
샘플 이미지는 서버 설정에 관계없이 데모로 실행합니다.

기본 요청 제한 시간은 45초입니다. 취소하거나 사진을 바꾸면 이전 요청을 중단합니다.
credentials: omit, cache: no-store, redirect: error로 요청합니다.
현재 인증 헤더/로그인은 구현하지 않았습니다.

## 좌표 규칙 — 반드시 먼저 합의

- 원점: **방향 보정된 원본 이미지의 왼쪽 위**.
- x는 오른쪽, y는 아래로 증가. 단위는 원본 픽셀.
- bbox는 {x, y, width, height}. 오른쪽/아래 끝은 x + width, y + height.
- 브라우저가 업로드 이미지를 방향 보정한 상태로 PNG 재인코딩하고 서버에 보냅니다.
- 서버는 받은 PNG를 다시 EXIF 회전하지 않습니다.
- 모델 입력을 축소하거나 타일로 나눠도 응답은 업로드 PNG 크기로 환산합니다.
- 화면 확대/축소 비율은 전송하지 않습니다.
- 프론트엔드는 내부적으로 0–1 비율을 저장하고, 내보낼 때 시작점을 내림,
  끝점을 올림해 영역을 충분히 덮는 정수 좌표로 변환합니다.
- 서버는 실제 디코딩 크기, 좌표 유한성·양수 크기·범위를 다시 검증해야 합니다.

## 1. POST /api/analyze

요청: multipart/form-data (boundary는 브라우저가 설정).

| 필드 | 형식 | 내용 |
|---|---|---|
| image | PNG 파일, input.png | 방향 보정된 원본 해상도 이미지 |

성공: HTTP 200, Content-Type: application/json.

```json
{
  "analysis_id": "analysis-demo-001",
  "status": "partial",
  "coordinate_space": "oriented_original_pixels",
  "width": 1440,
  "height": 1000,
  "regions": [
    {
      "id": "region-001",
      "type": "ADDRESS",
      "bbox": {"x": 212, "y": 440, "width": 632, "height": 77},
      "label": "송장 · 상세 주소",
      "evidence": "배송지의 도로명과 상세 주소가 함께 노출됩니다.",
      "text_preview": "가상시 안심구 · 상세 주소",
      "ocr_status": "ok"
    },
    {
      "id": "region-002",
      "type": "UNKNOWN",
      "bbox": {"x": 935, "y": 688, "width": 404, "height": 45},
      "label": "배경 화면 · 작은 글자",
      "evidence": "영역은 찾았지만 글자를 판독하지 못했습니다.",
      "text_preview": "",
      "ocr_status": "failed"
    }
  ],
  "warnings": ["일부 영역은 직접 확인이 필요합니다."]
}
```

- status: completed 또는 partial.
- 탐지 없음: completed + regions: []. 안전 판정으로 표시하지 않습니다.
- 일부 OCR 실패: partial + 해당 항목 ocr_status: failed.
  실패 영역도 기본 가림 대상으로 선택됩니다.
- type: NAME, PHONE, ADDRESS, STUDENT_ID, ORGANIZATION, EMAIL,
  BARCODE, DOCUMENT, UNKNOWN, CUSTOM. 모르는 값은 UNKNOWN으로 표시합니다.
- id는 비어 있지 않은 고유 문자열(최대 80자); 최대 300개 영역.
- width/height가 보낸 PNG와 다르거나 좌표 범위를 벗어나면 화면에서 응답을 거절합니다.
- label, evidence, text_preview는 일반 문자열입니다. HTML로 렌더링하지 않습니다.
- text_preview는 서버에서 일부 가린 짧은 요약을 권장합니다.
- analysis_id는 선택 필드이며 다음 저장 요청에서 그대로 전달됩니다.
- 프론트엔드는 사용자에게 성능/안전 보증을 표시하지 않습니다.

## 2. POST /api/redact

요청: multipart/form-data.

| 필드 | 형식 | 내용 |
|---|---|---|
| image | PNG 파일, input.png | 분석 시 사용한 방향·크기의 이미지 재전송 |
| request | JSON 문자열 | 아래 최종 영역·가림 옵션 |

```json
{
  "schema_version": "1.0",
  "coordinate_space": "oriented_original_pixels",
  "image": {"width": 1440, "height": 1000},
  "analysis_id": "analysis-demo-001",
  "regions": [
    {
      "id": "region-001",
      "type": "ADDRESS",
      "bbox": {"x": 212, "y": 440, "width": 632, "height": 77}
    },
    {
      "id": "custom-1",
      "type": "EMAIL",
      "bbox": {"x": 935, "y": 688, "width": 404, "height": 45}
    }
  ],
  "redaction": {"style": "solid", "strength": 80, "color": "#223a2d"},
  "remove_metadata": true,
  "output_format": "png"
}
```

사용자가 **선택한** 영역만 포함합니다. 삭제/해제 항목은 제외합니다.
직접 추가한 영역도 동일한 bbox 규칙을 사용합니다.
목록이 비어 있으면 가림 없이 촬영 메타데이터를 제외한 파일을 요청합니다.

style: pixel(모자이크), blur, solid.
strength는 UI의 0–100 값으로 서버는 범위를 검증하세요. solid에서는 무시합니다.
단색은 지정한 color로 불투명하게 덮습니다. 세부 픽셀/블러 알고리즘은 팀에서 합의해야 하며
프론트엔드 미리보기와 서버 결과가 다를 수 있어 **서버가 반환한 파일로 최종 미리보기**를 보여줍니다.

성공: HTTP 200, Content-Type: image/png, 본문은 **PNG 바이너리**.
JSON 다운로드 URL을 반환하는 규격은 지원하지 않습니다.
입력과 정확히 같은 폭/높이를 반환하세요.
원본 EXIF·XMP·GPS·촬영 기기 정보를 복사하지 마세요.
프론트엔드는 PNG 시그니처, 128 MiB 이하 크기, 실제 디코딩 해상도를 검증합니다.
서버 메타데이터 제거 여부는 백엔드 테스트에서 별도로 확인해야 합니다.

## 오류

HTTP 400(잘못된 입력), 413(크기 초과), 422(처리 불가), 500/503(서버 오류) 등을 반환합니다.

```json
{"error": {"code": "OCR_UNAVAILABLE", "message": "글자 판독 서비스에 연결할 수 없습니다."}}
```

사용자에게 보여도 되는 message만 포함하세요. 파일 경로, 인식한 개인정보, 스택 트레이스는 제외합니다.
프론트엔드는 분석 오류 시 재시도/직접 편집을, 저장 오류 시 재시도 안내를 제공합니다.
프론트엔드의 취소는 서버 연산·보관 종료를 보장하지 않으므로 백엔드에도 취소/정리 정책이 필요합니다.

## CORS·보관·용량

- 로컬 화면 출처: http://127.0.0.1:4173. 다른 포트라면 출처도 바뀝니다.
- 서버는 허용할 출처를 명시하고 POST/OPTIONS를 처리하세요. 프론트엔드는 쿠키를 보내지 않습니다.
- file:// 직접 실행의 null Origin 허용보다 로컬 HTTP 실행을 권장합니다.
- 원본 파일 선택 제한 20 MiB와 변환된 PNG 크기는 다릅니다. 서버 업로드 한도는
  24 MP PNG를 감당하도록 별도로 합의하고, 디코딩 후 픽셀 수를 검증하세요.
- 저장 때 이미지를 다시 보내므로 서버가 분석 원본을 계속 보관할 필요가 없습니다.
- 입력·임시 파일은 각 요청 완료/오류/취소에 정리하고, 이미지/OCR 원문을 DB·로그에 저장하지 않는
  계획을 백엔드에서 구현·검증하세요.
- 이 문서는 구현 제안이며 프론트엔드만으로 서버 삭제를 보장하지 않습니다.

## 합동 연동 점검

정상 / 빈 결과 / 일부 OCR 실패 / 잘못된 좌표 / 해상도 불일치 /
400·413·500 / 타임아웃 / 취소 / 새 사진으로 바꾸기 /
수정된 박스와 직접 추가 영역 / 선택 해제·삭제 / 단색 출력 픽셀 /
PNG 해상도·메타데이터 / 세로 JPEG 방향을 확인합니다.

자동 통신 검사는 가짜 fetch 응답을 사용합니다. 실제 YOLO·OCR 서버 성능을 검증한 결과는 아닙니다.
