"""vision/ 지속 학습 도구 테스트. YOLO 학습 없이 데이터 흐름만 확인한다."""

from __future__ import annotations

import pytest
from PIL import Image

from vision import build, ingest
from vision.workspace import DONE, REVIEW, SKIPPED, Row, Workspace


def _row(i, group, split="", source="real", status=DONE):
    return Row(id=f"id{i}", group=group, source=source, split=split, status=status,
               added_at="", orig_name="", prelabel="")


def test_split_fills_train_first_then_val_and_test():
    rows = {}
    got = []
    for i in range(6):
        sp = build._assign(f"g{i}", "real", rows)
        rows[str(i)] = _row(i, f"g{i}", sp)
        got.append(sp)
    assert got[:5] == ["train", "train", "val", "train", "test"]


def test_same_group_keeps_split_and_synth_is_train_only():
    rows = {"a": _row(0, "g0", "val")}
    assert build._assign("g0", "real", rows) == "val"
    assert build._assign("synth_0", "synth", rows) == "train"


def test_label_check_catches_bad_lines(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("0 0.5 0.5 0.2 0.2\n9 0.5 0.5 0.1 0.1\n1 1.5 0.5 0.1 0.1\n2 0.5\n", encoding="utf-8")
    problems = build._check_label(p)
    assert len(problems) == 3


@pytest.fixture
def ws(tmp_path):
    w = Workspace(tmp_path / "ws")
    w.init()
    return w


def _photo(path, with_gps=True):
    piexif = pytest.importorskip("piexif")
    path.parent.mkdir(parents=True, exist_ok=True)
    gps = {piexif.GPSIFD.GPSLatitudeRef: b"N", piexif.GPSIFD.GPSLatitude: ((37, 1), (0, 1), (0, 1))}
    exif = piexif.dump({"0th": {piexif.ImageIFD.Orientation: 6}, "GPS": gps if with_gps else {}})
    Image.new("RGB", (400, 200), (120, 130, 140)).save(path, "JPEG", exif=exif)


def test_ingest_strips_exif_rotates_dedupes_and_clears_inbox(ws):
    _photo(ws.inbox / "찬영_학생증_1007" / "a.jpg")
    (ws.inbox / "다인_송장_1007").mkdir(parents=True)
    (ws.inbox / "다인_송장_1007" / "same.jpg").write_bytes((ws.inbox / "찬영_학생증_1007" / "a.jpg").read_bytes())

    ingest.run(ws, prelabel=False)

    rows = ws.load()
    assert len(rows) == 1                                   # 같은 내용은 한 장
    (row,) = rows.values()
    assert row.group in ("찬영_학생증_1007", "다인_송장_1007") and row.status == REVIEW
    img = Image.open(ws.review / "images" / f"{row.id}.jpg")
    assert img.size == (200, 400)                           # 방향 6 → 90° 회전 반영
    assert not img.info.get("exif")                         # 위치정보 포함 EXIF 삭제
    assert (ws.review / "labels" / f"{row.id}.txt").read_text() == ""
    assert not any(ws.inbox.iterdir())                      # 원본·빈 폴더 정리


def test_build_moves_only_reviewed_and_writes_lists(ws):
    for i, g in enumerate(["g0", "g1", "g2"]):
        _photo(ws.inbox / g / f"{i}.jpg", with_gps=False)
        Image.new("RGB", (40 + i, 40), (i, i, i)).save(ws.inbox / g / f"x{i}.jpg")
    ingest.run(ws, prelabel=False)
    rows = ws.load()
    ids = sorted(rows)
    (ws.review / "labels" / f"{ids[0]}.txt").write_text("1 0.5 0.5 0.4 0.4\n", encoding="utf-8")
    (ws.review / "done" / f"{ids[0]}.ok").write_text("")
    (ws.review / "done" / f"{ids[1]}.skip").write_text("")
    (ws.review / "labels" / f"{ids[2]}.txt").write_text("7 0.5 0.5 0.4 0.4\n", encoding="utf-8")
    (ws.review / "done" / f"{ids[2]}.ok").write_text("")      # 없는 클래스 → 남겨 둠

    build.run(ws)

    rows = ws.load()
    assert rows[ids[0]].status == DONE and (ws.dataset / "images" / f"{ids[0]}.jpg").exists()
    assert rows[ids[1]].status == SKIPPED and not (ws.review / "images" / f"{ids[1]}.jpg").exists()
    assert rows[ids[2]].status == REVIEW and (ws.review / "images" / f"{ids[2]}.jpg").exists()
    assert all(rows[i].status == REVIEW for i in ids[3:])    # 검수 안 한 초벌은 학습에 안 감
    listed = (ws.dataset / f"{rows[ids[0]].split}.txt").read_text()
    assert f"./images/{ids[0]}.jpg" in listed
    assert "names:" in (ws.dataset / "data.yaml").read_text()


def test_lock_blocks_second_run(ws):
    with ws.lock("찬영"):
        with pytest.raises(SystemExit):
            with ws.lock("다인"):
                pass
    with ws.lock("다인"):                                   # 풀린 뒤에는 된다
        pass
