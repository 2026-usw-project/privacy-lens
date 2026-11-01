"""서비스 안정성 점검 — 실제 서버 코드(server.app)에 이상한 입력과 연속 요청을 넣어 본다.

정확도가 아니라 "멈추거나 이상한 응답을 내지 않는가"를 본다. 1차 완료 기준의
'30장 연속 처리 오류 0번', '사진 1장 10초 이내'를 여기서 잰다(docs/PLAN_1ST.md).

    PL_OCR=paddleocr python -m eval.stability          # 서비스와 같은 OCR 로
    PL_OCR=tesseract python -m eval.stability --n 30   # 연속 요청 수
    python -m eval.stability --quick                   # OCR 없이 입력 검증만(가짜 OCR)

입력 사진은 전부 그 자리에서 만든 가상 이미지다. 실사·개인정보는 쓰지 않는다.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import statistics
import sys
import threading
import time
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SLOW_SEC = 10.0  # 1차 완료 기준
QUICK = False    # 가짜 OCR 은 어떤 사진에도 같은 글자를 돌려주므로 '결과 없음' 안내는 보지 않는다


# ------------------------------------------------------------ 입력 만들기

def _save(img: Image.Image, fmt: str, **kw) -> bytes:
    buf = io.BytesIO()
    img.save(buf, fmt, **kw)
    return buf.getvalue()


def _waybill(size=(1600, 1000)) -> Image.Image:
    from samples.make_sample import make_waybill
    wb, _ = make_waybill(7)
    canvas = Image.new("RGB", size, (214, 200, 178))
    wb = wb.resize((int(size[0] * 0.6), int(size[0] * 0.6 * wb.height / wb.width)))
    canvas.paste(wb, ((size[0] - wb.width) // 2, (size[1] - wb.height) // 2))
    return canvas


def cases() -> list[tuple[str, bytes, int, str]]:
    """(이름, 바이트, 기대 상태코드, 설명)"""
    wb = _waybill()
    out = [
        ("송장 JPEG", _save(wb, "JPEG", quality=90), 200, "기본"),
        ("송장 PNG", _save(wb, "PNG"), 200, "PNG"),
        ("투명 PNG(RGBA)", _save(wb.convert("RGBA"), "PNG"), 200, "알파 채널"),
        ("흑백(L)", _save(wb.convert("L"), "PNG"), 200, "회색조"),
        ("팔레트(P)", _save(wb.convert("P"), "PNG"), 200, "색 256개"),
        ("CMYK JPEG", _save(wb.convert("CMYK"), "JPEG"), 200, "인쇄용 색공간"),
        ("16비트 흑백", _save(wb.convert("L").point(lambda v: v).convert("I;16"), "PNG"), 200, "의료·스캐너"),
        ("WEBP", _save(wb, "WEBP"), 200, "WEBP"),
        ("아주 작은 사진", _save(Image.new("RGB", (8, 8), "white"), "PNG"), 200, "8×8"),
        ("글자 없는 사진", _save(Image.new("RGB", (1200, 900), (120, 160, 200)), "JPEG"), 200, "결과 없음 안내"),
        ("세로 사진(EXIF 회전)", _rotated(wb), 200, "방향 태그 6"),
        ("큰 사진 48MP", _save(_waybill((8000, 6000)), "JPEG", quality=85), 200, "8000×6000"),
        ("화소 폭탄 70MP", _save(Image.new("L", (10000, 7000), 255), "PNG"), 413, "6천만 화소 초과"),
        ("빈 파일", b"", 400, "0바이트"),
        ("이미지 아닌 파일", b"hello, not an image" * 10, 400, "텍스트"),
        ("잘린 JPEG", _save(wb, "JPEG")[:5000], 400, "다운로드 중 끊김"),
        ("26MB 초과", b"\xff\xd8" + b"0" * (26 * 1024 * 1024), 413, "용량 초과"),
    ]
    heic = _heic(wb)
    if heic:
        out.insert(8, ("HEIC(아이폰)", heic, 200, "pillow-heif"))
    return out


def _rotated(img: Image.Image) -> bytes:
    """휴대폰 세로 사진: 화소는 가로로 누워 저장되고 '90° 돌려 보여라'(6) 태그만 붙는다."""
    exif = Image.Exif()
    exif[0x0112] = 6
    return _save(img, "JPEG", exif=exif)


def _heic(img: Image.Image) -> bytes | None:
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
        return _save(img, "HEIF")
    except Exception:
        return None


# ------------------------------------------------------------ 점검

def _client(quick: bool):
    from fastapi.testclient import TestClient

    import server
    if quick:
        from pipeline import ocr
        from pipeline.types import Box, TextSpan
        server._backend = ocr.ScriptedBackend([TextSpan("받는분 010-1234-5678", Box(10, 10, 200, 20), 0.95)])
    return TestClient(server.app), server


def check_inputs(client) -> list[dict]:
    rows = []
    for name, data, want, note in cases():
        t = time.perf_counter()
        try:
            r = client.post("/analyze", files={"image": ("x", data)})
            code, body = r.status_code, (r.json() if r.headers.get("content-type", "").startswith("application/json") else {})
        except Exception as exc:  # 서버가 예외를 밖으로 던지면 그 자체가 실패
            code, body = f"예외 {type(exc).__name__}", {}
        sec = time.perf_counter() - t
        ok = code == want
        detail = ""
        if code == 200:
            rep = body["report"]
            detail = f"{rep['width']}×{rep['height']}, 항목 {len(rep['findings'])}"
            if name.startswith("세로"):
                ok = ok and rep["height"] > rep["width"]  # 방향을 화소에 반영했는가
            if name.startswith("글자 없는") and not QUICK:
                ok = ok and bool(rep["notes"])  # '찾지 못함'을 안전하다고 말하지 않는 안내
        elif isinstance(body, dict) and body.get("detail"):
            detail = str(body["detail"])[:40]
        rows.append({"name": name, "note": note, "want": want, "code": code, "ok": ok, "sec": sec, "detail": detail})
    return rows


def check_redact(client) -> dict:
    """분석 → 가림 → 결과 파일 재검사까지 한 바퀴. 결과에 EXIF 가 남지 않아야 한다."""
    wb = _waybill()
    exif = Image.Exif()
    exif[0x8825] = {1: "N", 2: (37.0, 30.0, 0.0), 3: "E", 4: (127.0, 0.0, 0.0)}
    data = _save(wb, "JPEG", exif=exif)
    rep = client.post("/analyze", files={"image": ("x.jpg", data)}).json()["report"]
    boxes = [f["box"] for f in rep["findings"] if f["box"] and f["severity"] == "cover"]
    r = client.post("/redact", files={"image": ("x.jpg", data)},
                    data={"boxes": json.dumps(boxes), "style": "solid"})
    body = r.json()
    out = Image.open(io.BytesIO(base64.b64decode(body["file"])))
    return {"code": r.status_code, "boxes": len(boxes), "verification": body.get("verification"),
            "exif_left": bool(out.getexif()), "size_same": out.size == wb.size}


def check_sequence(client, n: int) -> dict:
    data = _save(_waybill(), "JPEG", quality=90)
    times, errors = [], 0
    for _ in range(n):
        t = time.perf_counter()
        r = client.post("/analyze", files={"image": ("x.jpg", data)})
        times.append(time.perf_counter() - t)
        errors += r.status_code != 200
    return {"n": n, "errors": errors, "avg": statistics.mean(times), "max": max(times),
            "p50": statistics.median(times)}


def check_parallel(client, k: int = 4) -> dict:
    """동시에 여러 명이 올릴 때. 대기열이 순서대로 처리하고 아무도 오류를 받지 않아야 한다."""
    data = _save(_waybill(), "JPEG", quality=90)
    codes: list[int] = []
    lock = threading.Lock()

    def one():
        r = client.post("/analyze", files={"image": ("x.jpg", data)})
        with lock:
            codes.append(r.status_code)

    threads = [threading.Thread(target=one) for _ in range(k)]
    t = time.perf_counter()
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    return {"k": k, "codes": sorted(codes), "sec": time.perf_counter() - t}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m eval.stability")
    ap.add_argument("--n", type=int, default=30, help="연속 요청 수(기본 30)")
    ap.add_argument("--quick", action="store_true", help="가짜 OCR 로 입력 검증만 빠르게")
    a = ap.parse_args(argv)
    global QUICK
    QUICK = a.quick
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    with _client(a.quick)[0] as client:
        from pipeline import ocr
        print(f"OCR: {'가짜(--quick)' if a.quick else ocr.get_backend().name}\n")
        rows = check_inputs(client)
        print("입력 종류별")
        for r in rows:
            mark = "통과" if r["ok"] else "실패"
            slow = "  ← 느림" if r["code"] == 200 and r["sec"] > SLOW_SEC else ""
            print(f"  {mark}  {r['name']:<16} 기대 {r['want']} → {r['code']}  {r['sec']:5.1f}초  {r['detail']}{slow}")
        red = check_redact(client)
        red_ok = red["code"] == 200 and not red["exif_left"] and red["size_same"]
        print(f"\n가림 한 바퀴  {'통과' if red_ok else '실패'}  상태 {red['code']}, 가린 곳 {red['boxes']}, "
              f"EXIF 남음 {red['exif_left']}, 크기 그대로 {red['size_same']}")
        print(f"  재검사: {json.dumps(red['verification'], ensure_ascii=False)[:160]}")
        seq = check_sequence(client, 3 if a.quick else a.n)
        seq_ok = seq["errors"] == 0 and seq["max"] <= SLOW_SEC
        print(f"\n연속 {seq['n']}장  {'통과' if seq_ok else '실패'}  오류 {seq['errors']}, "
              f"평균 {seq['avg']:.1f}초, 중간값 {seq['p50']:.1f}초, 최대 {seq['max']:.1f}초 (기준 {SLOW_SEC:.0f}초)")
        par = check_parallel(client)
        par_ok = all(c == 200 for c in par["codes"])
        print(f"동시 {par['k']}명  {'통과' if par_ok else '실패'}  상태 {par['codes']}, 모두 끝나는 데 {par['sec']:.1f}초")

    failed = [r for r in rows if not r["ok"]] + ([1] if not red_ok else []) + ([1] if not seq_ok else []) + ([1] if not par_ok else [])
    print("\n결과: " + ("모두 통과" if not failed else f"실패 {len(failed)}건"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
