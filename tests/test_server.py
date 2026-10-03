"""서버 입력 검증과 흐름. OCR 은 ScriptedBackend 로 바꿔 끼운다."""

import io
import json

import pytest
from PIL import Image

pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
from pipeline import ocr  # noqa: E402
from pipeline.types import Box, TextSpan  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    spans = [TextSpan("받는분 010-1234-5678", Box(10, 10, 200, 20), 0.95)]
    monkeypatch.setattr(server, "_backend", ocr.ScriptedBackend(spans))
    return TestClient(server.app)


def png(size=(300, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, "PNG")
    return buf.getvalue()


def rotated_jpeg_with_gps() -> bytes:
    exif = Image.Exif()
    exif[0x0112] = 6  # 화면에는 90도 돌려 보여야 하는 사진
    exif[0x8825] = {1: "N", 2: (37.0, 30.0, 0.0), 3: "E", 4: (127.0, 0.0, 0.0)}
    buf = io.BytesIO()
    Image.new("RGB", (300, 200), "white").save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def test_analyze(client):
    r = client.post("/analyze", files={"image": ("a.png", png())})
    assert r.status_code == 200
    kinds = [f["kind"] for f in r.json()["report"]["findings"]]
    assert "mobile" in kinds


def test_non_image_is_400(client):
    r = client.post("/analyze", files={"image": ("a.txt", b"not an image")})
    assert r.status_code == 400


def test_empty_is_400(client):
    r = client.post("/analyze", files={"image": ("a.png", b"")})
    assert r.status_code == 400


def test_too_large_is_413(client, monkeypatch):
    monkeypatch.setattr(server, "MAX_BYTES", 100)
    r = client.post("/analyze", files={"image": ("a.png", png())})
    assert r.status_code == 413


def test_exif_rotation_applied(client):
    r = client.post("/analyze", files={"image": ("a.jpg", rotated_jpeg_with_gps())})
    rep = r.json()["report"]
    assert (rep["width"], rep["height"]) == (200, 300)
    assert any(f["kind"] == "gps" for f in rep["findings"])


def test_redact_bad_boxes_is_400(client):
    for bad in ("not json", json.dumps({"x": 1}), json.dumps([{"x": 1}])):
        r = client.post("/redact", files={"image": ("a.png", png())}, data={"boxes": bad})
        assert r.status_code == 400, bad


def test_redact_gps_only_and_rotation(client):
    # 아무 영역도 고르지 않아도 저장된다. 위치정보는 지워지고 방향은 바로 선다.
    r = client.post("/redact", files={"image": ("a.jpg", rotated_jpeg_with_gps())},
                    data={"boxes": "[]"})
    assert r.status_code == 200
    body = r.json()
    import base64
    out = Image.open(io.BytesIO(base64.b64decode(body["file"])))
    assert out.size == (200, 300)
    assert not out.getexif()
    v = body["verification"]
    assert v["had_gps"] and v["gps_removed"]


def test_queue_endpoints(client):
    r = client.get("/queue")
    assert r.status_code == 200
    body = r.json()
    assert body["running"] == 0 and body["waiting"] == 0
    assert body["engine_ready"] is True
    assert client.get("/queue", params={"ticket": "abcdef1234"}).json()["state"] == "unknown"
    assert client.post("/queue/cancel", params={"ticket": "abcdef1234"}).json() == {"cancelled": False}


def test_analyze_accepts_ticket(client):
    r = client.post("/analyze", files={"image": ("a.png", png())}, data={"ticket": "t-12345678"})
    assert r.status_code == 200
    r = client.post("/analyze", files={"image": ("a.png", png())}, data={"ticket": "bad ticket!"})
    assert r.status_code == 400


def test_full_queue_is_503(client, monkeypatch):
    from jobqueue import WorkQueue
    monkeypatch.setattr(server, "QUEUE", WorkQueue(max_waiting=0))
    r = client.post("/analyze", files={"image": ("a.png", png())})
    assert r.status_code == 503
    assert r.headers.get("retry-after") == "10"


def test_large_upload_stays_in_memory():
    # 1MB 넘는 업로드도 디스크 임시파일로 넘어가지 않아야 한다
    from starlette.formparsers import MultiPartParser
    assert MultiPartParser.spool_max_size > server.MAX_BYTES


def test_preview_matches_saved_masking(client):
    import base64
    boxes = json.dumps([{"x": 10, "y": 10, "w": 100, "h": 40}])
    for style in ("blur", "solid"):
        r = client.post("/redact/preview", files={"image": ("a.png", png())},
                        data={"boxes": boxes, "style": style})
        assert r.status_code == 200 and r.json()["style"] == style
        shown = Image.open(io.BytesIO(base64.b64decode(r.json()["preview"])))
        assert shown.size == (300, 200)
        px = shown.convert("RGB").getpixel((60, 30))
        if style == "solid":
            assert max(px) < 60  # 검게 덮였다
        else:
            assert min(px) > 200  # 흰 바탕 주변색으로 흐리게 덮였다


def test_bad_style_is_400(client):
    for url in ("/redact/preview", "/redact"):
        r = client.post(url, files={"image": ("a.png", png())}, data={"style": "pixelate"})
        assert r.status_code == 400, url


def test_redact_clamps_boxes_outside_image(client):
    boxes = [{"x": -50, "y": -50, "w": 100, "h": 100}, {"x": 5000, "y": 0, "w": 10, "h": 10}]
    r = client.post("/redact", files={"image": ("a.png", png())},
                    data={"boxes": json.dumps(boxes)})
    assert r.status_code == 200
    assert r.json()["verification"]["selected_count"] == 1


def test_redact_accepts_outline(client):
    quad = [[20, 30], [200, 80], [195, 100], [15, 50]]
    ok = json.dumps([{"x": 15, "y": 30, "w": 185, "h": 70, "poly": quad}])
    r = client.post("/redact/preview", files={"image": ("a.png", png())},
                    data={"boxes": ok, "style": "solid"})
    assert r.status_code == 200
    import base64
    shown = Image.open(io.BytesIO(base64.b64decode(r.json()["preview"]))).convert("RGB")
    assert max(shown.getpixel((108, 65))) < 60          # 줄 가운데는 덮였다
    assert min(shown.getpixel((190, 34))) > 200         # 사각형 모서리(줄 밖)는 그대로

    for bad in ([[1, 2]], [[1, 2], [3, "x"], [5, 6]], [[0, 0], [1e9, 0], [0, 1]]):
        r = client.post("/redact/preview", files={"image": ("a.png", png())},
                        data={"boxes": json.dumps([{"x": 0, "y": 0, "w": 10, "h": 10, "poly": bad}])})
        assert r.status_code == 400, bad
