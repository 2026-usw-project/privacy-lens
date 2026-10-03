"""
데모 서버 — 실제 파이프라인

  uvicorn server.app:app --port 8000
  → http://localhost:8000          (web/dist 가 빌드돼 있으면 프론트까지 한 번에)
  → http://localhost:8000/docs     (API 직접 테스트)

환경변수
  PL_MOCK=1          모델 없이 목업 응답 (프론트 개발용)
  PL_OCR_ENGINE      easyocr(기본) | paddle
  PL_GPU=1           GPU 사용
"""
from __future__ import annotations

import os
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from schema.models import AnalyzeResponse, ErrorResponse

MOCK = os.environ.get("PL_MOCK", "0") == "1"
MAX_BYTES = 20 * 1024 * 1024
ALLOWED = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif", "application/octet-stream"}
DIST = Path(__file__).parents[1] / "web" / "dist"

app = FastAPI(title="Privacy Lens", version="0.2.0-demo")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])

_lock = threading.Lock()        # CPU 추론은 한 번에 하나씩 (동시 요청 시 메모리 · 속도 보호)
_ready = threading.Event()


def _warm():
    if not MOCK:
        from vision import ocr
        ocr.warmup()
    _ready.set()


threading.Thread(target=_warm, daemon=True).start()


def error(code: str, msg: str, status: int) -> JSONResponse:
    body = ErrorResponse(request_id=uuid.uuid4(), error={"code": code, "message": msg})
    return JSONResponse(body.model_dump(mode="json"), status_code=status)


@app.get("/api/v1/health")
def health():
    return {"status": "ok" if _ready.is_set() else "warming_up", "mock": MOCK}


@app.post("/api/v1/analyze", response_model=AnalyzeResponse, response_model_exclude_none=True)
def analyze(file: UploadFile = File(...), debug: bool = Query(False)):
    if file.content_type and file.content_type not in ALLOWED:
        return error("UNSUPPORTED_FORMAT", "JPG · PNG · WEBP 이미지만 지원합니다.", 415)
    raw = file.file.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        return error("FILE_TOO_LARGE", "20MB 이하 이미지만 지원합니다.", 413)
    if MOCK:
        return _mock(raw)
    from server.pipeline import BadImage, analyze as run
    _ready.wait(timeout=120)
    with _lock:
        try:
            return run(raw, debug=debug)
        except BadImage:
            return error("DECODE_FAILED", "이미지를 열 수 없습니다.", 400)
        except Exception as e:                       # noqa: BLE001
            return error("INTERNAL", f"분석 중 오류가 발생했습니다: {type(e).__name__}", 500)


def _mock(raw: bytes):
    import io, json
    from PIL import Image, ImageOps
    ex = Path(__file__).parents[1] / "schema/examples/analyze_response.json"
    data = json.loads(ex.read_text(encoding="utf-8"))
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(raw)))
    sx, sy = img.width / data["image"]["width"], img.height / data["image"]["height"]
    data["image"].update(width=img.width, height=img.height)
    data["request_id"] = str(uuid.uuid4())
    sc = lambda b: {"x1": int(b["x1"] * sx), "y1": int(b["y1"] * sy), "x2": int(b["x2"] * sx) + 1, "y2": int(b["y2"] * sy) + 1}
    for f in data["findings"]:
        f["bbox"] = sc(f["bbox"]); f.pop("polygon", None)
        for p in f["pii"]:
            if p.get("bbox"):
                p["bbox"] = sc(p["bbox"])
    return AnalyzeResponse.model_validate(data)


if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="web")
