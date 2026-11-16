"""서버 설정 파일(.env)을 읽어 환경 변수로 넣는다. 외부 패키지(python-dotenv) 없이.

- 위치: PL_ENV_FILE, 없으면 저장소 맨 위의 .env. 파일이 없으면 아무것도 하지 않는다.
- 이미 설정된 환경 변수는 덮어쓰지 않는다(명령줄·셸에서 준 값이 이긴다).
- 형식: KEY=VALUE 한 줄에 하나. # 으로 시작하는 줄은 주석, 'export ' 앞말은 무시, 값의 앞뒤 따옴표는 벗긴다.
- 값(특히 API 키)은 출력·로그에 넣지 않는다. 돌려주는 것은 이름뿐이다.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def parse(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        name, value = (part.strip() for part in line.split("=", 1))
        if not _NAME.match(name):
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:  # 따옴표 없는 값 뒤의 주석
            value = value.split(" #", 1)[0].rstrip()
        out[name] = value
    return out


def load(path: str | os.PathLike | None = None) -> list[str]:
    """.env 를 읽어 아직 없는 환경 변수만 넣는다. 넣은 이름 목록을 돌려준다."""
    p = Path(path or os.environ.get("PL_ENV_FILE") or ROOT / ".env")
    try:
        text = p.read_text(encoding="utf-8-sig")
    except (FileNotFoundError, IsADirectoryError):
        return []
    added = []
    for name, value in parse(text).items():
        if name not in os.environ:
            os.environ[name] = value
            added.append(name)
    return added
