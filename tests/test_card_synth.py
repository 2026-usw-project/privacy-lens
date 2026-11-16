"""가상 카드 합성(vision/card_synth.py): 라벨 형식, 원래 라벨 보존, 다시 돌려도 늘지 않음."""
import random
from pathlib import Path

from PIL import Image

from vision import card_synth as cs


def test_render_card_is_rgba_with_rounded_corners():
    card = cs.render_card(random.Random(1))
    assert card.mode == "RGBA" and max(card.size) == 856
    assert card.getpixel((0, 0))[3] == 0 and card.getpixel((card.width // 2, card.height // 2))[3] == 255


def test_add_to_dataset_appends_card_box_and_keeps_labels(tmp_path: Path):
    (tmp_path / "images/train").mkdir(parents=True)
    (tmp_path / "labels/train").mkdir(parents=True)
    Image.new("RGB", (800, 600), (120, 130, 140)).save(tmp_path / "images/train/a.jpg")
    (tmp_path / "labels/train/a.txt").write_text("3 0.5 0.5 0.2 0.2\n")
    assert cs.add_to_dataset(tmp_path, n=6, seed=1)["추가"] == 6
    assert cs.add_to_dataset(tmp_path, n=6, seed=1) == {"추가": 0, "이미 있음": 6}
    labels = sorted((tmp_path / "labels/train").glob(cs.PREFIX + "*.txt"))
    assert len(labels) == 6 and len(list((tmp_path / "images/train").glob(cs.PREFIX + "*.jpg"))) == 6
    for lab in labels:
        rows = [ln.split() for ln in lab.read_text().splitlines()]
        assert rows[0] == ["3", "0.5", "0.5", "0.2", "0.2"]              # 배경 사진의 원래 라벨
        assert int(rows[1][0]) == cs.CARD_CLASS
        assert all(int(r[0]) == cs.NUMBER_CLASS for r in rows[2:]) and len(rows) <= 3
        boxes = []
        for _cls, cx, cy, w, h in rows[1:]:
            cx, cy, w, h = map(float, (cx, cy, w, h))
            assert 0 < w <= 1 and 0 < h <= 1 and cx - w / 2 >= -1e-6 and cx + w / 2 <= 1 + 1e-6
            assert cy - h / 2 >= -1e-6 and cy + h / 2 <= 1 + 1e-6
            boxes.append((cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2))
        if len(boxes) == 2:                                               # 번호 줄은 카드 상자 안에 있다
            c, n = boxes
            assert n[0] >= c[0] - 1e-4 and n[1] >= c[1] - 1e-4 and n[2] <= c[2] + 1e-4 and n[3] <= c[3] + 1e-4


def test_card_class_matches_daily_classes():
    from vision import daily_data as dd
    assert dd.CLASSES[cs.CARD_CLASS] == "card"


def test_import_real_maps_classes_and_polygons(tmp_path: Path):
    """Roboflow YOLO zip: 번호 줄 → card_number, 카드 → card, 나머지는 버림. valid 는 val 로. 다각형은 상자로."""
    import io
    import zipfile
    zp = tmp_path / "Card Number Detecter.v4.yolov8.zip"
    buf = io.BytesIO()
    Image.new("RGB", (640, 400), "gray").save(buf, "JPEG")
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("data.yaml", "train: ../train/images\nnc: 3\nnames: ['Card number', 'Cardholder', 'credit-card']\n")
        z.writestr("train/images/a.jpg", buf.getvalue())
        z.writestr("train/labels/a.txt", "0 0.5 0.6 0.6 0.1\n1 0.3 0.8 0.3 0.05\n2 0.1 0.1 0.9 0.1 0.9 0.9 0.1 0.9\n")
        z.writestr("valid/images/b.jpg", buf.getvalue())
        z.writestr("valid/labels/b.txt", "1 0.3 0.8 0.3 0.05\n")          # 쓸 클래스가 없어 넣지 않는다
        z.writestr("test/images/c.jpg", buf.getvalue())
        z.writestr("test/labels/c.txt", "0 0.5 0.6 0.6 0.1\n")
    ds = tmp_path / "ds"
    got = cs.import_real(ds, [zp])[zp.name]
    assert (got["train"], got["val"], got["card"], got["card_number"]) == (1, 1, 1, 2)
    rows = next((ds / "labels/train").glob("realcard_*a.txt")).read_text().split("\n")
    assert rows[0].startswith(f"{cs.NUMBER_CLASS} 0.5") and rows[1] == f"{cs.CARD_CLASS} 0.500000 0.500000 0.800000 0.800000"
    assert cs.import_real(ds, [zp])[zp.name] == "이미 가져옴"
    assert cs.map_card_class("Expiry date") is None and cs.map_card_class("valid-credit-card") == cs.CARD_CLASS


def test_import_real_fields_only_adds_enclosing_card(tmp_path: Path):
    """카드 통째 라벨 없이 칸만 단 데이터(번호·이름·유효기간·로고)는 카드 근접 사진이라 사진 전체를 card 로 덧붙인다."""
    import io
    import zipfile
    zp = tmp_path / "credit card object detection.v1i.yolov8.zip"
    buf = io.BytesIO()
    Image.new("RGB", (640, 400), "gray").save(buf, "JPEG")
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("data.yaml", "nc: 5\nnames: ['Card issuer', 'Card number', 'Cardholder', 'Expiry date', 'Payment network']\n")
        z.writestr("train/images/a.jpg", buf.getvalue())
        z.writestr("train/labels/a.txt", "0 0.2 0.15 0.2 0.1\n1 0.5 0.55 0.6 0.1\n2 0.3 0.8 0.3 0.05\n")
        z.writestr("train/images/b.jpg", buf.getvalue())
        z.writestr("train/labels/b.txt", "1 0.5 0.55 0.6 0.1\n")                # 칸 하나뿐이면 card 를 지어내지 않는다
    ds = tmp_path / "ds"
    got = cs.import_real(ds, [zp])[zp.name]
    assert (got["train"], got["card"], got["card_number"]) == (2, 1, 2)
    rows = next((ds / "labels/train").glob("realcard_*_a.txt")).read_text().split()
    assert rows[0] == str(cs.CARD_CLASS)
    assert rows[1:5] == ["0.500000", "0.500000", "1.000000", "1.000000"]
    only = next((ds / "labels/train").glob("realcard_*_b.txt")).read_text().split("\n")
    assert only[0].startswith(f"{cs.NUMBER_CLASS} ")
