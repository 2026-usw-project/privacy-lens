"""문서 검출(YOLO) 단계. 실제 모델 없이 가짜 검출기와 가짜 OCR 로 흐름만 확인한다."""

import io

import pytest
from PIL import Image

from pipeline import analyze as pl
from pipeline import detect, redact
from pipeline.detect import Detection
from pipeline.types import Box, Certainty, Finding, Report, Severity, TextSpan

W, H = 2000, 1500


class FakeDetector:
    name = "yolo:test"
    device = "cpu"

    def __init__(self, dets):
        self.dets = dets

    def detect(self, image):
        return list(self.dets)


class TwoStageBackend:
    """사진 전체를 읽을 때와 잘라낸 조각을 읽을 때 다른 결과를 낸다.

    crop_spans 는 '원본 좌표'로 적어 두고, 조각 좌표로 바꿔서 돌려준다.
    그래야 detect 가 원본 좌표로 되돌리는 계산을 검사할 수 있다.
    """

    name = "two-stage"

    def __init__(self, full, crop_spans=(), det_box=None):
        self.full = full
        self.crop_spans = list(crop_spans)
        self.det_box = det_box
        self.calls = 0

    def read(self, image):
        self.calls += 1
        if image.size == (W, H):
            return list(self.full)
        crop = detect._crop_box(self.det_box, W, H)
        scale = image.width / crop.w
        out = []
        for s in self.crop_spans:
            b = s.box
            out.append(TextSpan(s.text, Box(int((b.x - crop.x) * scale), int((b.y - crop.y) * scale),
                                            int(b.w * scale), int(b.h * scale)), s.ocr_confidence))
        return out


def span(text, x, y, w=120, h=10, conf=0.95):
    return TextSpan(text, Box(x, y, w, h), conf)


CARD = Box(300, 300, 200, 130)   # 사진에 작게 찍힌 학생증
IMG = Image.new("RGB", (W, H), "white")


def test_without_detector_nothing_changes():
    backend = TwoStageBackend([span("연락처 010-2345-6789", 100, 100, 300, 30)])
    with_none = pl.analyze(IMG, backend=backend, detector=None)
    assert with_none.detector == ""
    assert with_none.as_dict()["detector_device"] == ""
    assert [f.kind for f in with_none.findings] == ["mobile"]
    assert backend.calls == 1


def test_small_card_is_reread_and_mapped_back_to_original_coordinates():
    # 전체 사진에서는 학생증 글자를 하나도 못 읽었다. 잘라 확대하면 읽힌다
    phone = span("연락처 010-2345-6789", 320, 360, 160, 9)
    backend = TwoStageBackend([], [phone], CARD)
    rep = pl.analyze(IMG, backend=backend, detector=FakeDetector([Detection("id_card", CARD, 0.9)]))

    assert backend.calls == 2
    assert rep.detector == "yolo:test"
    assert rep.as_dict()["detector_device"] == "cpu"
    (mobile,) = [f for f in rep.findings if f.kind == "mobile"]
    assert mobile.severity is Severity.COVER
    # 원본 좌표로 되돌아왔는지 (반올림 오차 2px 이내)
    assert abs(mobile.box.x - 320) <= 2 and abs(mobile.box.y - 360) <= 2
    assert abs(mobile.box.w - 160) <= 2
    assert mobile.detail.get("document_hint") == "id_card"
    assert not [f for f in rep.findings if f.kind == "document"]   # 읽었으니 영역 경고 없음


def test_unreadable_card_gets_region_warning_without_content():
    backend = TwoStageBackend([], [], CARD)
    rep = pl.analyze(IMG, backend=backend, detector=FakeDetector([Detection("id_card", CARD, 0.8)]))
    (doc,) = [f for f in rep.findings if f.kind == "document"]
    assert doc.certainty is Certainty.REGION_ONLY
    assert doc.severity is Severity.COVER          # 학생증은 못 읽어도 가림 권장
    assert doc.evidence_text is None               # 내용은 지어내지 않는다
    assert doc.box == CARD
    assert "학생증 또는 카드로 추정되는 영역" in doc.message
    assert rep.notes == []                         # '탐지된 항목 없음'이 붙지 않는다


def test_unreadable_waybill_is_review_not_cover():
    backend = TwoStageBackend([], [], CARD)
    rep = pl.analyze(IMG, backend=backend, detector=FakeDetector([Detection("waybill", CARD, 0.8)]))
    (doc,) = [f for f in rep.findings if f.kind == "document"]
    assert doc.severity is Severity.REVIEW
    assert "택배 송장으로" in doc.message


def test_screen_read_without_pii_is_not_flagged():
    text = span("오늘의 회의 자료 목록입니다", 310, 380, 180, 9)
    backend = TwoStageBackend([], [text], CARD)
    rep = pl.analyze(IMG, backend=backend, detector=FakeDetector([Detection("screen", CARD, 0.8)]))
    assert not [f for f in rep.findings if f.kind == "document"]


def test_card_with_only_header_read_still_gets_review():
    # 'STUDENT ID' 같은 머리글만 읽고 이름·번호는 못 읽었다. 사람은 읽는 정보를 놓친 상태
    header = span("한빛대학교 STUDENT ID", 310, 305, 180, 9)
    backend = TwoStageBackend([], [header], CARD)
    rep = pl.analyze(IMG, backend=backend, detector=FakeDetector([Detection("id_card", CARD, 0.8)]))
    (doc,) = [f for f in rep.findings if f.kind == "document"]
    assert doc.severity is Severity.REVIEW and doc.certainty is Certainty.PARTIAL
    assert "개인정보 항목을 확인하지 못했습니다" in doc.message


def test_card_with_pii_found_gets_no_extra_document_warning():
    phone = span("연락처 010-2345-6789", 320, 360, 160, 9)
    backend = TwoStageBackend([], [phone], CARD)
    rep = pl.analyze(IMG, backend=backend, detector=FakeDetector([Detection("id_card", CARD, 0.9)]))
    assert not [f for f in rep.findings if f.kind == "document"]


def test_well_read_large_document_is_not_reread():
    big = Box(100, 100, 1200, 900)
    lines = [span(f"충분히 큰 글자로 읽힌 줄 번호 {i}", 150, 150 + i * 60, 900, 40) for i in range(6)]
    backend = TwoStageBackend(lines, [], big)
    pl.analyze(IMG, backend=backend, detector=FakeDetector([Detection("waybill", big, 0.9)]))
    assert backend.calls == 1                      # 시간을 아끼려고 다시 읽지 않음


def test_worse_reread_keeps_original_reading():
    good = span("연락처 010-2345-6789", 320, 360, 160, 9, conf=0.9)
    worse = span("연락처 010-2", 320, 360, 160, 9, conf=0.5)
    backend = TwoStageBackend([good], [worse], CARD)
    rep = pl.analyze(IMG, backend=backend, detector=FakeDetector([Detection("id_card", CARD, 0.9)]))
    assert [f.evidence_text for f in rep.findings if f.kind == "mobile"] == ["010-2345-6789"]


def test_face_photo_and_undecoded_barcode_regions():
    face = Box(310, 310, 40, 50)
    code = Box(600, 600, 80, 30)
    qr_box = Box(900, 900, 50, 50)
    decoded = Finding(kind="qr", box=qr_box, certainty=Certainty.READ,
                      severity=Severity.REVIEW, message="m")
    dets = [Detection("face_photo", face, 0.7), Detection("barcode", code, 0.6),
            Detection("barcode", Box(905, 905, 45, 45), 0.6)]
    out = detect.region_findings(dets, [], [decoded])
    assert sorted(f.kind for f in out) == ["barcode", "face_photo"]   # 해독된 QR 은 중복으로 안 냄
    assert all(f.certainty is Certainty.REGION_ONLY and f.evidence_text is None for f in out)


def test_reread_is_capped_per_photo():
    cards = [Box(100 + i * 300, 100, 200, 130) for i in range(6)]
    backend = TwoStageBackend([], [], cards[0])
    backend.read = lambda image, _orig=backend.read: (setattr(backend, "calls", backend.calls + 1) or [])
    detect.reread_documents(IMG, [], [Detection("id_card", b, 0.9) for b in cards], backend)
    assert backend.calls == detect.MAX_REREAD


# ------------------------------------------------------------ 저장 전 재검사

def _png():
    buf = io.BytesIO()
    Image.new("RGB", (100, 100)).save(buf, "PNG")
    return buf.getvalue()


def test_masked_card_shape_is_not_counted_as_leak():
    # 학생증을 통째로 가려도 학생증 '모양'은 다시 검출된다. 내용 누출이 아니다
    card = Box(10, 10, 60, 40)
    shape = Finding(kind="document", box=card, certainty=Certainty.REGION_ONLY,
                    severity=Severity.COVER, message="m")
    v = redact.verify([card], _png(), lambda _i: Report(100, 100, [shape]), had_gps=False)
    assert v["passed"] and v["leaked_count"] == 0 and v["remaining_count"] == 0


def test_unmasked_card_shape_is_reported_as_remaining():
    shape = Finding(kind="document", box=Box(60, 60, 30, 30), certainty=Certainty.REGION_ONLY,
                    severity=Severity.COVER, message="m")
    v = redact.verify([Box(0, 0, 20, 20)], _png(), lambda _i: Report(100, 100, [shape]), had_gps=False)
    assert v["passed"] and v["remaining_count"] == 1


# ------------------------------------------------------------ 설정

@pytest.fixture
def fresh_detector_state(monkeypatch):
    monkeypatch.setattr(detect, "_loaded", detect._UNSET)
    yield
    detect._loaded = detect._UNSET


def test_no_weights_means_no_detector(fresh_detector_state, monkeypatch, tmp_path):
    monkeypatch.delenv("PL_YOLO_WEIGHTS", raising=False)
    monkeypatch.setattr(detect, "DEFAULT_WEIGHTS", tmp_path / "models" / "best.pt")
    assert detect.get_detector() is None


@pytest.mark.parametrize("versions,expected", [
    ([], "best.pt"),
    (["v001", "v004", "v003"], "v004/best.pt"),
    (["v9", "v10", "v002", "vbackup", "other"], "v10/best.pt"),
])
def test_default_weights_selects_numeric_version(monkeypatch, tmp_path, versions, expected):
    monkeypatch.setattr(detect, "DEFAULT_WEIGHTS", tmp_path / "best.pt")
    (tmp_path / "best.pt").touch()
    for version in versions:
        folder = tmp_path / version
        folder.mkdir()
        (folder / "best.pt").touch()
    (tmp_path / "v999").touch()  # 버전 이름이어도 파일이면 무시한다
    assert detect._default_weights() == tmp_path / expected


def test_auto_weights_loads_once_and_can_be_overridden(fresh_detector_state, monkeypatch, tmp_path):
    monkeypatch.delenv("PL_YOLO_WEIGHTS", raising=False)
    monkeypatch.delenv("PL_YOLO", raising=False)
    monkeypatch.setattr(detect, "DEFAULT_WEIGHTS", tmp_path / "best.pt")
    latest = tmp_path / "v004" / "best.pt"
    latest.parent.mkdir()
    latest.touch()
    loaded = []
    monkeypatch.setattr(detect, "YoloDetector", lambda path: loaded.append(path) or object())
    first = detect.get_detector()
    assert detect.get_detector() is first
    assert loaded == [latest]
    explicit = tmp_path / "custom.pt"
    explicit.touch()
    monkeypatch.setenv("PL_YOLO_WEIGHTS", str(explicit))
    monkeypatch.setattr(detect, "_loaded", detect._UNSET)
    detect.get_detector()
    assert loaded == [latest, explicit]
    monkeypatch.setenv("PL_YOLO", "off")
    monkeypatch.setattr(detect, "_loaded", detect._UNSET)
    assert detect.get_detector() is None
    assert loaded == [latest, explicit]


def test_missing_latest_weights_does_not_load_older_model(fresh_detector_state, monkeypatch, tmp_path):
    monkeypatch.delenv("PL_YOLO_WEIGHTS", raising=False)
    monkeypatch.delenv("PL_YOLO", raising=False)
    monkeypatch.setattr(detect, "DEFAULT_WEIGHTS", tmp_path / "best.pt")
    (tmp_path / "best.pt").touch()
    (tmp_path / "v004").mkdir()
    assert detect.get_detector() is None


def test_missing_weights_file_disables_detection_instead_of_crashing(
        fresh_detector_state, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("PL_YOLO_WEIGHTS", str(tmp_path / "없음.pt"))
    assert detect.get_detector() is None
    assert "문서 검출을 끕니다" in capsys.readouterr().err


# ------------------------------------------------------------ 일상 사진 9종 모델(D-19)

class _FakeDet:
    def __init__(self, name, dets):
        self.name, self.device, self._dets = name, "cpu", dets

    def detect(self, image):
        return list(self._dets)


def test_multi_detector_keeps_best_of_same_class():
    a = _FakeDet("yolo:v005", [Detection("waybill", Box(0, 0, 100, 100), 0.5)])
    b = _FakeDet("yolo:daily", [Detection("waybill", Box(5, 5, 100, 100), 0.8),
                               Detection("card", Box(300, 300, 50, 30), 0.6)])
    m = detect.MultiDetector([a, b])
    got = m.detect(Image.new("RGB", (10, 10)))
    assert m.name == "yolo:v005+yolo:daily"
    assert [(d.name, d.confidence) for d in got] == [("waybill", 0.8), ("card", 0.6)]


def test_daily_model_loaded_next_to_document_model(fresh_detector_state, monkeypatch, tmp_path):
    monkeypatch.delenv("PL_YOLO_WEIGHTS", raising=False)
    monkeypatch.delenv("PL_YOLO", raising=False)
    monkeypatch.delenv("PL_DAILY_MODEL", raising=False)
    monkeypatch.setattr(detect, "DEFAULT_WEIGHTS", tmp_path / "best.pt")
    (tmp_path / "daily.onnx").touch()
    loaded = []
    monkeypatch.setattr(detect, "YoloDetector",
                        lambda path, imgsz=None: loaded.append((path.name, imgsz)) or _FakeDet(path.name, []))
    assert detect.get_detector().name == "daily.onnx"       # 문서 모델이 없으면 일상 모델만
    assert loaded == [("daily.onnx", 640)]
    (tmp_path / "best.pt").touch()
    monkeypatch.setattr(detect, "_loaded", detect._UNSET)
    assert isinstance(detect.get_detector(), detect.MultiDetector)
    monkeypatch.setenv("PL_DAILY_MODEL", "off")
    monkeypatch.setattr(detect, "_loaded", detect._UNSET)
    assert detect.get_detector().name == "best.pt"


def test_unread_daily_objects_become_regions():
    dets = [Detection("card", Box(0, 0, 200, 120), 0.7),
            Detection("health_item", Box(300, 0, 80, 160), 0.6),
            Detection("ticket", Box(0, 300, 200, 80), 0.6)]
    out = detect.region_findings(dets, [], [])
    sev = {f.detail["detector_class"]: f.severity for f in out}
    assert sev == {"card": Severity.COVER, "health_item": Severity.REVIEW, "ticket": Severity.REVIEW}
    assert "결제 카드" in out[0].message and "약 또는 건강 관련 물건" in out[1].message


def test_tiled_detector_adds_small_objects_and_drops_cut_ones():
    """전체 보기는 큰 송장만, 조각에서는 구석의 작은 카드와 잘린 송장 조각이 보이는 상황."""
    class Inner:
        name, device, imgsz = "yolo:daily", "cpu", 640

        def detect(self, image):
            w, h = image.size
            if (w, h) == (4000, 3000):   # 전체 보기
                return [Detection("waybill", Box(1500, 1000, 1200, 900), 0.8)]
            # 조각: 모든 조각에 자른 선에 닿는 송장 조각, 오른쪽 아래 조각에만 작은 카드
            x0 = image._box[0]
            out = [Detection("waybill", Box(0 if x0 > 0 else w - 300, 100, 300, 300), 0.9)]
            if getattr(image, "_corner", False):
                out.append(Detection("card", Box(500, 500, 60, 40), 0.6))
            return out

    img = Image.new("RGB", (4000, 3000))
    det = detect.TiledDetector(Inner(), grid=2)
    tiles = det.tiles(4000, 3000)
    assert len(tiles) == 4 and tiles[0][:2] == (0, 0) and tiles[-1][2:] == (4000, 3000)
    orig_crop = Image.Image.crop

    def crop(self, box):
        c = orig_crop(self, box)
        c._corner = box == tiles[-1]
        c._box = box
        return c

    import pytest
    mp = pytest.MonkeyPatch()
    mp.setattr(Image.Image, "crop", crop)
    try:
        got = det.detect(img)
    finally:
        mp.undo()
    names = sorted((d.name, d.box.x >= tiles[-1][0]) for d in got)
    # 큰 송장 1개(전체 보기) + 작은 카드 1개(조각, 원래 좌표로 옮김). 자른 선에 닿은 송장 조각은 버림
    assert names == [("card", True), ("waybill", False)]
    card = next(d for d in got if d.name == "card")
    assert (card.box.x, card.box.y) == (tiles[-1][0] + 500, tiles[-1][1] + 500)
    assert "조각2x2" in det.name


def test_tiled_detector_skips_small_photos():
    det = detect.TiledDetector(_FakeDet("d", []), grid=2, min_side=1280)
    assert det.tiles(1000, 750) == []
