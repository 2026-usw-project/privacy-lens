"""집 PC(그래픽카드)에서 Colab 과 같은 학습을 돌린다 — Colab 무료 GPU 한도가 모자랄 때.

    python -m vision.pc_train check                      # 경로·GPU·드라이브 확인만
    python -m vision.pc_train face_eval                  # 증명사진: YuNet vs face_photo_v002
    python -m vision.pc_train plate                      # 번호판 v004 학습 + 평가
    python -m vision.pc_train daily                      # 일상 사진 9종: (zip 없으면 합치기) + 학습
    python -m vision.pc_train all                        # 위 셋을 차례로

경로는 환경 변수로 준다(설명: docs/PC_TRAIN.md).
    PL_DRIVE   구글 드라이브 데스크톱의 팀 폴더 (예: G:/내 드라이브/PrivacyLens-YOLO)
    PL_WORK    큰 임시 파일 폴더, 여유 50GB 이상 (예: D:/pl_work)
    PL_BATCH   배치(기본 16). 낮추면 그래픽카드 메모리·부하가 준다
    PL_GPU_MAX_TEMP  이 온도(°C, 기본 80)를 넘으면 식을 때까지(−8°C) 학습을 잠깐 멈춘다

학습 기록은 드라이브 objects/runs/ 에 남아 Colab 과 PC 를 오가며 이어서 할 수 있다.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

MAX_TEMP = int(os.environ.get("PL_GPU_MAX_TEMP", "80"))
CHECK_EVERY = 50   # 배치마다 nvidia-smi 를 부르면 느리므로 50 배치마다


def gpu_temp() -> int | None:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout.strip().splitlines()
        return int(out[0]) if out else None
    except Exception:
        return None


def make_guard(max_temp: int = MAX_TEMP, read=gpu_temp, sleep=time.sleep):
    """학습 콜백: 온도가 max_temp 이상이면 max_temp-8 이하가 될 때까지 쉰다."""
    state = {"n": 0}

    def on_batch_end(trainer=None):
        state["n"] += 1
        if state["n"] % CHECK_EVERY:
            return
        t = read()
        if t is None or t < max_temp:
            return
        print(f"\n그래픽카드 {t}°C — {max_temp - 8}°C 까지 잠깐 쉼", flush=True)
        while t is not None and t > max_temp - 8:
            sleep(20)
            t = read()
    return on_batch_end


def check() -> dict:
    import torch
    from vision import next_steps as ns
    info = {"드라이브": str(ns.ROOT), "드라이브 있음": ns.ROOT.exists(), "작업 폴더": str(ns.WORK),
            "GPU": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "없음(CPU)",
            "온도": gpu_temp(), "배치": ns.BATCH, "온도 한계": MAX_TEMP,
            "학습 기록": sorted(p.name for p in (ns.OUT / "runs").glob("*")) if (ns.OUT / "runs").exists() else []}
    for k, v in info.items():
        print(f"{k:>8}: {v}")
    if not info["드라이브 있음"]:
        print("\nPL_DRIVE 가 팀 폴더를 가리키지 않습니다. docs/PC_TRAIN.md 2단계를 보세요.")
    return info


def main(argv: list[str]) -> None:
    from vision import next_steps as ns
    ns.WORK.mkdir(parents=True, exist_ok=True)
    ns.TRAIN_CALLBACKS.append(("on_train_batch_end", make_guard()))
    step = argv[0] if argv else "check"
    if step == "check":
        check()
    if step in ("face_eval", "all"):
        ns.eval_face_photo()
    if step in ("plate", "all"):
        ns.train_plate_rot(epochs=20)
        ns.eval_plate()
    if step in ("daily", "all"):
        if not ns.DAILY_ZIP.exists():
            ns.build_daily()
        ns.train_daily(epochs=30)


if __name__ == "__main__":   # Windows 는 데이터 로더가 새 프로세스를 띄우므로 이 보호가 꼭 필요하다
    main(sys.argv[1:])
