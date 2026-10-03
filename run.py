"""환경을 점검하고 서버를 띄운다. Windows / macOS / Linux 공통.

    python run.py            점검 후 서버 실행
    python run.py --check    점검만
    python run.py --samples  샘플만 생성

에러가 난 뒤에 원인을 찾는 것보다, 시작하기 전에 뭐가 없는지 알려주는 편이 낫다.
"""

from __future__ import annotations

import subprocess
import sys
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


def main() -> int:
    args = set(sys.argv[1:])

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

    make_samples(force="--samples" in args)

    if not ocr_ok:
        print("\nOCR 없이는 탐지가 동작하지 않습니다. 위 안내대로 설치한 뒤 다시 실행하세요.")
        print("EXIF·QR 검사만 먼저 보려면  PL_OCR=none  으로 실행할 수 있습니다.")
        return 1

    if "--check" in args or "--samples" in args:
        print("\n점검 완료.")
        return 0

    print("\n서버를 시작합니다 — http://127.0.0.1:8000  (Ctrl+C 로 종료)\n")
    try:
        subprocess.run([sys.executable, str(ROOT / "server.py")], check=False)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
