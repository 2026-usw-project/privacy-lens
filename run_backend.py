"""엔진 서버(API, 화면 없음)를 띄운다. 보통 게이트웨이(run_gateway.py) 뒤에 둔다. 1 서버 1 엔진.

    python run_backend.py --host 0.0.0.0 --token <비밀값>  게이트웨이 뒤의 엔진 서버(기본 포트 8000)
    python run_backend.py --port 9000
    python run_backend.py --cors https://<화면 주소>         게이트웨이 없이 정적 화면이 바로 붙을 때(쉼표로 여러 개)
    python run_backend.py --check                          점검만

- 화면(/)은 내주지 않는다(PL_SERVE_FRONT=0). '/' 는 서비스 이름만, '/health' 는 살아 있는지.
- --token 을 주면 같은 비밀값을 가진 요청만 받는다. 생략하면 경고를 띄우고 연결을 받는다.
- 환경 점검은 run.py 와 같다(OCR·글꼴·모델).
- 포트가 쓰는 중이면 1 씩 올려 빈 포트로 연다. 바뀌면 게이트웨이의 --backend 주소도 그 번호로 준다.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))



def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Privacy Lens 백엔드(API)만 실행")
    ap.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    ap.add_argument("--cors", default=os.environ.get("PL_CORS_ORIGINS", ""),
                    help="게이트웨이 없이 브라우저가 바로 붙을 때 허용할 화면 주소(쉼표로 여러 개)")
    ap.add_argument("--check", action="store_true", help="점검만 하고 끝낸다")
    ap.add_argument("--token", default=os.environ.get("PL_GATEWAY_TOKEN", ""),
                    help="게이트웨이와 나눠 가진 비밀값. 주면 이 값을 가진 요청(게이트웨이)만 받는다")
    args = ap.parse_args(argv)

    from run import run_checks
    code = run_checks({"--check"} if args.check else set())
    if code or args.check:
        if not code:
            print("\n점검 완료.")
        return code

    from run import pick_port
    args.port = pick_port(args.port, args.host, "엔진 서버")   # 쓰는 중이면 1 씩 올려 빈 포트로
    env = dict(os.environ, PL_SERVE_FRONT="0", PL_CORS_ORIGINS=args.cors, HOST=args.host, PORT=str(args.port),
               PL_GATEWAY_TOKEN=args.token)
    if args.token:
        print("\n게이트웨이 전용 엔진: X-PL-Token 이 맞는 요청만 받습니다.")
    else:
        print("\n[경고] 엔진 토큰이 설정되지 않았습니다. 엔진 주소에 접근할 수 있는 요청을 모두 받습니다. 인터넷에 열지 마세요.")
    print(f"\n엔진 API: http://{args.host}:{args.port}   (화면 없음)")
    if args.cors:
        print(f"허용하는 화면 주소: {args.cors}")
    print("화면·대기열은 게이트웨이에서:  python run_gateway.py --backend http://<이 PC>:" + str(args.port)
          + (" --token <같은 비밀값>" if args.token else "") + "\n")
    try:
        subprocess.run([sys.executable, str(ROOT / "server.py")], env=env, check=False)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
