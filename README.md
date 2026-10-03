# Privacy Lens

이미지 공유 전 개인정보 노출 위험 자동 탐지 시스템
수원대학교 정보보호학과 · 시스템보안프로젝트 · 2026-2 · 5인 팀

사진을 올리면 배경에 찍힌 택배 송장, 학생증, 모니터 화면, 번호판, QR 같은 개인정보 노출 요소를 찾아냅니다. 찾은 위치를 표시하고 근거를 설명한 뒤, 가림 처리와 EXIF 제거까지 해줍니다.

## 문서

| 문서 | 내용 |
|---|---|
| [docs/PRD.md](docs/PRD.md) | 무엇을 왜 만드는지, 기능 요구사항, 성공 기준, 일정 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 처리 흐름, 모듈 경계, 기술 스택, 개인정보 설계 원칙 |
| [docs/ROLES.md](docs/ROLES.md) | 5인 역할과 경계, 역할별 첫 작업과 완료 기준 |
| [docs/DECISIONS.md](docs/DECISIONS.md) | 현재 기준과 미결 사항 (자료끼리 다를 때 먼저 볼 것) |
| [schema/SCHEMA.md](schema/SCHEMA.md) | 모듈 간 데이터 계약 |

## AI와 함께 작업하기

- **Claude Code**: 저장소 루트에서 실행하면 `CLAUDE.md` → `AGENTS.md`를 자동으로 읽습니다.
- **Codex · Cursor · GitHub Copilot 등 `AGENTS.md`를 지원하는 도구**: 이 파일을 읽습니다.
- **ChatGPT · Gemini 웹처럼 저장소를 직접 읽지 못하는 도구**: `docs/PRD.md`, `docs/ROLES.md`(내 역할 부분), `docs/DECISIONS.md`를 붙여 넣으세요.

어느 도구든 첫 메시지에 역할을 알려 주면 범위를 벗어나지 않고 도와줍니다.

> 나는 Privacy Lens 프로젝트의 N번(역할 이름) 담당이야. AGENTS.md와 docs/ 문서를 먼저 읽고, 내 역할 범위 안에서 도와줘. 문서와 코드가 서로 다르면 임의로 고치지 말고 알려줘.

## 폴더 구조

```
privacy-lens/
├── AGENTS.md          # AI 도구용 안내 (CLAUDE.md가 이 파일을 가져옴)
├── docs/              # PRD · 아키텍처 · 역할 · 결정 사항
├── schema/            # 모듈 간 데이터 스키마 (공동)  ← 현재 v0.1.0
│   ├── models.py      #   스키마 기준 파일 (Pydantic)
│   ├── interfaces.py  #   모듈 함수 시그니처
│   ├── SCHEMA.md      #   필드 설명 · 규칙
│   ├── classes.txt    #   YOLO 클래스 9종
│   └── examples/      #   예시 응답
├── server/            # FastAPI 서버 (4번)
│   ├── app.py         #   데모 v0.2 실제 파이프라인 API
│   ├── pipeline.py    #   EXIF → OCR → QR → 판정 조립
│   ├── exif.py        #   EXIF · GPS 파싱
│   └── mock_app.py    #   목업 API (모델 없이 예시 응답)
├── web/               # React 프론트 (5번) — 데모 v0.2 업로드 · 오버레이 · 모자이크 · 저장
├── vision/            # 데모 v0.2: OCR 래퍼 · QR (3번)  ※ 위치 논의 필요, 아래 참고
├── reader/            # 데모 v0.2: 정규식 판정 · 줄 묶기 · 위험도 (3번)
├── data/              # 데모 v0.2: 합성 테스트 사진 생성기 · 평가 스크립트 (1·2번)
├── tests/             # 단위 테스트 (pytest)
└── poc/               # 기술 검증 (OCR 비교 등)         - 예정
```

## 시작하기

```bash
pip install -r requirements.txt
python -m schema.generate                          # 스키마 검증
uvicorn server.mock_app:app --reload --port 8000   # 목업 API
```

→ http://localhost:8000/docs 에서 사진을 올려 응답 JSON을 확인할 수 있습니다.

## 데모 v0.2 (OCR 우선 방침의 첫 동작본)

```bash
pip install -r requirements.txt          # torch 포함이라 처음 한 번 몇 분 걸림
cd web && npm install && npm run build && cd ..
python -m data.synth.compose --n 12 --neg 3 --out data/demo   # 가상 정보 테스트 사진 15장
uvicorn server.app:app --port 8000       # → http://localhost:8000
```

첫 실행 때 EasyOCR 모델(약 100MB)을 GitHub에서 자동으로 받습니다. 서비스 경로는 로컬 OCR만 사용합니다(D-06의 (a)).

| 명령 | 용도 |
|---|---|
| `python -m data.eval --dir data/demo` | 항목별 재현율 · 오탐 · 응답 시간 |
| `python -m pytest -q tests` | 단위 테스트 15개 |
| `PL_MOCK=1 uvicorn server.app:app` | 목업 응답 (프론트 개발용) |
| `cd web && npm run dev` | 프론트 개발 서버 (5173 → API 8000 프록시) |
| `PL_GPU=1` / `PL_OCR_ENGINE=paddle` | GPU 사용 / PaddleOCR 교체 (paddle은 미검증) |

**동작 방식:** EXIF 파싱·방향 보정 → 글자 위치는 1280px 축소본에서 찾고 인식은 원본 해상도에서 수행(2단계 OCR) → QR 디코딩 → 정규식·문맥 규칙으로 판정 → 가까운 줄끼리 묶어 영역 생성 → 위험도·근거 문장.

**합성 사진 15장 측정 (2코어 CPU, 실사 아님):** 항목 재현율 92% (67/73) · 문서 검출 15/15 · 비위험 사진 오탐 0/3 · GPS 6/6 · 평균 6.5초 / 최대 9.9초. 합성 사진은 실사보다 쉬우므로 실사 테스트셋으로 다시 재야 합니다.

**미결 사항과의 관계 (임시 선택 — 팀 결정에 따라 바꿀 것):**
- D-05 가림·EXIF 제거 위치: 데모는 `SCHEMA.md` §5대로 **브라우저 Canvas**에서 처리합니다. 백엔드 처리로 정해지면 `web/src/mask.ts` 대신 서버 API로 옮기면 됩니다.
- D-04 지표: 데모 평가는 항목 단위 재현율을 주 지표로 씁니다(mAP 미사용).
- 합성 데이터: 학습용이 아니라 **데모·회귀 테스트용 가상 정보 사진**으로만 씁니다. D-07(EXIF 검증 샘플)에도 쓸 수 있습니다.
- 폴더: OCR 래퍼가 `vision/`에 있지만 ROLES.md 기준으로는 `reader/`가 맞을 수 있습니다. 3번 담당과 정해 옮기세요.

## 역할

| # | 담당 | 산출 |
|---|---|---|
| 1 | 데이터 구축 | 데이터셋 · 라벨링 기준서 |
| 2 | 평가 · 통합 지원 | 평가 코드 · 오류 목록 · 성능 보고서 |
| 3 | AI 분석 | OCR · 개인정보 판정 모듈 |
| 4 | 백엔드 | API · 보호 처리 · 배포 서버 |
| 5 | 프론트엔드 | 웹 화면 · 영역 편집 기능 |

1·2번은 2명이 함께 맡습니다. 자세한 책임과 완료 기준은 [docs/ROLES.md](docs/ROLES.md)를 봅니다.

## 협업 규칙

- `main`에 직접 push하지 않고, 브랜치를 만든 뒤 PR과 리뷰 1인 승인을 거쳐 merge합니다.
- 브랜치 이름은 `feat/<모듈>-<내용>` 형식으로 씁니다 (예: `feat/vision-sahi`).
- 스키마를 바꿀 때는 `schema/models.py`를 수정하고 `SCHEMA_VERSION`을 올린 뒤 PR에 팀 전원을 태그합니다.
- 개인정보가 담긴 실사 이미지는 커밋하지 않습니다 (`.gitignore` 참고).
