import json
from pathlib import Path

from PIL import Image

from vision import redactions as rd


def _fake(root: Path):
    (root / "annotations").mkdir(parents=True)
    (root / "images" / "train2017").mkdir(parents=True)
    (root / "images" / "val2017").mkdir(parents=True)
    for sp, iid in (("train2017", "2017_1"), ("val2017", "2017_2")):
        Image.new("RGB", (200, 100), "white").save(root / "images" / sp / f"{iid}.jpg")
        anno = {"annotations": {iid: {
            "image_path": f"images/{sp}/{iid}.jpg", "image_height": 100, "image_width": 200,
            "attributes": [
                {"attr_id": "a37_receipt", "instance_id": 0, "polygons": [[10, 10, 60, 10, 60, 50, 10, 50]]},
                {"attr_id": "a105_face_all", "instance_id": 1, "bbox": [100, 20, 30, 30]},
                {"attr_id": "a85_username", "instance_id": 2, "bbox": [0, 0, 10, 10]},   # 무시
            ]}}}
        (root / "annotations" / f"{sp}.json").write_text(json.dumps(anno))


def test_load_and_yolo(tmp_path: Path):
    _fake(tmp_path / "vr")
    recs = rd.load(tmp_path / "vr" / "annotations" / "train2017.json")
    assert [a for a, _ in recs[0]["insts"]] == ["a37_receipt", "a105_face_all"]
    assert recs[0]["insts"][0][1] == (10.0, 10.0, 50.0, 40.0)

    c = rd.to_yolo(tmp_path / "vr", tmp_path / "yolo")
    assert c["train:receipt"] == 1 and c["val:사진"] == 1
    lab = (tmp_path / "yolo" / "labels" / "train" / "2017_1.txt").read_text().split()
    assert lab[0] == str(list(rd.GROUPS).index("receipt"))          # 얼굴은 YOLO 학습 대상 아님
    assert abs(float(lab[1]) - 0.175) < 1e-6 and abs(float(lab[2]) - 0.3) < 1e-6
    assert "names:" in (tmp_path / "yolo" / "data.yaml").read_text()


def test_evaluate_service(tmp_path: Path):
    from pipeline.types import Box
    _fake(tmp_path / "vr")

    class F:
        def __init__(self, kind, box):
            self.kind, self.box = kind, box

    class R:
        findings = [F("face_photo", Box(105, 25, 20, 20))]   # 얼굴만 찾음, 영수증은 놓침

    res = rd.evaluate_service(tmp_path / "vr", split="val2017", limit=None, analyze_fn=lambda im: R())
    rows = {r["attr"]: r for r in res["rows"]}
    assert rows["a105_face_all"]["재현율"] == 1.0 and rows["a37_receipt"]["재현율"] == 0.0
    assert rows["a105_face_all"]["찾은 항목"] == {"face_photo": 1}
    assert "얼굴" in rd.table(res)
