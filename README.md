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
├── vision/            # (A) 2단계 OCR · QR 디코딩            ← 데모 v0.2
├── reader/            # (B) 정규식 판정 · 영역 묶기 · 위험도  ← 데모 v0.2
├── server/            # (D) FastAPI — app.py(실제) · mock_app.py(목업) · exif.py · pipeline.py
├── web/               # (D) React — 업로드 · 박스 오버레이 · 모자이크 · 안전본 저장
├── data/              # (C) synth/ 가짜 송장·학생증 합성기 · eval.py 평가
└── tests/             # 단위 테스트 (pytest)
```

## 데모 실행 (v0.2)

```bash
pip install -r requirements.txt          # 처음 한 번 (torch 포함이라 몇 분 걸림)
cd web && npm install && npm run build && cd ..
python -m data.synth.compose --n 12 --neg 3 --out data/demo   # 가짜 송장 사진 15장 생성
uvicorn server.app:app --port 8000
```

→ http://localhost:8000 에서 `data/demo/` 사진을 끌어다 놓으면 됩니다. 첫 실행 때 OCR 모델(약 100MB)을 GitHub에서 자동으로 받습니다.

| 명령 | 용도 |
|---|---|
| `python -m data.eval --dir data/demo` | 재현율 · 오탐 · 응답 시간 측정 |
| `python -m pytest -q tests` | 단위 테스트 |
| `PL_MOCK=1 uvicorn server.app:app` | 모델 없이 목업 응답 (프론트 개발용) |
| `cd web && npm run dev` | 프론트 개발 서버 (5173, API는 8000으로 프록시) |
| `PL_GPU=1` / `PL_OCR_ENGINE=paddle` | GPU 사용 / PaddleOCR로 교체 |

### 데모 v0.2 동작 방식
YOLO 학습 전 단계라서, **OCR로 읽은 글자 줄 중 개인정보가 나온 줄들을 가까운 것끼리 묶은 범위**를 영역으로 씁니다.

1. EXIF에서 GPS · 기기 정보 추출 → 방향 보정
2. 글자 위치는 1280px 축소본에서 찾고, 글자 인식은 원본 해상도에서 수행 (2단계 OCR)
3. QR 디코딩 (1600px 축소본)
4. 정규식 · 키워드로 개인정보 판정 → 줄 묶기 → 키워드로 문서 종류 추정
5. 위험도 = 유형 가중치 × 판독가능성 × 크기 보정, 근거 문장 생성

YOLO가 완성되면 4단계의 "줄 묶기"만 YOLO 박스로 바꾸면 됩니다. 응답 스키마는 그대로 유지됩니다.

### 합성 사진 15장 측정 결과 (2코어 CPU)
| 항목 | 결과 | 목표 |
|---|---|---|
| PII 항목 재현율 | 92% (67/73) | 85% |
| 문서 검출 | 15/15 | — |
| 오탐 (개인정보 없는 사진) | 0/3 | 15% 이하 |
| GPS 검출 | 6/6 | 100% |
| 응답 시간 | 평균 6.5초 · 최대 9.9초 | 5초 |

※ 합성 사진은 실사보다 쉽습니다. 실사 테스트셋으로 다시 측정해야 합니다.

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
