"""같은 번호표로 다시 온 요청(브라우저·프록시 재시도)과 Ultralytics 자동 설치 막기."""

import io
import threading
from pathlib import Path

import pytest
from PIL import Image

pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
from pipeline import objects  # noqa: E402
from pipeline.types import Box, TextSpan  # noqa: E402


def png(color="white") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (300, 200), color).save(buf, "PNG")
    return buf.getvalue()


class Slow:
    """첫 요청이 오래 걸리는 상황(서버를 켠 직후 엔진 준비 등)을 흉내 낸다."""
    name = "slow"
    ready = True

    def __init__(self):
        self.gate = threading.Event()
        self.started = threading.Event()
        self.calls = 0

    def read(self, image):
        self.calls += 1
        self.started.set()
        self.gate.wait(10)
        return [TextSpan("받는분 010-1234-5678", Box(10, 10, 200, 20), 0.95)]


@pytest.fixture(autouse=True)
def no_models(monkeypatch):
    """models/ 에 실제 모델이 있어도 테스트에서는 불러오지 않는다(느리고 컴퓨터마다 다르다)."""
    monkeypatch.setattr(server.pl.detect, "get_detector", lambda: None)
    monkeypatch.setattr(server.pl.objects, "find_objects", lambda *a, **k: [])


@pytest.fixture
def slow(monkeypatch):
    engine = Slow()
    monkeypatch.setattr(server, "_backend", engine)
    monkeypatch.setattr(server, "SAME", server._SameRequest())
    return engine


def post_analyze(client, data: bytes, ticket: str, out: list):
    out.append(client.post("/analyze", files={"image": ("a.png", data)}, data={"ticket": ticket}))


def test_retry_with_same_ticket_gets_first_result(slow):
    client = TestClient(server.app)
    results: list = []
    first = threading.Thread(target=post_analyze, args=(client, png(), "same-0001", results))
    first.start()
    assert slow.started.wait(20)
    retry = threading.Thread(target=post_analyze, args=(client, png(), "same-0001", results))
    retry.start()
    slow.gate.set()
    first.join(10)
    retry.join(10)
    assert [r.status_code for r in results] == [200, 200]
    assert results[0].json() == results[1].json()
    assert slow.calls == 1                     # OCR 은 한 번만 돌았다


def test_late_retry_after_finish_reuses_result(slow):
    slow.gate.set()
    client = TestClient(server.app)
    a = client.post("/analyze", files={"image": ("a.png", png())}, data={"ticket": "late-0001"})
    b = client.post("/analyze", files={"image": ("a.png", png())}, data={"ticket": "late-0001"})
    assert a.status_code == b.status_code == 200 and a.json() == b.json()
    assert slow.calls == 1


def test_other_photo_with_same_ticket_is_refused(slow):
    client = TestClient(server.app)
    results: list = []
    first = threading.Thread(target=post_analyze, args=(client, png(), "other-0001", results))
    first.start()
    assert slow.started.wait(20)
    r = client.post("/analyze", files={"image": ("a.png", png("black"))}, data={"ticket": "other-0001"})
    slow.gate.set()
    first.join(10)
    assert r.status_code == 400 and r.json()["detail"] == "이미 대기열에 있는 번호표입니다."
    assert "report" not in r.text            # 번호표만 알아서는 남의 결과를 받을 수 없다


def test_first_failure_is_repeated_to_retry(monkeypatch):
    monkeypatch.setattr(server, "SAME", server._SameRequest())
    client = TestClient(server.app)
    bad = b"not an image"
    a = client.post("/analyze", files={"image": ("a.png", bad)}, data={"ticket": "fail-0001"})
    b = client.post("/analyze", files={"image": ("a.png", bad)}, data={"ticket": "fail-0001"})
    assert a.status_code == b.status_code == 400 and a.json() == b.json()


def test_old_results_dropped(slow, monkeypatch):
    slow.gate.set()
    monkeypatch.setattr(server._SameRequest, "KEEP_S", -1.0)  # 윈도 시계는 두 요청이 같은 눈금일 수 있다
    client = TestClient(server.app)
    client.post("/analyze", files={"image": ("a.png", png())}, data={"ticket": "old-00001"})
    client.post("/analyze", files={"image": ("a.png", png())}, data={"ticket": "old-00001"})
    assert slow.calls == 2                     # 보관 시간이 지나면 다시 처리한다(결과를 오래 들고 있지 않는다)


def test_redact_retry_reuses_result(monkeypatch):
    from pipeline import ocr
    monkeypatch.setattr(server, "_backend", ocr.ScriptedBackend([]))
    monkeypatch.setattr(server, "SAME", server._SameRequest())
    client = TestClient(server.app)
    a = client.post("/redact", files={"image": ("a.png", png())}, data={"ticket": "red-00001", "boxes": "[]"})
    b = client.post("/redact", files={"image": ("a.png", png())}, data={"ticket": "red-00001", "boxes": "[]"})
    c = client.post("/redact", files={"image": ("a.png", png())},
                    data={"ticket": "red-00001", "boxes": '[{"x":1,"y":1,"w":5,"h":5}]'})
    assert a.status_code == b.status_code == 200 and a.json() == b.json()
    assert c.status_code == 400                # 같은 번호표라도 가릴 영역이 다르면 다른 요청


# ------------------------------------------------------------------ Ultralytics 자동 설치

def test_plate_detector_needs_onnxruntime(monkeypatch, tmp_path):
    real = objects.importlib.util.find_spec
    monkeypatch.setattr(objects.importlib.util, "find_spec",
                        lambda name, *a: None if name == "onnxruntime" else real(name, *a))
    model = tmp_path / "plate.onnx"
    model.write_bytes(b"x")
    with pytest.raises(RuntimeError, match="onnxruntime"):
        objects.PlateDetector(model)
    monkeypatch.setenv("PL_PLATE_MODEL", str(model))
    assert any("onnxruntime 없음" in line for line in objects.status())


def test_autoinstall_off_by_default(monkeypatch):
    monkeypatch.delenv("YOLO_AUTOINSTALL", raising=False)
    # YOLO 는 pipeline/ultra.py 의 yolo_class() 로만 불러온다(자동 설치 끔 + Image.open 원래대로)
    ultra = Path(objects.__file__).with_name("ultra.py").read_text(encoding="utf-8")
    assert 'os.environ.setdefault("YOLO_AUTOINSTALL", "false")' in ultra
    for mod in (objects, server.detect):
        src = Path(mod.__file__).read_text(encoding="utf-8")
        assert "yolo_class()" in src and "from ultralytics import YOLO" not in src
