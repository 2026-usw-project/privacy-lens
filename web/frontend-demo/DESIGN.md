---
name: Privacy Lens
description: 사진 배경의 개인정보를 찾아 위치와 근거를 보여 주고, 가린 사본을 저장하는 작업대
colors:
  bg: "#f7f6f3"
  surface: "#fdfdfc"
  surface-2: "#f0efeb"
  surface-3: "#e8e6e1"
  line: "#e6e3dd"
  line-strong: "#d4d0c7"
  ink: "#1f1d1a"
  ink-2: "#4a4741"
  muted: "#6b675f"
  accent: "#ef5a1c"
  accent-solid: "#cf4510"
  accent-hover: "#b23f0b"
  accent-ink: "#b23f0b"
  accent-tint: "#fdede4"
  accent-wash: "#fef6f1"
  accent-line: "#f5ccb6"
  ok: "#2c7a4b"
  warn: "#8a5a0c"
  warn-bg: "#fdf6e7"
  warn-line: "#efd9a8"
  error: "#b42318"
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
    backgroundColor: "{colors.accent}"
    textColor: "#ffffff"
    rounded: "{rounded.md}"
    padding: "0 16px"
    height: "40px"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
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
    backgroundColor: "{colors.accent-tint}"
    textColor: "{colors.accent-ink}"
  nav-item:
    textColor: "{colors.ink-2}"
    rounded: "{rounded.sm}"
    padding: "0 12px"
    height: "40px"
  nav-item-active:
    backgroundColor: "{colors.accent-tint}"
    textColor: "{colors.accent-ink}"
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

사진 검사는 마케팅 페이지가 아니라 대시보드 안의 한 작업 화면입니다. 웜 오프화이트 바닥 위에 흰 작업 면 하나를 놓고, 그 면을 1px 헤어라인으로 나눠 왼쪽에는 사진, 오른쪽에는 근거 목록과 저장 버튼을 둡니다. 화면 안에서 가장 시끄러운 것은 사진 위의 주황 박스여야 하고, 그 외의 장치는 조용히 물러납니다. 시각 문법은 Firecrawl 대시보드의 스타일만 빌렸고, 이름·로고·불꽃 아이콘은 쓰지 않습니다.

밀도는 데스크톱 도구 수준입니다. 본문은 13~14px, 행 높이는 34~48px, 패널 안쪽 여백은 20px 안팎으로 한 화면에 사진과 목록과 저장 버튼이 함께 들어갑니다. 숫자·좌표·파일 정보·상태는 모노 글꼴의 대괄호 라벨(`[ 가상 데이터 ]` 문법)로, 문장은 한글 산세리프로 씁니다. 깊이는 대부분 선과 면의 명도 차이로 만들고, 그림자는 실제로 떠 있는 물체(입력 막대, 사진, 대화상자, 토스트)에만 붙습니다.

글꼴은 Pretendard(OFL)를 `dist/fonts/`에 자체 호스팅합니다. KS X 1001 한글 서브셋 정적 4종(400·500·600·700, 각 약 270KB)이며 외부 요청은 없습니다(CSP `default-src 'self'`). 라이선스는 `dist/fonts/LICENSE.txt`.

**Key Characteristics:**
- 웜 오프화이트 바닥 + 흰 작업 면 하나, 1px 헤어라인 분할, 분할선이 테두리와 만나는 곳에 + 표시
- 주황은 주요 행동·선택·위험 표시·헤드라인의 한 단어에만
- 데이터와 상태는 모노 12px, 상태 태그는 대괄호로 감싼다
- 그림자는 떠 있는 물체에만, 패널과 목록은 평평하다
- 반응형은 구조만 바꾸고 글자 크기는 거의 고정

## Colors

따뜻한 회백색 중립색 위에 주황 하나가 일하는 단일 강조 팔레트입니다.

### Primary
- **신호 주황 (Signal Orange)** (`accent`): 탐지 박스 테두리, 진행 막대, 상태 점, 포커스 링, 브랜드 마크, 헤드라인의 강조 한 단어. 화면에서 "지금 여기를 보라"는 뜻만 가집니다. 흰 글자의 바탕으로는 쓰지 않습니다(3.4:1).
- **단단한 주황 (Solid Orange)** (`accent-solid`): 흰 글자가 올라가는 주황 면(주요 버튼, 박스 번호 라벨, 현재 단계 번호). 흰 글자 대비 4.65:1.
- **짙은 주황 (Ember)** (`accent-hover`): 주요 버튼의 hover 바탕(흰 글자 5.8:1).
- **녹슨 주황 글자 (Rust Ink)** (`accent-ink`): 연한 주황 바탕 위의 글자(선택된 내비, 위험 태그, 완료 단계, 진행 중 작업 번호). 주황을 글자로 쓸 때는 반드시 이 값입니다.
- **주황 틴트 (Apricot Tint)** (`accent-tint`): 선택·활성 상태의 채움(내비 활성, 칩 열림, 위험 태그 바탕, 완료 단계 원).
- **주황 워시 (Apricot Wash)** (`accent-wash`): 넓은 면의 선택·안내 바탕(선택된 목록 행, 선택된 가림 방식, 시연 진행 띠, 로컬 처리 카드, 드래그 중인 업로드 면).
- **주황 선 (Apricot Line)** (`accent-line`): 워시 면의 테두리.

### Neutral
- **웜 오프화이트 (Paper)** (`bg`): 페이지 바닥, 사이드바, 상단바, 목록 머리 띠, 점 패턴 아래 바탕.
- **작업 면 (Work Surface)** (`surface`): 작업 공간 프레임, 대화상자, 입력 칸, 하단 저장 영역.
- **보조 면 (Stone 2 / Stone 3)** (`surface-2`, `surface-3`): 고스트 버튼·칩·안내 상자의 바탕과 그 hover.
- **헤어라인 (Hairline)** (`line`): 모든 분할선과 프레임 테두리. **진한 헤어라인** (`line-strong`): 입력 테두리, 단계 원, 점선 빈 상태.
- **먹색 (Ink)** (`ink`): 제목과 주요 글자, 토스트·JSON 패널의 어두운 바탕. **보조 먹색** (`ink-2`): 설명 문장, 보조 버튼 글자. **흐린 글자** (`muted`): 메타 정보, 모노 라벨, 아이콘.

### Status
- **확인됨** (`ok`): 모든 영역이 가림 선택되었을 때 위험 요약 글자.
- **주의** (`warn`, `warn-bg`, `warn-line`): 일부 판독 실패, 서버 저장 안내, 내보내기 경고.
- **오류** (`error`): 오류 상태 줄, 입력 오류, 삭제 버튼 hover, `ERROR` 태그.

### Named Rules
**The One Signal Rule.** 주황은 주요 행동, 선택 상태, 위험 표시, 헤드라인의 한 단어에만 씁니다. 장식용 주황 선·배경·아이콘은 없습니다. 예외는 설명 목록의 대상 아이콘(탐지 대상 표시)처럼 "위험한 것"을 가리키는 경우뿐입니다.

**The Ink-on-Tint Rule.** 주황 계열 바탕 위의 글자는 `accent-ink`, 흰 면 위에 주황을 글자로 쓸 때도 `accent-ink`입니다. `accent` 자체를 작은 글자 색으로 쓰지 않습니다(헤드라인 30px의 강조 단어만 예외).

## Typography

**Display Font:** Pretendard (자체 호스팅 서브셋, 400·500·600·700) → Apple SD Gothic Neo → Malgun Gothic → system-ui. 650으로 적힌 굵기는 정적 글꼴에서 700으로 렌더링됩니다.
**Body Font:** 같은 스택.
**Label/Mono Font:** ui-monospace → SFMono-Regular → Cascadia Mono → Consolas, 한글은 산세리프 스택으로 폴백. 숫자는 항상 tabular.

**Character:** 장식 없는 한글 산세리프가 문장을 맡고, 모노가 숫자·좌표·상태를 맡아 "읽는 글"과 "측정값"이 한눈에 갈립니다. 큰 제목도 30px에서 멈춥니다.

### Hierarchy
- **Display** (700, 30px / 모바일 22px, 1.3, -0.035em): 빈 상태의 한 문장 헤드라인. 강조 한 단어만 주황. 화면당 하나.
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

평평한 것이 기본입니다. 패널, 목록, 카드, 사이드바는 그림자 없이 헤어라인과 면의 명도 차이(`bg` → `surface` → `surface-2`)로 층을 나눕니다. 그림자는 화면 위에 실제로 떠 있는 물체에만, 1~2px 접지 그림자와 넓고 옅은 블러를 겹친 형태로 씁니다. 그림자 색은 항상 먹색(`#1f1d1a`)에 알파를 준 값입니다.

### Shadow Vocabulary
- **떠 있는 입력 막대** (`0 1px 2px #1f1d1a0d, 0 12px 32px #1f1d1a12`): 업로드 면의 드롭 막대.
- **사진 받침** (`0 1px 2px #1f1d1a14, 0 10px 28px #1f1d1a14`): 캔버스의 사진, 내보내기 미리보기(블러 20px).
- **대화상자** (`0 2px 6px #1f1d1a14, 0 24px 64px #1f1d1a2e`): 모달 대화상자. 배경막은 `#1f1d1a59`.
- **토스트** (`0 12px 32px #1f1d1a33`): 하단 알림.
- **선택된 세그먼트** (`0 1px 2px #1f1d1a1f`): 세그먼트 컨트롤의 선택 칸.
- **주요 버튼 광택** (`inset 0 1px 0 #ffffff40, 0 1px 2px #b23f0b59`): 주황 버튼과 브랜드 마크의 윗면 하이라이트.
- **포커스된 박스 후광** (`0 0 0 3px #ef5a1c40`): 사진 위 선택된 탐지 박스.

### Named Rules
**The Only-What-Floats Rule.** 그림자는 입력 막대, 사진, 대화상자, 토스트처럼 바닥 위에 올라온 물체에만. 패널과 목록 행은 선으로 나눕니다.

## Shapes

부드러운 직각입니다. 컨트롤(버튼, 칩, 안내 상자, 카드형 옵션, 토스트)은 10px(`rounded.md`), 작은 컨트롤과 입력은 8px(`rounded.sm`), 작업 공간 프레임은 12px(`rounded.lg`), 드롭 막대와 대화상자는 14px(`rounded.xl`), 태그·코드 조각·박스 라벨은 4px(`rounded.xs`). 단계 번호와 상태 점만 원입니다. 사진 위 탐지 박스는 모서리가 없는 직사각형입니다.

선은 언제나 1px 헤어라인이고, 프레임 위·아래 테두리가 내부 분할선과 만나는 지점에 13px짜리 + 표시를 둡니다(`muted` 색 1px 십자). 점 패턴(`#d6d2c9` 1px 점, 14px 간격)은 사진을 놓는 바닥(업로드 면, 캔버스 무대, 내보내기 미리보기)에만 깔립니다.

## Components

### Buttons
조용하고 단단합니다. 누르면 1px 내려앉습니다.
- **Shape:** 10px 모서리, 높이 40px(작게 34px, 크게 48px).
- **Primary:** `accent-solid` 바탕, 흰 글자 14px 600, 위쪽 광택 그림자. 화면당 하나의 다음 행동(분석 시작, 저장, 다운로드)에만.
- **Hover / Focus:** 바탕이 `accent-hover`로. 포커스는 모든 요소 공통으로 2px 주황 외곽선, 2px 띄움.
- **Ghost:** `surface-2` 바탕, 먹색 글자, hover `surface-3`. 보조 행동(직접 지정, 취소, 시연 재현).
- **Text button:** 바탕 없음, 13px 500 `ink-2`, hover 시 `ink`. 되돌리기·전체 선택·닫기.
- **Disabled:** 불투명도 0.45.

### Chips
- **Style:** 상단바의 36px 칩. `surface-2` 바탕, 13px 500, 아이콘 15px.
- **State:** 펼쳐진 상태(`aria-expanded=true`)는 `accent-tint` 바탕 + `accent-ink` 글자.

### Cards / Containers
- **작업 공간 프레임:** `surface` 바탕, 1px `line` 테두리, 12px 모서리, 그림자 없음, 칸 사이 헤어라인과 + 표시.
- **안내 상자(note, callout, save-state):** `surface-2` 바탕, 테두리 없음, 10px 모서리, 12px×14px.
- **강조 안내(로컬 처리 카드, 시연 진행 띠, 수동 지정 안내):** `accent-wash` 바탕 + `accent-line` 테두리.
- **주의 안내:** `warn-bg` 바탕 + `warn-line` 테두리 + `warn` 글자, 8px 모서리.

### Inputs / Fields
- **Style:** `surface` 바탕, 1px `line-strong` 테두리, 8px 모서리(좌표 칸은 6px). 주소·좌표 입력은 모노.
- **Focus:** 공통 2px 주황 외곽선. 체크박스·라디오·슬라이더는 `accent-color`로 주황.
- **Selected option:** 라디오 옵션 카드와 가림 방식 버튼은 선택 시 테두리 `accent`, 바탕 `accent-wash`.
- **Error:** 입력 아래 13px `error` 글자 줄.

### Navigation
- **사이드바:** `bg` 바탕, 오른쪽 헤어라인. 항목 40px, 14px 500 `ink-2`, hover `surface-2`, 활성 `accent-tint` + `accent-ink`. 개수는 모노 12px로 오른쪽 끝.
- **단계 표시:** 22px 원 안의 모노 숫자, 단계 사이 28px 헤어라인. 현재 단계는 `accent-solid` 원 + 흰 숫자, 완료는 `accent-tint` 원 + 체크.
- **모바일:** 사이드바가 56px 상단 막대로, 내비는 아이콘만.

### Segmented Control
3px 안쪽 여백의 `surface-2` 트랙, 30px 칸. 선택된 칸은 `surface` 바탕 + 먹색 글자 + 1px 접지 그림자.

### Region Box (signature)
사진 위의 탐지 영역입니다. 1.5px 주황 테두리, 주황 8% 채움(hover·포커스 16%). 포커스되면 테두리 2px와 3px 주황 후광, 라벨이 박스 위로 올라가 유형 이름까지 보입니다. 평소 라벨은 박스 왼쪽 바깥에 번호만(`accent-solid` 바탕 흰 모노 12px, 4px 모서리) 붙어 이웃 박스를 덮지 않고, 포커스된 박스만 라벨이 위로 올라가 이름을 보입니다. 580px 이하에서는 박스 안 왼쪽 위 11px. 가림 해제된 박스는 회색 1px 점선에 채움 없음. 오른쪽 아래 12px 흰 크기 조절 손잡이.

### Region List Row (signature)
번호(모노 12px `muted`) + 이름(14px 600) + 오른쪽 위험 태그(`accent-tint` 바탕 모노 12px). 그 아래 26px 들여 쓴 근거 문장(13px `muted`)과 좌표 코드 조각. 행 사이는 헤어라인, 선택된 행은 `accent-wash` 바탕. 사진 위 박스와 목록 행은 같은 번호로 짝을 이룹니다.

## Do's and Don'ts

### Do:
- **Do** 새 화면도 `bg` 바닥 위의 `surface` 작업 면 하나로 시작하고, 칸은 1px `line` 헤어라인으로 나누세요.
- **Do** 숫자·좌표·파일 정보·상태는 모노 12px tabular로 쓰고, 상태 태그는 `[ ]`로 감싸 제목과 같은 줄에 두세요.
- **Do** 주황 계열 바탕 위의 글자는 `accent-ink`로 쓰세요.
- **Do** 사진을 놓는 바닥에는 점 패턴을, 사진 자체에는 사진 받침 그림자를 쓰세요.
- **Do** 선택 상태는 `accent-tint`(작은 컨트롤) 또는 `accent-wash` + `accent` 테두리(넓은 옵션)로 표시하세요.
- **Do** `prefers-reduced-motion`에서는 모든 애니메이션과 전환을 끄세요. 움직임은 150~250ms, `cubic-bezier(.16,1,.3,1)` 감속 곡선입니다.

### Don't:
- **Don't** 패널·목록·카드에 그림자를 넣지 마세요. 그림자는 떠 있는 물체에만 씁니다.
- **Don't** 주황을 장식(배경 띠, 구분선, 아이콘 일괄 착색)으로 쓰지 마세요.
- **Don't** 제목 위에 작은 대문자 라벨(아이브로·키커)을 얹지 마세요. 상태는 제목 옆 대괄호 태그로 말합니다.
- **Don't** 마케팅 히어로, 떠 있는 카드 그리드, 큰 장식 일러스트를 작업 화면에 들이지 마세요.
- **Don't** Firecrawl의 이름·로고·불꽃 아이콘을 쓰지 마세요. 렌즈 마크가 유일한 브랜드 표식입니다.
- **Don't** 외부 글꼴·이미지·CDN을 불러오지 마세요(CSP `default-src 'self'`). 글꼴은 `dist/fonts/`의 자체 호스팅 파일만 씁니다.

### Open Issues (기록만, 규칙 아님)
- 굵기 650은 가변 글꼴에서만 의미가 있습니다. 정적 서브셋에서는 700으로 렌더링되니, 새 코드에서는 600 또는 700을 쓰세요.
- 7·9·5·6px 모서리와 토큰 밖의 고정 색(`#8a857c`, `#d99a1e`, `#ffb48f`, `#8f2a14`, `#fbd3bd`)은 빌드에 남아 있지만 체계로 기록하지 않았습니다. 새 화면에서는 위 토큰을 쓰세요.
