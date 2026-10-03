# 아키텍처

- 기준: 2026-10-04, 백엔드를 Privacy Lens 2 로 교체한 뒤. 구현이 바뀌면 이 문서도 함께 고쳐 주세요.
- 설계 원칙·측정·한계의 자세한 설명은 [DEVELOPMENT.md](DEVELOPMENT.md)에 있습니다. 이 문서는 전체 그림입니다.
- 이전 구조(YOLO·SAHI 발표안, `schema/` v0.1.0, EasyOCR 데모)는 git 기록에 있습니다.

## 1. 구성

```
사용자 브라우저
  └─ 화면 web/frontend-demo (HTML·CSS·JS, 의존성 없음)
       │  같은 주소, 원본 파일 업로드
       ▼
  server.py (FastAPI, 무상태)
       ├─ jobqueue.py      OCR 대기열 (순서·번호표·취소·한도)
       └─ pipeline/
            ocr.py         Tesseract / PaddleOCR (외곽선 poly 포함)
            kr_patterns.py 한국 패턴·체크섬·OCR 잡음 정규화
            layout.py      글줄 좌표계 (기울어진 문서의 같은 줄·왼쪽·윗줄·거리)
            context.py     주변 문구로 심각도 판정, 라벨 뒤 이름, 운송장번호
            grouping.py    문서 단위 군집 → '함께 노출됨'
            metadata.py    EXIF GPS · QR(내용 재검사) · 바코드
            redact.py      흐리게(정보 없음)·검은색 가림, 메타데이터 제거, 재검사
            wording.py     사용자 문구 (단정 표현 차단)
```

DB 는 없습니다. 사진은 요청 처리 함수 안에서만 존재하고, 디스크(임시 파일 포함)·로그에 남기지 않습니다.

## 2. 처리 흐름

1. **업로드** — 화면이 원본 파일을 보낸다. 서버가 EXIF 방향을 화소에 반영한다(`exif_transpose`). 이후 좌표는 이 기준의 원본 픽셀.
2. **대기열** — OCR 은 한 번에 하나. 들어온 순서대로, 화면은 '앞에 N건 · 약 N초'를 묻는다.
3. **OCR** — 글자와 상자(기울어진 외곽선 포함). PaddleOCR 권장.
4. **판정** — 패턴(체크섬 포함)으로 후보를 찾고, 같은 줄 왼쪽 라벨 → 윗줄 라벨 이어받기 → 반경 안 단어 거리 순으로 가림 권장·검토 권장·참고를 정한다. 글줄 좌표계로 재서 기울어져도 같은 판단. 못 읽은 글자는 '내용 확인 불가'로 두고 내용을 지어내지 않는다.
5. **묶기** — 같은 종이(글자 군집) 안의 항목만 '함께 노출됨'으로 설명한다.
6. **확인·편집** — 사용자가 고르고, 놓친 곳을 그리고, 미리보기(`/redact/preview`)로 확인한다. 기본은 아무것도 고르지 않음.
7. **저장** — 서버가 가리고(외곽선 모양대로), 메타데이터를 지워 다시 인코딩하고, **결과 파일을 다시 검사**해 선택한 영역에서 읽히는 게 없는지 확인한다.

## 3. API

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/` | 화면 (`web/frontend-demo/privacy-lens.html`) |
| POST | `/analyze` | `image`, `mode`(full·baseline·naive), `ticket` → `report` + 미리보기 |
| POST | `/redact/preview` | `image`, `boxes`, `style`(blur·solid) → 가린 축소본. 대기열 없음 |
| POST | `/redact` | `image`, `boxes`, `style`, `ticket` → 가린 JPEG + 재검사 결과 |
| GET | `/queue` | 대기열 상태. `ticket` 을 주면 내 차례 |
| POST | `/queue/cancel` | 기다리던 요청 빼기 |

자세한 필드는 [web/frontend-demo/API_CONTRACT.md](../web/frontend-demo/API_CONTRACT.md). 오류는 `{"detail": …}` 로 400·409·413·503.

## 4. 기술 스택

| 영역 | 기술 |
|---|---|
| 백엔드 | FastAPI, Pillow, NumPy, OpenCV(QR·바코드), pillow-heif(선택) |
| OCR | PaddleOCR 3.7(`PP-OCRv6_medium_det` + `korean_PP-OCRv5_mobile_rec`, `paddlepaddle<3.3`) 또는 Tesseract 5 |
| 판정 | 정규식·체크섬(주민번호·카드 Luhn·사업자번호) + 문맥 규칙. NER·YOLO 없음 |
| 화면 | 의존성 없는 HTML/CSS/JS, Canvas(표시·편집만, 가림은 서버) |
| 검사 | pytest(백엔드), Node 스크립트(화면 정적·계약 검사) |

## 5. 개인정보 보호 설계 원칙

1. 원본 이미지를 저장하지 않는다. 업로드도 메모리에만 둔다(Starlette 의 디스크 임시 파일 기본값을 꺼 둠).
2. 인식한 문자열은 사진 주인의 화면에만 보이고, 로그·디스크에 남기지 않는다.
3. 확실성과 심각도를 섞지 않고, 점수 대신 근거를 보여 준다.
4. 다른 종이의 정보를 한 사람 것으로 묶지 않는다.
5. QR 안의 링크는 열지 않는다(호스트만 보여 줌).
6. 가린 자리에 원본 정보를 남기지 않는다(흐리게도 주변색으로 먼저 지움). 저장 파일은 다시 검사한다.
7. 외부 OCR API 로 사진을 보내지 않는다.
