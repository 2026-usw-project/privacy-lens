"""MIDV-2020 공개 데이터셋을 학습 데이터로 가져온다.

MIDV-2020 은 가상 신분증 1,000종을 직접 촬영한 연구용 데이터셋이다. 글자 내용은
가상이고 얼굴도 생성된 얼굴이라 실제 개인정보가 없다.
  https://l3i-share.univ-lr.fr/MIDV2020/midv2020.html  (신청서 작성·라이선스 동의 후 내려받기)

받은 뒤 photo.tar 를 풀고 그 폴더를 넘긴다(scan_rotated 도 가능).

  python -m vision import-midv  D:/MIDV2020/photo

주석은 VGG Image Annotator(VIA) JSON 이고, 사진마다 두 영역이 있다.
  doc_quad  문서 네 꼭짓점  → id_card (여권도 신분증류로 본다)
  face      얼굴 영역       → face_photo (인쇄된 증명사진 전체에 가깝게 조금 넓힌다)

가져온 사진은 합성과 마찬가지로 **학습(train)에만** 쓴다. 외국 신분증이라
점수는 팀이 찍은 한국 실사로만 낸다. 라이선스상 공유 폴더 밖으로 재배포하지 않는다.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageOps

from .ingest import MAX_SIDE
from .workspace import DONE, IMAGE_EXTS, Row, Workspace

ID_CARD, FACE_PHOTO = 1, 4
# 얼굴 영역 → 증명사진 전체로 넓히는 비율(좌우·위아래 각각). 대략치다
FACE_GROW_X, FACE_GROW_Y = 0.20, 0.25


def _points(shape: dict) -> list[tuple[float, float]] | None:
    kind = shape.get("name")
    if kind in ("polygon", "polyline"):
        return list(zip(map(float, shape["all_points_x"]), map(float, shape["all_points_y"])))
    if kind == "rect":
        x, y, w, h = (float(shape[k]) for k in ("x", "y", "width", "height"))
        return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    if kind in ("ellipse", "circle"):
        cx, cy = float(shape["cx"]), float(shape["cy"])
        rx = float(shape.get("rx", shape.get("r", 0)))
        ry = float(shape.get("ry", shape.get("r", 0)))
        return [(cx - rx, cy - ry), (cx + rx, cy + ry)]
    return None


def _field(region: dict) -> str:
    attrs = region.get("region_attributes") or {}
    for key in ("field_name", "name", "label", "type"):
        if isinstance(attrs.get(key), str):
            return attrs[key].strip()
    for v in attrs.values():  # 이름 키가 다를 때: 값에서 찾는다
        if v in ("doc_quad", "face", "photo"):
            return v
    return ""


def _entries(data) -> list[dict]:
    """VIA 프로젝트 파일과 내보내기 파일 둘 다 받는다."""
    if isinstance(data, dict) and "_via_img_metadata" in data:
        data = data["_via_img_metadata"]
    if isinstance(data, dict):
        return [v for v in data.values() if isinstance(v, dict) and "filename" in v]
    return []


def _find_image(json_path: Path, filename: str, index: dict[tuple[str, str], Path]) -> Path | None:
    direct = (json_path.parent / filename)
    if direct.exists():
        return direct
    # photo/annotations/alb_id.json ↔ photo/images/alb_id/00.jpg
    return index.get((json_path.stem, Path(filename).name))


def _bbox(points, W, H):
    xs = [min(max(p[0], 0), W) for p in points]
    ys = [min(max(p[1], 0), H) for p in points]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    return x0, y0, x1, y1


def _fits(points, W, H, slack=0.02) -> bool:
    return all(-W * slack <= x <= W * (1 + slack) and -H * slack <= y <= H * (1 + slack)
               for x, y in points)


def convert(json_path: Path, index) -> list[tuple[Path, Image.Image, list[str], str]]:
    """주석 파일 하나 → (원본 경로, 회전 맞춘 사진, YOLO 라벨 줄, 문서 종류)."""
    out = []
    data = json.loads(json_path.read_text(encoding="utf-8"))
    for e in _entries(data):
        img_path = _find_image(json_path, e["filename"], index)
        if img_path is None:
            continue
        fields = {}
        for r in e.get("regions") or []:
            pts = _points(r.get("shape_attributes") or {})
            if pts:
                fields.setdefault(_field(r), pts)
        quad = fields.get("doc_quad")
        if not quad:
            continue

        with Image.open(img_path) as raw:
            raw.load()
            # 주석 좌표가 EXIF 회전 전 기준인지 후 기준인지 파일마다 확인한다.
            # 문서 꼭짓점이 사진 안에 들어가는 쪽을 쓴다.
            if _fits(quad, *raw.size):
                im = raw.copy()
            else:
                turned = ImageOps.exif_transpose(raw)
                if turned.size == raw.size or not _fits(quad, *turned.size):
                    print(f"  ! {img_path.name}: 주석 좌표가 사진 밖이라 건너뜀")
                    continue
                im = turned
        im = im.convert("RGB")
        W, H = im.size

        lines = []
        b = _bbox(quad, W, H)
        if b:
            lines.append((ID_CARD, b))
        face = fields.get("face") or fields.get("photo")
        if face:
            fb = _bbox(face, W, H)
            if fb:
                x0, y0, x1, y1 = fb
                gx, gy = (x1 - x0) * FACE_GROW_X, (y1 - y0) * FACE_GROW_Y
                grown = _bbox([(x0 - gx, y0 - gy), (x1 + gx, y1 + gy)], W, H)
                if grown:
                    lines.append((FACE_PHOTO, grown))

        text = [f"{c} {(x0 + x1) / 2 / W:.6f} {(y0 + y1) / 2 / H:.6f} {(x1 - x0) / W:.6f} {(y1 - y0) / H:.6f}"
                for c, (x0, y0, x1, y1) in lines]
        out.append((img_path, im, text, json_path.stem))
    return out


def run(ws: Workspace, src: str, limit: int | None = None) -> None:
    ws.init()
    rows = ws.load()
    root = Path(src).expanduser().resolve()
    if not root.is_dir():
        raise SystemExit(f"폴더가 없습니다: {root}")

    index: dict[tuple[str, str], Path] = {}
    for p in root.rglob("*"):
        if p.suffix.lower() in IMAGE_EXTS:
            index.setdefault((p.parent.name, p.name), p)
    jsons = sorted(p for p in root.rglob("*.json") if "clips" not in p.parts)
    if not jsons:
        raise SystemExit("주석(.json) 파일을 찾지 못했습니다. photo.tar 를 푼 폴더를 지정하세요.")

    added = skipped = 0
    for jp in jsons:
        per_type = 0
        for img_path, im, lines, doc_type in convert(jp, index):
            if limit and per_type >= limit:
                break
            rel = img_path.relative_to(root).with_suffix("").as_posix()
            fid = f"midv_{doc_type}_{hashlib.sha1(rel.encode('utf-8')).hexdigest()[:10]}"
            if fid in rows:
                skipped += 1
                continue
            im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
            im.save(ws.dataset / "images" / f"{fid}.jpg", "JPEG", quality=90)  # EXIF 없이
            (ws.dataset / "labels" / f"{fid}.txt").write_text(
                "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
            rows[fid] = Row(id=fid, group=f"midv_{doc_type}", source="public", split="train",
                            status=DONE, added_at=dt.datetime.now().isoformat(timespec="seconds"),
                            orig_name=rel, prelabel="")
            added += 1
            per_type += 1
        print(f"  {jp.relative_to(root)}: {per_type}장")

    ws.save(rows)
    from .build import write_lists
    write_lists(ws, rows)
    print(f"\nMIDV-2020 {added}장을 학습 데이터에 넣었습니다(train 전용, 이미 있던 {skipped}장 건너뜀).")
