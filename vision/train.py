"""③ dataset 으로 학습하고 ④ models 에 새 버전을 남긴다.

순서
  1. 지금 모델(current)이 있으면 그 가중치에서 이어서 학습, 없으면 yolo11n.pt 에서 시작
  2. models/vNNN/ 에 best.pt · 학습 기록 · 평가 결과 저장
  3. 새 모델과 지금 모델을 **같은 시험 데이터**(test, 없으면 val)로 다시 채점
  4. 새 모델이 같거나 나으면 current 로 바꾼다. 나빠졌으면 저장만 하고 바꾸지 않는다

데이터가 늘면 시험 문제도 바뀐다. 예전에 기록한 점수끼리 비교하면 안 되고,
매번 같은 시험지로 두 모델을 다시 채점해야 공정하다.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import os
import shutil
import tempfile
from pathlib import Path

from .build import write_lists
from .classes import NAMES
from .workspace import Workspace

DEFAULT_BASE = "yolo11n.pt"


def _in_colab() -> bool:
    return Path("/content").is_dir() and "COLAB_RELEASE_TAG" in os.environ


def _score(weights: Path, data_yaml: Path, split: str, imgsz: int, device) -> dict:
    from ultralytics import YOLO

    m = YOLO(str(weights))
    r = m.val(data=str(data_yaml), split=split, imgsz=imgsz, device=device,
              plots=False, verbose=False, project=tempfile.mkdtemp(), name="val")
    per_class = {}
    for i, ap50 in zip(r.box.ap_class_index.tolist(), r.box.ap50.tolist()):
        per_class[NAMES.get(int(i), str(i))] = round(float(ap50), 4)
    return {
        "split": split,
        "mAP50": round(float(r.box.map50), 4),
        "mAP50_95": round(float(r.box.map), 4),
        "precision": round(float(r.box.mp), 4),
        "recall": round(float(r.box.mr), 4),
        "per_class_AP50": per_class,
    }


def _same_classes(weights: Path) -> bool:
    from ultralytics import YOLO

    names = YOLO(str(weights)).names
    return {int(k): v for k, v in names.items()} == NAMES


def run(
    ws: Workspace,
    *,
    epochs: int = 60,
    imgsz: int = 1280,
    batch: int = -1,
    base: str | None = None,
    device=None,
    who: str = "",
    force_promote: bool = False,
    copy_local: bool | None = None,
) -> None:
    from ultralytics import YOLO

    ws.init()
    write_lists(ws)
    yaml_path = ws.dataset / "data.yaml"
    n_train = sum(1 for line in (ws.dataset / "train.txt").read_text().splitlines() if line.strip())
    n_val = sum(1 for line in (ws.dataset / "val.txt").read_text().splitlines() if line.strip())
    n_test = sum(1 for line in (ws.dataset / "test.txt").read_text().splitlines() if line.strip())
    if n_train == 0:
        raise SystemExit("학습할 사진이 없습니다. 검수 후 `python -m vision build` 를 먼저 하세요.")
    if n_val == 0:
        print("⚠ 검증용 실사 묶음이 없어 학습 데이터로 검증합니다. 점수는 참고만 하세요.")

    # 시작 가중치
    current = ws.current_model()
    if base is None:
        if current and _same_classes(current):
            base = str(current)
        else:
            if current:
                print("⚠ 클래스 목록이 바뀌어 처음(yolo11n.pt)부터 학습합니다.")
            base = DEFAULT_BASE
    print(f"시작 가중치: {base}")
    print(f"사진: 학습 {n_train} · 검증 {n_val} · 시험 {n_test}")

    # Colab 은 드라이브 읽기가 느리다. 로컬 디스크로 복사해서 학습한다
    copy_local = _in_colab() if copy_local is None else copy_local
    data_dir = ws.dataset
    if copy_local:
        tmp = Path(tempfile.mkdtemp(prefix="pl_yolo_")) / "dataset"
        print(f"데이터를 {tmp} 로 복사하는 중…")
        shutil.copytree(ws.dataset, tmp, ignore=shutil.ignore_patterns("*.cache"))
        from .build import write_yaml
        write_yaml(tmp, has_val=n_val > 0, has_test=n_test > 0)
        data_dir = tmp
    data_yaml = data_dir / "data.yaml"

    version = ws.next_version()
    out_dir = ws.models / version
    run_dir = Path(tempfile.mkdtemp(prefix="pl_run_"))

    model = YOLO(base)
    model.train(
        data=str(data_yaml), epochs=epochs, imgsz=imgsz, batch=batch, device=device,
        project=str(run_dir), name="train", exist_ok=True, patience=20,
        # 문서는 위아래가 뒤집혀 찍히기도 한다. 좌우 반전은 글자 모양이 바뀌지만 박스 위치엔 상관없다
        degrees=10, flipud=0.0, fliplr=0.5, mosaic=1.0,
        workers=2, plots=True, verbose=False,
    )
    best = run_dir / "train" / "weights" / "best.pt"

    out_dir.mkdir(parents=True)
    shutil.copy2(best, out_dir / "best.pt")
    for name in ("results.csv", "args.yaml", "results.png", "confusion_matrix.png"):
        p = run_dir / "train" / name
        if p.exists():
            shutil.copy2(p, out_dir / name)

    # 같은 시험지로 두 모델 채점
    split = "test" if n_test else "val"
    new_score = _score(out_dir / "best.pt", data_yaml, split, imgsz, device)
    old_score = None
    if current and _same_classes(current):
        old_score = _score(current, data_yaml, split, imgsz, device)

    better = old_score is None or new_score["mAP50"] >= old_score["mAP50"]
    promoted = better or force_promote
    info = {
        "version": version,
        "trained_at": dt.datetime.now().isoformat(timespec="seconds"),
        "who": who,
        "base": Path(base).name if base != DEFAULT_BASE else DEFAULT_BASE,
        "base_version": ws.current_version() if base == str(current) else "",
        "epochs": epochs, "imgsz": imgsz,
        "images": {"train": n_train, "val": n_val, "test": n_test},
        "score": new_score,
        "previous": {"version": ws.current_version(), "score": old_score} if old_score else None,
        "promoted": promoted,
    }
    (out_dir / "metrics.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")

    if promoted:
        (ws.models / "current.txt").write_text(version + "\n", encoding="utf-8")

    hist = ws.models / "history.csv"
    new_file = not hist.exists()
    with hist.open("a", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["version", "trained_at", "who", "train", "val", "test", "split",
                        "mAP50", "prev_version", "prev_mAP50", "promoted"])
        w.writerow([version, info["trained_at"], who, n_train, n_val, n_test, split,
                    new_score["mAP50"], (info["previous"] or {}).get("version", ""),
                    old_score["mAP50"] if old_score else "", promoted])

    shutil.rmtree(run_dir, ignore_errors=True)
    if copy_local:
        shutil.rmtree(data_dir.parent, ignore_errors=True)

    print(f"\n── {version} 결과 ({split} {n_test if split == 'test' else n_val}장 기준)")
    print(f"  새 모델   mAP50 {new_score['mAP50']:.3f}  " +
          "  ".join(f"{k} {v:.2f}" for k, v in new_score["per_class_AP50"].items()))
    if old_score:
        print(f"  기존 모델 mAP50 {old_score['mAP50']:.3f}  ({info['previous']['version']})")
    print("  → current 로 교체했습니다." if promoted else
          "  → 기존 모델보다 낮아 교체하지 않았습니다. (--force 로 강제 교체 가능)")
    print(f"  저장 위치: {out_dir}")
