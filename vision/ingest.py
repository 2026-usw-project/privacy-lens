"""① inbox 의 새 사진을 정리해 ② review 로 옮긴다.

사진마다 하는 일
  1. EXIF 방향을 화소에 반영하고 **EXIF 를 전부 버린다**(촬영 장소 GPS 가 팀원 집일 수 있다)
  2. 긴 변을 MAX_SIDE 로 줄여 JPEG 로 저장. 이름은 원본 내용 해시 → 같은 사진을 두 번 넣어도 한 장
  3. 지금 모델이 있으면 박스를 미리 그려 둔다(초벌 라벨). 사람은 틀린 것만 고친다
  4. 원본은 inbox 에서 지운다(위치정보가 남은 파일을 공유 폴더에 오래 두지 않으려고)
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from PIL import Image, ImageOps

from .workspace import IMAGE_EXTS, REVIEW, Row, Workspace, file_id

MAX_SIDE = 2560      # 학습은 1280 으로 하지만 작은 물체 때문에 여유를 둔다
PRELABEL_CONF = 0.25 # 초벌 라벨 기준. 낮을수록 많이 그리고 사람이 지운다

try:  # 아이폰 HEIC
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass


def _group_of(path: Path, inbox: Path) -> str:
    rel = path.relative_to(inbox)
    if len(rel.parts) > 1:
        return rel.parts[0].strip()
    # inbox 바로 아래 넣은 사진은 날짜로 묶는다. 묶음 이름을 쓰는 게 좋다
    return "묶음없음_" + dt.date.today().strftime("%m%d")


def _clean_copy(src: Path, dst: Path) -> tuple[int, int]:
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGB")
        im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
        # exif 인자를 주지 않으면 메타데이터 없이 저장된다
        im.save(dst, "JPEG", quality=92, optimize=True)
        return im.size


def _prelabel(model, img_path: Path, label_path: Path, imgsz: int) -> int:
    res = model.predict(str(img_path), conf=PRELABEL_CONF, imgsz=imgsz, verbose=False)[0]
    lines = []
    for cls, xywhn in zip(res.boxes.cls.tolist(), res.boxes.xywhn.tolist()):
        x, y, w, h = xywhn
        lines.append(f"{int(cls)} {x:.6f} {y:.6f} {w:.6f} {h:.6f}")
    label_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return len(lines)


def run(ws: Workspace, *, keep_originals: bool = False, prelabel: bool = True) -> None:
    ws.init()
    rows = ws.load()

    files = sorted(
        p for p in ws.inbox.rglob("*")
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS and not p.name.startswith(".")
    )
    if not files:
        print("inbox 에 새 사진이 없습니다.")
        return

    model, version = None, ""
    weights = ws.current_model()
    if prelabel and weights:
        from ultralytics import YOLO
        model, version = YOLO(str(weights)), ws.current_version()
        imgsz = ws.model_imgsz()
        print(f"초벌 라벨: {version} 모델로 박스를 미리 그립니다.")
    elif prelabel:
        print("아직 학습된 모델이 없어 빈 라벨로 넣습니다. 첫 학습 뒤부터 초벌 라벨이 붙습니다.")

    added = dup = bad = 0
    for src in files:
        try:
            fid = file_id(src)
            if fid in rows:
                dup += 1
            else:
                img = ws.review / "images" / f"{fid}.jpg"
                _clean_copy(src, img)
                label = ws.review / "labels" / f"{fid}.txt"
                if model:
                    n = _prelabel(model, img, label, imgsz)
                else:
                    label.write_text("", encoding="utf-8")
                rows[fid] = Row(
                    id=fid, group=_group_of(src, ws.inbox), source="real", split="",
                    status=REVIEW, added_at=dt.datetime.now().isoformat(timespec="seconds"),
                    orig_name=src.name, prelabel=version,
                )
                added += 1
                print(f"  + {src.relative_to(ws.inbox)}  →  {fid}.jpg"
                      + (f"  (초벌 {n}개)" if model else ""))
            if not keep_originals:
                src.unlink()
        except Exception as exc:  # 깨진 파일 하나 때문에 전체가 멈추지 않게
            bad += 1
            print(f"  ! {src.name}: 열 수 없어 건너뜀 ({exc})")

    ws.save(rows)
    # 비어 버린 묶음 폴더 정리
    if not keep_originals:
        for d in sorted(ws.inbox.rglob("*"), key=lambda p: -len(p.parts)):
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()

    print(f"\n새 사진 {added}장, 이미 있던 사진 {dup}장, 실패 {bad}장")
    print(f"다음: 라벨링 도구로 {ws.review} 폴더를 열어 검수하세요.")
