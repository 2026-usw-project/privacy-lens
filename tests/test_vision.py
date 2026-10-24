"""vision/ 지속 학습 도구 테스트. YOLO 학습 없이 데이터 흐름만 확인한다."""

from __future__ import annotations

import json

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


# ------------------------------------------------------------ MIDV-2020 가져오기

def _via(entries):
    return {"_via_img_metadata": {f"{e['filename']}0": e for e in entries}}


def _region(name, xs, ys):
    return {"shape_attributes": {"name": "polygon", "all_points_x": xs, "all_points_y": ys},
            "region_attributes": {"field_name": name}}


def test_import_midv_converts_quad_and_face_and_handles_exif_rotation(ws, tmp_path):
    from vision import midv

    src = tmp_path / "photo"
    (src / "images" / "alb_id").mkdir(parents=True)
    (src / "annotations").mkdir()
    # 00: 회전 정보 없음. 400x700
    Image.new("RGB", (400, 700), (90, 90, 90)).save(src / "images" / "alb_id" / "00.jpg")
    # 01: 저장은 가로(700x400)인데 EXIF 6 = 세워서 보는 사진. 주석은 세운 기준(400x700)
    exif = Image.Exif()
    exif[0x0112] = 6
    Image.new("RGB", (700, 400), (90, 90, 90)).save(src / "images" / "alb_id" / "01.jpg", exif=exif)
    quad = _region("doc_quad", [40, 360, 360, 40], [400, 400, 600, 600])
    face = {"shape_attributes": {"name": "rect", "x": 60, "y": 430, "width": 50, "height": 60},
            "region_attributes": {"field_name": "face"}}
    (src / "annotations" / "alb_id.json").write_text(json.dumps(_via([
        {"filename": "00.jpg", "regions": [quad, face]},
        {"filename": "01.jpg", "regions": [quad]},
        {"filename": "없음.jpg", "regions": [quad]},          # 사진 없는 주석은 무시
    ])), encoding="utf-8")

    midv.run(ws, str(src))

    rows = [r for r in ws.load().values() if r.source == "public"]
    assert len(rows) == 2 and all(r.split == "train" and r.status == DONE for r in rows)
    by_name = {r.orig_name: r for r in rows}
    lab0 = (ws.dataset / "labels" / f"{by_name['images/alb_id/00'].id}.txt").read_text().split("\n")
    c, x, y, w, h = lab0[0].split()
    assert c == "1" and abs(float(x) - 0.5) < 1e-3 and abs(float(y) - 500 / 700) < 1e-3
    assert lab0[1].split()[0] == "4" and float(lab0[1].split()[3]) > 50 / 400   # 얼굴 → 넓힌 증명사진
    img1 = Image.open(ws.dataset / "images" / f"{by_name['images/alb_id/01'].id}.jpg")
    assert img1.size == (400, 700)            # EXIF 회전을 반영해서 주석과 맞춤
    assert not img1.info.get("exif")
    assert "train.txt" in [p.name for p in ws.dataset.iterdir()]

    midv.run(ws, str(src))                    # 다시 돌려도 중복으로 안 들어감
    assert len([r for r in ws.load().values() if r.source == "public"]) == 2


# ------------------------------------------------------------ 검수 강화

def _reviewed(ws, group, label_text):
    """inbox → review 로 한 장 넣고, 라벨과 완료 표시를 적는다. 사진 id 를 돌려준다."""
    (ws.inbox / group).mkdir(parents=True, exist_ok=True)
    n = len(ws.load())  # 사진마다 크기를 달리해 중복(같은 내용)으로 걸러지지 않게
    Image.new("RGB", (400 + n, 300), (120, 90, 90)).save(ws.inbox / group / "a.jpg")
    ingest.run(ws, prelabel=False)
    fid = next(r.id for r in ws.load().values() if r.group == group)
    (ws.review / "labels" / f"{fid}.txt").write_text(label_text, encoding="utf-8")
    (ws.review / "done" / f"{fid}.ok").write_text("", encoding="utf-8")
    return fid


def test_build_blocks_obvious_box_mistakes_and_warns_on_odd_ones(ws, capsys):
    good = _reviewed(ws, "찬영_학생증A_1013", "1 0.5 0.5 0.5 0.5\n4 0.40 0.5 0.1 0.2\n")
    tiny = _reviewed(ws, "다인_명찰A_1013", "2 0.5 0.5 0.005 0.5\n")
    dup = _reviewed(ws, "다인_송장A_1013", "0 0.5 0.5 0.4 0.4\n0 0.501 0.5 0.4 0.4\n")
    lone_face = _reviewed(ws, "찬영_화면A_1013", "4 0.2 0.2 0.1 0.1\n")

    build.run(ws)

    rows = ws.load()
    assert rows[good].status == DONE
    assert rows[tiny].status == REVIEW and rows[dup].status == REVIEW   # 실수로 보이는 박스는 막는다
    assert rows[lone_face].status == DONE                              # 일부러일 수 있으니 경고만
    assert "증명사진이 학생증·카드 박스 밖" in capsys.readouterr().out


def test_sheet_draws_one_page_per_group(ws):
    from vision import sheet
    _reviewed(ws, "찬영_학생증A_1013", "1 0.5 0.5 0.5 0.5\n")
    _reviewed(ws, "다인_명찰A_1013", "2 0.5 0.5 0.3 0.3\n")

    written = sheet.run(ws)

    assert sorted(p.name for p in written) == ["review_다인_명찰A_1013_1.jpg", "review_찬영_학생증A_1013_1.jpg"]
    assert Image.open(written[0]).size[0] == sheet.COLS * sheet.THUMB


def test_add_extra_appends_to_temporary_train_list_only(tmp_path):
    from vision import train
    data = tmp_path / "copy"
    for sub in ("images", "labels"):
        (data / sub).mkdir(parents=True)
    (data / "train.txt").write_text("./images/a.jpg\n", encoding="utf-8")
    extra = tmp_path / "aihub"
    (extra / "images").mkdir(parents=True)
    (extra / "labels").mkdir()
    for i in range(3):
        Image.new("RGB", (40, 30)).save(extra / "images" / f"s{i}.jpg")
    (extra / "labels" / "s1.txt").write_text("5 0.5 0.5 0.2 0.2\n", encoding="utf-8")

    assert train.add_extra(data, extra) == 3

    listed = (data / "train.txt").read_text(encoding="utf-8").split()
    assert listed == ["./images/a.jpg", "./images/extra_s0.jpg", "./images/extra_s1.jpg", "./images/extra_s2.jpg"]
    assert (data / "labels" / "extra_s0.txt").read_text() == ""            # 라벨 없음 = 배경
    assert (data / "labels" / "extra_s1.txt").read_text().startswith("5 ")
    assert train.add_extra(tmp_path / "copy", extra, limit=1) == 1


def test_synth_covers_every_class_and_small_documents():
    synth = pytest.importorskip("vision.synth", exc_type=Exception)  # 한글 폰트·OpenCV 가 없으면 건너뜀
    from vision.classes import NAMES
    seen, small = set(), 0
    for s in range(40):
        img, lines = synth.make_scene(s)
        W, H = img.size
        for ln in lines:
            c, cx, cy, w, h = ln.split()
            assert all(0 <= float(v) <= 1 for v in (cx, cy, w, h))
            seen.add(NAMES[int(c)])
            small += max(float(w) * W, float(h) * H) / min(W, H) < 0.2
    assert seen == set(NAMES.values())          # 송장·학생증·명찰·화면·증명사진·바코드 모두
    assert small > 0                            # 작게 찍힌 문서도 나온다


def test_occluded_part_gets_visible_box_only():
    synth = pytest.importorskip("vision.synth", exc_type=Exception)
    import numpy as np
    M = np.eye(3, dtype=np.float32)                   # 원근 없음: 그림 좌표 = 사진 좌표
    occ = np.zeros((100, 200), bool)
    occ[:, :50] = True                                # 왼쪽 50px 가림
    b = synth._visible_box(M, [20, 20, 120, 60], occ, 200, 100)
    assert b is not None and abs(b[2] * 200 - 70) <= 1   # 100px 중 보이는 70px 만
    assert synth._visible_box(M, [10, 20, 60, 60], occ, 200, 100) is None   # 80% 가려짐 → 박스 안 침
