# AGENTS.md

AI 코딩 도구(Claude Code, Codex, Cursor, GitHub Copilot 등)를 위한 이 저장소의 안내서입니다. Claude Code는 `CLAUDE.md`를 통해 이 파일을 읽습니다.

## 프로젝트

Privacy Lens — 사진을 SNS·중고거래에 올리기 전에 배경의 개인정보(택배 송장, 학생증, 모니터 화면 등)를 찾아 위치와 근거를 보여 주고, 가림 처리와 EXIF 제거까지 해 주는 웹 서비스. 수원대학교 정보보호학과 시스템보안프로젝트(2026-2), 5인 팀.

## 현재 구조 (2026-10-04 백엔드 교체 후)

- **백엔드는 Privacy Lens 2** 를 그대로 가져온 것입니다(`pipeline/`, `server.py`, `jobqueue.py`, `run.py`, `eval/`, `samples/`, `tests/`). 기준은 이 코드와 [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)의 설계 원칙입니다.
- **화면은 `web/frontend-demo/`** 입니다. `dist/` 가 편집 원본이고 `scripts/build.mjs` 가 `privacy-lens.html` 로 묶습니다. 게이트웨이(`gateway.py`)가 `/` 에서 이 파일을 내줍니다.
- **실행 구조(D-20)**: `run.py` 는 게이트웨이(화면 + 대기열) + 엔진 서버(`server.py`, 화면 없음) 1개를 함께 띄웁니다. 엔진을 늘릴 때는 `run_backend.py` 를 PC 마다 띄우고 `run_gateway.py --backend` 로 묶습니다.
- 이전의 `server/`·`reader/`·`schema/`·`data/`·React 앱은 삭제했습니다. [docs/DECISIONS.md](docs/DECISIONS.md)의 '교체로 사실상 정해진 것'을 먼저 봅니다.
- **YOLO 문서 검출(선택)**: `pipeline/detect.py` 는 `PL_YOLO_WEIGHTS` 또는 프로젝트 `models/v<최대 숫자>/best.pt`(버전 폴더가 없으면 `models/best.pt`)를 사용합니다. 모델이 없으면 OCR만 실행하며 `PL_YOLO=off`로 끌 수 있습니다. 학습 도구는 새 `vision/`(예전 `vision/` 과 무관, **YOLO26**, `ultralytics>=8.4`)이고, 사진·라벨·모델은 저장소가 아니라 팀 구글 드라이브 `PrivacyLens-YOLO` 에 둡니다. 사용법은 [vision/README.md](vision/README.md).
- **YOLO 역할 전환(D-16, 2026-11-02)**: 글자는 OCR 이 충분히 읽으므로 YOLO 는 글자가 아닌 이미지 객체(증명사진·얼굴·번호판·보안 표식) 쪽으로 옮깁니다. 문서 클래스는 지금 모델로 동결합니다.
- **시나리오(D-21, 2026-11-06)**: 일상 사진 속 **나도 모르게 작게 찍힌 개인정보**를 찾아 보여 주고 물건째 가린다. 문서 대량 검사는 대상이 아니다.
  일상 사진 9종 YOLO 는 `models/daily.onnx`(`PL_DAILY_MODEL`)로 켜고 문서 모델과 함께 돈다.

## 지금 단계 (2026-11-01~)

**1차 완성(안정화)** 단계입니다. [docs/PLAN_1ST.md](docs/PLAN_1ST.md) 의 할 일 표를 기준으로 일하고, 새 기능은 2차로 미룹니다.
판단 기준은 [docs/MASKING_CRITERIA.md](docs/MASKING_CRITERIA.md)(초안), 실사 평가 절차는 [docs/REAL_PHOTO_GUIDE.md](docs/REAL_PHOTO_GUIDE.md) 입니다.

## 작업 전에

1. 사용자의 역할(1~5번)을 모르면 먼저 묻고, [docs/ROLES.md](docs/ROLES.md)에서 그 역할의 범위를 확인합니다. ROLES 의 폴더 이름은 교체 전 기준이니 지금 구조로 바꿔 읽습니다.
2. [README.md](README.md)(개요·실행), [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)(설계 원칙·측정·한계·버그 기록), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)(흐름·API), [docs/DECISIONS.md](docs/DECISIONS.md)(결정·미결)를 읽습니다.
3. 문서끼리, 또는 문서와 코드가 다르면 임의로 한쪽에 맞추지 말고 사용자에게 알립니다.

## 규칙

- **브랜치와 PR**: `main`에 직접 push하지 않습니다. `feat/<모듈>-<내용>` 브랜치에서 작업하고 PR을 올려 리뷰 1인 승인을 받은 뒤 merge합니다.
- **좌표**: EXIF 방향 보정 후 원본 픽셀 기준의 `{x, y, w, h}`, 기울어진 글자는 `poly` 를 덧붙입니다.
- **출력 문구**: 사용자에게 나가는 문장은 `pipeline/wording.py` 에서만 만듭니다. 단정 표현은 `assert_safe()` 가 막습니다.
- **개인정보**: 실사 이미지, OCR 원문, 실제 개인정보를 커밋·로그·외부 API로 내보내지 않습니다. 샘플과 정답에는 가상 정보만 씁니다. 서버는 업로드를 디스크에 쓰지 않습니다. 예외는 '판단 모델' 창에서 고른 클라우드 LLM 판단 하나뿐이며(D-15), 가상 사진에만 씁니다. API 키는 브라우저에만 두고 서버·로그·저장소에 남기지 않습니다.
- **측정**: 성능 수치는 측정한 것만 씁니다. 합성 샘플 숫자는 실사로 다시 재야 한다고 함께 적습니다.
- **판단 규칙을 고치면** `python -m eval.judgment --check` 를 통과해야 합니다. 좋아졌으면 `--update` 로 `eval/baselines/judgment.json` 을 갱신해 같이 커밋합니다. 놓친 사례를 고칠 때는 먼저 `eval/judgment.py` 에 같은 유형의 가상 장면을 넣고 고칩니다.
- **실사 평가 사진·정답·`평가기록.csv`** 는 팀 드라이브 `PrivacyLens-Eval/` 에만 둡니다. `eval.failures --show-text` 출력은 공유하지 않습니다.
- **화면을 고치면** `node scripts/check.mjs`, `node scripts/check-contract.mjs`, `node scripts/build.mjs` 를 차례로 돌립니다.
- **언어와 커밋**: 문서·주석·커밋 메시지는 한국어, 식별자는 영어로 씁니다. 커밋 메시지는 `type(scope): 설명` 형식입니다.

## 명령어

```bash
pip install -r requirements.txt
python run.py                              # 환경 점검 → 게이트웨이(화면 + 대기열, 8000) + 엔진 서버 1개(이 PC 안, 8001)
python run_backend.py --host 0.0.0.0 --token <비밀값>          # 엔진 서버만(1 서버 1 엔진, 화면 없음)
python run_gateway.py --backend http://<엔진>:8000 --token <비밀값>   # 게이트웨이만: 화면 + 하나의 대기열 + 엔진 분산(8080)
cd web/frontend-demo && node scripts/build.mjs --api https://<게이트웨이>   # 정적 배포 폴더 site/ (게이트웨이는 --no-front --cors <화면 주소>)
python run_gateway.py ... --ssl-cert cert.pem --ssl-key key.pem       # 게이트웨이 https 직접. 도메인이 있으면 caddy run --config deploy/Caddyfile
python -m pytest tests                     # 백엔드 테스트 (OCR 불필요)
python -m eval.judgment --check            # 판단 회귀 검사(OCR 불필요, CI 와 같음)
python -m eval.failures run <폴더>          # 실사 실패 원인 분류(사진은 드라이브)
python -m eval.stability [--quick]         # 이상한 입력·연속 30장·동시 요청 점검
python -m eval.workers                     # OCR 작업자(엔진) 수에 따른 처리량·지연·메모리
python -m eval.names_check                 # 라벨 없는 이름 후보 판정(따로 모은 목록)
python -m eval.ner_compare --engine rules kiwi hf   # 이름 찾기 규칙 vs NER(hf 는 Colab)
python -m samples.props <폴더>              # 촬영용 가상 소품 + 정답
python -m eval.compare samples/out         # 비교 실험
PL_OCR=paddleocr python -m eval.rotation   # 회전 실험
PL_OCR=paddleocr python -m eval.realtext run <평가 묶음>              # AI 허브 실사 평가(데이터는 승인받은 본인만)
PL_OCR=paddleocr python -m eval.detector <폴더> --weights <best.pt>   # YOLO 전후 비교
python -m vision status --root <PrivacyLens-YOLO>                    # YOLO 학습 도구(보통 Colab: vision/colab.ipynb)
cd web/frontend-demo && node scripts/check.mjs && node scripts/check-contract.mjs && node scripts/build.mjs
```

기본 OCR 은 PaddleOCR 입니다. `pip install paddleocr "paddlepaddle<3.3"` 로 설치합니다. Tesseract 를 쓰려면 `PL_OCR=tesseract` 를 지정합니다.
