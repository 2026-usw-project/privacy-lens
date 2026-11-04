"""Colab 한 칸짜리 단계들 — vision/colab_next.ipynb 가 부른다.

노트북 상태(앞 칸 변수)에 기대지 않게, 단계마다 필요한 것을 스스로 만들거나 드라이브에서 읽는다.
런타임이 끊겨도(무료 Colab 은 약 4시간) 칸 하나만 다시 돌리면 이어진다.

    midv_dataset()   MIDV-2020 photo 받기(FTP, CC BY-SA 2.5) → 증명사진 YOLO 데이터(CPU 로 됨)
    train_face_photo()  YOLO26n 증명사진 학습(GPU) → 드라이브 objects/face_photo_vNNN/
    eval_face_photo()   YuNet(서비스) vs 학습 모델, 처음 보는 신분증 종류에서 크기·방향별
    plate_data()     Open Images 번호판·한국 번호판 zip·합성 사진 준비(CPU)
    train_plate_rot()   v003 에서 이어 학습 + 90도 회전 사본(GPU) → objects/plate_v004/
    eval_plate()     공개·v003·v004 를 한국(방향별)·해외, 돌려 찾기 켬/끔으로
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(os.environ.get("PL_DRIVE", "/content/drive/MyDrive/PrivacyLens-YOLO"))
OUT = ROOT / "objects"
MIDV = Path("/content/midv")
FP_DS = Path("/content/fp_ds")
OI = Path("/content/oi")
KR = Path("/content/kr")
SYNTH = Path("/content/plate_synth")
ROT = Path("/content/plate_rot")
KR_ZIPS = {"kr_eval": "Korea Car License Plate*.zip", "kr_train1": "license-plate-label*.zip",
           "kr_train2": "korea car plat*.zip"}


def _next_version(prefix: str) -> Path:
    """가장 큰 번호 + 1 (plate_v003 이 있으면 plate_v004)."""
    nums = [int(p.name.rsplit("_v", 1)[1]) for p in OUT.glob(f"{prefix}_v[0-9][0-9][0-9]")]
    return OUT / f"{prefix}_v{max(nums, default=0) + 1:03d}"


def _save_json(name: str, data) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / name
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    print("저장:", p)
    return p


# ------------------------------------------------------------------ 증명사진

def midv_dataset(*, backgrounds: str | None = None) -> dict:
    from vision import face_photo_data as fpd
    if not (MIDV / "annotations").exists():
        MIDV.mkdir(parents=True, exist_ok=True)
        print("MIDV-2020 photo.tar 받는 중(4GB, 3~5분)…", flush=True)
        subprocess.run(f"curl -s ftp://smartengines.com/midv-2020/dataset/photo.tar | tar x -C {MIDV}",
                       shell=True, check=True)
    if (FP_DS / "data.yaml").exists():
        print("이미 있음:", FP_DS)
        return {}
    bg = backgrounds or (str(OI / "plate" / "images") if (OI / "plate" / "images").exists() else None)
    c = fpd.build(MIDV, FP_DS, backgrounds=Path(bg) if bg else None)
    print("증명사진 데이터", c, "배경:", bg or "잡음")
    return c


def resumable_train(base: str, *, data: str, name: str, epochs: int, **kw) -> Path:
    """학습 기록을 드라이브(objects/runs/<name>)에 두고, 끊겼으면 last.pt 부터 이어서 학습한다.

    무료 Colab 은 런타임이 끊기면 /content 가 지워진다(2026-11-04 증명사진 35/40 epoch 에서 잃음).
    다 끝난 학습은 DONE 표시가 있어 다시 돌리지 않는다. 반환: 마지막 가중치(last.pt)."""
    from ultralytics import YOLO
    run = OUT / "runs" / name
    last = run / "weights" / "last.pt"
    if (run / "DONE").exists():
        print("이미 끝난 학습:", run)
        return last
    if last.exists():
        print("이어서 학습:", last, flush=True)
        YOLO(str(last)).train(resume=True)
    else:
        YOLO(base).train(data=data, epochs=epochs, imgsz=640, batch=16, workers=2, project=str(OUT / "runs"),
                         name=name, exist_ok=True, patience=0, verbose=False, plots=False, **kw)
    (run / "DONE").write_text("ok")
    return last


def train_face_photo(*, epochs: int = 40, base: str = "yolo26n.pt") -> Path:
    from ultralytics import YOLO
    done = sorted(OUT.glob("face_photo_v[0-9][0-9][0-9]/best.onnx"))
    if done and (OUT / "runs" / "face_photo" / "DONE").exists():
        print("이미 있음:", done[-1])
        return done[-1]
    midv_dataset()
    last = resumable_train(base, data=str(FP_DS / "data.yaml"), name="face_photo", epochs=epochs)
    YOLO(str(last)).export(format="onnx", imgsz=640)
    dst = _next_version("face_photo")
    dst.mkdir(parents=True)
    shutil.copy(last, dst / "best.pt")
    shutil.copy(last.with_suffix(".onnx"), dst / "best.onnx")
    print("저장:", dst)
    return dst / "best.onnx"


def eval_face_photo(model: str | None = None, *, limit: int | None = None) -> dict:
    """처음 보는 신분증 종류(검증 종류)에서 YuNet 끔/켬 vs 학습 모델."""
    from pipeline.objects import MODELS, YUNET_FILE, FaceDetector, download_yunet
    from vision import face_photo_data as fpd
    midv_dataset()
    if not (MODELS / YUNET_FILE).exists():
        download_yunet()
    models = {"YuNet": FaceDetector(MODELS / YUNET_FILE, score=0.3, rotations=(0,)),
              "YuNet+돌려찾기": FaceDetector(MODELS / YUNET_FILE, score=0.3, rotations=(0, 90, 270))}
    if model is None:
        found = sorted(glob.glob(str(OUT / "face_photo_v*/best.onnx")))
        model = found[-1] if found else None
    if model:
        models[f"YOLO({Path(model).parent.name})"] = fpd.YoloBoxes(model)
    res = fpd.evaluate_models(MIDV, models, limit=limit)
    for k, rows in res.items():
        r = {x["thr"]: x for x in rows}
        print(f"{k:<40}", "  ".join(f"{t}: R{r[t]['recall']} P{r[t]['precision']}" for t in (0.4, 0.6) if t in r))
    _save_json("eval_face_photo.json", res)
    return res


# ------------------------------------------------------------------ 번호판

def export_oi(cls: str, split: str, n: int, name: str) -> int:
    import fiftyone as fo
    import fiftyone.zoo as foz
    ds = foz.load_zoo_dataset("open-images-v7", split=split, label_types=["detections"], classes=[cls],
                              max_samples=n, only_matching=True, seed=0, shuffle=True,
                              dataset_name=f"{name}-{split}-{n}")
    ds.export(export_dir=str(OI / name), dataset_type=fo.types.YOLOv5Dataset, label_field="ground_truth",
              split="val" if split == "validation" else "train", classes=[cls])
    m = len(ds)
    ds.delete()
    return m


def unpack_kr() -> dict[str, Path | None]:
    out = {}
    for name, pattern in KR_ZIPS.items():
        found = sorted(glob.glob(str(OUT / "kr" / f"{name}.zip")) + glob.glob(str(OUT / "kr" / pattern)))
        if not found:
            print("없음:", name)
            out[name] = None
            continue
        d = KR / name
        if not d.exists():
            zipfile.ZipFile(found[0]).extractall(d)
            for lab in glob.glob(f"{d}/**/labels/*.txt", recursive=True):  # 모든 클래스 → 0(번호판)
                lines = [l.split() for l in open(lab).read().splitlines() if l.strip()]
                open(lab, "w").write("".join("0 " + " ".join(p[1:]) + "\n" for p in lines))
        out[name] = d
    return out


def plate_data(*, train_n: int = 2000, val_n: int = 300, rotate_frac: float = 0.3) -> dict:
    from vision import plate_synth as ps
    if not (OI / "plate" / "images" / "val").exists():
        print("번호판 검증", export_oi("Vehicle registration plate", "validation", val_n, "plate"), flush=True)
    if not (OI / "plate" / "images" / "train").exists():
        print("번호판 학습", export_oi("Vehicle registration plate", "test", train_n, "plate"), flush=True)
    kr = unpack_kr()
    trains = [p for d in (kr["kr_train1"], kr["kr_train2"]) if d for p in glob.glob(f"{d}/*/images")
              if "/test/" not in p + "/"]
    if not (SYNTH / "images" / "train").exists():
        crops = ps.collect_crops([kr["kr_train1"], kr["kr_train2"]])
        print("합성", ps.build(OI / "plate" / "images" / "train", crops, SYNTH, keep=0.2), flush=True)
    if not (ROT / "images" / "train").exists():
        n = ps.rotated_copies([OI / "plate" / "images" / "train", SYNTH / "images" / "train", *map(Path, trains)],
                              ROT, frac=rotate_frac)
        print("90도 회전 사본", n, flush=True)
    return {"kr": kr, "kr_trains": trains}


def train_plate_rot(*, epochs: int = 20, base: str | None = None) -> Path:
    from vision import plate_synth as ps
    info = plate_data()
    base = base or str(OUT / "plate_v003" / "best.pt")
    done = sorted(p.parent for p in OUT.glob("plate_v00[4-9]/best.onnx"))
    if done and (OUT / "runs" / "plate_rot" / "DONE").exists():
        print("이미 있음:", done[-1])
        return done[-1] / "best.onnx"
    dst = _next_version("plate")
    onnx = ps.train_next(base=base, oi_root=str(OI / "plate"), synth_root=str(SYNTH),
                         kr_dirs=[str(info["kr"]["kr_train1"]), str(info["kr"]["kr_train2"])],
                         out_dir=str(dst), epochs=epochs, name="plate_rot",
                         extra_train=[str(ROT / "images" / "train")], runs_root=True)
    print("저장:", onnx)
    return Path(onnx)


def eval_plate(models: dict[str, str] | None = None) -> dict:
    """한국(바로 선·누운 사진)·해외, 돌려 찾기 끔/켬."""
    from vision import objects_eval as oe
    info = plate_data()
    kr_pairs = oe.roboflow_originals(oe.yolo_pairs(info["kr"]["kr_eval"])) if info["kr"]["kr_eval"] else []
    up, side = oe.split_orientation(kr_pairs)
    oi = oe.yolo_pairs(OI / "plate" / "images" / "val")
    if models is None:
        models = {p.parent.name: str(p) for p in sorted(OUT.glob("plate_v00[3-9]/best.onnx"))}
    res = {}
    for name, path in models.items():
        for rot in ((0,), (0, 90, 270)):
            for key, ps_ in (("한국_바로", up), ("한국_누움", side), ("한국_전체", kr_pairs), ("해외", oi)):
                if not ps_:
                    continue
                r = oe.sweep(oe.predict_plates(path, ps_, rotations=rot), [0.4])[0]
                res[f"{name}|{'돌려찾기' if len(rot) > 1 else '그대로'}|{key}"] = r
                print(f"{name:<12} {'돌려찾기' if len(rot) > 1 else '그대로':<5} {key:<6} "
                      f"재현율 {r['recall']}  정밀도 {r['precision']}", flush=True)
    _save_json("eval_plate_v004.json", res)
    return res
