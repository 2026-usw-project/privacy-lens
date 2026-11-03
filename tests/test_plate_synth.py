from pathlib import Path

from PIL import Image

from vision import plate_synth as ps


def _yolo(root: Path, name: str, size, boxes, color):
    (root / "images" / "train").mkdir(parents=True, exist_ok=True)
    (root / "labels" / "train").mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(root / "images" / "train" / f"{name}.jpg")
    W, H = size
    (root / "labels" / "train" / f"{name}.txt").write_text(
        "".join(f"0 {(x + w / 2) / W} {(y + h / 2) / H} {w / W} {h / H}\n" for x, y, w, h in boxes))


def test_collect_paste_build(tmp_path: Path):
    kr = tmp_path / "kr"
    _yolo(kr, "close", (400, 200), [(50, 50, 260, 60), (10, 10, 20, 20)], (250, 250, 250))  # 두 번째는 너무 작음
    crops = ps.collect_crops([kr])
    assert len(crops) == 1 and crops[0].size == (260, 60)

    scene = tmp_path / "scene"
    _yolo(scene, "car", (640, 480), [(300, 300, 80, 20), (5, 5, 4, 4)], (20, 20, 20))
    out = tmp_path / "out"
    assert ps.build(scene, crops, out, keep=0.0) == 1
    img = Image.open(out / "images" / "train" / "kr_car.jpg")
    assert img.size == (640, 480)
    assert img.getpixel((340, 310))[0] > 60          # 번호판 자리가 바뀜(밝은 조각)
    assert img.getpixel((100, 100))[0] < 40          # 다른 곳은 그대로
    assert (out / "labels" / "train" / "kr_car.txt").read_text().count("\n") == 2  # 라벨 그대로


def test_miss_grid(tmp_path: Path):
    from pipeline.types import Box
    from vision.objects_eval import GT, Pred
    p = tmp_path / "a.jpg"
    Image.new("RGB", (200, 200), (9, 9, 9)).save(p)
    samples = [([GT(Box(10, 10, 40, 10)), GT(Box(100, 100, 40, 10))], [Pred(Box(10, 10, 40, 10), 0.9)])]
    g = ps.miss_grid(samples, [(p, p)], cell=50)
    assert g.size == (400, 50)
