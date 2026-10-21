# 화면 ↔ 서버 규격

서버는 저장소 루트의 `server.py`(Privacy Lens 2 백엔드)이고, 화면과 같은 주소에서 나옵니다.
이 문서는 화면(`dist/api.js`, `dist/core.js`)이 쓰는 부분만 정리합니다. 기준은 서버 코드입니다.

## 좌표

- 원점은 **EXIF 방향 보정 후 원본 이미지**의 왼쪽 위, 단위는 원본 픽셀.
- 상자는 `{x, y, w, h}`. 기울어진 글자는 `poly`(꼭짓점 3~16개, `[[x, y], …]`)가 붙습니다.
- 화면은 0–1 비율로 저장하고 보낼 때 원본 픽셀로 바꿉니다(시작 내림, 끝 올림).

## POST /analyze

multipart: `image`(원본 파일), `mode`(`full` | `baseline` | `naive`), `ticket`(번호표, 선택).

```json
{
  "report": {
    "width": 1440, "height": 1000,
    "findings": [
      {"kind": "mobile", "box": {"x": 20, "y": 126, "w": 260, "h": 24, "poly": [[20,126],[280,130],[279,154],[19,150]]},
       "certainty": "read", "certainty_label": "내용 확인됨",
       "severity": "cover", "severity_label": "가림 권장",
       "message": "'연락처' 주변에서 휴대전화번호가 인식됨", "evidence_text": "010-5179-2931",
       "group_id": "g0", "context_words": ["연락처"], "detail": {}},
      {"kind": "gps", "box": null, "severity": "cover", "message": "사진 파일에 촬영 위치 좌표가 포함됨 (…)", "…": "…"}
    ],
    "groups": [{"group_id": "g0", "kinds": ["name", "mobile"], "message": "… 함께 노출됨. …", "…": "…"}],
    "elapsed_ms": 132, "ocr_backend": "paddleocr 3.7.0 · PP-OCRv6_medium_det + korean_PP-OCRv5_mobile_rec", "notes": []
  },
  "preview": "<base64 JPEG, 긴 변 1400px 이하>", "preview_scale": 1.0, "mode": "full"
}
```

- `kind`: name, mobile, landline, service_line, tollfree, email, rrn, rrn_unverified, card, brn,
  plate, address_road, address_unit, tracking, long_digits, qr, barcode, gps,
  document(문서 검출: 못 읽은 문서 영역), face_photo(문서 검출: 증명사진 영역).
  문서 검출 항목은 `detail.source == "detector"` 이고 `certainty` 는 region 입니다.
- `report.detector`: 문서 검출 모델 이름(예: `yolo:v003`). 검출을 쓰지 않았으면 빈 문자열.
- `report.detector_device`: YOLO가 실제 추론에 사용한 장치(예: `cpu`, `cuda:0`). 검출을 쓰지 않았거나 장치를 알 수 없으면 빈 문자열. 화면 하단에 OCR 모델과 함께 YOLO 버전·장치를 표시하며 검출 미사용 시 `YOLO 꺼짐`으로 표시합니다.
- `severity`: cover(가림 권장) · review(검토 권장) · info(참고). `certainty`: read · partial · region.
- `evidence_text` 는 글자를 못 읽었으면 `null` 입니다. 화면은 내용을 지어내지 않습니다.
- `box: null` 은 이미지 전체(위치정보)입니다.
- 화면은 이미지 밖으로 조금 넘친 상자는 자르고, 완전히 밖인 상자는 버립니다.

### Raw OCR 표시

`report.raw_ocr`는 `{text, box, ocr_confidence}` 배열입니다. `box`는 방향 보정 후
원본 픽셀 좌표이며 `poly`를 포함할 수 있습니다. 신뢰도는 OCR 엔진의 0~1 값으로,
개인정보 위험도를 뜻하지 않습니다. `report.raw_ocr_note`는 화면 안내 문구입니다.

- 개인정보 패턴·문맥 판정 전 모든 비어 있지 않은 OCR 조각을 반환합니다.
- Tesseract는 줄 병합 전 낱말 조각, PaddleOCR는 어댑터가 받은 인식 조각입니다.
- 최초 전체 사진 결과 뒤에 문서 확대 재판독 결과를 붙입니다. 최종 판정에 채택되지
  않은 재판독도 원본 좌표로 변환해 포함하므로 중복이 있을 수 있습니다.
- 엔진 내부 검출·인식 기준을 변경하지 않습니다. 엔진이 반환하지 않은 결과는 없습니다.
- 빈 배열은 인식 결과 없음, 필드 누락은 구버전 서버로 구분합니다.
- 화면의 `Raw OCR` 스위치는 원문 목록과 파란 외곽선을 보여 줍니다. 원문에는
  개인정보 항목의 120자·300개 제한을 적용하지 않습니다. 가림 선택·저장에는 영향을
  주지 않으며 새 이미지·재분석·초기화 시 원문과 스위치 상태를 지웁니다.
- 원문은 요청/화면 메모리에서만 사용하며 로그·디스크·브라우저 저장소에 기록하지 않습니다.

## POST /redact/preview

multipart: `image`, `boxes`(JSON 배열), `style`(`blur` | `solid`). 대기열을 거치지 않습니다.
응답 `{"preview": "<base64 JPEG>", "preview_scale": 1.0, "style": "blur"}`.

## POST /redact

multipart: `image`, `boxes`, `style`, `ticket`(선택). 대기열을 거칩니다.

```json
{"file": "<base64 JPEG, 원본 크기, 메타데이터 없음>", "bytes": 81234,
 "verification": {"selected_count": 4, "leaked_count": 0, "remaining_count": 1,
   "had_gps": true, "gps_removed": true, "leaked": [], "remaining": [ … ], "passed": true}}
```

`passed` 는 '선택한 영역마다 다시 탐지되는 것이 없고 위치정보가 남지 않음'입니다.

## GET /queue · POST /queue/cancel

- `GET /queue?ticket=…` → `{"running", "waiting", "max_waiting", "avg_s", "engine_ready", "state", "ahead", "eta_s"}`.
  `state` 는 waiting · running · unknown(아직 도착 전).
- `POST /queue/cancel?ticket=…` → `{"cancelled": true|false}`. 화면은 응답을 기다리지 않습니다(keepalive).

## 오류

FastAPI 형식 `{"detail": "사용자에게 보여도 되는 문장"}`.
400(잘못된 입력·번호표·가림 방식), 409(취소된 요청 — 화면은 조용히 무시), 413(크기),
503(대기열 가득 + `Retry-After`).
