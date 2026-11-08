"""엔진 서버(PL_SERVE_FRONT=0, PL_CORS_ORIGINS), 정적 배포 빌드, run.py(게이트웨이 + 엔진)."""

import importlib
import socket
import subprocess
import sys

import pytest

pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

import run  # noqa: E402

FRONT = run.ROOT / "web" / "frontend-demo"
FONTS = FRONT / "dist" / "fonts"


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


# ------------------------------------------------------------------ 정적 배포(build.mjs --api)

def _node():
    import shutil
    node = shutil.which("node")
    if node is None:
        pytest.skip("node 가 없습니다")
    return node


def _build(*args):
    import subprocess
    return subprocess.run([_node(), "scripts/build.mjs", *args], cwd=FRONT, capture_output=True,
                          text=True, encoding="utf-8", timeout=120)


def test_static_site_carries_api_and_fonts(tmp_path):
    out = tmp_path / "site"
    r = _build("--api", "https://gw.example.org/pl/", "--out", str(out))
    assert r.returncode == 0, r.stderr
    page = (out / "index.html").read_text(encoding="utf-8")
    assert page.index('globalThis.PRIVACY_LENS_API="https://gw.example.org/pl"') < page.index("PrivacyLensAPI")
    assert "url(dist/fonts/" in page and (out / ".nojekyll").exists()
    fonts = {p.name for p in FONTS.glob("*.woff2")}
    assert fonts and fonts <= {p.name for p in (out / "dist" / "fonts").iterdir()}


@pytest.mark.parametrize("args", [("--api", "javascript:alert(1)"), ("--api",), ("--out", "x")])
def test_static_build_refuses_bad_options(tmp_path, args):
    r = _build(*args)
    assert r.returncode == 2 and "[오류]" in r.stderr


# ------------------------------------------------------------------ run.py(게이트웨이 + 엔진)

def test_port_free_detects_used_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        assert run.port_free(s.getsockname()[1]) is False


def test_port_free_reuses_addr_like_uvicorn_except_windows(monkeypatch):
    """Linux 에서 방금 끈 서버의 TIME_WAIT 때문에 '쓰는 중'으로 잘못 알리던 문제(2026-11-08 minipc)."""
    calls = []

    class FakeSocket:
        def __init__(self, *a):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def setsockopt(self, *a):
            calls.append(a)

        def bind(self, addr):
            pass

    monkeypatch.setattr(run.socket, "socket", FakeSocket)
    for name, expect in (("posix", True), ("nt", False)):
        calls.clear()
        monkeypatch.setattr(run.os, "name", name)
        assert run.port_free(8000) is True
        assert (calls == [(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)]) is expect


def test_free_port_moves_up_past_busy_ports():
    with socket.socket() as a, socket.socket() as b:
        a.bind(("127.0.0.1", 0))
        a.listen()
        start = a.getsockname()[1]
        try:
            b.bind(("127.0.0.1", start + 1))
            b.listen()
        except OSError:
            pytest.skip("바로 다음 포트를 잡지 못했습니다")
        got = run.free_port(start)
        assert got is not None and got >= start + 2                 # 두 칸 다 쓰는 중이면 그 다음
        assert run.free_port(start, avoid={got}) not in (start, start + 1, got)


def test_pick_port_tells_when_it_moves(monkeypatch, capsys):
    monkeypatch.setattr(run, "port_free", lambda p, host="127.0.0.1": p >= 8002)
    assert run.pick_port(8000, "127.0.0.1", "화면·API") == 8002
    assert "8000 번 포트를 쓰는 중이라 8002 번으로 엽니다" in capsys.readouterr().out
    assert run.pick_port(8002, "127.0.0.1", "화면·API") == 8002
    assert capsys.readouterr().out == ""                              # 그대로면 조용히
    monkeypatch.setattr(run, "port_free", lambda p, host="127.0.0.1": False)
    with pytest.raises(SystemExit):
        run.pick_port(8000, "127.0.0.1", "화면·API")


def test_engine_port_skips_gateway_port(monkeypatch):
    monkeypatch.setattr(run, "port_free", lambda p, host="127.0.0.1": True)
    assert run.free_port(8001, avoid={8001}) == 8002


def test_windows_checks_both_local_and_any_address(monkeypatch):
    seen = []
    monkeypatch.setattr(run, "_can_bind", lambda host, port: seen.append(host) or True)
    monkeypatch.setattr(run.os, "name", "nt")
    run.port_free(8000)
    assert sorted(seen) == ["0.0.0.0", "127.0.0.1"]
    seen.clear()
    monkeypatch.setattr(run.os, "name", "posix")
    run.port_free(8000)
    assert seen == ["127.0.0.1"]


def test_wait_engine_gives_up_when_engine_exits():
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    assert run.wait_engine(proc, "http://127.0.0.1:9", "t", timeout=5) is False


def test_engine_runs_locally_with_token(monkeypatch):
    seen = {}

    class FakePopen:
        def __init__(self, cmd, env):
            seen.update(cmd=cmd, env=env)

    monkeypatch.setattr(run.subprocess, "Popen", FakePopen)
    run.start_engine(8123, "secret-x")
    env = seen["env"]
    assert seen["cmd"][-1].endswith("server.py")
    assert env["HOST"] == "127.0.0.1" and env["PORT"] == "8123" and env["PL_SERVE_FRONT"] == "0"
    assert env["PL_GATEWAY_TOKEN"] == "secret-x" and env["PL_CORS_ORIGINS"] == ""
