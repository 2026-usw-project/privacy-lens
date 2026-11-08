import json
from pathlib import Path

from PIL import Image

from vision import daily_data as dd


def test_map_name():
    assert dd.map_name("credit_or_debit_card") == "card"
    assert dd.map_name("business_card") == "name_tag"
    assert dd.map_name("letters_with_address") == "waybill"
    assert dd.map_name("Text:Computer Screen") == "screen"
    assert dd.map_name("license_plate_all") is None      # 번호판은 따로(plate.onnx)
    assert dd.map_name("email") is None                  # 글자 항목 → 우편물로 묶지 않음
    assert dd.map_name("face_all") is None and dd.map_name("taxi") is None


def test_coco_vizwiz_writer(tmp_path: Path):
    imgs = tmp_path / "imgs"
    imgs.mkdir()
    for n in ("a.jpg", "b.jpg", "c.jpg"):
        Image.new("RGB", (2000, 1000), "white").save(imgs / n)
    coco = {"categories": [{"id": 1, "name": "credit_or_debit_card"}, {"id": 2, "name": "card_number"}],
            "images": [{"id": 1, "file_name": "a.jpg", "width": 2000, "height": 1000},
                       {"id": 2, "file_name": "b.jpg", "width": 2000, "height": 1000}],
            "annotations": [{"image_id": 1, "category_id": 1, "bbox": [100, 100, 400, 200]},
                            {"image_id": 1, "category_id": 2, "bbox": [150, 150, 100, 20]}]}
    (tmp_path / "c.json").write_text(json.dumps(coco))
    vwp = tmp_path / "vwp"
    vwp.mkdir()
    (vwp / "train.json").write_text(json.dumps([{"image": "c.jpg", "private": 1, "private_regions": [
        {"class": "Text:Letter", "polygon": [[10, 10], [110, 10], [110, 60], [10, 60]]},
        {"class": "Object:Face", "polygon": [[0, 0], [5, 5]]}]}]))

    w = dd.Writer(tmp_path / "out", max_side=1000)
    dd.add_coco(w, tmp_path / "c.json", imgs, "hit", split="train", keep_empty=0.0,
                only_names={"credit_or_debit_card"})
    dd.add_vizwiz_priv(w, vwp, imgs, keep_empty=0.0)
    res = w.finish()
    assert res["counts"]["train:card"] == 1 and res["counts"]["train:waybill"] == 1
    assert res["counts"]["train:사진"] == 2                        # 상자 없는 b.jpg 는 빠짐
    assert any("card_number" in k for k in res["안 씀"])           # 부분 범주는 안 씀
    out = tmp_path / "out"
    assert Image.open(out / "images" / "train" / "hit_a_1.jpg").size == (1000, 500)   # 긴 변 1000 으로 줄임
    cls, cx, cy, bw, bh = (out / "labels" / "train" / "hit_a_1.txt").read_text().split()
    assert int(cls) == dd.CLASSES.index("card") and abs(float(cx) - 0.15) < 1e-6 and abs(float(bh) - 0.2) < 1e-6
    assert "health_item" in (out / "data.yaml").read_text()


def test_vizwiz_priv_extension_mismatch(tmp_path: Path):
    """라벨은 .jpg 인데 채운 사진은 .png 로 들어 있어도 찾는다(11-04 빌드에서 7,447장이 모두 빠졌던 문제)."""
    imgs = tmp_path / "Filling_Image"
    imgs.mkdir()
    Image.new("RGB", (400, 300), "white").save(imgs / "VizWiz_train_00000001.png")
    vwp = tmp_path / "vwp"
    vwp.mkdir()
    (vwp / "train.json").write_text(json.dumps([
        {"image": "VizWiz_train_00000001.jpg", "private": 1, "private_regions": [
            {"class": "Text:Miscellaneous Papers", "polygon": [[10, 10], [110, 10], [110, 60]]}]},
        {"image": "VizWiz_train_00000002.jpg", "private": 1, "private_regions": [
            {"class": "Text:Miscellaneous Papers", "polygon": [[10, 10], [110, 10], [110, 60]]}]}]))
    w = dd.Writer(tmp_path / "out", max_side=1000)
    dd.add_vizwiz_priv(w, vwp, imgs, keep_empty=0.0)
    res = w.finish()
    assert res["counts"]["train:document"] == 1                    # Miscellaneous Papers → 개인 서류
    assert res["안 씀"]["vizwiz_priv:사진 없음"] == 1
    assert any("VizWiz_train_00000002.jpg" in k for k in res["안 씀"])   # 없는 이름 예시를 남김
    assert any("사진 폴더 파일 1개" in k for k in res["안 씀"])
