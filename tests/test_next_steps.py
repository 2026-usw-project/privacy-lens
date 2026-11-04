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


def test_resumable_train(tmp_path: Path, monkeypatch):
    """끊긴 학습은 last.pt 에서 resume, 끝난 학습(DONE)은 다시 돌리지 않는다."""
    import sys
    import types
    calls = []

    class FakeYOLO:
        def __init__(self, w):
            self.w = w

        def train(self, **kw):
            calls.append((Path(self.w).name, kw.get("resume", False)))
            if not kw.get("resume"):
                d = Path(kw["project"]) / kw["name"] / "weights"
                d.mkdir(parents=True, exist_ok=True)
                (d / "last.pt").write_text("w")

    monkeypatch.setitem(sys.modules, "ultralytics", types.SimpleNamespace(YOLO=FakeYOLO))
    monkeypatch.setattr(ns, "OUT", tmp_path / "objects")
    last = ns.resumable_train("yolo26n.pt", data="d.yaml", name="face_photo", epochs=2)
    assert calls == [("yolo26n.pt", False)] and last.exists()
    assert ns.resumable_train("yolo26n.pt", data="d.yaml", name="face_photo", epochs=2) == last
    assert len(calls) == 1                                # DONE → 건너뜀

    (tmp_path / "objects" / "runs" / "face_photo" / "DONE").unlink()   # 끊긴 상황
    ns.resumable_train("yolo26n.pt", data="d.yaml", name="face_photo", epochs=2)
    assert calls[-1] == ("last.pt", True)
