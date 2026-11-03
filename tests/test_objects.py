"""이미지 객체(얼굴·증명사진·번호판) 판단. 실제 모델 대신 상자를 돌려주는 가짜 검출기를 쓴다."""

from PIL import Image

from pipeline import objects, wording
from pipeline.types import Box, Certainty, Finding, Severity, TextSpan


class Fake:
    name = "fake"

    def __init__(self, *boxes, kind="face"):
        self.boxes = [objects.ObjectBox(kind, b, 0.9) for b in boxes]

    def detect(self, image):
        return self.boxes


IMG = Image.new("RGB", (800, 600), "white")
FACE = Box(100, 100, 60, 80)


def kinds(fs):
    return [(f.kind, f.severity) for f in fs]


def test_face_on_card_is_id_photo_cover():
    spans = [TextSpan("누리대학교 학생증", Box(180, 90, 200, 20), 0.95)]
    fs = objects.find_objects(IMG, spans, [], mode="card", face_detector=Fake(FACE), plate_detector=False)
    assert kinds(fs) == [("face_photo", Severity.COVER)]
    assert fs[0].detail["source"] == "object" and fs[0].certainty is Certainty.REGION_ONLY


def test_face_next_to_name_or_rrn_finding_is_id_photo():
    name = Finding(kind="name", box=Box(180, 110, 80, 20), certainty=Certainty.READ,
                   severity=Severity.COVER, message="")
    fs = objects.find_objects(IMG, [], [name], mode="card", face_detector=Fake(FACE), plate_detector=False)
    assert kinds(fs) == [("face_photo", Severity.COVER)]


def test_scene_face_only_in_all_mode():
    far = [TextSpan("학생증", Box(700, 550, 60, 20), 0.95)]  # 얼굴에서 멀다
    assert objects.find_objects(IMG, far, [], mode="card", face_detector=Fake(FACE), plate_detector=False) == []
    fs = objects.find_objects(IMG, far, [], mode="all", face_detector=Fake(FACE), plate_detector=False)
    assert kinds(fs) == [("face", Severity.REVIEW)]
    assert objects.find_objects(IMG, far, [], mode="off", face_detector=Fake(FACE), plate_detector=False) == []


def test_face_inside_yolo_card_box_and_no_duplicate_with_yolo_face_photo():
    class Det:
        name = "id_card"
        box = Box(50, 50, 300, 200)
    fs = objects.find_objects(IMG, [], [], [Det()], mode="card", face_detector=Fake(FACE), plate_detector=False)
    assert kinds(fs) == [("face_photo", Severity.COVER)]
    yolo = Finding(kind="face_photo", box=Box(98, 98, 64, 84), certainty=Certainty.REGION_ONLY,
                   severity=Severity.REVIEW, message="")
    assert objects.find_objects(IMG, [], [yolo], mode="all", face_detector=Fake(FACE), plate_detector=False) == []


def test_plate_region_only_when_ocr_did_not_read_it():
    plate_box = Box(400, 400, 120, 40)
    fs = objects.find_objects(IMG, [], [], mode="off", face_detector=False,
                              plate_detector=Fake(plate_box, kind="plate"))
    assert kinds(fs) == [("plate", Severity.REVIEW)] and fs[0].evidence_text is None
    read = Finding(kind="plate", box=Box(410, 405, 100, 30), certainty=Certainty.READ,
                   severity=Severity.REVIEW, message="", evidence_text="12가3456")
    assert objects.find_objects(IMG, [], [read], mode="off", face_detector=False,
                                plate_detector=Fake(plate_box, kind="plate")) == []


def test_missing_models_are_quietly_off(monkeypatch, tmp_path):
    monkeypatch.setenv("PL_FACE_MODEL", str(tmp_path / "none.onnx"))
    monkeypatch.delenv("PL_PLATE_MODEL", raising=False)
    monkeypatch.setattr(objects, "MODELS", tmp_path)
    assert objects.get_face_detector() is None and objects.get_plate_detector() is None
    assert objects.find_objects(IMG, [], [], mode="all") == []


def test_plate_model_path_default_env_and_off(monkeypatch, tmp_path):
    monkeypatch.setattr(objects, "MODELS", tmp_path)
    monkeypatch.delenv("PL_PLATE_MODEL", raising=False)
    assert objects.plate_model_path() is None
    (tmp_path / objects.PLATE_FILE).write_bytes(b"x")
    assert objects.plate_model_path() == tmp_path / objects.PLATE_FILE
    monkeypatch.setenv("PL_PLATE_MODEL", "off")
    assert objects.plate_model_path() is None
    monkeypatch.setenv("PL_PLATE_MODEL", "/x/other.onnx")
    assert str(objects.plate_model_path()) == "/x/other.onnx"


def test_mode_and_wording():
    assert objects.face_mode("ALL") == "all" and objects.face_mode("weird") == "card"
    wording.face_region(), wording.plate_region()


def test_redact_verify_ignores_object_shapes_inside_selection():
    # 가린 자리에도 얼굴·번호판 '모양'은 남을 수 있다. 내용이 새어 나간 것으로 세지 않는다
    import io
    from pipeline import redact
    from pipeline.types import Report
    buf = io.BytesIO()
    IMG.save(buf, "JPEG")
    sel = [Box(90, 90, 100, 120)]
    shape = dict(certainty=Certainty.REGION_ONLY, severity=Severity.REVIEW, message="",
                 detail={"source": "object"})
    after = [Finding(kind="face", box=Box(100, 100, 60, 80), **shape),
             Finding(kind="plate", box=Box(100, 100, 60, 30), **shape)]
    check = redact.verify(sel, buf.getvalue(), lambda im: Report(800, 600, findings=after), had_gps=False)
    assert check["leaked_count"] == 0
