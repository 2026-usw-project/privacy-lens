# 아키텍처

- 기준: 2026-10-01. 구현이 진행되면 이 문서도 함께 고쳐 주세요.
- 모듈 사이의 데이터 계약은 [schema/SCHEMA.md](../schema/SCHEMA.md)와 `schema/models.py`가 기준입니다. 이 문서는 전체 그림과 기술 선택을 설명합니다.
- `(D-xx)`는 [DECISIONS.md](DECISIONS.md)의 미결 사항입니다.

## 1. 구성

```
사용자
  └─ 웹 클라이언트 (React + Canvas): 결과 표시 · 영역 편집 · 미리보기
       └─ API 서버 (FastAPI): 업로드 수신 · EXIF · 작업 관리 (+ 가림·EXIF 제거, 위치 미정)
            ├─ AI 분석 모듈: OCR → 개인정보 판정 (우선) / 객체 검출 · NER (조건부)
            └─ DB (PostgreSQL): 비식별 작업 기록만 (이미지·OCR 원문 없음)
```

## 2. 처리 흐름 (현재 방침: OCR 우선)

1. 업로드를 받아 EXIF를 파싱하고 방향을 보정한다(`ImageOps.exif_transpose`). 이후 모든 좌표는 이 보정 후 원본 해상도 기준이다.
2. OCR로 글자와 좌표를 추출한다. 작은 글자가 문제면 원본 해상도·분할(타일) OCR을 비교한다.
3. 개인정보를 판정한다. 전화번호·이메일 같은 형식은 정규식으로, 주소·이름은 주변 문맥과 규칙으로 판정한다. 규칙만으로 부족한 사례가 확인되면 NER 등을 비교한다.
4. 글자와 위치를 연결한다. 여러 줄로 나뉜 주소를 한 항목으로 묶고, 같은 항목의 중복 검출을 정리한다.
5. 결과를 만든다: 유형, 위치, 근거 문장, 판독 불가·판정 불확실 상태, 위험도.
6. 사용자가 결과를 확인하고 영역을 추가·삭제·이동·크기 변경한 뒤 가릴 영역을 고른다.
7. 최종 좌표로 가림 처리하고 EXIF를 제거해 내려받게 한다. 처리 위치는 미정이다 (D-05).

발표안(2026-09-16)은 1단계 뒤에 "SAHI 타일(640px, 30% 중첩) + YOLO로 9종 객체 후보를 검출 → 검출 영역만 원본 해상도로 크롭해 OCR"을 넣고, 판정에 NER을 함께 쓰는 구조였습니다. 현재 방침에서는 이 부분이 조건부입니다. 9종은 `schema/classes.txt`(택배 송장, 명찰·사원증, 학생증, 카드, 화면, 차량 번호판, 영수증, 문서·우편물·고지서, QR·바코드)입니다.

## 3. 모듈 경계와 계약

현재 스키마(v0.1.0)의 흐름은 발표안 기준입니다.

EXIF 파싱·방향 보정 → `Detector.detect(image)` → `Reader.read_and_judge(image, detections)` → 응답 조립

- `image`는 EXIF 방향 보정이 끝난 원본 해상도 RGB 배열(`numpy`)입니다.
- 함수 시그니처는 [schema/interfaces.py](../schema/interfaces.py)에 있습니다.
- OCR 우선 방침에서는 3번이 "함수 하나를 호출하면 정해진 형식의 결과가 나오는" 모듈을 제공하는 것이 목표입니다. 그 형식(스키마 개정 포함)은 미정입니다 (D-01).

꼭 지킬 규칙 (`schema/SCHEMA.md` §2):

1. 좌표는 방향 보정 후 원본 픽셀 기준
2. bbox는 `{x1, y1, x2, y2}` (xywh·정규화 좌표 금지)
3. 개인정보는 마스킹한 값(`value_masked`)만 응답하고, 원문은 서버 메모리 안에서만 쓰며 DB에 기록하지 않음
4. `ocr` 필드는 debug 모드에서만 채움
5. 정의되지 않은 필드는 오류(`extra="forbid"`). 필요하면 `models.py`부터 고치고 PR로 공유

## 4. API

| 메서드 | 경로 | 설명 | 상태 |
|---|---|---|---|
| GET | `/api/v1/health` | 상태 확인 | 목업 구현됨 |
| POST | `/api/v1/analyze` | 이미지 업로드(`multipart`, 필드명 `file`) → `AnalyzeResponse` 또는 `ErrorResponse` | 목업 구현됨 (고정 예시 응답) |

5인 분담안에서 4번이 추가로 정할 것: 분석 상태·결과 조회, 사용자가 수정한 영역 제출, 보호 처리된 이미지 다운로드, 작업 ID·상태 관리, 타임아웃·동시 실행 제한, 요청 취소.

- 목업(`server/mock_app.py`)의 업로드 한도는 20MB이고, CORS는 `http://localhost:5173`만 허용합니다.
- 오류 코드: `UNSUPPORTED_FORMAT`, `FILE_TOO_LARGE`, `DECODE_FAILED`, `TIMEOUT`, `INTERNAL`
- 지원 이미지 형식(스키마): jpeg, png, webp, heic

## 5. 기술 스택

| 영역 | 기술 | 상태 |
|---|---|---|
| 백엔드 | FastAPI, Pydantic v2, Pillow, NumPy | 사용 중 (`requirements.txt`) |
| 프론트엔드 | React + HTML5 Canvas (타입은 JSON Schema에서 자동 생성) | 계획 |
| DB | PostgreSQL: 작업 시간·오류 유형·모델 버전 같은 비식별 기록만 | 계획 |
| OCR | PaddleOCR(korean) / 외부 OCR API / Tesseract | 후보. 같은 이미지로 비교해 선정 (D-06) |
| 개인정보 판정 | 정규식 룰셋(카드번호는 Luhn 검증), 문맥 규칙 | 우선 구현 |
| NER | KoELECTRA NER | 조건부 |
| 객체 검출 | YOLOv8/v11 + SAHI (640px 타일, 30% 중첩, NMS) | 조건부 |
| QR·바코드 | OpenCV WeChatQRCode, pyzbar | 후보. QR·바코드를 범위에 넣을 때 |
| EXIF | piexif, exifread | 후보 |

## 6. 개인정보 보호 설계 원칙

이 서비스는 개인정보를 다루는 도구이므로 아래를 기본값으로 둡니다.

1. 원본 이미지는 DB에 저장하지 않는다. 임시 파일·결과 파일은 정상 종료뿐 아니라 실패·취소 때도 정리한다.
2. 개인정보 원문은 서버 메모리 안에서만 쓰고, 응답에는 마스킹한 값만 담는다.
3. OCR 원문은 debug 모드에서만 응답에 넣고, 로그에는 남기지 않는다.
4. DB에는 유형·점수·시간·모델 버전 같은 비식별 지표만 기록한다.
5. 학습·평가에는 가상 정보와 팀원이 직접 촬영한 사진만 쓴다. 실사 이미지는 git에 올리지 않는다.
6. 외부 서비스(외부 OCR API 등)로 사진이나 크롭을 보내는 설계는 먼저 팀에서 합의한다 (D-06).

## 7. 실행

```bash
pip install -r requirements.txt
python -m schema.generate                          # JSON Schema 생성 + 예시 검증
uvicorn server.mock_app:app --reload --port 8000   # 목업 API → http://localhost:8000/docs
```

## 8. 폴더와 담당

README의 폴더 구조를 새 역할 번호에 대응시킨 표입니다. 없는 폴더는 처음 작업하는 사람이 만듭니다.

| 폴더 | 내용 | 담당 |
|---|---|---|
| `schema/` | 모듈 간 데이터 계약 | 공동 (변경 시 전원 태그) |
| `server/` | FastAPI 서버 (현재는 목업) | 4 |
| `web/` | React 프론트 (현재는 타입 파일뿐) | 5 |
| `reader/` (예정) | OCR · 정규식 · NER | 3 |
| `vision/` (예정) | YOLO · SAHI · QR. 객체 검출을 도입할 때 | 3 |
| `data/` (예정) | 라벨 · 평가 | 1·2 |
| `poc/` (예정) | 기술 검증 (OCR 비교 등) | 3 |
