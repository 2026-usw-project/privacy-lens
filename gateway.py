"""게이트웨이 — 화면을 내주고, 분석 요청을 줄 세워 여러 엔진 서버에 나눠 보낸다.

    사용자 ──▶ 게이트웨이(화면 + 대기열 + 분산 + 상태 확인) ──▶ 엔진 서버 1..N (run_backend.py, 1서버 1엔진)

- **대기열은 게이트웨이에 하나다.** 들어온 순서대로 줄을 세우고, 비어 있는 엔진이 생길 때만 하나씩 보낸다.
  엔진마다 따로 줄을 서면 늦게 온 요청이 먼저 끝날 수 있다. 엔진 서버의 대기열에는 늘 많아야 한 건이다.
- **번호표마다 엔진을 고정한다.** /analyze 를 엔진 2 에 보냈으면 그 번호표의 /queue·/progress·/queue/cancel 도
  엔진 2 로 보낸다. 아직 배정 전이면 게이트웨이가 '대기 N건 · 약 N초'를 직접 답한다.
- **줄을 서지 않는 요청**(/redact/preview, /llm/models)은 살아 있는 엔진에 번갈아 보낸다.
- **상태 확인**: 엔진마다 /health 를 주기적으로 묻고, 안 되는 엔진은 빼고 살아나면 다시 넣는다.
  보내다가 연결이 안 되면(처리 전) 그 엔진을 빼고 같은 요청을 줄 맨 앞에 다시 세운다.
- **엔진은 게이트웨이만 받는다.** 공유 비밀값(PL_GATEWAY_TOKEN)을 X-PL-Token 헤더로 보낸다(run_backend.py --token).
- **무상태 원칙은 그대로다.** 기다리는 사진은 메모리에만 있고, 디스크·로그에 남기지 않는다. 결과도 돌려주면 버린다
  (같은 번호표 재시도를 위해 끝난 뒤 30초만 메모리에 둔다).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

FRONT = Path(__file__).resolve().parent / "web" / "frontend-demo"
TICKET = re.compile(r"^[A-Za-z0-9-]{8,64}$")
MAX_BYTES = 25 * 1024 * 1024
TOKEN_HEADER = "X-PL-Token"
HEALTH_EVERY_S = 5.0
HEALTH_TIMEOUT_S = 5.0
SLOW_FAILS = 2           # 느리거나 오류인 상태 확인이 이만큼 연속이면 뺀다(연결 거부는 바로)
JOB_TIMEOUT_S = 15 * 60.0
KEEP_DONE_S = 30.0
MAX_ATTEMPTS = 3          # 연결 실패로 다른 엔진에 다시 보내는 최대 횟수
QUEUED_KINDS = {"/analyze": "analyze", "/redact": "redact"}

log = logging.getLogger("privacy_lens.gateway")
if not log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s [gateway] %(levelname)s %(message)s"))
    log.addHandler(_h)
    log.setLevel(logging.INFO)
    log.propagate = False


@dataclass
class Backend:
    url: str
    healthy: bool = False
    engine_ready: bool = False
    busy: bool = False              # 게이트웨이가 보낸 줄 선 요청을 처리하는 중
    fails: int = 0
    checked: float = 0.0


@dataclass
class Job:
    ticket: str
    path: str                       # /analyze 또는 /redact
    fingerprint: str
    files: dict                     # {"image": (이름, 바이트, 형식)}
    fields: dict                    # 폼 칸(문자열)
    future: asyncio.Future = field(default=None)  # type: ignore[assignment]
    backend: Optional[Backend] = None
    attempts: int = 0
    queued_at: float = field(default_factory=time.monotonic)
    started_at: Optional[float] = None
    done_at: Optional[float] = None


class Gateway:
    def __init__(self, backends: list[str], *, token: str = "", max_waiting: int = 24,
                 transport: httpx.AsyncBaseTransport | None = None):
        if not backends:
            raise ValueError("엔진 서버 주소가 하나도 없습니다(--backend).")
        self.backends = [Backend(u.rstrip("/")) for u in backends]
        self.token = token
        self.max_waiting = max_waiting
        self.transport = transport
        self.queue: deque[Job] = deque()
        self.jobs: dict[str, Job] = {}       # 번호표 → 줄 선 요청(대기·처리·끝난 뒤 KEEP_DONE_S)
        self.wake = asyncio.Event()
        self.avg_s: Optional[float] = None   # 엔진에서 한 건 처리에 걸린 시간 이동평균(대기 시간 추정용)
        self._rr = 0
        self.client: httpx.AsyncClient | None = None
        self._tasks: list[asyncio.Task] = []

    # ------------------------------------------------------------ 시작·끝

    async def start(self) -> None:
        self.client = httpx.AsyncClient(transport=self.transport, timeout=httpx.Timeout(JOB_TIMEOUT_S, connect=5.0),
                                        headers={TOKEN_HEADER: self.token} if self.token else {})
        await self.check_all()
        self._tasks = [asyncio.create_task(self._health_loop()), asyncio.create_task(self._dispatch_loop())]

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        if self.client is not None:
            await self.client.aclose()

    # ------------------------------------------------------------ 상태 확인

    async def check(self, b: Backend) -> None:
        """연결이 거부되면(꺼짐) 바로 빼고, 느리거나 오류면 SLOW_FAILS 번 연속일 때 뺀다.
        엔진은 켠 직후 OCR 모델을 불러오느라 몇 초씩 늦게 답한다(그동안 빼 두면 화면에 '연결 안 됨'이 깜빡인다)."""
        refused = False
        try:
            r = await self.client.get(b.url + "/health", timeout=HEALTH_TIMEOUT_S)
            ok = r.status_code == 200
            data = r.json() if ok else {}
        except (httpx.ConnectError, httpx.ConnectTimeout):
            ok, data, refused = False, {}, True
        except (httpx.HTTPError, ValueError):
            ok, data = False, {}
        b.checked = time.monotonic()
        if ok:
            if not b.healthy:
                log.info("엔진 %s 사용 가능", b.url)
            b.healthy, b.engine_ready, b.fails = True, bool(data.get("engine_ready")), 0
            self.wake.set()
            return
        b.fails += 1
        if b.healthy and (refused or b.fails >= SLOW_FAILS):
            log.warning("엔진 %s 응답 없음 — 빼 둔다", b.url)
            b.healthy = False

    async def check_all(self) -> None:
        await asyncio.gather(*(self.check(b) for b in self.backends))

    async def _health_loop(self) -> None:
        while True:
            await asyncio.sleep(HEALTH_EVERY_S)
            await self.check_all()

    def free_backend(self) -> Optional[Backend]:
        free = [b for b in self.backends if b.healthy and not b.busy]
        # 엔진이 준비된 곳 먼저(서버를 켠 직후 엔진을 만드는 중인 곳은 뒤로)
        free.sort(key=lambda b: not b.engine_ready)
        return free[0] if free else None

    def any_backend(self) -> Optional[Backend]:
        alive = [b for b in self.backends if b.healthy]
        if not alive:
            return None
        self._rr = (self._rr + 1) % len(alive)
        return alive[self._rr]

    # ------------------------------------------------------------ 줄 세우기·보내기

    def _sweep(self) -> None:
        now = time.monotonic()
        for t in [t for t, j in self.jobs.items() if j.done_at and now - j.done_at > KEEP_DONE_S]:
            del self.jobs[t]

    def enqueue(self, job: Job) -> Job:
        """같은 번호표의 같은 요청이 이미 있으면 그것을 돌려준다(브라우저·프록시 재시도)."""
        self._sweep()
        old = self.jobs.get(job.ticket)
        if old is not None:
            if old.fingerprint != job.fingerprint or old.path != job.path:
                raise GatewayError(400, "이미 대기열에 있는 번호표입니다.")
            return old
        if len(self.queue) >= self.max_waiting:
            raise GatewayError(503, "지금 기다리는 요청이 많습니다. 잠시 후 다시 시도해 주세요.", retry=True)
        job.future = asyncio.get_running_loop().create_future()
        self.jobs[job.ticket] = job
        self.queue.append(job)
        self.wake.set()
        return job

    def cancel(self, ticket: str) -> bool:
        job = self.jobs.get(ticket)
        if job is None or job not in self.queue:
            return False
        self.queue.remove(job)
        del self.jobs[ticket]
        if not job.future.done():
            job.future.set_result((409, {"detail": "취소된 요청입니다."}))
        return True

    async def _dispatch_loop(self) -> None:
        while True:
            await self.wake.wait()
            self.wake.clear()
            while self.queue:
                b = self.free_backend()
                if b is None:
                    break
                job = self.queue.popleft()
                b.busy, job.backend, job.started_at = True, b, time.monotonic()
                job.attempts += 1
                asyncio.create_task(self._run(job, b))

    async def _run(self, job: Job, b: Backend) -> None:
        try:
            files = {k: (n, data, ctype) for k, (n, data, ctype) in job.files.items()}
            r = await self.client.post(b.url + job.path, data=job.fields, files=files)
            try:
                body = r.json()
            except ValueError:
                body = {"detail": f"엔진 서버가 처리하지 못했습니다. (HTTP {r.status_code})"}
            took = time.monotonic() - job.started_at
            if r.status_code < 500:
                self.avg_s = took if self.avg_s is None else 0.7 * self.avg_s + 0.3 * took
            self._finish(job, (r.status_code, body))
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError) as exc:
            # 보내지도 못했거나 처리 중 엔진이 꺼졌다. 처리 전 실패만 다른 엔진에서 다시(같은 사진을 두 번 처리하지 않게)
            b.healthy = False
            b.fails += 1
            log.warning("엔진 %s 연결 실패(%s)", b.url, type(exc).__name__)
            if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)) and job.attempts < MAX_ATTEMPTS:
                job.backend, job.started_at = None, None
                self.queue.appendleft(job)
            else:
                self._finish(job, (503, {"detail": "분석 서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요."}))
        except httpx.TimeoutException:
            self._finish(job, (504, {"detail": "분석 서버가 제때 응답하지 않았습니다. 다시 시도해 주세요."}))
        finally:
            b.busy = False
            self.wake.set()

    def _finish(self, job: Job, result: tuple[int, dict]) -> None:
        job.done_at = time.monotonic()
        if not job.future.done():
            job.future.set_result(result)

    # ------------------------------------------------------------ 상태

    def engines(self) -> dict:
        alive = [b for b in self.backends if b.healthy]
        return {"total": len(self.backends), "alive": len(alive), "busy": sum(b.busy for b in self.backends)}

    def waiting_progress(self, job: Job) -> dict:
        """아직 엔진에 배정되지 않은 번호표. 앞 사람 수와 대략의 대기 시간."""
        ahead_in_line = list(self.queue).index(job)
        busy = sum(b.busy for b in self.backends)
        alive = max(1, self.engines()["alive"])
        eta = None
        if self.avg_s is not None:
            # 내 앞(처리 중 + 줄)과 나를 엔진 수로 나눠 차례가 몇 바퀴 뒤인지
            rounds = (busy + ahead_in_line) // alive + 1
            eta = round(rounds * self.avg_s, 1)
        return {"state": "waiting", "ahead": busy + ahead_in_line, "eta_s": eta, "stages": [], "total_s": None}


class GatewayError(Exception):
    def __init__(self, status: int, detail: str, retry: bool = False):
        super().__init__(detail)
        self.status, self.detail, self.retry = status, detail, retry


# ------------------------------------------------------------------ 앱

def create_app(backends: list[str], *, token: str = "", serve_front: bool = True,
               transport: httpx.AsyncBaseTransport | None = None, max_waiting: int = 24) -> FastAPI:
    gw = Gateway(backends, token=token, transport=transport, max_waiting=max_waiting)

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(_app):
        await gw.start()
        try:
            yield
        finally:
            await gw.stop()

    app = FastAPI(title="Privacy Lens Gateway", lifespan=lifespan)
    app.state.gateway = gw

    def error(status: int, detail: str, retry: bool = False) -> JSONResponse:
        return JSONResponse({"detail": detail}, status_code=status, headers={"Retry-After": "10"} if retry else None)

    if serve_front:
        app.mount("/dist/fonts", StaticFiles(directory=FRONT / "dist" / "fonts"), name="fonts")

        @app.get("/", response_class=HTMLResponse)
        def index() -> str:
            return (FRONT / "privacy-lens.html").read_text(encoding="utf-8")

    @app.get("/health")
    async def health():
        e = gw.engines()
        return {"ok": e["alive"] > 0, "gateway": True, "engines": e,
                "engine_ready": any(b.healthy and b.engine_ready for b in gw.backends)}

    # ---------------- 줄 서는 요청
    async def queued(request: Request, path: str):
        form = await request.form()
        upload = form.get("image")
        if upload is None or not hasattr(upload, "read"):
            return error(422, "사진(image)이 필요합니다.")
        data = await upload.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            return error(413, f"파일이 너무 큽니다. {MAX_BYTES // 1024 // 1024}MB 이하로 넣어주세요.")
        if not data:
            return error(400, "빈 파일입니다.")
        fields = {k: v for k, v in form.items() if k != "image" and isinstance(v, str)}
        ticket = fields.get("ticket") or os.urandom(16).hex()
        if not TICKET.match(ticket):
            return error(400, "번호표 형식이 올바르지 않습니다.")
        fields["ticket"] = ticket
        h = hashlib.sha256(data)
        for k in sorted(fields):
            h.update(f"\0{k}={fields[k]}".encode())
        job = Job(ticket, path, h.hexdigest(), {"image": (upload.filename or "image", data,
                                                          upload.content_type or "application/octet-stream")}, fields)
        try:
            job = gw.enqueue(job)
        except GatewayError as exc:
            return error(exc.status, exc.detail, exc.retry)
        try:
            status, body = await asyncio.shield(job.future)
        except asyncio.CancelledError:
            raise
        return JSONResponse(body, status_code=status)

    @app.post("/analyze")
    async def analyze(request: Request):
        return await queued(request, "/analyze")

    @app.post("/redact")
    async def redact(request: Request):
        return await queued(request, "/redact")

    # ---------------- 줄 서지 않는 요청: 살아 있는 엔진에 번갈아
    async def passthrough(request: Request, path: str):
        b = gw.any_backend()
        if b is None:
            return error(503, "사용할 수 있는 분석 서버가 없습니다. 잠시 후 다시 시도해 주세요.", True)
        body = await request.body()
        headers = {"content-type": request.headers.get("content-type", "")}
        try:
            r = await gw.client.post(b.url + path, content=body, headers=headers, timeout=120.0)
        except httpx.HTTPError:
            b.healthy = False
            return error(503, "분석 서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.", True)
        return Response(r.content, status_code=r.status_code, media_type=r.headers.get("content-type"))

    @app.post("/redact/preview")
    async def preview(request: Request):
        return await passthrough(request, "/redact/preview")

    @app.post("/llm/models")
    async def models(request: Request):
        return await passthrough(request, "/llm/models")

    # ---------------- 번호표: 배정 전에는 게이트웨이가, 배정 뒤에는 그 엔진이 답한다
    @app.get("/queue")
    async def queue_status(ticket: Optional[str] = None):
        e = gw.engines()
        out = {"running": e["busy"], "waiting": len(gw.queue), "max_waiting": gw.max_waiting,
               "avg_s": round(gw.avg_s, 1) if gw.avg_s is not None else None,
               "engine_ready": any(b.healthy and b.engine_ready for b in gw.backends), "engines": e}
        if not ticket:
            return out
        job = gw.jobs.get(ticket)
        if job is None:
            out["state"] = "unknown"
            return out
        if job.backend is None and job in gw.queue:
            p = gw.waiting_progress(job)
            out.update(state="waiting", ahead=p["ahead"], eta_s=p["eta_s"], progress=p)
            return out
        b = job.backend
        if b is not None:
            try:
                r = await gw.client.get(b.url + "/queue", params={"ticket": ticket}, timeout=5.0)
                data = r.json()
                for k in ("state", "ahead", "eta_s", "progress"):
                    if k in data:
                        out[k] = data[k]
                return out
            except (httpx.HTTPError, ValueError):
                pass
        out["state"] = "running" if job.done_at is None else "unknown"
        return out

    @app.post("/queue/cancel")
    async def queue_cancel(ticket: str):
        if gw.cancel(ticket):
            return {"cancelled": True}
        job = gw.jobs.get(ticket)
        if job is not None and job.backend is not None:
            try:
                r = await gw.client.post(job.backend.url + "/queue/cancel", params={"ticket": ticket}, timeout=5.0)
                return r.json()
            except (httpx.HTTPError, ValueError):
                pass
        return {"cancelled": False}

    @app.get("/progress")
    async def progress(ticket: str, request: Request):
        """배정 전에는 게이트웨이가 '대기' 상태를 보내다가, 엔진에 배정되면 그 엔진의 SSE 를 그대로 잇는다."""
        if not TICKET.match(ticket):
            return error(400, "번호표 형식이 올바르지 않습니다.")

        def frame(event: str, data: dict) -> bytes:
            return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()

        async def events():
            yield b"retry: 2000\n\n"
            first = time.monotonic()
            while True:
                if await request.is_disconnected():
                    return
                job = gw.jobs.get(ticket)
                if job is None:
                    if time.monotonic() - first > 30:
                        yield frame("gone", {})
                        return
                elif job.backend is None and job in gw.queue:
                    yield frame("progress", gw.waiting_progress(job))
                elif job.backend is not None:
                    b = job.backend
                    try:
                        async with gw.client.stream("GET", b.url + "/progress", params={"ticket": ticket},
                                                    timeout=httpx.Timeout(None, connect=5.0)) as r:
                            async for chunk in r.aiter_raw():
                                if await request.is_disconnected():
                                    return
                                yield chunk
                        return
                    except httpx.HTTPError:
                        yield frame("gone", {})  # 화면은 /queue 폴링으로 넘어간다
                        return
                await asyncio.sleep(1.0)

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return app
