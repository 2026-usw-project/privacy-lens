---
name: Privacy Lens
description: 사진 배경의 개인정보를 찾아 위치와 근거를 보여 주고, 가린 사본을 저장하는 작업대
colors:
  # 밝은 화면 값. 어두운 화면 값은 아래 Colors > Dark 와 dist/styles.css 의 :root[data-theme="dark"]
  bg: "#f1f3f8"
  surface: "#ffffff"
  surface-2: "rgb(28 40 96 / 0.055)"
  surface-3: "rgb(28 40 96 / 0.095)"
  line: "#eceff2"
  line-strong: "#d1d6db"
  ink: "#191f28"
  ink-2: "#4e5968"
  muted: "#56616f"
  primary: "#2f5bff"
  primary-solid: "#2449e8"
  primary-hover: "#1d3bcc"
  primary-ink: "#1f3fd1"
  primary-tint: "#eaefff"
  primary-wash: "#f5f7ff"
  primary-line: "#cdd7ff"
  accent: "#f04452"
  accent-solid: "#d92d3b"
  accent-hover: "#bf2431"
  accent-ink: "#c42231"
  accent-tint: "#fff0f1"
  accent-wash: "#fff7f7"
  accent-line: "#ffd0d4"
  review: "#e8a21a"
  review-label: "#8a5a0c"
  ok: "#137a4c"
  warn: "#a95a05"
  warn-bg: "#fff6e5"
  warn-line: "#ffe0a3"
  error: "#d92d3b"
  stage: "#f1f3f8"
  stage-line: "#e3e7f0"
  tag-dim: "#5f6b7a"
  glow-1: "rgb(47 91 255 / 0.36)"
  glow-2: "rgb(124 96 255 / 0.28)"
  glow-3: "rgb(64 170 255 / 0.26)"
  glow-4: "rgb(176 190 255 / 0.55)"
  glass: "rgb(255 255 255 / 0.64)"
  glass-hi: "rgb(255 255 255 / 0.72)"
  glass-floor: "rgb(255 255 255 / 0.34)"
  glass-drop: "rgb(36 58 190 / 0.30)"
  toast-bg: "#191f28"
typography:
  display:
    fontFamily: "Pretendard, Apple SD Gothic Neo, Malgun Gothic, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "30px"
    fontWeight: 700
    lineHeight: 1.3
    letterSpacing: "-0.035em"
  headline:
    fontFamily: "Pretendard, Apple SD Gothic Neo, Malgun Gothic, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "20px"
    fontWeight: 650
    lineHeight: 1.35
    letterSpacing: "-0.02em"
  title:
    fontFamily: "Pretendard, Apple SD Gothic Neo, Malgun Gothic, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "14px"
    fontWeight: 600
    lineHeight: 1.5
  body:
    fontFamily: "Pretendard, Apple SD Gothic Neo, Malgun Gothic, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.7
  body-sm:
    fontFamily: "Pretendard, Apple SD Gothic Neo, Malgun Gothic, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.65
  label:
    fontFamily: "ui-monospace, SFMono-Regular, Cascadia Mono, Consolas, Pretendard, Apple SD Gothic Neo, Malgun Gothic, monospace"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.5
    fontFeature: "tnum"
  numeral:
    fontFamily: "ui-monospace, SFMono-Regular, Cascadia Mono, Consolas, monospace"
    fontSize: "28px"
    fontWeight: 400
    lineHeight: 1
    letterSpacing: "-0.02em"
    fontFeature: "tnum"
rounded:
  xs: "4px"
  sm: "8px"
  md: "10px"
  lg: "12px"
  xl: "14px"
  full: "50%"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "20px"
  2xl: "24px"
components:
  button-primary:
    backgroundColor: "{colors.primary-solid}"
    textColor: "#ffffff"
    rounded: "{rounded.md}"
    padding: "0 16px"
    height: "40px"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
  button-ghost:
    backgroundColor: "{colors.surface-2}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "0 16px"
    height: "40px"
  button-ghost-hover:
    backgroundColor: "{colors.surface-3}"
  chip-button:
    backgroundColor: "{colors.surface-2}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "0 12px"
    height: "36px"
  chip-button-active:
    backgroundColor: "{colors.primary-tint}"
    textColor: "{colors.primary-ink}"
  nav-item:
    textColor: "{colors.ink-2}"
    rounded: "{rounded.sm}"
    padding: "0 12px"
    height: "40px"
  nav-item-active:
    backgroundColor: "{colors.primary-tint}"
    textColor: "{colors.primary-ink}"
  risk-tag:
    backgroundColor: "{colors.accent-tint}"
    textColor: "{colors.accent-ink}"
    typography: "{typography.label}"
    padding: "2px 6px"
  input-field:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "10px 12px"
  workspace:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.lg}"
  dialog:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.xl}"
    padding: "24px"
---

# Design System: Privacy Lens

## Overview

**Creative North Star: "검수 작업대 (The Inspection Bench)"**

사진 검사는 마케팅 페이지가 아니라 대시보드 안의 한 작업 화면입니다. 옅은 푸른 회색 바닥과 그 위로 천천히 번지는 코발트 빛 위에 반투명 유리 작업 면을 놓고, 그 면을 1px 헤어라인으로 나눠 왼쪽에는 사진, 오른쪽에는 근거 목록과 저장 버튼을 둡니다. 화면 안에서 가장 시끄러운 것은 사진 위의 빨간 탐지 박스여야 하고, 그 외의 장치는 조용히 물러납니다. 행동·선택·진행은 상징색 일렉트릭 코발트 하나가 맡습니다.

밀도는 데스크톱 도구 수준입니다. 본문은 13~14px, 행 높이는 34~48px, 패널 안쪽 여백은 20px 안팎으로 한 화면에 사진과 목록과 저장 버튼이 함께 들어갑니다. 숫자·좌표·파일 정보·상태는 모노 글꼴의 대괄호 라벨(`[ 가상 데이터 ]` 문법)로, 문장은 한글 산세리프로 씁니다. 깊이는 대부분 선과 면의 명도 차이로 만들고, 그림자는 실제로 떠 있는 물체(입력 막대, 사진, 대화상자, 토스트)에만 붙습니다.

글꼴은 Pretendard(OFL)를 `dist/fonts/`에 자체 호스팅합니다. KS X 1001 한글 서브셋 정적 4종(400·500·600·700, 각 약 270KB)이며 외부 요청은 없습니다(CSP `default-src 'self'`). 라이선스는 `dist/fonts/LICENSE.txt`.

**Key Characteristics:**
- 옅은 푸른 회색 바닥 + 코발트·남보라·하늘 빛 + 반투명 유리 작업 면
- 코발트는 누르는 것·고른 것·진행·헤드라인의 한 단어에만, 빨강은 위험 표시에만
- 데이터와 상태는 모노 12px, 상태 태그는 대괄호로 감싼다
- 그림자는 떠 있는 물체에만, 패널과 목록은 평평하다
- 반응형은 구조만 바꾸고 글자 크기는 거의 고정

## Colors

두 가지 색이 각자 한 가지 일만 합니다. **코발트**는 사용자가 누르는 것·고른 것·진행을, **빨강**은 사진 속 위험(가림 권장)을 말합니다. 그 밖은 푸른 기가 살짝 도는 회색 중립색입니다. 값의 원본은 `dist/styles.css` 의 `:root`(밝은 화면)과 `:root[data-theme="dark"]`(어두운 화면)이고, 이 문서는 그 값을 옮겨 적은 것입니다.

### Primary — 일렉트릭 코발트 (행동·선택·진행)
- **코발트 (Electric Cobalt)** (`primary` `#2f5bff`): 상징색. 헤드라인의 강조 한 단어, 포커스 링, 렌즈 점, `accent-color`·`caret-color`. 흰 글자 대비 5.2:1.
- **단단한 코발트 (Solid Cobalt)** (`primary-solid` `#2449e8`): 흰 글자가 올라가는 면(주요 버튼, 현재 단계 번호, 브랜드 마크). 버튼은 `primary-solid` → `primary-hover` 세로 그라데이션. 흰 글자 6.6:1.
- **짙은 코발트 (Deep Cobalt)** (`primary-hover` `#1d3bcc`): 버튼 그라데이션 아래쪽, hover. 흰 글자 8.2:1.
- **코발트 글자 (Cobalt Ink)** (`primary-ink` `#1f3fd1`): 연한 코발트 바탕 위 글자(활성 내비, 펼친 칩, 완료 단계). 코발트를 작은 글자로 쓸 때는 이 값. 틴트 위 6.8:1.
- **코발트 틴트 / 워시 / 선** (`primary-tint` `#eaefff`, `primary-wash` `#f5f7ff`, `primary-line` `#cdd7ff`): 선택·활성 채움, 넓은 안내 면, 그 테두리.

### Risk — 빨강 (가림 권장) · 주황 (검토 권장)
- **위험 빨강** (`accent` `#f04452`): 사진 위 가림 권장 박스의 모서리 꺾쇠와 채움(8%, hover·포커스 16%). 흰 글자 바탕으로는 쓰지 않습니다(3.7:1).
- **단단한 빨강** (`accent-solid` `#d92d3b`): 박스 번호 라벨 바탕, 오류 글자(`error`). 흰 글자 4.8:1. hover `accent-hover` `#bf2431`.
- **빨강 글자 / 틴트 / 워시 / 선** (`accent-ink` `#c42231`, `accent-tint` `#fff0f1`, `accent-wash` `#fff7f7`, `accent-line` `#ffd0d4`): 목록의 '가림 권장' 태그(틴트 위 5.2:1)와 위험 안내 면.
- **검토 주황** (`review` `#e8a21a`, 라벨 `review-label` `#8a5a0c`): 검토 권장 박스와 그 번호 라벨(흰 글자 5.9:1). 목록 태그는 `warn-bg` 바탕 + `warn` 글자.
- **참고 회색** (`tag-dim` `#5f6b7a`): 참고 박스와 가림 해제된 박스의 라벨.

### Neutral
- **바닥 (Cool Paper)** (`bg` `#f1f3f8`): 페이지 바닥, 브라우저 `theme-color`. 사진 받침 판(`stage`)도 같은 값, 그 선은 `stage-line` `#e3e7f0`.
- **흰 면 (Surface)** (`surface` `#ffffff`): 대화상자, 펼침 메뉴, 입력 칸처럼 읽기가 우선인 곳. 큰 작업 면은 아래 유리를 씁니다.
- **옅은 칸** (`surface-2`, `surface-3`: 남색 `rgb(28 40 96)` 5.5% / 9.5%): 고스트 버튼·칩·세그먼트 트랙·안내 상자의 바탕과 hover. 바탕 빛이 비치도록 반투명입니다.
- **헤어라인** (`line` `#eceff2`, `line-strong` `#d1d6db`): 분할선, 입력 테두리, 단계 사이 막대, 점 바닥의 점.
- **먹색** (`ink` `#191f28`, `ink-2` `#4e5968`, `muted` `#56616f`): 제목, 설명 문장(흰 면 위 7.1:1), 메타 정보(바닥 위 5.7:1).

### Backdrop & Glass — 바탕 빛과 유리 면
- **바탕 빛** (`glow-1`~`glow-4`): 고정 층의 큰 원 넷이 29~41초 주기로 천천히 번집니다. 코발트 `rgb(47 91 255/.36)`, 남보라 `rgb(124 96 255/.28)`, 하늘 `rgb(64 170 255/.26)`, 옅은 페리윙클 `rgb(176 190 255/.55)`. 빨강은 위험 표시 전용이라 바탕에 쓰지 않습니다. `prefers-reduced-motion` 이면 멈춘 그림.
- **유리 면** (`glass` 흰색 64%, `glass-hi` 72%, `glass-floor` 34%): 사진 작업 면·결과 면·카드(64%), 버튼 윗면·칩(72%), 점 바닥(34%) 순으로 옅습니다. 테두리 대신 안쪽 1px 흰 선(`glass-edge` 70%)과 코발트 그림자(`glass-drop` `rgb(36 58 190/.30)`).
- **흐림(`backdrop-filter`)** 은 상단바와 저장 칸에만.

### Status
- **확인됨** (`ok` `#137a4c`): 모두 가림 선택됐을 때의 요약 글자. 토스트 아이콘은 어두운 토스트 위 `toast-icon` `#5ee0a0`.
- **주의** (`warn` `#a95a05`, `warn-bg` `#fff6e5`, `warn-line` `#ffe0a3`): 일부 판독 실패, 함께 노출 안내, 검토 권장 태그. 바탕 위 4.7:1.
- **오류** (`error` `#d92d3b`): 오류 줄, 입력 오류, 삭제 hover.

### Dark
어두운 화면은 같은 이름의 값만 바꿉니다: `bg` `#17171c`, `surface` `#202027`, `ink` `#f2f4f6`, `primary` `#6b8aff`(면 위 5.2:1), `primary-ink` `#a3b7ff`, `primary-tint` `#1b2149`, `accent` `#f6606c`, `accent-ink` `#ff8d96`, 바탕 빛은 같은 색상을 더 옅게(코발트 `rgb(36 73 232/.32)` 등), 유리는 `rgb(32 32 39/.62)`. `primary-solid`·`accent-solid` 는 밝은 화면과 같습니다.

### Named Rules
**The Two Signals Rule.** 코발트는 행동·선택·진행과 헤드라인의 한 단어에만, 빨강은 사진 속 위험(가림 권장)에만 씁니다. 둘 다 장식(배경 띠, 구분선, 아이콘 일괄 착색)으로 쓰지 않습니다. 바탕 빛은 예외로 코발트 계열이지만 빨강은 섞지 않습니다.

**The Ink-on-Tint Rule.** 코발트·빨강 계열 바탕 위의 글자는 각각 `primary-ink`·`accent-ink` 입니다. `primary`·`accent` 자체를 작은 글자 색으로 쓰지 않습니다(헤드라인 강조 단어만 예외).

## Typography

**Display Font:** Pretendard (자체 호스팅 서브셋, 400·500·600·700) → Apple SD Gothic Neo → Malgun Gothic → system-ui. 650으로 적힌 굵기는 정적 글꼴에서 700으로 렌더링됩니다.
**Body Font:** 같은 스택.
**Label/Mono Font:** ui-monospace → SFMono-Regular → Cascadia Mono → Consolas, 한글은 산세리프 스택으로 폴백. 숫자는 항상 tabular.

**Character:** 장식 없는 한글 산세리프가 문장을 맡고, 모노가 숫자·좌표·상태를 맡아 "읽는 글"과 "측정값"이 한눈에 갈립니다. 큰 제목도 30px에서 멈춥니다.

### Hierarchy
- **Display** (700, 30px / 모바일 22px, 1.3, -0.035em): 빈 상태의 한 문장 헤드라인. 강조 한 단어만 코발트(`primary`). 화면당 하나.
- **Headline** (650, 20px, 1.35, -0.02em): 오른쪽 패널 제목, 대화상자 제목. 결과 목록 제목은 18px.
- **Title** (600, 14~15px, 1.5): 작업 공간 제목(15px), 목록 행 이름, 카드·타일 제목.
- **Body** (400, 14px, 1.7, `ink-2`): 패널 부제, 대화상자 소개, 안내 단계. 빈 상태 설명만 15px, 최대 44ch.
- **Body small** (400, 13px, 1.6~1.7, `muted` 또는 `ink-2`): 행 설명, 상태 줄, 버튼 외 보조 문장. 이 제품에서 가장 많이 쓰이는 크기입니다.
- **Label** (모노 400~500, 12px, tabular): 파일 형식·크기·좌표·행 번호·단계 번호·상태 태그.
- **Numeral** (모노 400, 28px / 진행률 40px, -0.02em): 결과 개수와 분석 진행률. 큰 숫자는 굵게 하지 않습니다.

### Named Rules
**The Bracket Status Rule.** 상태와 출처를 말하는 짧은 태그(`SAMPLE`, `MANUAL`, `SERVER`, `ERROR`, `시연`, `가상 데이터`)는 모노 12px에 `[ ` ` ]`를 붙여 제목과 **같은 줄 오른쪽**에 둡니다. 제목 위에 얹는 아이브로가 아닙니다.

**The Fixed Type Rule.** 반응형은 구조를 바꾸고 글자 크기는 거의 바꾸지 않습니다. 580px 이하에서 줄어드는 것은 Display(30→22px)와 일부 13→12px뿐입니다.

## Layout

화면은 세 층입니다. 왼쪽 고정 사이드바(232px), 위쪽 고정 상단바(60px, 단계 표시와 시연 메뉴), 그 아래 본문의 **작업 공간 프레임** 하나. 프레임은 `minmax(0, 1fr)` 사진 칸과 380px 결과 칸의 2열 격자이며, 두 칸 사이는 1px 헤어라인입니다. 결과 칸은 상단바 아래에 sticky로 붙고 자체 스크롤을 가져 저장 버튼이 항상 보입니다. 사진 칸의 캔버스 무대 높이는 화면 높이에서 고정 요소를 뺀 값(`clamp(340px, 100dvh - 268px, 1100px)`)으로 사진이 세로를 채웁니다.

여백 리듬은 4px 단위입니다. 본문 바깥 여백 24px, 패널 머리 높이 56px, 패널 안쪽 20~22px, 목록 행 10px×20px, 컨트롤 사이 8~12px. 샘플·탐지 대상 격자는 3열이고, 칸 사이 간격 없이 헤어라인으로 나눕니다.

반응형 단계: 1180px 이하 사이드바가 64px 아이콘 레일로 접히고 결과 칸 340px. 1020px 이하 현재 단계만 이름을 보이고 도구줄이 줄바꿈. 820px 이하 작업 공간이 1열로 쌓이고 + 표시와 sticky가 해제. 580px 이하 사이드바가 56px 상단 막대가 되고 본문 여백 12px, 탐지 대상 격자 2열.

## Elevation & Depth

평평한 것이 기본입니다. 패널, 목록, 카드, 사이드바는 그림자 없이 헤어라인과 면의 명도 차이(`bg` → `surface` → `surface-2`)로 층을 나눕니다. 그림자는 화면 위에 실제로 떠 있는 물체에만, 1~2px 접지 그림자와 넓고 옅은 블러를 겹친 형태로 씁니다. 그림자 색은 먹색 또는 코발트에 알파를 준 값입니다.

### Shadow Vocabulary
- **유리 면** (`inset 0 0 0 1px glass-edge, 0 24px 56px -30px glass-drop`): 사진 작업 면, 결과 면, '남기지 않아요' 카드. 그림자 색은 코발트 `rgb(36 58 190/.30)`.
- **사진 받침** (`0 1px 2px #0000000f, 0 10px 28px #00000014`): 캔버스의 사진.
- **주요 버튼 입체** (`--raise-primary`): 윗면 흰 하이라이트 1px, 아랫면 두께 2px(`--lip`: `primary-solid` 72% + `#0b1766`), 코발트 26% 바닥 그림자. 누르면 내려앉습니다.
- **부드러운 버튼** (`--raise-soft`): 고스트 버튼·칩. 흰 하이라이트 + `line-strong` 아랫면 + 먹색 7% 그림자.
- **대화상자** (`0 8px 48px #00000033`): 모달. 배경막은 `#191f2873`.
- **포커스된 박스 후광** (`0 0 0 3px` 박스 색 28%): 사진 위 선택된 탐지 박스.

### Named Rules
**The Only-What-Floats Rule.** 그림자는 입력 막대, 사진, 대화상자, 토스트처럼 바닥 위에 올라온 물체에만. 패널과 목록 행은 선으로 나눕니다.

## Shapes

부드러운 직각입니다. 컨트롤(버튼, 칩, 안내 상자, 카드형 옵션, 토스트)은 10px(`rounded.md`), 작은 컨트롤과 입력은 8px(`rounded.sm`), 작업 공간 프레임은 12px(`rounded.lg`), 드롭 막대와 대화상자는 14px(`rounded.xl`), 태그·코드 조각·박스 라벨은 4px(`rounded.xs`). 단계 번호와 상태 점만 원입니다. 사진 위 탐지 박스는 모서리가 없는 직사각형입니다.

선은 언제나 1px 헤어라인이고, 프레임 위·아래 테두리가 내부 분할선과 만나는 지점에 13px짜리 + 표시를 둡니다(`muted` 색 1px 십자). 점 패턴(`line-strong` 1px 점, 16px 간격)은 사진을 놓는 바닥(업로드 면, 캔버스 무대, 내보내기 미리보기)에만 깔립니다.

## Components

### Buttons
조용하고 단단합니다. 누르면 1px 내려앉습니다.
- **Shape:** 10px 모서리, 높이 40px(작게 34px, 크게 48px).
- **Primary:** `primary-solid` → `primary-hover` 그라데이션, 흰 글자 14px 600, 주요 버튼 입체 그림자. 화면당 하나의 다음 행동(분석 시작, 저장, 다운로드)에만.
- **Hover / Focus:** 그림자가 조금 더 떠오릅니다. 포커스는 모든 요소 공통으로 2px `primary` 외곽선, 2px 띄움.
- **Ghost:** `surface-2` 바탕, 먹색 글자, hover `surface-3`. 보조 행동(직접 지정, 취소, 시연 재현).
- **Text button:** 바탕 없음, 13px 500 `ink-2`, hover 시 `ink`. 되돌리기·전체 선택·닫기.
- **Disabled:** 불투명도 0.45.

### Chips
- **Style:** 상단바의 36px 칩. `surface-2` 바탕, 13px 500, 아이콘 15px.
- **State:** 펼쳐진 상태(`aria-expanded=true`)는 `primary-tint` 바탕 + `primary-ink` 글자.

### Cards / Containers
- **작업 공간 프레임:** `surface` 바탕, 1px `line` 테두리, 12px 모서리, 그림자 없음, 칸 사이 헤어라인과 + 표시.
- **안내 상자(note, callout, save-state):** `surface-2` 바탕, 테두리 없음, 10px 모서리, 12px×14px.
- **강조 안내(시연 진행 띠, 수동 지정 안내):** `primary-wash` 바탕 + `primary-line` 테두리.
- **주의 안내:** `warn-bg` 바탕 + `warn-line` 테두리 + `warn` 글자, 8px 모서리.

### Inputs / Fields
- **Style:** `surface` 바탕, 1px `line-strong` 테두리, 8px 모서리(좌표 칸은 6px). 주소·좌표 입력은 모노.
- **Focus:** 공통 2px `primary` 외곽선. 체크박스·라디오·슬라이더는 `accent-color`로 코발트.
- **Selected option:** 라디오 옵션 카드와 가림 방식 버튼은 선택 시 테두리 `primary`, 바탕 `primary-wash`.
- **Error:** 입력 아래 13px `error` 글자 줄.

### Navigation
- **사이드바:** `bg` 바탕, 오른쪽 헤어라인. 항목 40px, 14px 500 `ink-2`, hover `surface-2`, 활성 `primary-tint` + `primary-ink`. 개수는 모노 12px로 오른쪽 끝.
- **단계 표시:** 22px 원 안의 모노 숫자, 단계 사이 28px 헤어라인. 현재 단계는 코발트 그라데이션 원(`primary-solid` → `primary-hover`) + 흰 숫자, 완료는 `primary-tint` 원 + `primary-ink` 체크.
- **모바일:** 사이드바가 56px 상단 막대로, 내비는 아이콘만.

### Segmented Control
3px 안쪽 여백의 `surface-2` 트랙, 30px 칸. 선택된 칸은 `surface` 바탕 + 먹색 글자 + 1px 접지 그림자.

### Region Box (signature)
사진 위의 탐지 영역입니다. 심각도 색(`--hud`: 가림 권장 `accent`, 검토 권장 `review`, 참고 `tag-dim`)으로 네 모서리 꺾쇠 2px와 34% 1px 테두리, 8% 채움(hover·포커스 16%). 포커스되면 3px 후광(28%), 라벨이 박스 위로 올라가 유형 이름까지 보입니다. 평소 라벨은 박스 왼쪽 바깥에 번호만(가림 권장 `accent-solid`, 검토 권장 `review-label`, 참고 `tag-dim` 바탕 흰 숫자) 붙어 이웃 박스를 덮지 않고, 포커스된 박스만 라벨이 위로 올라가 이름을 보입니다. 580px 이하에서는 박스 안 왼쪽 위 11px. 가림 해제된 박스는 회색 1px 점선에 채움 없음. 편집 모드에서만 보이는 오른쪽 아래 12px 흰 크기 조절 손잡이(`primary` 테두리).

### Region List Row (signature)
번호(모노 12px `muted`) + 이름(14px 600) + 오른쪽 위험 태그(가림 권장 `accent-tint` + `accent-ink`, 검토 권장 `warn-bg` + `warn`, 참고 `surface-2` + `muted`). 그 아래 26px 들여 쓴 근거 문장(13px `muted`)과 좌표 코드 조각. 행 사이는 헤어라인, 선택된 행은 `primary-wash` 바탕과 왼쪽 코발트 막대. 사진 위 박스와 목록 행은 같은 번호로 짝을 이룹니다.

## Do's and Don'ts

### Do:
- **Do** 새 화면도 `bg` 바닥 위의 `surface` 작업 면 하나로 시작하고, 칸은 1px `line` 헤어라인으로 나누세요.
- **Do** 숫자·좌표·파일 정보·상태는 모노 12px tabular로 쓰고, 상태 태그는 `[ ]`로 감싸 제목과 같은 줄에 두세요.
- **Do** 코발트·빨강 계열 바탕 위의 글자는 `primary-ink`·`accent-ink`로 쓰세요.
- **Do** 사진을 놓는 바닥에는 점 패턴을, 사진 자체에는 사진 받침 그림자를 쓰세요.
- **Do** 선택 상태는 `primary-tint`(작은 컨트롤) 또는 `primary-wash` + `primary` 테두리(넓은 옵션)로 표시하세요.
- **Do** `prefers-reduced-motion`에서는 모든 애니메이션과 전환을 끄세요. 움직임은 150~250ms, `cubic-bezier(.16,1,.3,1)` 감속 곡선입니다.

### Don't:
- **Don't** 패널·목록·카드에 그림자를 넣지 마세요. 그림자는 떠 있는 물체에만 씁니다.
- **Don't** 코발트·빨강을 장식(배경 띠, 구분선, 아이콘 일괄 착색)으로 쓰지 마세요. 빨강은 바탕 빛에도 섞지 않습니다.
- **Don't** 제목 위에 작은 대문자 라벨(아이브로·키커)을 얹지 마세요. 상태는 제목 옆 대괄호 태그로 말합니다.
- **Don't** 마케팅 히어로, 떠 있는 카드 그리드, 큰 장식 일러스트를 작업 화면에 들이지 마세요.
- **Don't** 다른 서비스의 이름·로고·아이콘을 쓰지 마세요. 렌즈 마크가 유일한 브랜드 표식입니다.
- **Don't** 외부 글꼴·이미지·CDN을 불러오지 마세요(CSP `default-src 'self'`). 글꼴은 `dist/fonts/`의 자체 호스팅 파일만 씁니다.

### Open Issues (기록만, 규칙 아님)
- 굵기 650은 가변 글꼴에서만 의미가 있습니다. 정적 서브셋에서는 700으로 렌더링되니, 새 코드에서는 600 또는 700을 쓰세요.
- 색 값은 2026-11-17(상징색 일렉트릭 코발트, #103) 화면에 맞췄습니다. **모서리·여백·글자 크기·그림자 원칙(Shapes, Layout, Typography, Elevation 의 '평평한 것이 기본')은 예전 주황 테마 시절 기록**이라 지금 화면(모서리 20px, 반투명 유리 면)과 다른 곳이 있습니다.
- 토큰 밖 고정 색(`#e8a21a` 검토 박스, `#8a5a0c` 검토 라벨, 전후 비교 손잡이 선 `#2449e8`)은 위 `review`·`review-label`·`primary-solid` 로 기록만 했고 CSS 변수는 아닙니다.
