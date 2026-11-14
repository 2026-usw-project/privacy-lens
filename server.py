"""Privacy Lens 데모 서버.

무상태로 설계했다. 업로드된 이미지를 디스크에 쓰지 않고, 세션에 담지 않고,
요청이 끝나면 메모리에서 사라진다. 가림 요청 때 이미지를 다시 받는 것도
그 때문이다. 서버가 원본을 들고 있지 않다.

로깅도 마찬가지다. uvicorn 접근 로그에는 경로만 남고 본문은 남지 않는다.
추출된 문자열은 어떤 로그에도 기록하지 않는다. 실패한 요청은 서버 콘솔에 한 줄씩
남긴다(메서드·경로·상태·걸린 시간·화면에 나간 문구·예외 종류). 사진·OCR 원문·API 키는 넣지 않는다.

엔드포인트는 일부러 `async def` 가 아니라 `def` 다. OCR 은 수 초씩 CPU 를
붙잡는 동기 작업이라, async 안에서 돌리면 이벤트 루프가 멈춰 요청 하나가
서버 전체를 세운다. `def` 로 두면 FastAPI 가 스레드풀에서 돌린다.

OCR 은 대기열(jobqueue.py)을 거친다. 엔진은 한 번에 하나만 돌 수 있어서,
들어온 순서대로 줄을 세우고 화면에 '앞에 몇 건'을 보여준다. 대기열 조회와
취소는 스레드풀을 쓰지 않도록 `async def` 다. 줄이 길어 스레드가 모두
기다리는 중이어도 조회는 응답해야 한다.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import io
import json
import logging
import mimetypes
import os
import re
import threading
import time
import traceback
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError
from starlette.formparsers import MultiPartParser

from jobqueue import Cancelled, QueueFull, WorkQueue
from progress import ProgressBoard
from timing import TimingStore, default_path

from pipeline import analyze as pl
from pipeline import detect, llm_judge, ocr, redact, wording
from pipeline.worker import OcrUnavailable, ThreadBoundBackend
from pipeline.types import Box

# 서버 콘솔 오류 기록. uvicorn 이 루트 로거를 설정하지 않으므로 직접 붙인다.
log = logging.getLogger("privacy_lens")
if not log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s [privacy-lens] %(levelname)s %(message)s"))
    log.addHandler(_handler)
    log.setLevel(logging.INFO)
    log.propagate = False

# iPhone 기본 형식(HEIC). 패키지가 없으면 JPEG/PNG 만 받는다.
try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass

# 업로드 한도. 휴대폰 원본 사진은 대개 3~12MB 다.
MAX_BYTES = 25 * 1024 * 1024
# 화소 한도. 이보다 크면 Pillow 가 DecompressionBombError 를 낸다.
Image.MAX_IMAGE_PIXELS = 60_000_000
MAX_BOXES = 300
MAX_POLY_POINTS = 16

# Starlette 는 1MB 넘는 업로드를 임시 '파일'로 디스크에 쓴다. 그러면 '업로드를
# 디스크에 쓰지 않는다'는 원칙이 조용히 깨진다. 한도까지는 메모리에 둔다.
MultiPartParser.spool_max_size = MAX_BYTES + 1024 * 1024

# 한 번에 기다릴 수 있는 요청 수. 넘으면 503 으로 돌려보낸다.
QUEUE = WorkQueue(max_waiting=int(os.environ.get("PL_QUEUE_MAX", "12")))
_TICKET = re.compile(r"^[A-Za-z0-9-]{8,64}$")

# 화면은 web/frontend-demo 다. dist/ 가 편집 원본이고, scripts/build.mjs 가 한 파일
# (privacy-lens.html)로 묶는다. 글꼴만 따로 dist/fonts 에서 읽는다.
FRONT = Path(__file__).parent / "web" / "frontend-demo"
# Windows 의 MIME 표에는 .woff2 가 없어 text/plain 으로 나간다. 엄격한 브라우저·프록시는
# 글꼴로 받지 않을 수 있다.
mimetypes.add_type("font/woff2", ".woff2")

_backend = None
_backend_lock = threading.Lock()

# 단계별 걸린 시간(남은 시간 추정용). 숫자와 단계 키만 파일에 남긴다(D-17). PL_TIMING=off 면 메모리에만
TIMING = TimingStore(None if os.environ.get("PL_TIMING", "").lower() == "off" else default_path())


# 번호표별 진행 상태(남은 시간). 메모리에만 있다
BOARD = ProgressBoard(TIMING)
SSE_POLL_S = 0.5          # 진행 상태를 들여다보는 간격
SSE_MAX_GAP_S = 1.0       # 바뀐 게 없어도 이만큼마다 보낸다(화면이 시계를 다시 맞추게)
SSE_UNKNOWN_GIVEUP_S = 30.0  # 번호표가 이만큼 안 나타나면 끝낸다(화면은 /queue 폴링으로 돌아간다)


def _peek_megapixels(data: bytes) -> float | None:
    """헤더만 읽어 크기를 안다. 화소를 풀지 않으므로 '차례가 온 뒤에 디코딩' 원칙은 그대로다."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            return img.width * img.height / 1_000_000
    except Exception:
        return None


def _register(ticket: str, kind: str, data: bytes, cfg) -> str | None:
    """진행 상태를 만든다. 같은 번호표가 이미 돌고 있으면 그 상태를 덮지 않고 None."""
    engine = _backend
    ocr_key = pl.ocr_key(engine) if engine is not None else "ocr:" + os.environ.get("PL_OCR", "paddleocr").lower()
    ok = BOARD.register(ticket, kind, ocr_key=ocr_key, judge_key=pl.judge_key(cfg),
                        megapixels=_peek_megapixels(data),
                        detector=isinstance(detect._loaded, detect.YoloDetector))
    return ticket if ok else None


def _on_stage(engine, ticket: str | None):
    """analyze 의 on_stage: 시간 기록 + 진행 상태."""
    record = _recorder(engine)

    def on_stage(event: str, name: str, units: float, seconds: float | None) -> None:
        record(event, name, units, seconds)
        BOARD.stage(ticket, event, name, units)

    return on_stage


def _recorder(engine):
    """analyze 의 on_stage 콜백. 끝난 단계의 시간을 기록한다.

    엔진이 아직 준비되지 않았으면 이번 OCR 은 엔진을 만드는 시간까지 먹으므로 OCR 기록에서 뺀다.
    """
    warm = getattr(engine, "ready", True)

    def on_stage(event: str, name: str, units: float, seconds: float | None) -> None:
        if event != "end" or seconds is None:
            return
        if name.startswith("ocr") and not warm:
            return
        TIMING.record(name, units, seconds)

    return on_stage


class _Timed:
    """서버에서 직접 재는 단계(사진 열기·가리기·파일 만들기). 진행 상태에도 알린다."""

    def __init__(self, name: str, ticket: str | None = None, units: float | None = None):
        self.name, self.ticket, self.units = name, ticket, units

    def __enter__(self) -> "_Timed":
        BOARD.stage(self.ticket, "start", self.name, self.units)
        self.started = time.perf_counter()
        return self

    def __exit__(self, exc_type, *_):
        if exc_type is None:
            TIMING.record(self.name, self.units or 0.0, time.perf_counter() - self.started)
            BOARD.stage(self.ticket, "end", self.name, self.units)
        return False


def backend():
    # 요청이 스레드풀에서 동시에 들어와도 엔진은 하나만 만든다.
    global _backend
    with _backend_lock:
        if _backend is None:
            _backend = ThreadBoundBackend(ocr.get_backend)
    return _backend


def _close_backend():
    global _backend
    with _backend_lock:
        if isinstance(_backend, ThreadBoundBackend):
            _backend.close()
            _backend = None


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """OCR 엔진을 미리 만든다. PaddleOCR 는 불러오는 데만 1분 넘게 걸려서,
    첫 요청에서 만들면 첫 사진이 그만큼 멈춘다. 서버는 바로 뜨고 엔진은
    뒤에서 준비된다. 그 사이 들어온 요청은 잠금에서 기다린다."""
    def run() -> None:
        try:
            backend()
        except Exception:
            pass  # 첫 요청에서 같은 오류가 다시 나며 그때 사용자에게 보인다
        detect.get_detector()  # PL_YOLO_WEIGHTS 가 있을 때만. 실패하면 경고 후 OCR 만 쓴다

    warmup = threading.Thread(target=run, daemon=True)
    warmup.start()
    try:
        yield
    finally:
        # 준비 중에 종료해도 전용 스레드를 남기지 않는다.
        await asyncio.to_thread(warmup.join)
        await asyncio.to_thread(_close_backend)
        await asyncio.to_thread(TIMING.flush)


app = FastAPI(title="Privacy Lens", lifespan=_lifespan)

# 화면과 API 를 한 서버에서, 또는 엔진 서버로(API 만, run_backend.py·run.py 가 게이트웨이 뒤에 띄움).
#   PL_SERVE_FRONT=0      화면(/, /dist/fonts)을 내주지 않는다. API 만
#   PL_CORS_ORIGINS=a,b   이 주소들(화면 서버)에서 오는 요청을 허용한다. 비우면 같은 주소에서만(지금처럼)
SERVE_FRONT = os.environ.get("PL_SERVE_FRONT", "1").strip() != "0"
CORS_ORIGINS = [o.strip().rstrip("/") for o in os.environ.get("PL_CORS_ORIGINS", "").split(",") if o.strip()]
if SERVE_FRONT:
    app.mount("/dist/fonts", StaticFiles(directory=FRONT / "dist" / "fonts"), name="fonts")
if CORS_ORIGINS:
    # 쿠키·인증을 쓰지 않으므로 credentials 는 끈다. 화면이 보내는 것은 multipart 폼과 GET 뿐이다
    app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["GET", "POST"],
                       allow_headers=["*"], allow_credentials=False, max_age=600)


def _note(request: Request, message: str) -> None:
    """실패 이유를 요청에 붙여 둔다. 아래 미들웨어가 상태 코드와 함께 한 줄로 찍는다."""
    request.state.error_note = message[:300]


# 엔진 서버로 띄울 때(run_backend.py --token) 게이트웨이만 받는다. 같은 비밀값을 X-PL-Token 헤더로 보내야 한다
GATEWAY_TOKEN = os.environ.get("PL_GATEWAY_TOKEN", "")


class _Peers:
    """누가 연결을 요청했는지 엔진 콘솔에 남긴다(3-way handshake 처럼 '요청 → 수락/거절').
    게이트웨이는 5초마다 /health 를 묻는다. 처음 보거나 RECONNECT_S 넘게 조용했던 상대만 적고,
    거절은 상대마다 QUIET_S 에 한 번만 적는다. 사진·결과는 적지 않는다."""

    RECONNECT_S = 30.0
    QUIET_S = 60.0
    WATCH_EVERY_S = 10.0

    def __init__(self):
        self._seen: dict[str, float] = {}
        self._denied: dict[str, float] = {}
        self._lock = threading.Lock()
        self._watcher: threading.Thread | None = None

    def sweep(self, now: float | None = None) -> list[str]:
        """RECONNECT_S 넘게 조용한 게이트웨이를 '연결 끊김'으로 적고 지운다. 지운 이름 목록."""
        now = time.monotonic() if now is None else now
        with self._lock:
            gone = [k for k, t in self._seen.items() if now - t > self.RECONNECT_S]
            for k in gone:
                del self._seen[k]
        for k in gone:
            name, ip = k.rsplit("@", 1)
            log.info("게이트웨이 %s(%s) 연결이 끊겼습니다 — %d초 넘게 요청이 없습니다", name or "이름 없음", ip,
                     int(self.RECONNECT_S))
        return gone

    def _watch(self) -> None:
        while True:
            time.sleep(self.WATCH_EVERY_S)
            self.sweep()

    @staticmethod
    def _who(request: Request) -> tuple[str, str]:
        ip = request.client.host if request.client else "알 수 없음"
        name = re.sub(r"[^\w.-]", "", request.headers.get("x-pl-gateway", ""))[:64]
        return ip, name

    def accepted(self, request: Request) -> None:
        ip, name = self._who(request)
        if not name:
            return  # 게이트웨이(X-PL-Gateway 이름을 보냄)만 적는다. 브라우저·run.py 시작 확인은 적지 않는다
        key, now = f"{name}@{ip}", time.monotonic()
        with self._lock:
            last = self._seen.get(key)
            self._seen[key] = now
            if self._watcher is None:
                self._watcher = threading.Thread(target=self._watch, name="pl-peers", daemon=True)
                self._watcher.start()
        if last is None or now - last > self.RECONNECT_S:
            log.info("게이트웨이 %s(%s) 에서 연결을 요청했습니다 → 수락했습니다", name or "이름 없음", ip)

    def denied(self, request: Request) -> None:
        ip, name = self._who(request)
        now = time.monotonic()
        with self._lock:
            last = self._denied.get(ip)
            if last is not None and now - last < self.QUIET_S:
                return
            self._denied[ip] = now
        log.warning("%s(%s) 에서 연결을 요청했습니다 → 비밀값이 맞지 않아 거절했습니다", name or "이름 없음", ip)


PEERS = _Peers()


@app.middleware("http")
async def _gateway_only(request: Request, call_next):
    if GATEWAY_TOKEN and not hmac.compare_digest(request.headers.get("x-pl-token", ""), GATEWAY_TOKEN):
        PEERS.denied(request)
        return JSONResponse({"detail": "게이트웨이를 거친 요청만 받습니다."}, status_code=403)
    PEERS.accepted(request)
    return await call_next(request)


@app.middleware("http")
async def _log_failures(request: Request, call_next):
    """모든 요청 중 실패(4xx·5xx)와 처리하지 못한 예외를 서버 콘솔에 남긴다. 본문은 남기지 않는다."""
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:
        ms = int((time.perf_counter() - started) * 1000)
        log.error("%s %s → 500 (%dms) 처리하지 못한 예외 %s\n%s", request.method, request.url.path, ms,
                  type(exc).__name__, "".join(traceback.format_tb(exc.__traceback__)).rstrip())
        raise
    if response.status_code >= 400:
        ms = int((time.perf_counter() - started) * 1000)
        note = getattr(request.state, "error_note", "")
        level = logging.ERROR if response.status_code >= 500 else logging.WARNING
        log.log(level, "%s %s → %d (%dms)%s", request.method, request.url.path, response.status_code, ms,
                f" {note}" if note else "")
    return response


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException):
    if isinstance(exc.detail, str):
        _note(request, exc.detail)
    return await http_exception_handler(request, exc)


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError):
    # 어떤 칸이 빠졌는지만. 보낸 값(input)은 남기지 않는다.
    fields = sorted({".".join(str(p) for p in e.get("loc", ())) for e in exc.errors()})
    _note(request, "입력 형식 오류: " + ", ".join(fields))
    return await request_validation_exception_handler(request, exc)


@app.exception_handler(OcrUnavailable)
async def ocr_unavailable(request: Request, exc: OcrUnavailable):
    _note(request, wording.OCR_UNAVAILABLE + (f" (원인: {exc.cause})" if getattr(exc, "cause", "") else ""))
    return JSONResponse(
        status_code=503,
        content={"detail": wording.OCR_UNAVAILABLE},
        headers={"Retry-After": "10"},
    )


def _ticket(raw: str | None) -> str:
    """화면이 보낸 번호표. 없으면(curl 등) 서버가 만든다."""
    if not raw:
        return uuid.uuid4().hex
    if not _TICKET.match(raw):
        raise HTTPException(400, "번호표 형식이 올바르지 않습니다.")
    return raw


class _Turn:
    """with _Turn(ticket): ... — 대기열 예외를 HTTP 오류로 바꾼다."""

    def __init__(self, ticket: str):
        self._cm = QUEUE.slot(ticket)

    def __enter__(self):
        try:
            return self._cm.__enter__()
        except QueueFull:
            raise HTTPException(
                503, "지금 기다리는 요청이 많습니다. 잠시 후 다시 시도해 주세요.",
                headers={"Retry-After": "10"},
            )
        except Cancelled:
            raise HTTPException(409, "취소된 요청입니다.")
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    def __exit__(self, *exc):
        return self._cm.__exit__(*exc)


def _read(upload: UploadFile) -> bytes:
    data = upload.file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, f"파일이 너무 큽니다. {MAX_BYTES // 1024 // 1024}MB 이하로 넣어주세요.")
    if not data:
        raise HTTPException(400, "빈 파일입니다.")
    return data


def _open(data: bytes) -> Image.Image:
    """연다. 그리고 EXIF 회전 정보를 화소에 반영한다.

    휴대폰 세로 사진은 화소가 누운 채 저장되고 '90도 돌려 보여라'는 태그만
    붙어 있다. 반영하지 않으면 OCR 이 누운 글자를 읽고, 내보낼 때 EXIF 를
    지우면서 결과 사진도 누운 채 저장된다. exif_transpose 는 GPS 태그는 남긴다.
    """
    try:
        img = Image.open(io.BytesIO(data))
        # Pillow 는 한도의 2배를 넘을 때만 오류를 내고, 1~2배 사이는 경고만 하고 연다.
        # 6천만~1억2천만 화소 사진이 그대로 OCR 까지 가면 메모리가 넘친다. 열기 전에 막는다.
        if img.width * img.height > Image.MAX_IMAGE_PIXELS:
            raise Image.DecompressionBombError("too many pixels")
        img.load()
    except Image.DecompressionBombError:
        raise HTTPException(413, "화소 수가 너무 많은 이미지입니다.")
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, ImportError):
        # ImportError: Image.open 을 바꿔 둔 라이브러리가 없는 플러그인(pi_heif 등)을 찾다 실패한 경우(pipeline/ultra.py)
        raise HTTPException(400, "이미지로 읽을 수 없는 파일입니다. JPEG, PNG, HEIC 를 넣어주세요.")
    return ImageOps.exif_transpose(img) or img


def _parse_poly(raw, size: tuple[int, int]):
    """기울어진 외곽선 [[x, y], ...]. 없으면 None. 이상하면 400.

    꼭짓점은 자르지 않는다. 외곽선을 이미지 경계로 자르면 모양이 찌그러져서
    바깥으로 넓힐 때 방향이 틀어진다. 가릴 때 이미지 밖은 어차피 버려진다.
    다만 터무니없는 좌표는 받지 않는다.
    """
    if raw is None:
        return None
    bad = HTTPException(400, "가릴 영역의 외곽선 형식이 올바르지 않습니다.")
    if not isinstance(raw, list) or not 3 <= len(raw) <= MAX_POLY_POINTS:
        raise bad
    width, height = size
    pts = []
    for pt in raw:
        try:
            x, y = float(pt[0]), float(pt[1])
        except (TypeError, IndexError, ValueError):
            raise bad
        if not (-width <= x <= 2 * width and -height <= y <= 2 * height):
            raise bad
        pts.append((x, y))
    return tuple(pts)


def _parse_boxes(raw: str, size: tuple[int, int]) -> list[Box]:
    """클라이언트가 보낸 상자를 검증한다. 이미지 밖으로 나간 부분은 잘라낸다.

    상자마다 기울어진 외곽선(poly)이 붙어 있을 수 있다. 있으면 그 모양대로 가린다.
    """
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(400, "가릴 영역 형식이 올바르지 않습니다.")
    if not isinstance(items, list) or len(items) > MAX_BOXES:
        raise HTTPException(400, "가릴 영역 형식이 올바르지 않습니다.")

    width, height = size
    boxes: list[Box] = []
    for item in items:
        try:
            x, y, w, h = (int(round(float(item[k]))) for k in ("x", "y", "w", "h"))
        except (TypeError, KeyError, ValueError):
            raise HTTPException(400, "가릴 영역 형식이 올바르지 않습니다.")
        poly = _parse_poly(item.get("poly") if isinstance(item, dict) else None, size)
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(width, x + w), min(height, y + h)
        if x1 > x0 and y1 > y0:
            boxes.append(Box(x0, y0, x1 - x0, y1 - y0, poly=poly))
    return boxes


def _preview(img: Image.Image, max_side: int = 1400) -> tuple[str, float]:
    """화면 표시용 축소본. 좌표 환산에 쓸 배율도 같이 돌려준다."""
    scale = min(1.0, max_side / max(img.size))
    shown = img if scale == 1.0 else img.resize(
        (int(img.width * scale), int(img.height * scale)), Image.LANCZOS
    )
    buf = io.BytesIO()
    shown.convert("RGB").save(buf, format="JPEG", quality=88)
    return base64.b64encode(buf.getvalue()).decode(), scale


@app.get("/", response_class=HTMLResponse)
def index():
    if not SERVE_FRONT:  # API 만 띄웠을 때(엔진 서버). 화면은 게이트웨이가 내준다
        return JSONResponse({"service": "privacy-lens-api", "front": False})
    return (FRONT / "privacy-lens.html").read_text(encoding="utf-8")


@app.get("/health")
async def health():
    """살아 있는지만. 게이트웨이가 엔진 상태를 확인할 때 쓴다."""
    return {"ok": True, "engine_ready": _backend is not None}


@app.get("/queue")
async def queue_status(ticket: str | None = None):
    """대기열 상태. 번호표를 주면 내 앞에 몇 건인지도 알려준다."""
    out = QUEUE.status(ticket)
    out["engine_ready"] = _backend is not None
    if ticket:
        running, waiting = QUEUE.order()
        snap = BOARD.snapshot(ticket, running=running, waiting=waiting)
        if snap is not None:
            out["progress"] = snap  # SSE 를 못 쓰는 환경의 폴링도 같은 남은 시간을 받는다
    return out


@app.get("/progress")
async def progress_stream(ticket: str, request: Request):
    """번호표의 진행 상태를 SSE 로 보낸다. 단계가 바뀌면 바로, 아니면 1초마다.

    event: progress  data: {state, stages[], remaining_s, stage_elapsed_s, overdue_s, eta_s, ahead …}
    event: done      data: 같은 형식(state 가 done 또는 failed). 보낸 뒤 연결을 닫는다
    event: gone      번호표가 30초 안에 나타나지 않음. 화면은 /queue 폴링으로 돌아간다
    단계 이름과 숫자만 보낸다. 사진·원문은 없다. 스레드풀을 쓰지 않는다(async).
    """
    t = _ticket(ticket)

    def frame(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    async def events():
        yield "retry: 2000\n\n"
        first_seen = time.monotonic()
        last_shape, last_sent = None, 0.0
        while True:
            if await request.is_disconnected():
                return
            running, waiting = QUEUE.order()
            snap = BOARD.snapshot(t, running=running, waiting=waiting)
            now = time.monotonic()
            if snap is None:
                if now - first_seen > SSE_UNKNOWN_GIVEUP_S:
                    yield frame("gone", {})
                    return
            elif snap["state"] in ("done", "failed"):
                yield frame("done", snap)
                return
            else:
                # 시간 값만 바뀐 것은 1초마다, 단계·상태가 바뀐 것은 바로 보낸다
                shape = json.dumps([snap["state"], snap.get("current"), snap.get("ahead"),
                                    [s["state"] for s in snap["stages"]], [s["estimate_s"] for s in snap["stages"]]])
                if shape != last_shape or now - last_sent >= SSE_MAX_GAP_S:
                    yield frame("progress", snap)
                    last_shape, last_sent = shape, now
            await asyncio.sleep(SSE_POLL_S)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/queue/cancel")
async def queue_cancel(ticket: str):
    """기다리는 요청을 뺀다. 화면이 닫히거나 다른 사진을 넣을 때 부른다."""
    return {"cancelled": QUEUE.cancel(ticket)}


@app.exception_handler(llm_judge.LlmJudgeError)
async def llm_failed(request: Request, exc: llm_judge.LlmJudgeError):
    # detail 은 wording 이 만든 문구뿐이다. 서버 로그에는 공급자·모델·상태 코드까지만 남긴다.
    # llm_trace(요청·응답, 키 가림)는 화면이 개발자 콘솔에 찍도록 응답에만 싣는다.
    last = exc.trace[-1] if exc.trace else {}
    where = f"{last.get('provider', '?')}/{last.get('model') or '-'}" if last else "설정"
    status = f" HTTP {exc.status}" if exc.status else ""
    _note(request, f"LLM 실패 [{where}{status}] {exc}")
    content = {"detail": str(exc)}
    if exc.trace:
        content["llm_trace"] = exc.trace
    return JSONResponse(status_code=502, content=content)


def _judge(raw: str | None) -> llm_judge.JudgeConfig | None:
    """판단 모델 창의 판단 설정. 비었으면 규칙 기반. 키는 이 요청에서만 쓰고 저장하지 않는다."""
    try:
        return llm_judge.parse_config(raw)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/llm/models")
def llm_models(judge: str = Form(...)):
    """판단 모델 창: 고른 공급자에서 쓸 수 있는 모델 이름 목록. 키는 본문으로 받아 이 요청에서만 쓴다.

    OCR 이 없어 대기열을 거치지 않는다. 사진도 원문도 보내지 않는다.
    """
    try:
        cfg = llm_judge.parse_config(judge, need_model=False)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if cfg is None:
        return {"models": []}
    trace: list = []
    return {"models": llm_judge.list_models(cfg, trace=trace), "llm_trace": trace}


class _SameRequest:
    """같은 번호표로 같은 요청이 다시 오면 처음 요청의 결과를 기다려 그대로 돌려준다.

    화면은 번호표마다 요청을 한 번만 보내지만, 브라우저·프록시·터널이 오래 걸리는 POST 를 다시 보내는 일이 있다
    (서버를 켠 직후 엔진 준비로 첫 요청이 1분 넘게 걸렸을 때 실제로 '이미 대기열에 있는 번호표' 400 이 났다).
    그러면 화면은 실패를 보고, 처음 요청은 아무도 받지 않을 결과를 만든다.

    - 같은 요청인지는 사진 바이트와 설정의 해시(fingerprint)로 본다. 번호표만 아는 다른 사람은 결과를 받을 수 없다
      (같은 사진을 가진 사람만 같은 결과를 받는다). 다르면 지금처럼 400.
    - 처음 요청이 끝난 뒤 KEEP_S 초 동안은 늦게 온 재시도에도 같은 결과를 준다. 결과는 메모리에만, 그 뒤 지운다.
    - 처음 요청이 실패했으면 같은 오류를 돌려준다.
    """

    KEEP_S = 30.0
    WAIT_S = 15 * 60.0

    def __init__(self):
        self._lock = threading.Lock()
        self._jobs: dict[str, dict] = {}

    def run(self, key: str, fingerprint: str, work):
        with self._lock:
            now = time.monotonic()
            for k in [k for k, j in self._jobs.items() if j["at"] is not None and now - j["at"] > self.KEEP_S]:
                del self._jobs[k]
            job = self._jobs.get(key)
            owner = job is None
            if owner:
                job = self._jobs[key] = {"fp": fingerprint, "done": threading.Event(), "result": None,
                                         "error": None, "at": None}
        if not owner:
            if job["fp"] != fingerprint:
                raise HTTPException(400, "이미 대기열에 있는 번호표입니다.")
            if not job["done"].wait(self.WAIT_S):
                raise HTTPException(503, "처음 보낸 요청이 아직 끝나지 않았습니다. 잠시 후 다시 시도해 주세요.",
                                    headers={"Retry-After": "10"})
            if job["error"] is not None:
                raise job["error"]
            return job["result"]
        try:
            job["result"] = work()
            return job["result"]
        except Exception as exc:
            job["error"] = exc
            raise
        finally:
            job["at"] = time.monotonic()
            job["done"].set()


SAME = _SameRequest()


def _fingerprint(data: bytes, *parts: str | None) -> str:
    h = hashlib.sha256(data)
    for part in parts:
        h.update(b"\0" + (part or "").encode("utf-8"))
    return h.hexdigest()


@app.post("/analyze")
def analyze_endpoint(
    image: UploadFile = File(...),
    ticket: str | None = Form(None),
    judge: str | None = Form(None),
):
    # 기다리는 동안에는 받은 바이트만 들고 있는다. 디코딩은 차례가 온 뒤에.
    data = _read(image)
    cfg = _judge(judge)
    t = _ticket(ticket)
    body = SAME.run("analyze:" + t, _fingerprint(data, judge), lambda: _analyze_turn(data, cfg, t))
    return JSONResponse(body)


def _analyze_turn(data: bytes, cfg, t: str) -> dict:
    live = _register(t, "analyze", data, cfg)
    ok = False
    try:
        with _Turn(t):
            BOARD.begin(live)
            with _Timed("decode", live) as st:
                img = _open(data)
                st.units = pl.megapixels(img)
            engine = backend()
            report = pl.analyze(img, backend=engine, judge=cfg, llm_trace=[] if cfg else None,
                                on_stage=_on_stage(engine, live))
        ok = True
    finally:
        BOARD.finish(live, ok)
    preview, scale = _preview(img)

    return {
        "report": report.as_dict(),
        "preview": preview,
        "preview_scale": scale,
    }


def _style(raw: str) -> str:
    if raw not in redact.STYLES:
        raise HTTPException(400, "가림 방식은 blur 또는 solid 입니다.")
    return raw


@app.post("/redact/preview")
def redact_preview(
    image: UploadFile = File(...),
    boxes: str = Form("[]"),
    style: str = Form(redact.DEFAULT_STYLE),
):
    """가린 모습 미리 보기. 저장할 때와 같은 함수로 가린다.

    OCR 을 돌리지 않으니 대기열을 거치지 않는다. 화면용 축소본만 돌려준다.
    축소본이라도 가린 뒤에 줄이므로 원본 글자가 섞여 나오지 않는다.
    """
    style = _style(style)
    img = _open(_read(image))
    masked = redact.apply_masks(img, _parse_boxes(boxes, img.size), style)
    preview, scale = _preview(masked)
    return JSONResponse({"preview": preview, "preview_scale": scale, "style": style})


@app.post("/redact")
def redact_endpoint(
    image: UploadFile = File(...),
    boxes: str = Form("[]"),
    style: str = Form(redact.DEFAULT_STYLE),
    ticket: str | None = Form(None),
):
    style = _style(style)
    data = _read(image)
    t = _ticket(ticket)
    body = SAME.run("redact:" + t, _fingerprint(data, boxes, style),
                    lambda: _redact_request(data, boxes, style, t))
    return JSONResponse(body)


def _redact_request(data: bytes, boxes: str, style: str, t: str) -> dict:
    live = _register(t, "redact", data, None)
    ok = False
    try:
        with _Turn(t):
            BOARD.begin(live)
            out, selected_count = _redact_turn(data, boxes, style, live)
        ok = True
    finally:
        BOARD.finish(live, ok)
    return {
        "file": base64.b64encode(out).decode(),
        "bytes": len(out),
        "selected_count": selected_count,
    }


def _redact_turn(data: bytes, boxes: str, style: str, live: str | None) -> tuple[bytes, int]:
    """/redact 의 차례가 오면 선택 영역을 가리고 메타데이터 없는 JPEG 를 만든다."""
    with _Timed("decode", live) as st:
        img = _open(data)
        st.units = pl.megapixels(img)
    wanted = _parse_boxes(boxes, img.size)
    mp = pl.megapixels(img)

    with _Timed("mask", live, mp):
        masked = redact.apply_masks(img, wanted, style)
    with _Timed("export", live, mp):
        out = redact.export(masked)

    return out, len(wanted)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 8000)),
                access_log=False)
