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
│   └── mock_app.py    #   목업 API (모델 없이 예시 응답)
├── web/               # React 프론트 (5번)
│   └── src/types.gen.ts
├── vision/            # YOLO · SAHI · QR (3번, 조건부)  - 예정
├── reader/            # OCR · 정규식 · NER (3번)        - 예정
├── data/              # 라벨 · 평가 (1·2번)             - 예정
└── poc/               # 기술 검증 (OCR 비교 등)         - 예정
```

## 시작하기

```bash
pip install -r requirements.txt
python -m schema.generate                          # 스키마 검증
uvicorn server.mock_app:app --reload --port 8000   # 목업 API
```

→ http://localhost:8000/docs 에서 사진을 올려 응답 JSON을 확인할 수 있습니다.

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
