"""게이트웨이(화면 + 대기열 + 분산 + 상태 확인)를 띄운다. 엔진 서버(run_backend.py)는 PC 마다 따로 띄운다.

    # 엔진 PC 마다(1 서버 1 엔진)
    python run_backend.py --host 0.0.0.0 --token <비밀값>
    # 게이트웨이 PC
    python run_gateway.py --host 0.0.0.0 --backend http://192.168.0.21:8000 --backend http://192.168.0.22:8000 --token <비밀값>

- 화면은 게이트웨이 주소(기본 http://127.0.0.1:8080)에서 나온다. API 도 같은 주소라 CORS 가 필요 없다.
- 화면을 정적 호스팅에 따로 올리면 --no-front 로 API 만 띄우고 --cors 에 화면 주소를 준다.
- 엔진 서버 목록은 --backend 를 여러 번, 또는 PL_BACKENDS=주소,주소. 비밀값은 --token 또는 PL_GATEWAY_TOKEN.
- 게이트웨이는 OCR·모델이 필요 없다(fastapi·uvicorn·httpx 만).
- 엔진 목록 관리(화면의 '엔진 N대'): 관리 키가 있어야 한다. --admin-key 또는 PL_ADMIN_KEY, 없으면 켤 때마다 새로 만들어 콘솔에 보여 준다.
- 포트(--port, 기본 8080)가 쓰는 중이면 1 씩 올려 빈 포트로 연다.
- https: 인증서가 있으면 --ssl-cert/--ssl-key 로 직접 연다. 도메인이 있으면 앞에 Caddy(deploy/Caddyfile)를 두는 편이 쉽다.
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
import urllib.parse


def _url(raw: str) -> str:
    p = urllib.parse.urlsplit(raw.strip())
    if p.scheme not in ("http", "https") or not p.netloc:
        raise SystemExit(f"엔진 주소는 http:// 또는 https:// 로 시작해야 합니다: {raw!r}")
    return f"{p.scheme}://{p.netloc}{p.path.rstrip('/')}"


def ssl_files(cert: str, key: str) -> dict:
    """uvicorn 에 넘길 인증서 옵션. 둘 다 없으면 http, 하나만 있거나 파일이 없으면 멈춘다."""
    if not cert and not key:
        return {}
    if not (cert and key):
        raise SystemExit("--ssl-cert 와 --ssl-key 는 함께 줘야 합니다.")
    for p in (cert, key):
        if not os.path.isfile(p):
            raise SystemExit(f"인증서 파일이 없습니다: {p}")
    return {"ssl_certfile": cert, "ssl_keyfile": key}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Privacy Lens 게이트웨이(화면 + 대기열 + 분산)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--backend", action="append", default=[], help="엔진 서버 주소(여러 번)")
    ap.add_argument("--token", default=os.environ.get("PL_GATEWAY_TOKEN", ""), help="엔진과 나눠 가진 비밀값")
    ap.add_argument("--queue-max", type=int, default=int(os.environ.get("PL_GATEWAY_QUEUE_MAX", 24)))
    ap.add_argument("--no-front", action="store_true", help="화면을 내주지 않는다(정적 호스팅에 따로 올릴 때)")
    ap.add_argument("--cors", default="", help="--no-front 일 때 요청을 허용할 화면 주소(쉼표)")
    ap.add_argument("--ssl-cert", default=os.environ.get("PL_SSL_CERT", ""), help="https 인증서(PEM)")
    ap.add_argument("--ssl-key", default=os.environ.get("PL_SSL_KEY", ""), help="https 개인 키(PEM)")
    ap.add_argument("--admin-key", default=os.environ.get("PL_ADMIN_KEY", ""),
                    help="화면에서 엔진을 더하고 뺄 때 쓰는 관리 키. 없으면 켤 때마다 새로 만든다")
    args = ap.parse_args(argv)
    tls = ssl_files(args.ssl_cert, args.ssl_key)
    from run import pick_port
    args.port = pick_port(args.port, args.host, "게이트웨이")   # 쓰는 중이면 1 씩 올려 빈 포트로

    backends = [_url(u) for u in (args.backend or os.environ.get("PL_BACKENDS", "").split(",")) if u.strip()]
    if not backends:
        print("엔진 서버 주소가 필요합니다:  --backend http://127.0.0.1:8000", file=sys.stderr)
        return 2
    if not args.token:
        print("[경고] --token 이 없습니다. 엔진 서버에 아무나 직접 요청할 수 있습니다(같은 컴퓨터 시험용으로만).")

    import uvicorn
    from fastapi.middleware.cors import CORSMiddleware

    from gateway import create_app

    admin_key, generated = args.admin_key, not args.admin_key
    if generated:
        admin_key = secrets.token_urlsafe(18)
    app = create_app(backends, token=args.token, serve_front=not args.no_front, max_waiting=args.queue_max,
                     admin_key=admin_key)
    origins = [o.strip().rstrip("/") for o in args.cors.split(",") if o.strip()]
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"],
                           allow_headers=["*"], allow_credentials=False, max_age=600)

    shown = "127.0.0.1" if args.host in ("0.0.0.0", "") else args.host
    print("\nPrivacy Lens — 게이트웨이\n")
    scheme = "https" if tls else "http"
    print(f"화면·API: {scheme}://{shown}:{args.port}" + ("  (API 만)" if args.no_front else ""))
    for b in backends:
        print(f"  엔진: {b}")
    if generated:
        # 콘솔에만 보여 준다(파일·로그에 따로 남기지 않음). 매번 같은 키를 쓰려면 PL_ADMIN_KEY 를 정해 둔다
        print(f"\n엔진 관리 키(이번 실행에만): {admin_key}")
        print("  화면 오른쪽 위 '엔진 N대'를 눌러 엔진을 더하거나 뺄 때 입력합니다.")
    else:
        print("\n엔진 관리 키: --admin-key / PL_ADMIN_KEY 로 정한 값")
    print()
    uvicorn.run(app, host=args.host, port=args.port, access_log=False, **tls)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
