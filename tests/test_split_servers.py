"""화면·API 따로 실행(run_frontend.py, run_backend.py, PL_SERVE_FRONT, PL_CORS_ORIGINS)."""

import importlib
import threading
import urllib.error
import urllib.request

import pytest

pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

import run_frontend  # noqa: E402


# ------------------------------------------------------------------ 백엔드

@pytest.fixture
def reload_server(monkeypatch):
    """환경변수를 바꿔 server 를 새로 불러온다. 끝나면 기본 설정으로 되돌린다."""
    import server

    def load(**env):
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        return importlib.reload(server)

    yield load
    monkeypatch.delenv("PL_SERVE_FRONT", raising=False)
    monkeypatch.delenv("PL_CORS_ORIGINS", raising=False)
    importlib.reload(server)


def test_default_serves_front_without_cors(reload_server):
    server = reload_server()
    client = TestClient(server.app)
    r = client.get("/")
    assert r.status_code == 200 and "<html" in r.text.lower()
    r = client.get("/health", headers={"Origin": "http://127.0.0.1:8080"})
    assert r.json()["ok"] is True and "access-control-allow-origin" not in r.headers


def test_api_only_with_cors(reload_server):
    server = reload_server(PL_SERVE_FRONT="0", PL_CORS_ORIGINS="http://127.0.0.1:8080, http://localhost:8080/")
    client = TestClient(server.app)
    assert client.get("/").json() == {"service": "privacy-lens-api", "front": False}
    assert client.get("/dist/fonts/x.woff2").status_code == 404
    ok = client.get("/health", headers={"Origin": "http://localhost:8080"})
    assert ok.headers["access-control-allow-origin"] == "http://localhost:8080"
    other = client.get("/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in other.headers
    pre = client.options("/analyze", headers={"Origin": "http://127.0.0.1:8080",
                                              "Access-Control-Request-Method": "POST"})
    assert pre.status_code == 200 and pre.headers["access-control-allow-origin"] == "http://127.0.0.1:8080"


# ------------------------------------------------------------------ 화면 서버

def test_api_origin_validation():
    assert run_frontend.api_origin("http://127.0.0.1:8000/") == "http://127.0.0.1:8000"
    assert run_frontend.api_origin(" https://api.example.org/pl/ ") == "https://api.example.org/pl"
    for bad in ("javascript:alert(1)", "127.0.0.1:8000", "file:///etc/passwd", ""):
        with pytest.raises(ValueError):
            run_frontend.api_origin(bad)


def test_api_injected_safely():
    html = run_frontend.page_with_api("<html><head><title>t</title></head>", 'http://a:1/</script><b>')
    assert html.index("PRIVACY_LENS_API") < html.index("<title>")
    assert "</script><b>" not in html.split("PRIVACY_LENS_API", 1)[1].split(";</script>")[0]


@pytest.fixture
def front():
    server = run_frontend.make_server("127.0.0.1", 0, "http://127.0.0.1:8000")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def test_front_serves_page_with_api_and_fonts(front):
    status, headers, body = get(front + "/")
    text = body.decode("utf-8")
    assert status == 200 and headers["Content-Type"].startswith("text/html")
    assert 'globalThis.PRIVACY_LENS_API="http://127.0.0.1:8000"' in text and "PrivacyLensAPI" in text
    font = next(run_frontend.FONTS.glob("*.woff2"))
    status, headers, body = get(front + "/dist/fonts/" + font.name)
    assert status == 200 and headers["Content-Type"] == "font/woff2" and body == font.read_bytes()


@pytest.mark.parametrize("path", ["/server.py", "/dist/fonts/../../../server.py", "/dist/fonts/%2e%2e/%2e%2e/index.html",
                                  "/dist/app.js", "/.env"])
def test_front_serves_nothing_else(front, path):
    assert get(front + path)[0] == 404

