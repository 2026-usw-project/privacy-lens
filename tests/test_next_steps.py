import zipfile
from pathlib import Path

from vision import next_steps as ns


def test_next_version_and_unpack(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(ns, "OUT", tmp_path / "objects")
    monkeypatch.setattr(ns, "KR", tmp_path / "kr")
    (tmp_path / "objects" / "plate_v003").mkdir(parents=True)
    assert ns._next_version("plate").name == "plate_v004"
    assert ns._next_version("face_photo").name == "face_photo_v001"

    (tmp_path / "objects" / "kr").mkdir()
    z = tmp_path / "objects" / "kr" / "Korea Car License Plate.v2i.yolov8.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("train/labels/a.txt", "3 0.5 0.5 0.1 0.1\n")
        f.writestr("train/images/a.jpg", b"")
    out = ns.unpack_kr()
    assert out["kr_eval"] is not None and out["kr_train1"] is None
    assert (out["kr_eval"] / "train" / "labels" / "a.txt").read_text().startswith("0 ")
