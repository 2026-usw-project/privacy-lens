"""백엔드(API)만 띄운다. 화면은 run_frontend.py 로 따로 띄운다.

    python run_backend.py                                  점검 후 API 실행(http://127.0.0.1:8000)
    python run_backend.py --port 9000
    python run_backend.py --host 0.0.0.0                   다른 기기에서 접속(같은 네트워크)
    python run_backend.py --cors http://192.168.0.10:8080  화면 서버 주소(여러 개면 쉼표)
    python run_backend.py --check                          점검만

- 화면(/)은 내주지 않는다(PL_SERVE_FRONT=0). '/' 는 서비스 이름만, '/health' 는 살아 있는지.
- 화면 서버 주소에서 오는 요청만 허용한다(PL_CORS_ORIGINS). 기본은 이 컴퓨터의 8080 번 화면 서버.
- 환경 점검은 run.py 와 같다(OCR·글꼴·모델).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

DEFAULT_CORS = "http://127.0.0.1:8080,http://localhost:8080"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Privacy Lens 백엔드(API)만 실행")
    ap.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    ap.add_argument("--cors", default=os.environ.get("PL_CORS_ORIGINS", DEFAULT_CORS),
                    help="요청을 허용할 화면 주소(쉼표로 여러 개)")
    ap.add_argument("--check", action="store_true", help="점검만 하고 끝낸다")
    args = ap.parse_args(argv)

    from run import run_checks
    code = run_checks({"--check"} if args.check else set())
    if code or args.check:
        if not code:
            print("\n점검 완료.")
        return code

    env = dict(os.environ, PL_SERVE_FRONT="0", PL_CORS_ORIGINS=args.cors, HOST=args.host, PORT=str(args.port))
    print(f"\nAPI: http://{args.host}:{args.port}   (화면 없음)")
    print(f"허용하는 화면 주소: {args.cors}")
    print("화면은 다른 창에서:  python run_frontend.py --api http://127.0.0.1:" + str(args.port) + "\n")
    try:
        subprocess.run([sys.executable, str(ROOT / "server.py")], env=env, check=False)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
