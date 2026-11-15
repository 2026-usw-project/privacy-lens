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
        cls, cx, cy, w, h = rows[-1]
        assert int(cls) == cs.CARD_CLASS
        cx, cy, w, h = map(float, (cx, cy, w, h))
        assert 0 < w <= 1 and 0 < h <= 1 and cx - w / 2 >= -1e-6 and cx + w / 2 <= 1 + 1e-6
        assert cy - h / 2 >= -1e-6 and cy + h / 2 <= 1 + 1e-6


def test_card_class_matches_daily_classes():
    from vision import daily_data as dd
    assert dd.CLASSES[cs.CARD_CLASS] == "card"
