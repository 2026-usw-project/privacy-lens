## 무엇을, 왜

<!-- 한두 줄. 관련 이슈가 있으면 "closes #번호" -->

## 1차 계획 항목

<!-- docs/PLAN_1ST.md 의 몇 번 항목인지. 해당 없으면 지우세요 -->

## 확인한 것

- [ ] `python -m pytest tests` 통과
- [ ] 판단 규칙(`pipeline/`)을 고쳤다면 `python -m eval.judgment --check` 통과, 좋아졌으면 `--update` 결과도 커밋
- [ ] 화면(`web/frontend-demo/dist/`)을 고쳤다면 `check.mjs` · `check-contract.mjs` · `build.mjs` 를 돌리고 `privacy-lens.html` 도 커밋
- [ ] 실사 사진·OCR 원문·실제 개인정보가 커밋·로그·스크린샷에 없음(가상 정보만)
- [ ] 성능 숫자를 적었다면 어디서 잰 숫자인지 적음(합성 / 가상 텍스트 / 실사 몇 장)

## 측정 (해당할 때)

<!-- 예: 실사-개발용 10장, eval.failures: 판단 실패 9 → 4 (평가기록.csv 두 줄) -->
