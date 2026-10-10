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

from .classes import NAMES
from .workspace import DONE, REVIEW, SKIPPED, Workspace


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
            problems = _check_label(label)
            if problems:
                print(f"  ! {fid}: 라벨 오류 {problems} → 검수 폴더에 남겨 둡니다")
                broken += 1
                marker.unlink()
                continue
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
        groups = len({r.group for r in rows.values() if r.status == DONE and r.split == sp})
        print(f"    {sp:<5} 실사 {real:>4}장  합성 {synth:>4}장  묶음 {groups}개")

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
