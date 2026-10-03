# AGENTS.md

AI 코딩 도구(Claude Code, Codex, Cursor, GitHub Copilot 등)를 위한 이 저장소의 안내서입니다. Claude Code는 `CLAUDE.md`를 통해 이 파일을 읽습니다.

## 프로젝트

Privacy Lens — 사진을 SNS·중고거래에 올리기 전에 배경의 개인정보(택배 송장, 학생증, 모니터 화면 등)를 찾아 위치와 근거를 보여 주고, 가림 처리와 EXIF 제거까지 해 주는 웹 서비스. 수원대학교 정보보호학과 시스템보안프로젝트(2026-2), 5인 팀.

## 현재 구조 (2026-10-04 백엔드 교체 후)

- **백엔드는 Privacy Lens 2** 를 그대로 가져온 것입니다(`pipeline/`, `server.py`, `jobqueue.py`, `run.py`, `eval/`, `samples/`, `tests/`). 기준은 이 코드와 [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)의 설계 원칙입니다.
- **화면은 `web/frontend-demo/`** 입니다. `dist/` 가 편집 원본이고 `scripts/build.mjs` 가 `privacy-lens.html` 로 묶습니다. 서버가 `/` 에서 이 파일을 내줍니다.
- 이전의 `server/`·`reader/`·`vision/`·`schema/`·`data/`·React 앱은 삭제했습니다. [docs/DECISIONS.md](docs/DECISIONS.md)의 '교체로 사실상 정해진 것'을 먼저 봅니다.

## 작업 전에

1. 사용자의 역할(1~5번)을 모르면 먼저 묻고, [docs/ROLES.md](docs/ROLES.md)에서 그 역할의 범위를 확인합니다. ROLES 의 폴더 이름은 교체 전 기준이니 지금 구조로 바꿔 읽습니다.
2. [README.md](README.md)(개요·실행), [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)(설계 원칙·측정·한계·버그 기록), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)(흐름·API), [docs/DECISIONS.md](docs/DECISIONS.md)(결정·미결)를 읽습니다.
3. 문서끼리, 또는 문서와 코드가 다르면 임의로 한쪽에 맞추지 말고 사용자에게 알립니다.

## 규칙

- **브랜치와 PR**: `main`에 직접 push하지 않습니다. `feat/<모듈>-<내용>` 브랜치에서 작업하고 PR을 올려 리뷰 1인 승인을 받은 뒤 merge합니다.
- **좌표**: EXIF 방향 보정 후 원본 픽셀 기준의 `{x, y, w, h}`, 기울어진 글자는 `poly` 를 덧붙입니다.
- **출력 문구**: 사용자에게 나가는 문장은 `pipeline/wording.py` 에서만 만듭니다. 단정 표현은 `assert_safe()` 가 막습니다.
- **개인정보**: 실사 이미지, OCR 원문, 실제 개인정보를 커밋·로그·외부 API로 내보내지 않습니다. 샘플과 정답에는 가상 정보만 씁니다. 서버는 업로드를 디스크에 쓰지 않습니다.
- **측정**: 성능 수치는 측정한 것만 씁니다. 합성 샘플 숫자는 실사로 다시 재야 한다고 함께 적습니다.
- **화면을 고치면** `node scripts/check.mjs`, `node scripts/check-contract.mjs`, `node scripts/build.mjs` 를 차례로 돌립니다.
- **언어와 커밋**: 문서·주석·커밋 메시지는 한국어, 식별자는 영어로 씁니다. 커밋 메시지는 `type(scope): 설명` 형식입니다.

## 명령어

```bash
pip install -r requirements.txt
python run.py                              # 환경 점검 → 서버 + 화면 (http://127.0.0.1:8000)
python -m pytest tests                     # 백엔드 테스트 (OCR 불필요)
python -m eval.compare samples/out         # 비교 실험
PL_OCR=paddleocr python -m eval.rotation   # 회전 실험
cd web/frontend-demo && node scripts/check.mjs && node scripts/check-contract.mjs && node scripts/build.mjs
```

PaddleOCR 를 쓰려면 `pip install paddleocr "paddlepaddle<3.3"`, 실행 시 `PL_OCR=paddleocr`.
