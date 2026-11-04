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
# 작업 폴더: Colab 은 /content, 집 PC 는 PL_WORK 로 바꾼다(예: D:/pl_work). 드라이브는 PL_DRIVE(구글 드라이브 데스크톱 경로)
WORK = Path(os.environ.get("PL_WORK", "/content"))
# 학습 부하: PC 그래픽카드를 아끼려면 PL_BATCH 를 낮춘다(기본 16)
BATCH = int(os.environ.get("PL_BATCH", "16"))
WORKERS = int(os.environ.get("PL_WORKERS", "2"))
OUT = ROOT / "objects"
MIDV = WORK / "midv"
FP_DS = WORK / "fp_ds"
OI = WORK / "oi"
KR = WORK / "kr"
SYNTH = WORK / "plate_synth"
ROT = WORK / "plate_rot"
KR_ZIPS = {"kr_eval": "Korea Car License Plate*.zip", "kr_train1": "license-plate-label*.zip",
           "kr_train2": "korea car plat*.zip"}


def _fresh(name: str):
    """노트북에서 git pull 한 뒤에도 예전 모듈이 남지 않게 다시 불러온다."""
    import importlib
    return importlib.reload(importlib.import_module(name))


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
        tar = OUT / "raw" / "midv_photo.tar"   # 드라이브에 보관 → 런타임이 끊겨도 다시 안 받음
        if not tar.exists():
            print("MIDV-2020 photo.tar 받는 중(4GB, 드라이브에 보관)…", flush=True)
            tar.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["curl", "-s", "-o", str(tar) + ".part", "ftp://smartengines.com/midv-2020/dataset/photo.tar"],
                           check=True)
            Path(str(tar) + ".part").rename(tar)
        print("MIDV-2020 푸는 중…", flush=True)
        subprocess.run(["tar", "xf", str(tar), "-C", str(MIDV)], check=True)
    if (FP_DS / "data.yaml").exists():
        print("이미 있음:", FP_DS)
        return {}
    bg = backgrounds or (str(OI / "plate" / "images") if (OI / "plate" / "images").exists() else None)
    c = fpd.build(MIDV, FP_DS, backgrounds=Path(bg) if bg else None)
    print("증명사진 데이터", c, "배경:", bg or "잡음")
    return c


# (이벤트, 함수) — 학습 모델에 붙일 콜백. 집 PC 는 vision.pc_train 이 그래픽카드 온도 보호를 붙인다.
TRAIN_CALLBACKS: list = []


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
    model = YOLO(str(last) if last.exists() else base)
    for event, fn in TRAIN_CALLBACKS:
        model.add_callback(event, fn)
    if last.exists():
        print("이어서 학습:", last, flush=True)
        model.train(resume=True)
    else:
        model.train(data=data, epochs=epochs, imgsz=640, batch=BATCH, workers=WORKERS, project=str(OUT / "runs"),
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


# ------------------------------------------------------------------ 일상 사진(VISPR-redactions)

VR = WORK / "vr"


def service_models() -> dict:
    """서비스가 쓰는 모델을 드라이브에서 저장소 models/ 로 가져온다: 문서 YOLO(models/v*/best.pt), 번호판 v003, YuNet."""
    from pipeline.objects import MODELS, YUNET_FILE, download_yunet
    MODELS.mkdir(exist_ok=True)
    got = {}
    docs = sorted((ROOT / "models").glob("v[0-9]*/best.pt"), key=lambda p: int(p.parent.name[1:]))
    if docs and not (MODELS / docs[-1].parent.name / "best.pt").exists():
        shutil.copytree(docs[-1].parent, MODELS / docs[-1].parent.name, dirs_exist_ok=True)
    got["문서"] = docs[-1].parent.name if docs else "없음"
    plate = OUT / "plate_v003" / "best.onnx"
    if plate.exists() and not (MODELS / "plate.onnx").exists():
        shutil.copy(plate, MODELS / "plate.onnx")
    got["번호판"] = "plate_v003" if plate.exists() else "없음"
    if not (MODELS / YUNET_FILE).exists():
        download_yunet()
    got["얼굴"] = "YuNet"
    print("서비스 모델:", got)
    return got


def vr_data(splits=("test2017",)) -> Path:
    """VISPR-redactions 라벨·사진 받기(라벨은 드라이브 objects/vr/ 에도 복사)."""
    rd = _fresh("vision.redactions")
    rd.download(VR, splits, keep=OUT / "raw" / "vr")
    keep = OUT / "vr"
    keep.mkdir(parents=True, exist_ok=True)
    for sp in splits:
        src = VR / "annotations" / f"{sp}.json"
        if src.exists() and not (keep / src.name).exists():
            shutil.copy(src, keep / src.name)
    return VR


def eval_daily(*, limit: int = 300) -> dict:
    """지금 서비스(규칙 기반 + 문서 YOLO + 얼굴 + 번호판)가 일상 사진의 개인정보를 종류별로 몇 % 찾나. CPU 로 됨."""
    rd = _fresh("vision.redactions")
    vr_data(("test2017",))
    service_models()
    res = rd.evaluate_service(VR, split="test2017", limit=limit)
    print(rd.table(res))
    _save_json(f"eval_daily_service_{limit}.json", res)
    return res


OI_SCREENS = ["Computer monitor", "Mobile phone", "Laptop", "Television", "Tablet computer"]
DAILY_DS = WORK / "daily_ds"
DAILY_ZIP = OUT / "daily_ds.zip"


def export_oi_multi(classes: list[str], split: str, n: int, name: str) -> int:
    import fiftyone as fo
    import fiftyone.zoo as foz
    ds = foz.load_zoo_dataset("open-images-v7", split=split, label_types=["detections"], classes=classes,
                              max_samples=n, only_matching=True, seed=0, shuffle=True,
                              dataset_name=f"{name}-{split}-{n}")
    ds.export(export_dir=str(OI / name), dataset_type=fo.types.YOLOv5Dataset, label_field="ground_truth",
              split="val" if split == "validation" else "train", classes=classes)
    m = len(ds)
    ds.delete()
    return m


def build_daily(*, oi_train: int = 2000, oi_val: int = 300, hit_step: int = 2, rebuild: bool = False) -> dict:
    """공개 데이터 5개를 한 YOLO 데이터로(CPU). 결과는 드라이브 objects/daily_ds.zip 과 objects/daily_ds_counts.json."""
    dd, rd = _fresh("vision.daily_data"), _fresh("vision.redactions")
    if DAILY_ZIP.exists() and not rebuild:
        print("이미 있음(다시 만들려면 rebuild=True):", DAILY_ZIP)
        return json.loads((OUT / "daily_ds_counts.json").read_text())
    raw = WORK / "daily_raw"
    got = dd.download_all(raw, manual=OUT / "manual", keep=OUT / "raw")
    rd.download(VR, ("train2017", "val2017"), keep=OUT / "raw" / "vr")
    if not (OI / "screen" / "images" / "val").exists():
        print("Open Images 화면 검증", export_oi_multi(OI_SCREENS, "validation", oi_val, "screen"), flush=True)
    if not (OI / "screen" / "images" / "train").exists():
        print("Open Images 화면 학습", export_oi_multi(OI_SCREENS, "test", oi_train, "screen"), flush=True)
    if rebuild and DAILY_DS.exists():
        shutil.rmtree(DAILY_DS)
    w = dd.Writer(DAILY_DS)
    print("VISPR-redactions…", flush=True)
    dd.add_redactions(w, VR)
    for part, sp in (("ann_train", "train"), ("ann_val", "val")):
        if f"hit_{part}" not in got:
            continue
        for js in glob.glob(f"{got['hit_' + part]}/**/*.json", recursive=True):
            print("BIV-Priv-HIT", sp, Path(js).name, flush=True)
            dd.add_coco(w, Path(js), got["hit_img_" + sp], "hit", split=sp, frame_step=hit_step,
                        only_names=dd.BIV_OBJECTS)
    if "seg_ann" in got:
        print("BIV-Priv-Seg…", flush=True)
        dd.add_coco(w, got["seg_ann"], got["seg_img"], "seg", val_frac=0.2)
    if "vwp_ann" in got:
        print("VizWiz-Priv…", flush=True)
        dd.add_vizwiz_priv(w, got["vwp_ann"], got["vwp_img"])
    sources = sorted({k.split("_")[0] for k in got}) + ["redactions", "oi"]
    print("Open Images 화면…", flush=True)
    dd.add_yolo_dir(w, OI / "screen", "oi", dict(enumerate(OI_SCREENS)))
    res = w.finish()
    res["받은 데이터"] = sources
    print(json.dumps(res, ensure_ascii=False, indent=1))
    _save_json("daily_ds_counts.json", res)
    print("드라이브로 압축 복사 중…", flush=True)
    dd.zip_dir(DAILY_DS, DAILY_ZIP)
    print("저장:", DAILY_ZIP)
    return res


def train_daily(*, epochs: int = 30, base: str = "yolo26n.pt") -> Path:
    """일상 사진 개인정보 물체 9종 YOLO26n(GPU). 데이터는 build_daily 가 만든 드라이브 zip. 끊기면 이어서."""
    from ultralytics import YOLO
    dd = _fresh("vision.daily_data")
    done = sorted(OUT.glob("daily_v[0-9][0-9][0-9]/best.onnx"))
    if done and (OUT / "runs" / "daily_objects" / "DONE").exists():
        print("이미 있음:", done[-1])
        return done[-1]
    if not (DAILY_DS / "data.yaml").exists():
        print("데이터 풀기…", flush=True)
        zipfile.ZipFile(DAILY_ZIP).extractall(DAILY_DS)
        (DAILY_DS / "data.yaml").write_text(
            f"path: {DAILY_DS}\ntrain: images/train\nval: images/val\nnames:\n" +
            "".join(f"  {i}: {n}\n" for i, n in enumerate(dd.CLASSES)))
    last = resumable_train(base, data=str(DAILY_DS / "data.yaml"), name="daily_objects", epochs=epochs)
    m = YOLO(str(last))
    metrics = m.val(data=str(DAILY_DS / "data.yaml"), imgsz=640, verbose=False, plots=False)
    per = {}
    for i, c in enumerate(metrics.box.ap_class_index):
        name = m.names[int(c)]
        per[name] = {"정밀도": round(float(metrics.box.p[i]), 3), "재현율": round(float(metrics.box.r[i]), 3),
                     "mAP50": round(float(metrics.box.ap50[i]), 3)}
    print("클래스별:", json.dumps(per, ensure_ascii=False, indent=1), " 전체 mAP50:", round(float(metrics.box.map50), 3))
    m.export(format="onnx", imgsz=640)
    dst = _next_version("daily")
    dst.mkdir(parents=True)
    shutil.copy(last, dst / "best.pt")
    shutil.copy(last.with_suffix(".onnx"), dst / "best.onnx")
    _save_json(f"{dst.name}_val.json", {"map50": round(float(metrics.box.map50), 3), "per_class": per})
    return dst / "best.onnx"
