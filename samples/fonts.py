"""한국어 폰트 찾기.

운영체제마다 한글 폰트가 다른 자리에 있다. 경로를 박아두면 다른 컴퓨터에서
바로 깨진다. 후보를 순서대로 훑고, 그래도 없으면 폰트 폴더를 뒤진다.

Windows  맑은 고딕 (malgun.ttf)
macOS    Apple SD Gothic Neo
Linux    Noto Sans CJK / 나눔고딕
"""

from __future__ import annotations

import sys
from pathlib import Path

# (일반, 굵게) 쌍. 굵은 폰트가 없으면 일반을 그대로 쓴다.
CANDIDATES: list[tuple[str, str | None]] = [
    # Windows
    (r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\malgunbd.ttf"),
    (r"C:\Windows\Fonts\NanumGothic.ttf", r"C:\Windows\Fonts\NanumGothicBold.ttf"),
    (r"C:\Windows\Fonts\gulim.ttc", None),
    (r"C:\Windows\Fonts\batang.ttc", None),
    # macOS
    ("/System/Library/Fonts/AppleSDGothicNeo.ttc", None),
    ("/System/Library/Fonts/Supplemental/AppleGothic.ttf", None),
    ("/Library/Fonts/AppleGothic.ttf", None),
    # Linux
    (
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    ),
    (
        "/usr/share/fonts/opentype/noto/NotoSansCJKkr-Regular.otf",
        "/usr/share/fonts/opentype/noto/NotoSansCJKkr-Bold.otf",
    ),
    (
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    ),
]

# 폴더를 뒤질 때 쓸 이름 조각
NAME_HINTS = ("malgun", "nanum", "notosanscjk", "notosanskr", "applegothic",
              "gulim", "batang", "dotum", "sourcehansans")

SEARCH_DIRS = [
    Path(r"C:\Windows\Fonts"),
    Path.home() / "AppData/Local/Microsoft/Windows/Fonts",
    Path("/System/Library/Fonts"),
    Path("/Library/Fonts"),
    Path.home() / "Library/Fonts",
    Path("/usr/share/fonts"),
    Path("/usr/local/share/fonts"),
    Path.home() / ".local/share/fonts",
]


# 굵기 선호도. Black/Thin 을 본문에 쓰면 보기 나쁘다.
_WEIGHTS = ["regular", "bold", "medium", "semibold", "light", "black", "thin"]


def _weight_rank(stem: str) -> int:
    """0 = Regular 가장 선호, 숫자가 클수록 덜 선호."""
    for i, w in enumerate(_WEIGHTS):
        if w in stem:
            return i
    return 0  # 굵기 표기가 없으면 보통 Regular 다


def _scan() -> tuple[str, str] | None:
    for base in SEARCH_DIRS:
        if not base.is_dir():
            continue
        try:
            files = list(base.rglob("*.tt[cf]")) + list(base.rglob("*.otf"))
        except OSError:
            continue
        hits = []
        for f in files:
            stem = f.stem.lower().replace(" ", "").replace("-", "").replace("_", "")
            if any(h in stem for h in NAME_HINTS):
                hits.append((_weight_rank(stem), str(f)))
        if hits:
            hits.sort()
            best = hits[0][1]
            bold = next((p for r, p in hits if r == 1), best)
            return best, bold
    return None


def find_korean_font() -> tuple[str, str]:
    """(일반 폰트 경로, 굵은 폰트 경로) 를 돌려준다."""
    for regular, bold in CANDIDATES:
        if Path(regular).exists():
            if bold and Path(bold).exists():
                return regular, bold
            return regular, regular

    found = _scan()
    if found:
        return found

    raise RuntimeError(
        "한글 폰트를 찾지 못했습니다.\n"
        + (
            "  Windows: 맑은 고딕이 기본 설치돼 있어야 합니다. "
            "없으면 나눔고딕을 설치하세요.\n"
            if sys.platform == "win32"
            else "  Linux: sudo apt install fonts-nanum  또는  fonts-noto-cjk\n"
            "  macOS: 기본 폰트가 있어야 정상입니다.\n"
        )
        + "  설치 후 다시 실행하세요."
    )
