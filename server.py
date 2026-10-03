"""Privacy Lens 데모 서버.

무상태로 설계했다. 업로드된 이미지를 디스크에 쓰지 않고, 세션에 담지 않고,
요청이 끝나면 메모리에서 사라진다. 가림 요청 때 이미지를 다시 받는 것도
그 때문이다. 서버가 원본을 들고 있지 않다.

로깅도 마찬가지다. uvicorn 접근 로그에는 경로만 남고 본문은 남지 않는다.
추출된 문자열은 어떤 로그에도 기록하지 않는다.

엔드포인트는 일부러 `async def` 가 아니라 `def` 다. OCR 은 수 초씩 CPU 를
붙잡는 동기 작업이라, async 안에서 돌리면 이벤트 루프가 멈춰 요청 하나가
서버 전체를 세운다. `def` 로 두면 FastAPI 가 스레드풀에서 돌린다.

OCR 은 대기열(jobqueue.py)을 거친다. 엔진은 한 번에 하나만 돌 수 있어서,
들어온 순서대로 줄을 세우고 화면에 '앞에 몇 건'을 보여준다. 대기열 조회와
취소는 스레드풀을 쓰지 않도록 `async def` 다. 줄이 길어 스레드가 모두
기다리는 중이어도 조회는 응답해야 한다.
"""

from __future__ import annotations

import base64
import io
import json
import mimetypes
import os
import re
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError
from starlette.formparsers import MultiPartParser

from jobqueue import Cancelled, QueueFull, WorkQueue

from pipeline import analyze as pl
from pipeline import metadata, ocr, redact
from pipeline.types import Box

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


def backend():
    # 요청이 스레드풀에서 동시에 들어와도 엔진은 하나만 만든다.
    global _backend
    with _backend_lock:
        if _backend is None:
            _backend = ocr.get_backend()
    return _backend


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

    threading.Thread(target=run, daemon=True).start()
    yield


app = FastAPI(title="Privacy Lens", lifespan=_lifespan)
app.mount("/dist/fonts", StaticFiles(directory=FRONT / "dist" / "fonts"), name="fonts")


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
        img.load()
    except Image.DecompressionBombError:
        raise HTTPException(413, "화소 수가 너무 많은 이미지입니다.")
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
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
def index() -> str:
    return (FRONT / "privacy-lens.html").read_text(encoding="utf-8")


@app.get("/queue")
async def queue_status(ticket: str | None = None):
    """대기열 상태. 번호표를 주면 내 앞에 몇 건인지도 알려준다."""
    out = QUEUE.status(ticket)
    out["engine_ready"] = _backend is not None
    return out


@app.post("/queue/cancel")
async def queue_cancel(ticket: str):
    """기다리는 요청을 뺀다. 화면이 닫히거나 다른 사진을 넣을 때 부른다."""
    return {"cancelled": QUEUE.cancel(ticket)}


@app.post("/analyze")
def analyze_endpoint(
    image: UploadFile = File(...),
    mode: str = Form("full"),
    ticket: str | None = Form(None),
):
    # 기다리는 동안에는 받은 바이트만 들고 있는다. 디코딩은 차례가 온 뒤에.
    data = _read(image)

    runner = {
        "naive": pl.naive_regex,
        "baseline": pl.baseline,
        "full": pl.analyze,
    }.get(mode, pl.analyze)

    with _Turn(_ticket(ticket)):
        img = _open(data)
        report = runner(img, backend=backend())
    preview, scale = _preview(img)

    return JSONResponse({
        "report": report.as_dict(),
        "preview": preview,
        "preview_scale": scale,
        "mode": mode,
    })


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

    with _Turn(_ticket(ticket)):
        img = _open(data)
        wanted = _parse_boxes(boxes, img.size)

        masked = redact.apply_masks(img, wanted, style)
        out = redact.export(masked)

        # 원본 전체를 다시 분석하지 않는다. 검증에 필요한 건 '원본에 위치정보가
        # 있었는가' 뿐이고, 그건 EXIF 만 읽으면 된다. OCR 은 결과 파일에 한 번만.
        had_gps = bool(metadata.check_exif(img))
        check = redact.verify(
            wanted, out, lambda im: pl.analyze(im, backend=backend()), had_gps=had_gps
        )

    return JSONResponse({
        "file": base64.b64encode(out).decode(),
        "verification": check,
        "bytes": len(out),
    })


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", 8000)),
                access_log=False)
