"""
저장본(안전 버전)에 EXIF 가 남아 있는지 검사 — 성공 기준 'EXIF 제거율 100%' 확인용

  python -m data.check_exif ~/Downloads/safe_*.jpg
  python -m data.check_exif 폴더

하나라도 EXIF 가 남아 있으면 종료 코드 1.
"""
from __future__ import annotations

import sys
from pathlib import Path

from server.exif import parse


def leftover(raw: bytes) -> str | None:
    """EXIF 가 남아 있으면 이유, 깨끗하면 None"""
    info = parse(raw)
    if info.gps:
        return "GPS 위치가 남아 있음"
    return "메타데이터(기기·시각 등)가 남아 있음" if info.present else None


def main(args: list[str]) -> int:
    files = [f for a in args for f in (sorted(Path(a).glob("*")) if Path(a).is_dir() else [Path(a)])
             if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")]
    if not files:
        print("검사할 이미지가 없습니다.")
        return 2
    bad = 0
    for f in files:
        why = leftover(f.read_bytes())
        bad += why is not None
        print(f"{'남음' if why else '깨끗'}  {f.name}" + (f"  — {why}" if why else ""))
    print(f"\nEXIF 제거율 {len(files) - bad}/{len(files)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
