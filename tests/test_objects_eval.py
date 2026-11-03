from pathlib import Path

from pipeline.types import Box
from vision.objects_eval import GT, Pred, match, pick, sweep, yolo_labels, yolo_pairs


def test_ignored_ground_truth_is_not_false_positive():
    gts = [GT(Box(0, 0, 50, 50)), GT(Box(200, 200, 100, 100), ignore=True), GT(Box(400, 0, 10, 10))]
    preds = [Pred(Box(2, 2, 48, 48), 0.9),       # 맞힘
             Pred(Box(220, 220, 30, 30), 0.9),   # 묶음 라벨 안: 무시
             Pred(Box(400, 0, 10, 10), 0.9),     # 작은 얼굴: min_size 로 무시
             Pred(Box(600, 600, 40, 40), 0.9)]   # 진짜 오탐
    assert match(gts, preds, thr=0.5, min_size=20) == (1, 0, 1)


def test_threshold_trades_recall_for_precision():
    gts = [GT(Box(0, 0, 50, 50)), GT(Box(100, 0, 50, 50))]
    preds = [Pred(Box(0, 0, 50, 50), 0.95), Pred(Box(100, 0, 50, 50), 0.6), Pred(Box(300, 0, 50, 50), 0.65)]
    low, high = sweep([(gts, preds)], [0.5, 0.9])
    assert (low["recall"], low["precision"]) == (1.0, 0.6667)
    assert (high["recall"], high["precision"]) == (0.5, 1.0)
    assert pick([low, high], min_precision=0.85)["thr"] == 0.9
    assert pick([low], min_precision=0.85)["thr"] == 0.5  # 기준을 못 넘으면 F1 최대


def test_yolo_labels_and_pairs(tmp_path: Path):
    (tmp_path / "valid" / "images").mkdir(parents=True)
    (tmp_path / "valid" / "labels").mkdir(parents=True)
    (tmp_path / "valid" / "images" / "a.jpg").write_bytes(b"")
    lab = tmp_path / "valid" / "labels" / "a.txt"
    lab.write_text("0 0.5 0.5 0.2 0.1\n1 0.1 0.1 0.3 0.1 0.3 0.2 0.1 0.2\n")
    assert yolo_pairs(tmp_path) == [(tmp_path / "valid" / "images" / "a.jpg", lab)]
    a, b = yolo_labels(lab, 100, 100)
    assert (a.box.x, a.box.y, a.box.w, a.box.h) == (40, 45, 20, 10)
    assert (b.box.x, b.box.y, b.box.w, b.box.h) == (10, 10, 20, 10)


def test_roboflow_originals_keeps_one_per_source():
    from vision.objects_eval import roboflow_originals
    p = [(Path(f"train/images/IMG_1_jpg.rf.{h}.jpg"), Path("x")) for h in ("aa", "bb", "cc")]
    p.append((Path("valid/images/IMG_2_jpg.rf.dd.jpg"), Path("y")))
    assert [i.name for i, _ in roboflow_originals(p)] == ["IMG_1_jpg.rf.aa.jpg", "IMG_2_jpg.rf.dd.jpg"]


def test_recall_by_size():
    from vision.objects_eval import recall_by_size
    gts = [GT(Box(0, 0, 10, 10)), GT(Box(100, 0, 40, 40))]
    preds = [Pred(Box(100, 0, 40, 40), 0.9)]
    r = recall_by_size([(gts, preds)], thr=0.5, bins=(0, 16, 1000))
    assert [(x["total"], x["recall"]) for x in r] == [(1, 0.0), (1, 1.0)]
