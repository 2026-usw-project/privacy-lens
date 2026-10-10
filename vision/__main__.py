"""YOLO 지속 학습 명령.

  python -m vision init     --root <작업폴더>   폴더 구조 만들기 (처음 한 번)
  python -m vision ingest   --root <작업폴더>   inbox 새 사진 → 정리 + 초벌 라벨 → review
  (라벨링 도구 vision/label_tool.html 로 review 폴더를 열어 검수)
  python -m vision build    --root <작업폴더>   검수 끝난 사진 → dataset
  python -m vision train    --root <작업폴더>   학습 → 더 나으면 current 교체
  python -m vision status   --root <작업폴더>   현황
  python -m vision synth    --root <작업폴더>   합성 사진으로 학습 데이터 채우기(첫 모델용)
  python -m vision predict  --root <작업폴더> 사진.jpg   current 모델로 시험 삼아 검출

--root 대신 환경변수 PL_YOLO_ROOT 를 써도 됩니다.
"""

from __future__ import annotations

import argparse
import sys

from .workspace import Workspace


def main(argv: list[str] | None = None) -> None:
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        try:  # Windows 콘솔 한글
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    ap = argparse.ArgumentParser(prog="python -m vision", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", help="작업 폴더 (기본: 환경변수 PL_YOLO_ROOT)")
    common.add_argument("--who", default="", help="실행한 사람 (잠금·학습 기록용)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    add = lambda name: sub.add_parser(name, parents=[common])

    add("init")
    p = add("ingest")
    p.add_argument("--keep", action="store_true", help="inbox 원본을 지우지 않음")
    p.add_argument("--no-prelabel", action="store_true", help="초벌 라벨 없이 넣기")
    add("build")
    add("status")
    p = add("train")
    p.add_argument("--epochs", type=int, default=60)
    p.add_argument("--imgsz", type=int, default=1280)
    p.add_argument("--batch", type=int, default=-1, help="-1 = GPU 메모리에 맞춰 자동")
    p.add_argument("--base", help="시작 가중치 (기본: current 모델, 없으면 yolo11n.pt)")
    p.add_argument("--device", help="0 = 첫 GPU, cpu = CPU (기본: 자동)")
    p.add_argument("--force", action="store_true", help="점수가 낮아도 current 로 교체")
    p.add_argument("--no-copy", action="store_true", help="로컬 디스크로 복사하지 않고 학습")
    p = add("synth")
    p.add_argument("--n", type=int, default=200)
    p.add_argument("--seed", type=int, default=0)
    p = add("predict")
    p.add_argument("images", nargs="+")
    p.add_argument("--conf", type=float, default=0.25)

    a = ap.parse_args(argv)
    ws = Workspace(a.root)
    if a.cmd in ("ingest", "build", "train", "synth"):
        ws.root.mkdir(parents=True, exist_ok=True)
        with ws.lock(a.who):
            _run(a, ws)
    else:
        _run(a, ws)


def _run(a, ws: Workspace) -> None:
    if a.cmd == "init":
        ws.init()
        print(f"작업 폴더 준비 완료: {ws.root}")
    elif a.cmd == "ingest":
        from . import ingest
        ingest.run(ws, keep_originals=a.keep, prelabel=not a.no_prelabel)
    elif a.cmd == "build":
        from . import build
        build.run(ws)
    elif a.cmd == "status":
        from . import build
        ws.init()
        build.status(ws)
    elif a.cmd == "train":
        from . import train
        train.run(ws, epochs=a.epochs, imgsz=a.imgsz, batch=a.batch, base=a.base,
                  device=a.device, who=a.who, force_promote=a.force,
                  copy_local=False if a.no_copy else None)
    elif a.cmd == "synth":
        from . import synth
        synth.run(ws, n=a.n, seed=a.seed)
    elif a.cmd == "predict":
        weights = ws.current_model()
        if not weights:
            raise SystemExit("아직 current 모델이 없습니다.")
        from ultralytics import YOLO
        from .classes import LABELS_KO
        m = YOLO(str(weights))
        for path in a.images:
            r = m.predict(path, conf=a.conf, imgsz=ws.model_imgsz(), verbose=False)[0]
            print(f"{path}: {len(r.boxes)}개")
            for c, conf, xyxy in zip(r.boxes.cls.tolist(), r.boxes.conf.tolist(), r.boxes.xyxy.tolist()):
                print(f"  {LABELS_KO.get(int(c), c):<8} {conf:.2f}  {[round(v) for v in xyxy]}")


if __name__ == "__main__":
    main()
