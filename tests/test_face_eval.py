import json
from pathlib import Path

from PIL import Image

from pipeline.objects import ObjectBox
from pipeline.types import Box
from vision import face_eval


def test_midv_faces_and_evaluate(tmp_path: Path):
    (tmp_path / "images" / "alb_id").mkdir(parents=True)
    (tmp_path / "annotations").mkdir()
    Image.new("RGB", (400, 300)).save(tmp_path / "images" / "alb_id" / "00.jpg")
    via = {"00.jpg": {"filename": "00.jpg", "regions": [
        {"shape_attributes": {"name": "polygon", "all_points_x": [10, 390, 390, 10], "all_points_y": [10, 10, 290, 290]},
         "region_attributes": {"field_name": "doc_quad"}},
        {"shape_attributes": {"name": "rect", "x": 40, "y": 60, "width": 80, "height": 100},
         "region_attributes": {"field_name": "face"}}]}}
    (tmp_path / "annotations" / "alb_id.json").write_text(json.dumps(via))
    items = face_eval.midv_faces(tmp_path)
    assert len(items) == 1 and items[0][1][0] == Box(40, 60, 80, 100)

    class Perfect:  # 정답 자리를 그대로 '찾는' 가짜 검출기(크기·회전을 따라간다)
        def detect(self, im):
            if im.width < im.height:          # 돌린 사진: 시계 90도
                return [ObjectBox("face", Box(im.width - int(160 * im.width / 300), int(40 * im.height / 400),
                                              int(100 * im.width / 300), int(80 * im.height / 400)), 0.9)]
            s = im.width / 400
            return [ObjectBox("face", Box(int(40 * s), int(60 * s), int(80 * s), int(100 * s)), 0.9)]

    for rot in (False, True):
        r = face_eval.evaluate(items, Perfect(), scales=(1.0, 0.5), rotate=rot, thresholds=(0.5,))
        assert all(v["rows"][0]["recall"] == 1.0 for v in r.values()), r
