"""② review 에서 검수가 끝난 사진을 ③ dataset 으로 옮기고 학습 목록을 다시 만든다.

라벨링 도구가 저장하면 review/done/<id>.ok 가 생긴다. '사진 제외'는 <id>.skip.
.ok 인 것만 dataset 으로 간다. 검수하지 않은 초벌 라벨은 절대 학습에 쓰지 않는다
(모델이 자기 실수를 다시 배운다).

분할 원칙
  - 묶음 단위로 나눈다(누수 방지). 한 번 정한 분할은 바꾸지 않는다(manifest 에 기록)
  - val·test 는 **직접 촬영한 사진만**. 합성은 학습에만 쓴다. 평가는 실사로 해야 의미가 있다
  - 새 묶음은 목표 비율(70/15/15)에서 가장 모자란 쪽으로 간다
"""

from __future__ import annotations

import shutil

from PIL import Image

from .classes import NAMES
from .workspace import DONE, REVIEW, SKIPPED, Workspace

MIN_BOX_PX = 6     # 이보다 작은 박스는 클릭 실수로 본다
DUP_IOU = 0.9      # 같은 클래스 박스가 이만큼 겹치면 두 번 그린 것
_IDX = {n: i for i, n in NAMES.items()}


def _split_of_group(group: str, rows) -> str | None:
    for r in rows.values():
        if r.group == group and r.split:
            return r.split
    return None


TARGET = {"train": 0.70, "val": 0.15, "test": 0.15}


def _assign(group: str, source: str, rows) -> str:
    """새 묶음을 목표 비율(70/15/15)에서 가장 모자란 쪽에 넣는다.

    해시로 무작위 배정하면 묶음이 몇 개 안 될 때 학습 쪽이 텅 빌 수 있다.
    모자란 쪽부터 채우면 묶음 3개째에 val, 5개째에 test 가 생긴다.
    """
    if source != "real":
        return "train"
    known = _split_of_group(group, rows)
    if known:
        return known
    groups: dict[str, str] = {}
    for r in rows.values():
        if r.source == "real" and r.split:
            groups[r.group] = r.split
    total = len(groups) + 1
    count = {k: sum(1 for v in groups.values() if v == k) for k in TARGET}
    return max(TARGET, key=lambda k: TARGET[k] * total - count[k])  # 동점이면 train → val → test


def _check_label(path) -> list[str]:
    """라벨 한 줄 = 'cls cx cy w h' (0~1). 잘못된 줄은 이유와 함께 돌려준다."""
    problems = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split()
        try:
            cls, *xywh = int(parts[0]), *map(float, parts[1:])
        except ValueError:
            problems.append(f"{i}행 숫자가 아님")
            continue
        if len(xywh) != 4:
            problems.append(f"{i}행 값 개수 {len(xywh)}개")
        elif cls not in NAMES:
            problems.append(f"{i}행 없는 클래스 {cls}")
        elif not all(0 <= v <= 1 for v in xywh) or xywh[2] <= 0 or xywh[3] <= 0:
            problems.append(f"{i}행 좌표 범위 밖")
    return problems


def _iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix * iy
    return ix * iy / union if union > 0 else 0.0


def _check_boxes(path, size) -> tuple[list[str], list[str]]:
    """형식은 맞지만 이상한 박스를 찾는다. (막을 것, 경고만 할 것).

    _check_label 을 통과한 파일만 넣는다. 막는 것은 거의 확실한 실수(클릭 실수로 생긴
    점 같은 박스, 같은 박스를 두 번 그림)뿐이고, 일부러 그랬을 수도 있는 것은 경고만 한다.
    """
    W, H = size
    boxes = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            c, cx, cy, w, h = line.split()
            cx, cy, w, h = float(cx) * W, float(cy) * H, float(w) * W, float(h) * H
            boxes.append((int(c), (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)))
    problems, warnings = [], []
    for i, (c, b) in enumerate(boxes, 1):
        if b[2] - b[0] < MIN_BOX_PX or b[3] - b[1] < MIN_BOX_PX:
            problems.append(f"{i}번째 박스가 {MIN_BOX_PX}px보다 작음")
        if any(c == c2 and _iou(b, b2) >= DUP_IOU for c2, b2 in boxes[:i - 1]):
            problems.append(f"{i}번째 박스를 두 번 그림")
        if (b[2] - b[0]) * (b[3] - b[1]) >= 0.9 * W * H:
            warnings.append(f"{i}번째 박스가 사진 거의 전체")
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        if c == _IDX["face_photo"] and not any(
                c2 == _IDX["id_card"] and b2[0] <= cx <= b2[2] and b2[1] <= cy <= b2[3]
                for c2, b2 in boxes):
            warnings.append(f"{i}번째 증명사진이 학생증·카드 박스 밖에 있음")
    return problems, warnings


def run(ws: Workspace) -> None:
    ws.init()
    rows = ws.load()
    done_dir = ws.review / "done"

    moved = skipped = broken = 0
    for marker in sorted(done_dir.glob("*.*")):
        fid, kind = marker.stem, marker.suffix
        row = rows.get(fid)
        img = ws.review / "images" / f"{fid}.jpg"
        label = ws.review / "labels" / f"{fid}.txt"
        if row is None or row.status != REVIEW:
            marker.unlink()
            continue

        if kind == ".skip":
            img.unlink(missing_ok=True)
            label.unlink(missing_ok=True)
            row.status = SKIPPED
            skipped += 1
        elif kind == ".ok":
            if not img.exists():
                print(f"  ! {fid}: 사진 파일이 없음")
                broken += 1
                continue
            if not label.exists():
                label.write_text("", encoding="utf-8")  # 물체 없는 사진(배경). 오탐을 줄이는 데 쓴다
            problems, warnings = _check_label(label), []
            if not problems:
                with Image.open(img) as im:
                    more, warnings = _check_boxes(label, im.size)
                problems += more
            if problems:
                print(f"  ! {fid}: 라벨 오류 {problems} → 검수 폴더에 남겨 둡니다")
                broken += 1
                marker.unlink()
                continue
            for w in warnings:
                print(f"  ? {fid}: {w} — 맞는지 확인하세요")
            row.split = _assign(row.group, row.source, rows)
            shutil.move(str(img), ws.dataset / "images" / img.name)
            shutil.move(str(label), ws.dataset / "labels" / label.name)
            row.status = DONE
            moved += 1
        else:
            continue
        marker.unlink()

    ws.save(rows)
    write_lists(ws, rows)
    print(f"\n데이터셋에 {moved}장 추가, 제외 {skipped}장, 오류 {broken}장")
    waiting = sum(1 for r in rows.values() if r.status == REVIEW)
    if not (moved or skipped or broken) and waiting:
        print(f"  ? 검수 대기 {waiting}장에 완료 표시가 없습니다. 라벨 도구에서 Enter 를 눌렀는지, "
              "데스크톱 앱이 드라이브에 다 올렸는지(동기화) 확인한 뒤 다시 실행하세요")
    status(ws, rows)


def write_lists(ws: Workspace, rows=None) -> None:
    """train/val/test.txt 와 data.yaml. 경로는 상대 경로라 Colab·내 PC 어디서든 맞다."""
    rows = rows if rows is not None else ws.load()
    lists = {"train": [], "val": [], "test": []}
    for r in sorted(rows.values(), key=lambda r: r.id):
        if r.status == DONE and (ws.dataset / "images" / f"{r.id}.jpg").exists():
            lists[r.split or "train"].append(f"./images/{r.id}.jpg")
    for name, items in lists.items():
        (ws.dataset / f"{name}.txt").write_text("\n".join(items) + "\n", encoding="utf-8")
    write_yaml(ws.dataset, has_test=bool(lists["test"]), has_val=bool(lists["val"]))


def write_yaml(dataset_dir, *, has_val: bool, has_test: bool) -> None:
    names = "\n".join(f"  {i}: {n}" for i, n in NAMES.items())
    val = "val.txt" if has_val else "train.txt"  # 실사 묶음이 하나뿐일 때만 임시로
    text = (
        f"# 자동 생성 — 직접 고치지 마세요 (python -m vision build)\n"
        f"path: {dataset_dir.resolve().as_posix()}\n"
        f"train: train.txt\nval: {val}\n"
        + (f"test: test.txt\n" if has_test else "")
        + f"names:\n{names}\n"
    )
    (dataset_dir / "data.yaml").write_text(text, encoding="utf-8")


def status(ws: Workspace, rows=None) -> None:
    from collections import Counter

    rows = rows if rows is not None else ws.load()
    by_status = Counter(r.status for r in rows.values())
    print(f"\n── 현황 ({ws.root})")
    print(f"  inbox 대기   {sum(1 for p in ws.inbox.rglob('*') if p.is_file())}장")
    print(f"  검수 대기     {by_status.get(REVIEW, 0)}장"
          f"  (검수 완료 표시 {len(list((ws.review / 'done').glob('*.*')))}장 → build 필요)")
    print(f"  데이터셋      {by_status.get(DONE, 0)}장  (제외 {by_status.get(SKIPPED, 0)}장)")

    split_count = Counter((r.split, r.source) for r in rows.values() if r.status == DONE)
    for sp in ("train", "val", "test"):
        real, synth = split_count.get((sp, "real"), 0), split_count.get((sp, "synth"), 0)
        public = split_count.get((sp, "public"), 0)
        groups = len({r.group for r in rows.values() if r.status == DONE and r.split == sp})
        print(f"    {sp:<5} 실사 {real:>4}장  합성 {synth:>4}장  공개 {public:>4}장  묶음 {groups}개")

    box_count = Counter()
    for r in rows.values():
        if r.status != DONE:
            continue
        p = ws.dataset / "labels" / f"{r.id}.txt"
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    box_count[int(line.split()[0])] += 1
    from .classes import LABELS_KO
    print("  클래스별 박스  " + "  ".join(f"{LABELS_KO[i]} {box_count.get(i, 0)}" for i in NAMES))
    cur = ws.current_version()
    print(f"  현재 모델     {cur or '없음'}")
