# AGENTS.md

AI 코딩 도구(Claude Code, Codex, Cursor, GitHub Copilot 등)를 위한 이 저장소의 안내서입니다. Claude Code는 `CLAUDE.md`를 통해 이 파일을 읽습니다.

## 프로젝트

Privacy Lens — 사진을 SNS·중고거래에 올리기 전에 배경의 개인정보(택배 송장, 학생증, 모니터 화면 등)를 AI로 찾아 위치와 근거를 보여 주고, 가림 처리와 EXIF 제거까지 해 주는 웹 서비스. 수원대학교 정보보호학과 시스템보안프로젝트(2026-2), 5인 팀.

## 작업 전에

1. 사용자의 역할(1~5번)을 모르면 먼저 묻고, [docs/ROLES.md](docs/ROLES.md)에서 그 역할의 범위를 확인합니다. 요청이 없으면 다른 역할의 폴더는 고치지 않습니다.
2. [docs/PRD.md](docs/PRD.md)(무엇을·왜), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)(어떻게), [docs/DECISIONS.md](docs/DECISIONS.md)(미결 사항)를 읽습니다. 모듈 간 데이터 계약은 [schema/SCHEMA.md](schema/SCHEMA.md)입니다.
3. 문서끼리, 또는 문서와 코드가 다르면 **임의로 한쪽에 맞추지 말고** 사용자에게 알리고 `docs/DECISIONS.md`에 항목을 추가하도록 제안합니다. '미결' 항목은 한쪽으로 가정하고 구현하지 않습니다.

## 현재 방침 (2026-10-01)

- **OCR 우선**: 기존 OCR로 글자와 좌표를 얻고 정규식·문맥 규칙으로 판정하는 것부터 만듭니다. YOLO·NER·합성 데이터·추가 학습은 측정으로 필요가 확인될 때만 도입합니다.
- `schema/` v0.1.0과 README·발표안 일부는 이전 계획(YOLO 우선, 4인)을 기준으로 쓰여 있습니다. 차이는 `docs/DECISIONS.md`에 정리돼 있습니다.
- 성능 수치(PRD §9)는 **목표**입니다. 측정하기 전에 달성했다고 쓰지 않습니다.

## 규칙

- **브랜치와 PR**: `main`에 직접 push하지 않습니다. `feat/<모듈>-<내용>` 브랜치에서 작업하고 PR을 올려 리뷰 1인 승인을 받은 뒤 merge합니다.
- **스키마**: `schema/models.py`가 기준입니다. 고치면 `SCHEMA_VERSION`을 올리고 `python -m schema.generate`를 실행하고, PR에 팀 전원을 태그합니다. 정의되지 않은 필드는 스키마가 거부합니다(`extra="forbid"`).
- **좌표**: EXIF 방향 보정 후 원본 픽셀 기준의 `{x1, y1, x2, y2}`입니다. 리사이즈·타일 좌표나 xywh·정규화 좌표를 넘기지 않습니다.
- **개인정보**: 실사 이미지, OCR 원문, 실제 개인정보를 커밋·로그·외부 API로 내보내지 않습니다. 샘플과 정답에는 가상 정보만 씁니다. 응답에는 마스킹한 값(`value_masked`)만 담습니다.
- **언어와 커밋**: 문서·주석·커밋 메시지는 한국어, 식별자는 영어로 씁니다. 커밋 메시지는 `type(scope): 설명` 형식입니다(예: `feat(server): 목업 API 추가`).

## 명령어

```bash
pip install -r requirements.txt
python -m schema.generate                          # JSON Schema 생성 + 예시 검증
uvicorn server.mock_app:app --reload --port 8000   # 목업 API (http://localhost:8000/docs)
```
