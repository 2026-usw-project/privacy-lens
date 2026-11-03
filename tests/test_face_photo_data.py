import json
from pathlib import Path

from PIL import Image, ImageDraw

from pipeline.objects import ObjectBox
from pipeline.types import Box
from vision import face_photo_data as fpd
from vision.objects_eval import yolo_labels


def _midv(root: Path, doc: str, n: int = 2):
    (root / "images" / doc).mkdir(parents=True)
    (root / "annotations").mkdir(exist_ok=True)
    via = {}
    for i in range(n):
        im = Image.new("RGB", (400, 300), (30, 30, 30))
        ImageDraw.Draw(im).rectangle([40, 60, 120, 160], fill=(250, 250, 250))  # 얼굴 자리
        im.save(root / "images" / doc / f"{i:02d}.jpg")
        via[f"{i:02d}.jpg"] = {"filename": f"{i:02d}.jpg", "regions": [
            {"shape_attributes": {"name": "polygon", "all_points_x": [10, 390, 390, 10], "all_points_y": [10, 10, 290, 290]},
             "region_attributes": {"field_name": "doc_quad"}},
            {"shape_attributes": {"name": "rect", "x": 40, "y": 60, "width": 80, "height": 100},
             "region_attributes": {"field_name": "face"}}]}
    (root / "annotations" / f"{doc}.json").write_text(json.dumps(via))


def test_build_splits_by_doc_type_and_labels_follow_pixels(tmp_path: Path):
    src = tmp_path / "midv"
    _midv(src, "alb_id")
    _midv(src, "svk_id")
    out = tmp_path / "ds"
    c = fpd.build(src, out, rotate_frac=1.0, zoom_copies=1)
    assert c["val"] == 4 and c["train"] == 8      # 검증: 원본+줌, 학습: (원본+줌)×(1+회전)
    for img in (out / "images" / "train").glob("*.jpg"):
        im = Image.open(img).convert("L")
        (g,) = yolo_labels(out / "labels" / "train" / (img.stem + ".txt"), *im.size)
        cx, cy = g.box.x + g.box.w // 2, g.box.y + g.box.h // 2
        assert im.getpixel((cx, cy)) > 150, img.name   # 라벨 중심이 흰 얼굴 자리
    assert "face_photo" in (out / "data.yaml").read_text()


def test_rotate90_both_ways():
    im = Image.new("RGB", (300, 200))
    ImageDraw.Draw(im).rectangle([40, 120, 100, 140], fill=(255, 255, 255))
    for cw in (True, False):
        r, b = fpd.rotate90(im, Box(40, 120, 61, 21), cw)
        assert r.getpixel((b.x + b.w // 2, b.y + b.h // 2)) == (255, 255, 255)


def test_evaluate_models_center_hit(tmp_path: Path):
    src = tmp_path / "midv"
    _midv(src, "svk_id", n=1)

    class Bright:  # 흰 영역을 찾는 가짜 검출기
        def detect(self, im):
            import numpy as np
            ys, xs = np.where(np.asarray(im.convert("L")) > 150)
            return [ObjectBox("face", Box(int(xs.min()), int(ys.min()), int(np.ptp(xs)) + 1, int(np.ptp(ys)) + 1), 0.9)]

    r = fpd.evaluate_models(src, {"fake": Bright()}, scales=(1.0, 0.25), thresholds=(0.5,))
    assert all(v[0]["recall"] == 1.0 for v in r.values()), r
