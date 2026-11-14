"""게이트웨이(gateway.py): 하나의 대기열, 엔진 분산, 번호표 고정, 재시도, 상태 확인, 엔진 토큰.

엔진은 가짜 FastAPI 앱이고, 호스트 이름(e1, e2…)으로 나눠 보내는 httpx 전송을 쓴다. OCR 은 필요 없다.
"""

import asyncio
import importlib
import json

import pytest

httpx = pytest.importorskip("httpx")
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import JSONResponse, StreamingResponse  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import gateway  # noqa: E402

TOKEN = "test-secret"
PNG = b"\x89PNG fake image bytes"


class FakeEngine:
    """엔진 서버 흉내. /analyze 는 gate 가 열릴 때까지 기다린다."""

    def __init__(self, name: str):
        self.name = name
        self.gate = asyncio.Event()
        self.seen: list[str] = []          # 받은 번호표 순서
        self.tokens: set[str] = set()
        self.healthy = True
        self.reject = False                 # 비밀값이 달라 403 으로 거절하는 엔진
        app = FastAPI()

        @app.middleware("http")
        async def remember_token(request: Request, call_next):
            self.tokens.add(request.headers.get("x-pl-token", ""))
            return await call_next(request)

        @app.get("/health")
        async def health():
            if self.reject:
                return JSONResponse({"detail": "게이트웨이를 거친 요청만 받습니다."}, status_code=403)
            if not self.healthy:
                return JSONResponse({"ok": False}, status_code=503)
            return {"ok": True, "engine_ready": True}

        async def work(request: Request, kind: str):
            form = await request.form()
            ticket = form["ticket"]
            self.seen.append(ticket)
            await self.gate.wait()
            return {"engine": self.name, "kind": kind, "ticket": ticket, "size": len(await form["image"].read())}

        @app.post("/analyze")
        async def analyze(request: Request):
            return await work(request, "analyze")

        @app.post("/redact")
        async def redact(request: Request):
            return await work(request, "redact")

        @app.post("/redact/preview")
        async def preview(request: Request):
            return {"engine": self.name, "bytes": len(await request.body())}

        @app.get("/queue")
        async def queue(ticket: str = ""):
            return {"state": "running", "ahead": 0, "eta_s": 3.0, "progress": {"state": "running", "engine": self.name}}

        @app.post("/queue/cancel")
        async def cancel(ticket: str):
            return {"cancelled": False, "engine": self.name}

        @app.get("/progress")
        async def progress(ticket: str):
            async def gen():
                yield f"event: progress\ndata: {json.dumps({'engine': self.name})}\n\n".encode()
                yield b"event: done\ndata: {}\n\n"
            return StreamingResponse(gen(), media_type="text/event-stream")

        self.app = app


class Router(httpx.AsyncBaseTransport):
    """http://e1:8000 → 엔진 e1. down 에 있는 엔진은 연결 실패."""

    def __init__(self, engines: dict[str, FakeEngine]):
        self.engines = engines
        self.down: set[str] = set()
        self.slow: set[str] = set()
        self.transports = {n: httpx.ASGITransport(app=e.app) for n, e in engines.items()}

    async def handle_async_request(self, request):
        host = request.url.host
        if host in self.down:
            raise httpx.ConnectError("down", request=request)
        if host in self.slow and request.url.path == "/health":
            raise httpx.ReadTimeout("slow", request=request)
        return await self.transports[host].handle_async_request(request)


async def until(cond, timeout=3.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not cond():
        if loop.time() > end:
            raise AssertionError("시간 안에 조건이 맞지 않았습니다")
        await asyncio.sleep(0.01)


def run_with_gateway(names, body, *, max_waiting=24, token=TOKEN, spare=(), admin_key=""):
    """가짜 엔진들 + 게이트웨이를 띄우고 body(client, gw, engines, router)를 실행한다.
    spare: 처음 목록에는 없지만 네트워크에는 있는 엔진(관리 화면에서 더할 것)."""

    async def main():
        engines = {n: FakeEngine(n) for n in (*names, *spare)}
        router = Router(engines)
        app = gateway.create_app([f"http://{n}:8000" for n in names], token=token, serve_front=False,
                                 transport=router, max_waiting=max_waiting, admin_key=admin_key)
        gw = app.state.gateway
        await gw.start()
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gw",
                                         timeout=10) as client:
                await body(client, gw, engines, router)
        finally:
            for e in engines.values():
                e.gate.set()
            await gw.stop()

    asyncio.run(main())


def post(client, ticket, path="/analyze", data=PNG, **fields):
    return client.post(path, data={"ticket": ticket, **fields}, files={"image": ("a.png", data, "image/png")})


T = [f"ticket-{i:04d}" for i in range(10)]


# ------------------------------------------------------------------ 분산·순서

def test_spreads_over_engines_and_queues_in_order():
    async def body(client, gw, engines, router):
        tasks = [asyncio.create_task(post(client, t)) for t in T[:2]]
        await until(lambda: len(engines["e1"].seen) + len(engines["e2"].seen) == 2)
        assert {engines["e1"].seen[0], engines["e2"].seen[0]} == set(T[:2])   # 한 엔진에 한 건씩

        third = asyncio.create_task(post(client, T[2]))
        await until(lambda: len(gw.queue) == 1)
        q = (await client.get("/queue", params={"ticket": T[2]})).json()
        assert q["state"] == "waiting" and q["ahead"] == 2 and q["engines"] == {"total": 2, "alive": 2, "busy": 2}

        engines["e2"].gate.set()                                            # e2 가 먼저 비면 다음 차례는 e2 로
        await until(lambda: T[2] in engines["e2"].seen)
        engines["e1"].gate.set()
        results = [r.json() for r in await asyncio.gather(*tasks, third)]
        assert [r["ticket"] for r in results] == T[:3]
        assert results[2]["engine"] == "e2" and results[0]["size"] == len(PNG)
        assert engines["e1"].tokens == engines["e2"].tokens == {TOKEN}      # 엔진에는 늘 토큰을 붙인다

    run_with_gateway(["e1", "e2"], body)


def test_ticket_is_pinned_to_its_engine():
    async def body(client, gw, engines, router):
        task = asyncio.create_task(post(client, T[0]))
        await until(lambda: engines["e1"].seen or engines["e2"].seen)
        owner = "e1" if engines["e1"].seen else "e2"
        q = (await client.get("/queue", params={"ticket": T[0]})).json()
        assert q["state"] == "running" and q["progress"]["engine"] == owner
        assert (await client.post("/queue/cancel", params={"ticket": T[0]})).json()["engine"] == owner
        r = await client.get("/progress", params={"ticket": T[0]})
        assert f'"engine": "{owner}"' in r.text and "event: done" in r.text
        engines[owner].gate.set()
        assert (await task).json()["engine"] == owner

    run_with_gateway(["e1", "e2"], body)


def test_waiting_progress_then_engine_stream():
    async def body(client, gw, engines, router):
        first = asyncio.create_task(post(client, T[0]))
        await until(lambda: engines["e1"].seen)
        second = asyncio.create_task(post(client, T[1]))
        await until(lambda: len(gw.queue) == 1)
        stream = asyncio.create_task(client.get("/progress", params={"ticket": T[1]}))
        await asyncio.sleep(0.2)
        engines["e1"].gate.set()
        text = (await stream).text
        waiting = text.index('"state": "waiting"')
        assert waiting < text.index('"engine": "e1"') < text.index("event: done")
        await asyncio.gather(first, second)

    run_with_gateway(["e1"], body)


# ------------------------------------------------------------------ 같은 번호표·취소·가득 참

def test_same_request_twice_gets_one_result_but_different_one_is_refused():
    async def body(client, gw, engines, router):
        a = asyncio.create_task(post(client, T[0]))
        await until(lambda: engines["e1"].seen)
        b = asyncio.create_task(post(client, T[0]))                       # 프록시 재시도: 같은 사진·같은 칸
        other = await post(client, T[0], data=b"other image")
        assert other.status_code == 400
        engines["e1"].gate.set()
        ra, rb = await asyncio.gather(a, b)
        assert ra.json() == rb.json() and engines["e1"].seen == [T[0]]     # 엔진은 한 번만 처리

    run_with_gateway(["e1"], body)


def test_cancel_waiting_and_full_queue():
    async def body(client, gw, engines, router):
        running = asyncio.create_task(post(client, T[0]))
        await until(lambda: engines["e1"].seen)
        waiting = asyncio.create_task(post(client, T[1]))
        await until(lambda: len(gw.queue) == 1)
        full = await post(client, T[2])
        assert full.status_code == 503 and full.headers["retry-after"]
        assert (await client.post("/queue/cancel", params={"ticket": T[1]})).json() == {"cancelled": True}
        assert (await waiting).status_code == 409
        engines["e1"].gate.set()
        assert (await running).status_code == 200 and engines["e1"].seen == [T[0]]

    run_with_gateway(["e1"], body, max_waiting=1)


def test_bad_ticket_and_missing_image():
    async def body(client, gw, engines, router):
        assert (await post(client, "bad ticket!")).status_code == 400
        assert (await client.post("/analyze", data={"ticket": T[0]})).status_code == 422
        assert (await client.get("/progress", params={"ticket": "x"})).status_code == 400

    run_with_gateway(["e1"], body)


# ------------------------------------------------------------------ 엔진 장애

def test_connect_failure_moves_job_to_another_engine():
    async def body(client, gw, engines, router):
        router.down.add("e1")                                             # 상태 확인 사이에 e1 이 꺼짐
        for e in engines.values():
            e.gate.set()
        results = [(await post(client, t)).json() for t in T[:3]]
        assert all(r["engine"] == "e2" for r in results)
        assert gw.backends[0].healthy is False

        router.down.clear()                                               # 다시 켜지면 상태 확인이 넣는다
        await gw.check_all()
        assert gw.engines()["alive"] == 2

    run_with_gateway(["e1", "e2"], body)


def test_no_engine_alive():
    async def body(client, gw, engines, router):
        router.down.update({"e1"})
        await gw.check_all()
        health = (await client.get("/health")).json()
        assert health["ok"] is False and health["engines"]["alive"] == 0
        r = await client.post("/redact/preview", content=b"x", headers={"content-type": "application/json"})
        assert r.status_code == 503
        router.down.clear()
        await gw.check_all()
        assert (await client.get("/health")).json()["ok"] is True

    run_with_gateway(["e1"], body)


def test_slow_health_needs_two_misses_but_refused_drops_at_once():
    async def body(client, gw, engines, router):
        b = gw.backends[0]
        router.slow.add("e1")                     # 켠 직후 모델을 불러오느라 늦게 답함
        await gw.check(b)
        assert b.healthy is True                  # 한 번 늦은 것으로는 빼지 않는다
        router.slow.clear()
        await gw.check(b)
        router.slow.add("e1")
        await gw.check(b)
        assert b.healthy is True                  # 사이에 답했으면 다시 처음부터 센다
        await gw.check(b)
        assert b.healthy is False                 # 연속 두 번이면 뺀다
        router.slow.clear()
        await gw.check(b)
        assert b.healthy is True
        router.down.add("e1")
        await gw.check(b)
        assert b.healthy is False                 # 연결 거부(꺼짐)는 바로 뺀다

    run_with_gateway(["e1"], body)


def test_unhealthy_engine_is_skipped():
    async def body(client, gw, engines, router):
        engines["e1"].healthy = False
        await gw.check_all()
        await gw.check_all()                      # 오류 응답은 두 번 연속이어야 뺀다(SLOW_FAILS)
        assert gw.backends[0].healthy is False
        engines["e2"].gate.set()
        assert (await post(client, T[0])).json()["engine"] == "e2"
        assert engines["e1"].seen == []

    run_with_gateway(["e1", "e2"], body)


def test_passthrough_alternates_between_engines():
    async def body(client, gw, engines, router):
        seen = set()
        for _ in range(4):
            r = await client.post("/redact/preview", content=b"abc", headers={"content-type": "application/json"})
            assert r.json()["bytes"] == 3
            seen.add(r.json()["engine"])
        assert seen == {"e1", "e2"}

    run_with_gateway(["e1", "e2"], body)


# ------------------------------------------------------------------ 엔진 서버: 게이트웨이만 받기

@pytest.fixture
def engine_with_token(monkeypatch):
    import server
    monkeypatch.setenv("PL_GATEWAY_TOKEN", TOKEN)
    yield importlib.reload(server)
    monkeypatch.delenv("PL_GATEWAY_TOKEN", raising=False)
    importlib.reload(server)


def test_engine_accepts_only_gateway_token(engine_with_token):
    client = TestClient(engine_with_token.app)
    assert client.get("/health").status_code == 403
    assert client.get("/health", headers={"X-PL-Token": "wrong"}).status_code == 403
    assert client.get("/health", headers={"X-PL-Token": TOKEN}).json()["ok"] is True


def test_launcher_https_options(tmp_path):
    import run_gateway
    assert run_gateway.ssl_files("", "") == {}
    cert, key = tmp_path / "c.pem", tmp_path / "k.pem"
    cert.write_text("x")
    key.write_text("x")
    assert run_gateway.ssl_files(str(cert), str(key)) == {"ssl_certfile": str(cert), "ssl_keyfile": str(key)}
    for bad in ((str(cert), ""), ("", str(key)), (str(cert), str(tmp_path / "none.pem"))):
        with pytest.raises(SystemExit):
            run_gateway.ssl_files(*bad)


def test_launcher_rejects_bad_backend_url():
    import run_gateway
    assert run_gateway._url("http://192.168.0.21:8000/") == "http://192.168.0.21:8000"
    with pytest.raises(SystemExit):
        run_gateway._url("192.168.0.21:8000")


# ------------------------------------------------------------------ 엔진 목록 관리(관리 키)

ADMIN = "admin-key-for-tests"
H = {"X-PL-Admin": ADMIN}


def test_admin_needs_key():
    async def body(client, gw, engines, router):
        assert (await client.get("/admin/engines")).status_code == 403
        assert (await client.get("/admin/engines", headers={"X-PL-Admin": "wrong"})).status_code == 403
        r = await client.post("/admin/engines", json={"url": "http://e2:8000"}, headers={"X-PL-Admin": "wrong"})
        assert r.status_code == 403 and len(gw.backends) == 1
        r = await client.get("/admin/engines", headers=H)
        assert r.json()["engines"] == [{"url": "http://e1:8000", "state": "ready", "busy": False}]
        assert (await client.get("/queue")).json()["manage"] is True

    run_with_gateway(["e1"], body, admin_key=ADMIN)


def test_admin_off_without_key():
    async def body(client, gw, engines, router):
        r = await client.get("/admin/engines", headers={"X-PL-Admin": ""})
        assert r.status_code == 403 and "꺼져" in r.json()["detail"]
        assert (await client.get("/queue")).json()["manage"] is False

    run_with_gateway(["e1"], body)


def test_admin_add_engine_then_it_takes_work():
    async def body(client, gw, engines, router):
        r = await client.post("/admin/engines", json={"url": "http://e2:8000/"}, headers=H)
        assert r.status_code == 200 and r.json()["added"] == {"url": "http://e2:8000", "state": "ready", "busy": False}
        assert r.json()["total"] == 2 and r.json()["alive"] == 2
        assert (await client.post("/admin/engines", json={"url": "http://e2:8000"}, headers=H)).status_code == 409
        for bad in ("e2:8000", "ftp://x", "http://u:p@e2:8000", "http://e2:8000/?a=1"):
            assert (await client.post("/admin/engines", json={"url": bad}, headers=H)).status_code == 400
        # 두 건을 동시에 보내면 새 엔진도 한 건을 맡는다
        tasks = [asyncio.create_task(post(client, t)) for t in T[:2]]
        await until(lambda: engines["e1"].seen and engines["e2"].seen)
        engines["e1"].gate.set()
        engines["e2"].gate.set()
        assert {r.json()["engine"] for r in await asyncio.gather(*tasks)} == {"e1", "e2"}

    run_with_gateway(["e1"], body, spare=["e2"], admin_key=ADMIN)


def test_gateway_starts_empty_and_accepts_first_engine():
    async def body(client, gw, engines, router):
        status = (await client.get("/queue")).json()
        assert status["engines"] == {"total": 0, "alive": 0, "busy": 0}
        assert status["manage"] is True
        for path in ("/analyze", "/redact", "/redact/preview"):
            response = await post(client, T[0], path=path)
            assert response.status_code == 503
            assert "분석 엔진을 추가한 뒤" in response.json()["detail"]
        assert not gw.jobs

        response = await client.post("/admin/engines", json={"url": "http://e1:8000"}, headers=H)
        assert response.status_code == 200 and response.json()["alive"] == 1
        engines["e1"].gate.set()
        response = await post(client, T[0])
        assert response.status_code == 200 and response.json()["engine"] == "e1"

    run_with_gateway([], body, spare=["e1"], admin_key=ADMIN)


def test_admin_add_shows_down_and_rejected_engines():
    async def body(client, gw, engines, router):
        router.down.add("e2")
        r = await client.post("/admin/engines", json={"url": "http://e2:8000"}, headers=H)
        assert r.json()["added"]["state"] == "down"           # 목록에는 두고, 켜지면 상태 확인이 넣는다
        router.down.clear()
        await gw.check_all()
        assert gw.backends[1].healthy is True
        engines["e3"].reject = True
        r = await client.post("/admin/engines", json={"url": "http://e3:8000"}, headers=H)
        assert r.json()["added"]["state"] == "rejected"       # 비밀값이 다른 엔진

    run_with_gateway(["e1"], body, spare=["e2", "e3"], admin_key=ADMIN)


def test_admin_remove_engine_disconnects_but_finishes_running_job():
    async def body(client, gw, engines, router):
        running = asyncio.create_task(post(client, T[0]))
        await until(lambda: engines["e1"].seen or engines["e2"].seen)
        owner = "e1" if engines["e1"].seen else "e2"
        other = "e2" if owner == "e1" else "e1"
        r = await client.post("/admin/engines/remove", json={"url": f"http://{owner}:8000"}, headers=H)
        assert r.status_code == 200 and [e["url"] for e in r.json()["engines"]] == [f"http://{other}:8000"]
        engines[owner].gate.set()
        assert (await running).json()["engine"] == owner        # 처리 중이던 건은 끝까지 받는다
        engines[other].gate.set()
        assert (await post(client, T[1])).json()["engine"] == other   # 새 요청은 남은 엔진으로
        await gw.check_all()
        assert all(b.url != f"http://{owner}:8000" for b in gw.backends)  # 다시 들어오지 않는다
        r = await client.post("/admin/engines/remove", json={"url": f"http://{owner}:8000"}, headers=H)
        assert r.status_code == 404

    run_with_gateway(["e1", "e2"], body, admin_key=ADMIN)


def _capture(logger):
    import logging
    records = []
    handler = logging.Handler()
    handler.emit = records.append
    logger.addHandler(handler)
    return records, handler


def test_gateway_logs_connect_and_reject():
    records, handler = _capture(gateway.log)

    async def body(client, gw, engines, router):
        engines["e2"].reject = True
        await client.post("/admin/engines", json={"url": "http://e2:8000"}, headers=H)
        await gw.check(gw.backends[1])
        router.down.add("e1")
        await gw.check(gw.backends[0])

    try:
        run_with_gateway(["e1"], body, spare=["e2"], admin_key=ADMIN)
    finally:
        gateway.log.removeHandler(handler)
    text = [r.getMessage() for r in records]
    assert any("e1:8000 에 연결을 요청합니다" in t for t in text)
    assert any("e1:8000 에 연결되었습니다" in t for t in text)
    assert sum("e2:8000 이 연결을 거절했습니다" in t for t in text) == 1   # 거절은 한 번만
    assert any("e1:8000 연결이 끊겼습니다(연결 거부)" in t for t in text)


def test_gateway_tells_engine_its_name():
    async def body(client, gw, engines, router):
        assert engines["e1"].names

    orig = FakeEngine.__init__

    def init(self, name):
        orig(self, name)
        self.names = []

        @self.app.middleware("http")
        async def remember(request, call_next):
            self.names.append(request.headers.get("x-pl-gateway"))
            return await call_next(request)

    FakeEngine.__init__ = init
    try:
        run_with_gateway(["e1"], body)
    finally:
        FakeEngine.__init__ = orig


def test_engine_logs_handshake_once_and_throttles_rejects(engine_with_token):
    server = engine_with_token
    records, handler = _capture(server.log)
    try:
        client = TestClient(server.app)
        gw = {"X-PL-Token": TOKEN, "X-PL-Gateway": "gw-pc;rm -rf"}
        for _ in range(3):
            client.get("/health", headers=gw)
        for _ in range(3):
            client.get("/health", headers={"X-PL-Token": "wrong"})
    finally:
        server.log.removeHandler(handler)
    text = [r.getMessage() for r in records]
    accepted = [t for t in text if "수락했습니다" in t]
    assert len(accepted) == 1 and "gw-pcrm-rf" in accepted[0]    # 이름은 글자·숫자·.-_ 만 남긴다(로그 위조 방지)
    assert sum("비밀값이 맞지 않아 거절했습니다" in t for t in text) == 1


def test_engine_logs_disconnect_after_silence(engine_with_token):
    import time as _time
    server = engine_with_token
    records, handler = _capture(server.log)
    try:
        TestClient(server.app).get("/health", headers={"X-PL-Token": TOKEN, "X-PL-Gateway": "gw-pc"})
        assert server.PEERS.sweep() == []                                    # 방금 왔으면 그대로
        assert server.PEERS.sweep(_time.monotonic() + 31) == ["gw-pc@testclient"]
    finally:
        server.log.removeHandler(handler)
    assert any("gw-pc(testclient) 연결이 끊겼습니다" in r.getMessage() for r in records)
