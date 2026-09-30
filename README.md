# Privacy Lens

이미지 공유 전 개인정보 노출 위험 자동 탐지 시스템
수원대학교 정보보호학과 · 시스템보안프로젝트 · 2026-2 · 4인 팀

사진을 올리면 배경에 찍힌 택배 송장, 학생증, 모니터 화면, 번호판, QR 같은 개인정보 노출 요소를 찾아냅니다. 찾은 위치를 표시하고 근거를 설명한 뒤, 가림 처리와 EXIF 제거까지 해줍니다.

## 폴더 구조

```
privacy-lens/
├── schema/            # 모듈 간 데이터 스키마 (공동)  ← 현재 v0.1.0
│   ├── models.py      #   스키마 기준 파일 (Pydantic)
│   ├── interfaces.py  #   모듈 함수 시그니처
│   ├── SCHEMA.md      #   필드 설명 · 규칙
│   ├── classes.txt    #   YOLO 클래스 9종
│   └── examples/      #   예시 응답
├── server/            # FastAPI 서버 (D)
│   └── mock_app.py    #   목업 API (모델 없이 예시 응답)
├── web/               # React 프론트 (D)
│   └── src/types.gen.ts
├── vision/            # YOLO · SAHI · QR (A)       - 예정
├── reader/            # OCR · 정규식 · NER (B)     - 예정
├── data/              # 합성 데이터 · 평가 (C)     - 예정
└── poc/               # P0 기술 검증               - 예정
```

## 시작하기

```bash
pip install -r requirements.txt
python -m schema.generate                          # 스키마 검증
uvicorn server.mock_app:app --reload --port 8000   # 목업 API
```

→ http://localhost:8000/docs 에서 사진을 올려 응답 JSON을 확인할 수 있습니다.

## 역할

| | 담당 | 산출 |
|---|---|---|
| A | 비전 검출 | 이미지 → `list[Detection]` |
| B | 판독 · 판정 | `Detection` → `list[Finding]` |
| C | 데이터 · 평가 | 학습셋 · 평가 리포트 |
| D | 서비스 · 프론트 | 동작하는 웹 서비스 |

## 협업 규칙

- `main`에 직접 push하지 않고, 브랜치를 만든 뒤 PR과 리뷰 1인 승인을 거쳐 merge합니다.
- 브랜치 이름은 `feat/<모듈>-<내용>` 형식으로 씁니다 (예: `feat/vision-sahi`).
- 스키마를 바꿀 때는 `schema/models.py`를 수정하고 `SCHEMA_VERSION`을 올린 뒤 PR에 팀 전원을 태그합니다.
- 개인정보가 담긴 실사 이미지는 커밋하지 않습니다 (`.gitignore` 참고).
