"""OCR 작업자 수에 따른 처리량 실험.

지금 서버는 PaddleOCR 엔진 하나를 전용 스레드 하나에 고정하고 요청을 줄 세운다
(DEVELOPMENT.md 버그 17, '서버 동시 요청 오류 대응'). 엔진을 여러 개 띄우면 동시에
몇 장을 처리할 수 있는지, 그 대가(메모리·준비 시간·한 장의 지연)가 얼마인지 잰다.

  작업자 = 엔진을 하나씩 가진 별도 프로세스. 엔진 하나를 나눠 쓰지 않는다(스레드 안전하지 않음).
  스레드 = 엔진 하나가 쓰는 CPU 스레드(cpu_threads, PaddleOCR 기본 10). PL_PADDLE_THREADS 로 넘긴다.

    python -m eval.workers                         # 기본 조합
    python -m eval.workers --configs 1x10 2x8 4x4  # 작업자x스레드
    python -m eval.workers --repeat 4 --scale 3    # 사진을 3배로 키워(≈10MP) 휴대폰 사진에 가깝게

사진은 samples/out 의 합성 송장(가상 정보)만 쓴다. OCR(판단 제외) 시간만 잰다.
결과는 표로 찍고 --json 으로 저장할 수 있다. 숫자는 이 컴퓨터·이 사진 기준이다.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import platform
import statistics
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIGS = ["1x10", "1x16", "2x8", "2x10", "3x5", "4x4", "4x10"]


# ------------------------------------------------------------------ 작업자(별도 프로세스)

def _worker(threads: int, jobs, results, ready, go, scale: float) -> None:
    os.environ["PL_PADDLE_THREADS"] = str(threads)
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    sys.path.insert(0, str(ROOT))
    import io
    import contextlib

    from PIL import Image

    started = time.perf_counter()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        from pipeline import ocr
        backend = ocr.PaddleBackend()
    load_s = time.perf_counter() - started

    def open_image(path: str) -> Image.Image:
        img = Image.open(path).convert("RGB")
        if scale != 1.0:
            img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
        return img

    # 첫 추론은 그래프 준비로 느리다. 재지 않는다
    warm = time.perf_counter()
    backend.read(open_image(str(ROOT / "samples" / "out" / "waybill_0_flat.png")))
    warm_s = time.perf_counter() - warm
    ready.put({"pid": os.getpid(), "load_s": load_s, "warm_s": warm_s})
    go.wait()

    while True:
        path = jobs.get()
        if path is None:
            break
        img = open_image(path)
        t0 = time.perf_counter()
        try:
            spans = backend.read(img)
        except Exception as exc:  # 엔진이 죽어도 실험은 멈추지 않고 결과에 남긴다
            results.put({"pid": os.getpid(), "error": type(exc).__name__})
            continue
        results.put({"pid": os.getpid(), "latency_s": time.perf_counter() - t0, "spans": len(spans),
                     "megapixels": img.width * img.height / 1e6})


# ------------------------------------------------------------------ 한 조합

def _rss_gb(pids: list[int]) -> float:
    import psutil
    total = 0
    for pid in pids:
        try:
            total += psutil.Process(pid).memory_info().rss
        except psutil.Error:
            pass
    return total / 2**30


def run_config(workers: int, threads: int, images: list[str], scale: float) -> dict:
    import psutil

    ctx = mp.get_context("spawn")
    jobs, results, ready = ctx.Queue(), ctx.Queue(), ctx.Queue()
    go = ctx.Event()
    procs = [ctx.Process(target=_worker, args=(threads, jobs, results, ready, go, scale), daemon=True)
             for _ in range(workers)]
    t_load = time.perf_counter()
    for p in procs:
        p.start()
    infos = [ready.get(timeout=600) for _ in procs]
    all_ready_s = time.perf_counter() - t_load
    pids = [i["pid"] for i in infos]
    rss_idle = _rss_gb(pids)

    for path in images:
        jobs.put(path)
    for _ in procs:
        jobs.put(None)

    # 도는 동안 CPU 사용률과 메모리 최대치를 잰다
    cpu_samples: list[float] = []
    peak = [rss_idle]
    stop = threading.Event()

    def sample() -> None:
        psutil.cpu_percent(None)
        while not stop.wait(0.5):
            cpu_samples.append(psutil.cpu_percent(None))
            peak[0] = max(peak[0], _rss_gb(pids))

    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    t0 = time.perf_counter()
    go.set()
    done = [results.get(timeout=1800) for _ in images]
    wall = time.perf_counter() - t0
    stop.set()
    sampler.join()
    for p in procs:
        p.join(timeout=60)

    errors = [d["error"] for d in done if "error" in d]
    done = [d for d in done if "error" not in d]
    if not done:
        return {"workers": workers, "threads": threads, "images": len(images), "errors": errors,
                "ready_s": round(all_ready_s, 1), "rss_idle_gb": round(rss_idle, 2), "rss_peak_gb": round(peak[0], 2)}
    lat = sorted(d["latency_s"] for d in done)
    return {
        "workers": workers, "threads": threads, "images": len(images), "errors": errors,
        "wall_s": round(wall, 2),
        "images_per_min": round(len(images) / wall * 60, 1),
        "latency_mean_s": round(statistics.mean(lat), 2),
        "latency_p95_s": round(lat[min(len(lat) - 1, int(0.95 * len(lat)))], 2),
        "ready_s": round(all_ready_s, 1),
        "load_s_max": round(max(i["load_s"] for i in infos), 1),
        "rss_idle_gb": round(rss_idle, 2),
        "rss_peak_gb": round(peak[0], 2),
        "cpu_mean_pct": round(statistics.mean(cpu_samples), 0) if cpu_samples else None,
        "megapixels_mean": round(statistics.mean(d["megapixels"] for d in done), 2),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--configs", nargs="+", default=DEFAULT_CONFIGS, help="작업자x스레드, 예: 2x8")
    ap.add_argument("--repeat", type=int, default=4, help="samples/out 6장을 몇 번 돌릴지")
    ap.add_argument("--scale", type=float, default=1.0, help="사진 확대 배율(3 이면 약 10MP)")
    ap.add_argument("--json", type=Path, help="결과를 저장할 파일")
    args = ap.parse_args(argv)

    import psutil

    images = sorted(str(p) for p in (ROOT / "samples" / "out").glob("*.png")) * args.repeat
    if not images:
        print("samples/out 에 사진이 없습니다. python samples/make_sample.py samples/out", file=sys.stderr)
        return 1
    env = {"cpu": platform.processor(), "logical_cpus": os.cpu_count(),
           "physical_cpus": psutil.cpu_count(logical=False),
           "ram_gb": round(psutil.virtual_memory().total / 2**30, 1), "python": platform.python_version()}
    print(f"# {env}  사진 {len(images)}장 · 배율 {args.scale}")
    head = ("작업자", "스레드", "총 시간", "장/분", "한 장 평균", "한 장 p95", "준비", "메모리(대기)", "메모리(최대)", "CPU%")
    print(" | ".join(head))
    rows = []
    for cfg in args.configs:
        w, t = (int(x) for x in cfg.lower().split("x"))
        r = run_config(w, t, images, args.scale)
        rows.append(r)
        if "wall_s" not in r:
            print(f'{r["workers"]} | {r["threads"]} | 모두 실패: {", ".join(sorted(set(r["errors"])))} '
                  f'({len(r["errors"])}장, 메모리 최대 {r["rss_peak_gb"]}GB)', flush=True)
            continue
        note = f' (실패 {len(r["errors"])}장: {", ".join(sorted(set(r["errors"])))})' if r["errors"] else ""
        print(" | ".join(str(v) for v in (r["workers"], r["threads"], f'{r["wall_s"]}s', r["images_per_min"],
                                           f'{r["latency_mean_s"]}s', f'{r["latency_p95_s"]}s', f'{r["ready_s"]}s',
                                           f'{r["rss_idle_gb"]}GB', f'{r["rss_peak_gb"]}GB', r["cpu_mean_pct"])) + note,
              flush=True)
    if args.json:
        args.json.write_text(json.dumps({"env": env, "scale": args.scale, "rows": rows}, ensure_ascii=False, indent=1),
                             encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
