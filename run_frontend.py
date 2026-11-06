"""화면만 띄운다. API 는 run_backend.py 로 따로 띄운다. 파이썬 기본 기능만 써서 OCR·패키지 설치가 필요 없다.

    python run_frontend.py                                     http://127.0.0.1:8080, API http://127.0.0.1:8000
    python run_frontend.py --api http://192.168.0.20:8000      다른 컴퓨터의 API 쓰기
    python run_frontend.py --host 0.0.0.0 --port 8080          다른 기기에서 화면 접속

- 화면 파일은 web/frontend-demo/privacy-lens.html(빌드 결과). 고쳤으면 먼저 node scripts/build.mjs.
- 페이지에 API 주소(globalThis.PRIVACY_LENS_API)를 넣어 준다. 화면은 그 주소로 요청한다.
- 백엔드는 이 화면 주소를 허용해야 한다(run_backend.py --cors, 기본은 이 컴퓨터의 8080).
- PC 웹캠은 https 또는 localhost 에서만 켜진다. 다른 기기에서 http://IP:8080 으로 접속하면 파일 고르기로 넘어간다.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import urllib.error
import urllib.parse
import urllib.request
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FRONT = Path(__file__).resolve().parent / "web" / "frontend-demo"
PAGE = FRONT / "privacy-lens.html"
FONTS = FRONT / "dist" / "fonts"
mimetypes.add_type("font/woff2", ".woff2")


def api_origin(raw: str) -> str:
    """http(s) 주소만. 끝의 / 는 뗀다."""
    parts = urllib.parse.urlsplit(raw.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError(f"API 주소는 http:// 또는 https:// 로 시작해야 합니다: {raw!r}")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def page_with_api(html: str, api: str) -> str:
    """<head> 바로 뒤에 API 주소를 넣는다. 화면 스크립트보다 먼저 실행된다."""
    value = json.dumps(api).replace("</", "<\\/")
    tag = f"<script>globalThis.PRIVACY_LENS_API={value};</script>"
    return html.replace("<head>", "<head>\n" + tag, 1) if "<head>" in html else tag + html


class Handler(BaseHTTPRequestHandler):
    server_version = "PrivacyLensFront"

    def __init__(self, *args, api: str, **kwargs):
        self.api = api
        super().__init__(*args, **kwargs)

    def log_message(self, fmt, *args):  # 접근 로그는 남기지 않는다(서버와 같은 원칙)
        pass

    def _send(self, status: int, body: bytes, ctype: str, cache: str = "no-store") -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path in ("/", "/index.html"):
            if not PAGE.exists():
                self._send(500, "privacy-lens.html 이 없습니다. web/frontend-demo 에서 node scripts/build.mjs".encode(),
                           "text/plain; charset=utf-8")
                return
            body = page_with_api(PAGE.read_text(encoding="utf-8"), self.api).encode("utf-8")
            self._send(200, body, "text/html; charset=utf-8")
            return
        if path.startswith("/dist/fonts/"):
            target = (FONTS / urllib.parse.unquote(path[len("/dist/fonts/"):])).resolve()
            if target.parent == FONTS.resolve() and target.is_file():
                ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                self._send(200, target.read_bytes(), ctype, cache="public, max-age=86400")
                return
        self._send(404, b"not found", "text/plain; charset=utf-8")


def check_api(api: str) -> None:
    try:
        with urllib.request.urlopen(api + "/health", timeout=3) as res:
            data = json.loads(res.read().decode("utf-8"))
        print(f"  [OK] API 응답 — {api}" + ("" if data.get("engine_ready") else " (OCR 엔진 준비 중)"))
    except (urllib.error.URLError, OSError, ValueError):
        print(f"  [경고] API 에 연결하지 못했습니다 — {api}. 다른 창에서  python run_backend.py  를 먼저 실행하세요.")


def make_server(host: str, port: int, api: str) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), partial(Handler, api=api))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Privacy Lens 화면만 실행")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--api", default="http://127.0.0.1:8000", help="백엔드(API) 주소")
    args = ap.parse_args(argv)
    try:
        api = api_origin(args.api)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2

    print("\nPrivacy Lens — 화면 서버\n")
    check_api(api)
    shown = "127.0.0.1" if args.host in ("0.0.0.0", "") else args.host
    print(f"\n화면: http://{shown}:{args.port}   →  API: {api}")
    print(f"백엔드가 이 주소를 허용해야 합니다:  python run_backend.py --cors http://{shown}:{args.port}\n")
    server = make_server(args.host, args.port, api)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
