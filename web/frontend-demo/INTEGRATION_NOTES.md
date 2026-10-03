# 팀 저장소 편입 메모

2026-10-03, 5번 프론트엔드 담당의 독립 데모를 `web/frontend-demo/`에 추가합니다.
이 데모는 팀 저장소를 확인하기 전에 백엔드 규격이 없는 것으로 안내받아 만든 시연본입니다.
기존 `web/src/`, `server/`, `schema/`의 구현이나 계약은 수정하지 않았습니다.

## 실행

저장소 루트에서 `cd web/frontend-demo` 후 `node server.mjs`를 실행하고
http://127.0.0.1:4173 에 접속합니다. 기본 데모 모드를 사용하세요.
기존 데모 서버가 4173 포트를 사용하면 그 서버를 그대로 이용하거나
PowerShell에서 `$env:PORT=4174`를 설정한 뒤 실행하세요.

## 확인한 차이 — 현재 계약을 바꾸는 제안이 아님

| 항목 | 현재 팀 기준 | 이번 독립 시연본 |
|---|---|---|
| 화면 기술 | React + TypeScript | 의존성 없는 HTML/CSS/JavaScript |
| 분석 API | `/api/v1/analyze`, multipart `file` | 미채택 제안 `/api/analyze`, multipart `image` |
| 외부 좌표 | 방향 보정 후 `{x1,y1,x2,y2}` | 데모 JSON의 `{x,y,width,height}` |
| 응답 | AnalyzeResponse, findings, value_masked | 데모 전용 regions, text_preview |
| 최종 가림 | D-05 미결, 현재 앱은 Canvas 처리 | 기본 Canvas, 제안 `/api/redact` 어댑터 |
| 탐지 대상 | schema/classes.txt 9종 | 일부 다른 예시 대상 포함 |
| 사진 형식 | PRD에 HEIC 포함 | JPEG/PNG/WEBP만 지원 |

API_CONTRACT.md와 dist/api.js는 이전에 작성한 제안의 보존본이며,
현재 팀 서버와의 연동 완료를 뜻하지 않습니다. 서버 모드를 활성화하더라도
현재 팀 API에는 연결할 수 없습니다. 실제 사진이나 OCR 원문은 커밋하지 않았습니다.
화면에 사용하는 샘플은 코드로 생성한 가상 데이터입니다.

## 합의 후 할 일

- 4·5번: D-05의 처리 위치, 편집 영역 제출·결과 다운로드 API를 결정.
- 3·4·5번: 현재 스키마 응답을 화면 유형·근거·판독 상태와 어떻게 연결할지 결정.
- 5번: 합의된 계약을 따르는 어댑터 작성. 실제 통신 경계에는 현재 기준 xyxy 좌표를 사용.
- 5번: 기존 React 앱으로 필요한 화면·편집 기능을 옮기는 범위 결정.
- 2·4·5번: 업로드 방향, 좌표 일치, EXIF 제거, 실패·취소와 파일 저장을 합동 검증.

`docs/DECISIONS.md`에 **독립 프론트 데모의 편입 및 API 차이** 항목을 추가해
D-01·D-05와 함께 검토할 것을 제안합니다. 이번 업로드에서는 미결 사항을 결정하거나
공동 스키마·다른 역할 폴더를 수정하지 않았습니다.

## 검증

`node scripts/check.mjs` 28개, `node scripts/check-contract.mjs` 39개 검사.
기존 작업 폴더에서 주요 편집·세로 사진·모바일·파일 선택·PNG 미리보기 확인.
실제 팀 서버 통합, 팀원 사용성 평가, 다운로드 파일의 디스크 저장 검증은 남아 있습니다.
