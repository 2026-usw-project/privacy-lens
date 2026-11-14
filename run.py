"""환경을 점검하고 게이트웨이 + 엔진 서버 1개를 함께 띄운다. Windows / macOS / Linux 공통.

    python run.py            점검 후 실행(화면 + API, http://127.0.0.1:8000)
    python run.py --check    점검만
    python run.py --samples  샘플만 생성

    사용자 ──▶ 게이트웨이(화면 + 대기열, PORT=8000) ──▶ 엔진 서버(이 PC 안, PL_ENGINE_PORT=8001)

- 여러 PC 로 나눌 때와 같은 구조다. 엔진을 더 붙이려면 run_gateway.py --backend 를 여러 번 쓴다(README).
- 엔진은 이 PC 안(127.0.0.1)에서만 연다. PL_GATEWAY_TOKEN 을 설정하면 같은 토큰을 가진 요청만 받는다.
- HOST=0.0.0.0 이면 게이트웨이만 다른 기기에 열린다.
- 포트가 쓰는 중이면 1 씩 올려 빈 포트로 연다(PORT 부터, 엔진은 그 다음 번호부터). 바뀌면 콘솔에 알린다.

에러가 난 뒤에 원인을 찾는 것보다, 시작하기 전에 뭐가 없는지 알려주는 편이 낫다.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

OK, BAD, WARN = "  [OK]", "  [실패]", "  [경고]"

REQUIRED = {
    "PIL": "pillow",
    "cv2": "opencv-python-headless",
    "pytesseract": "pytesseract",
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "multipart": "python-multipart",
    "qrcode": "qrcode",
    "httpx": "httpx",
}


def check_packages() -> list[str]:
    missing = []
    for module, package in REQUIRED.items():
        try:
            __import__(module)
            print(f"{OK} {package}")
        except ImportError:
            print(f"{BAD} {package}")
            missing.append(package)
    try:
        __import__("pillow_heif")
        print(f"{OK} pillow-heif (iPhone HEIC)")
    except ImportError:
        print(f"{WARN} pillow-heif 없음 — HEIC 사진은 받지 못합니다 (pip install pillow-heif)")
    return missing


def check_font() -> bool:
    try:
        from samples.fonts import find_korean_font

        regular, _ = find_korean_font()
        print(f"{OK} 한글 폰트 — {Path(regular).name}")
        return True
    except Exception as exc:
        print(f"{BAD} 한글 폰트")
        print("\n".join("       " + line for line in str(exc).splitlines()))
        return False


def check_ocr_choice() -> str:
    import os

    choice = os.environ.get("PL_OCR", "paddleocr").lower()
    if choice != "paddleocr":
        print(f"{WARN} PL_OCR={choice} — PaddleOCR 대신 이 백엔드를 씁니다")
    return choice


def check_paddle() -> bool:
    try:
        import paddleocr
    except ImportError:
        print(f"{BAD} paddleocr — pip install paddleocr \"paddlepaddle<3.3\"")
        return False
    version = getattr(paddleocr, "__version__", "?")
    print(f"{OK} paddleocr {version}")
    # paddleocr 는 껍데기다. 추론 엔진 paddlepaddle 이 없으면 모델을 다 받은 뒤에야
    # "Engine 'paddle_static' is unavailable" 로 멈춘다. 먼저 확인한다.
    try:
        import paddle
    except ImportError:
        print(f"{BAD} paddlepaddle — pip install \"paddlepaddle<3.3\"")
        return False
    print(f"{OK} paddlepaddle {getattr(paddle, '__version__', '?')}")
    try:
        from pipeline.ocr import PaddleBackend

        engine = PaddleBackend()
        print(f"{OK} PaddleOCR 초기화 — {engine.name}")
        return True
    except Exception as exc:
        print(f"{BAD} PaddleOCR 초기화: {type(exc).__name__}: {exc}")
        print("       처음 실행이면 모델 가중치 다운로드 중일 수 있습니다.")
        return False


def check_tesseract() -> bool:
    try:
        from pipeline.ocr import TesseractBackend, locate_tesseract
    except ImportError:
        print(f"{BAD} Tesseract — pytesseract 가 없습니다")
        return False

    exe = locate_tesseract()
    if exe is None:
        print(f"{BAD} Tesseract 실행 파일을 찾지 못했습니다")
        if sys.platform == "win32":
            print("       https://github.com/UB-Mannheim/tesseract/wiki 에서 설치하고,")
            print("       설치 중 Additional language data 에서 Korean 을 선택하세요.")
        elif sys.platform == "darwin":
            print("       brew install tesseract tesseract-lang")
        else:
            print("       sudo apt install tesseract-ocr tesseract-ocr-kor")
        return False

    print(f"{OK} Tesseract — {exe}")

    try:
        TesseractBackend()._ensure()
        print(f"{OK} 한국어 데이터 (kor)")
        return True
    except RuntimeError as exc:
        print(f"{BAD} 한국어 데이터")
        print("\n".join("       " + line for line in str(exc).splitlines()[1:]))
        return False


def make_samples(force: bool = False) -> bool:
    out = ROOT / "samples" / "out"
    if out.exists() and any(out.glob("*.png")) and not force:
        print(f"{OK} 샘플 이미지 — 이미 있습니다")
        return True
    try:
        from samples.make_sample import make_waybill, place_on_desk

        out.mkdir(parents=True, exist_ok=True)
        for seed in range(3):
            wb, _ = make_waybill(seed)
            wb.save(out / f"waybill_{seed}_flat.png")
            place_on_desk(wb, seed).save(out / f"waybill_{seed}_desk.png")
        print(f"{OK} 샘플 이미지 6장 생성 — {out}")
        return True
    except Exception as exc:
        print(f"{BAD} 샘플 생성: {exc}")
        return False


def run_checks(args: set[str]) -> int:
    """점검. 0 이면 서버를 띄워도 된다. run_backend.py 도 같이 쓴다."""
    print(f"\nPrivacy Lens — 환경 점검  ({sys.platform}, Python {sys.version.split()[0]})\n")

    missing = check_packages()
    if missing:
        print(f"\n설치가 필요합니다:\n  {sys.executable} -m pip install " + " ".join(missing))
        return 1

    font_ok = check_font()
    choice = check_ocr_choice()
    ocr_ok = check_paddle() if choice == "paddleocr" else check_tesseract()

    if not font_ok:
        return 1

    try:
        from pipeline import objects
        for line in objects.status():
            print(f"{OK if '없음' not in line else WARN} {line}")
    except Exception as exc:
        print(f"{WARN} 이미지 객체 검출 점검 실패: {exc}")

    make_samples(force="--samples" in args)

    if not ocr_ok:
        print("\nOCR 없이는 탐지가 동작하지 않습니다. 위 안내대로 설치한 뒤 다시 실행하세요.")
        print("EXIF·QR 검사만 먼저 보려면  PL_OCR=none  으로 실행할 수 있습니다.")
        return 1
    return 0


def _can_bind(host: str, port: int) -> bool:
    """uvicorn 처럼 SO_REUSEADDR 를 켜고 열어 본다.
    Linux 는 이 옵션 없이는 방금 끈 서버의 연결(TIME_WAIT)이 남아 있는 동안 '쓰는 중'으로 본다(실제로는 비어 있음).
    Windows 의 SO_REUSEADDR 는 다른 프로그램이 쓰는 포트도 열게 해 버리므로 켜지 않는다."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if os.name != "nt":
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def port_free(port: int, host: str = "127.0.0.1") -> bool:
    """uvicorn 이 이 포트를 열 수 있고, 다른 프로그램과 겹치지 않는지.
    Windows 는 127.0.0.1 과 0.0.0.0 을 서로 다른 자리로 봐서, 다른 프로그램이 한쪽을 쓰고 있어도 다른 쪽은 열린다
    (그러면 같은 주소로 들어온 요청이 엉뚱한 프로그램으로 간다). 그래서 Windows 는 둘 다 비어 있어야 비었다고 본다."""
    addrs = {"0.0.0.0" if host in ("", "0.0.0.0") else host}
    if os.name == "nt":
        addrs |= {"127.0.0.1", "0.0.0.0"}
    return all(_can_bind(a, port) for a in sorted(addrs))


def free_port(start: int, host: str = "127.0.0.1", *, avoid=(), tries: int = 50) -> int | None:
    """start 부터 1 씩 올리며 열 수 있는 첫 포트. tries 번 안에 없으면 None."""
    for p in range(start, min(start + tries, 65536)):
        if p not in avoid and port_free(p, host):
            return p
    return None


def pick_port(want: int, host: str, what: str, *, avoid=()) -> int:
    """빈 포트를 고르고, 바뀌었으면 알린다. 없으면 SystemExit."""
    got = free_port(want, host, avoid=avoid)
    if got is None:
        raise SystemExit(f"\n{BAD} {want}~{want + 49} 번 포트가 모두 쓰는 중입니다({what}). 다른 번호를 주세요.")
    if got != want:
        print(f"{WARN} {want} 번 포트를 쓰는 중이라 {got} 번으로 엽니다({what}). "
              f"이 주소를 가리키는 터널·게이트웨이 설정이 있으면 함께 바꿔 주세요.")
    return got


def wait_engine(proc: subprocess.Popen, url: str, token: str, timeout: float = 180.0) -> bool:
    """엔진 서버가 /health 에 답할 때까지 기다린다. 엔진 프로세스가 먼저 끝나면 False."""
    end = time.monotonic() + timeout
    headers = {"X-PL-Token": token} if token else {}
    req = urllib.request.Request(url + "/health", headers=headers)
    while time.monotonic() < end:
        if proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(req, timeout=2) as r:
                if r.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.5)
    return False


def start_engine(port: int, token: str) -> subprocess.Popen:
    """엔진 서버(server.py, 화면 없음)를 이 PC 안에서만 띄운다."""
    env = dict(os.environ, PL_SERVE_FRONT="0", PL_CORS_ORIGINS="", HOST="127.0.0.1", PORT=str(port),
               PL_GATEWAY_TOKEN=token)
    return subprocess.Popen([sys.executable, str(ROOT / "server.py")], env=env)


def stop(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> int:
    args = set(sys.argv[1:])
    code = run_checks(args)
    if code:
        return code

    if "--check" in args or "--samples" in args:
        print("\n점검 완료.")
        return 0

    host = os.environ.get("HOST", "127.0.0.1")
    print()
    try:
        port = pick_port(int(os.environ.get("PORT", 8000)), host, "화면·API")
        # 엔진은 PL_ENGINE_PORT, 없으면 게이트웨이 다음 번호부터
        engine_port = pick_port(int(os.environ.get("PL_ENGINE_PORT", port + 1)), "127.0.0.1", "엔진 서버", avoid={port})
    except SystemExit as exc:
        print(exc)
        return 1

    token = os.environ.get("PL_GATEWAY_TOKEN", "")
    engine_url = f"http://127.0.0.1:{engine_port}"
    print(f"\n엔진 서버를 띄우는 중... ({engine_url}, 이 PC 안에서만)")
    engine = start_engine(engine_port, token)
    try:
        if not wait_engine(engine, engine_url, token):
            print(f"{BAD} 엔진 서버가 뜨지 않았습니다. 위의 오류를 확인하세요.")
            return 1
        import run_gateway
        return run_gateway.main(["--host", host, "--port", str(port), "--backend", engine_url, "--token", token])
    except KeyboardInterrupt:
        return 0
    finally:
        stop(engine)


if __name__ == "__main__":
    raise SystemExit(main())
