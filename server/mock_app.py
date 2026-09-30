"""
목업 API — 모델이 완성되기 전에 프론트(D)가 먼저 개발할 수 있도록 예시 JSON 을 돌려줍니다.

실행 (privacy-lens/ 에서):
  pip install fastapi uvicorn python-multipart pillow
  uvicorn server.mock_app:app --reload --port 8000

테스트:
  curl -F "file=@test.jpg" http://localhost:8000/api/v1/analyze
"""
import io
import json
import uuid
from pathlib import Path

from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from PIL import Image, ImageOps

from schema.models import AnalyzeResponse, ErrorResponse

EXAMPLE = Path(__file__).parents[1] / "schema/examples/analyze_response.json"
MAX_BYTES = 20 * 1024 * 1024

app = FastAPI(title="Privacy Lens (mock)")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])


def error(code: str, msg: str, status: int) -> JSONResponse:
    body = ErrorResponse(request_id=uuid.uuid4(), error={"code": code, "message": msg})
    return JSONResponse(body.model_dump(mode="json"), status_code=status)


@app.get("/api/v1/health")
def health():
    return {"status": "ok", "mock": True}


@app.post("/api/v1/analyze", response_model=AnalyzeResponse)
async def analyze(file: UploadFile = File(...)):
    raw = await file.read()
    if len(raw) > MAX_BYTES:
        return error("FILE_TOO_LARGE", "20MB 이하 이미지만 지원합니다.", 413)
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(raw)))  # 실제 서버와 동일하게 방향 보정
    except Exception:
        return error("DECODE_FAILED", "이미지를 열 수 없습니다.", 400)

    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    data["request_id"] = str(uuid.uuid4())
    # 업로드한 사진 크기에 맞춰 예시 박스 좌표를 비율 환산 → 프론트에서 실제 사진 위에 박스가 그려짐
    sx, sy = img.width / data["image"]["width"], img.height / data["image"]["height"]
    data["image"].update(width=img.width, height=img.height)

    def scale(b):
        return {"x1": int(b["x1"] * sx), "y1": int(b["y1"] * sy),
                "x2": max(int(b["x2"] * sx), int(b["x1"] * sx) + 1), "y2": max(int(b["y2"] * sy), int(b["y1"] * sy) + 1)}

    for f in data["findings"]:
        f["bbox"] = scale(f["bbox"])
        f.pop("polygon", None)
        for p in f["pii"]:
            if p.get("bbox"):
                p["bbox"] = scale(p["bbox"])
    del raw, img  # 원본 미저장 정책
    return AnalyzeResponse.model_validate(data)
