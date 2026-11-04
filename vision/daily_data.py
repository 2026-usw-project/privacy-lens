"""일상 사진 개인정보 물체 — 공개 데이터 여러 개를 한 YOLO 데이터로 합친다 (D-19, 2026-11-04).

교수님 피드백: 일부러 넣은 개인정보가 아니라 일상 사진에 자연스럽게 찍힌 개인정보를 잡아야 한다.
위치 라벨이 있고 바로 받을 수 있는 데이터만 쓴다.

    출처              사진                                    라벨                라이선스
    VISPR-redactions  Flickr 일상 사진 8,473장                다각형(24종)         라벨 CC BY-NC 4.0, 사진 원 라이선스
    BIV-Priv-HIT      개인정보 물건을 배경·전경에 두고 찍은 영상 프레임   COCO(물체·부분 40종)  CC BY 4.0
    BIV-Priv-Seg      시각장애인이 찍은 사진 1,056장            COCO(16종)           CC BY 4.0
    VizWiz-Priv       시각장애인 사진, 개인정보는 가짜 내용으로 채움   다각형                CC BY 4.0
    Open Images V7    일상 사진의 모니터·휴대폰·노트북·TV         상자                 CC BY 4.0

사진은 드라이브·런타임에만 두고 저장소·발표 자료에 넣지 않는다. 비영리(수업) 사용.
출처마다 이름이 달라 아래 CLASSES 로 묶는다. 묶이지 않은 이름은 결과의 '안 씀' 에 남겨 확인한다.
"""

from __future__ import annotations

import glob
import hashlib
import json
import random
import re
import shutil
import subprocess
import zipfile
from collections import defaultdict
from pathlib import Path

from PIL import Image

CLASSES = ["id_card", "card", "name_tag", "waybill", "receipt", "document", "ticket", "screen", "health_item"]
CLASS_KO = {"id_card": "신분증", "card": "결제 카드", "name_tag": "명함·명찰", "waybill": "우편물·송장",
            "receipt": "영수증·고지서", "document": "개인 서류", "ticket": "티켓", "screen": "화면",
            "health_item": "약·건강 관련 물건"}

# 이름(소문자, _·공백 정리)에 들어 있는 낱말로 묶는다. 위에서부터 먼저 맞는 것.
RULES: list[tuple[str, str]] = [
    (r"business.?card|name.?tag|badge", "name_tag"),
    (r"passport|driver|licen[cs]e|student.?id|ausweis|identity|\bid\b|id.?card", "id_card"),
    (r"credit|debit|bank.?card|payment.?card", "card"),
    (r"letter|\bmail\b|envelope|package|parcel|shipping|address.?label", "waybill"),
    (r"receipt|bill", "receipt"),
    (r"bank.?statement|statement|prescription|medical.?record|transcript|mortgage|investment|\btax\b|"
     r"\bcheck\b|cheque|\bform\b|document|report", "document"),
    (r"ticket|boarding", "ticket"),
    (r"screen|monitor|laptop|computer|television|\btv\b|mobile.?phone|cell.?phone|smartphone|tablet", "screen"),
    (r"pill|medicine|pregnancy|condom", "health_item"),
]
SKIP = re.compile(r"face|person|newspaper|tattoo|nudity|signature|handwriting|fingerprint|plate|e.?mail")

URLS = {
    "hit": {
        "img_train": "https://bivpriv.colorado.edu/BIVPriv-HIT/images/training.zip",
        "img_val": "https://bivpriv.colorado.edu/BIVPriv-HIT/images/validation.zip",
        "ann_train": "https://bivpriv.colorado.edu/BIVPriv-HIT/annotations/training/training.zip",
        "ann_val": "https://bivpriv.colorado.edu/BIVPriv-HIT/annotations/validation/validation.zip",
    },
    "seg": {
        "img": "https://vizwiz.cs.colorado.edu/biv-priv/images/query_images.zip",
        "ann": "https://vizwiz.cs.colorado.edu/VizWiz_all_answers/biv-priv-seg-query.json",
    },
    "vwp": {
        "img": "https://vizwiz.cs.colorado.edu/dataset_downloads/VizWiz-Priv-v1.0/Filling_Image.zip",
        "ann": "https://vizwiz.cs.colorado.edu/dataset_downloads/VizWiz-Priv-v1.0/Annotations.zip",
    },
}


# BIV-Priv-HIT 는 물체 16종 + 그 물체의 '개인정보 부분' 범주가 섞여 있다. 부분을 같은 클래스로 넣으면
# 물체 상자 안에 같은 클래스 상자가 겹치므로, 물체 16종(BIV-Priv-Seg 와 같은 이름)만 쓴다.
BIV_OBJECTS = {"local_newspaper", "bank_statement", "bills_or_receipt", "business_card", "condom_box",
               "credit_or_debit_card", "doctors_prescription", "letters_with_address", "medical_record_document",
               "pregnancy_test", "empty_pill_bottle", "tattoo_sleeve", "transcript", "mortgage_or_investment_report",
               "condom_with_plastic_bag", "pregnancy_test_box"}


def map_name(name: str) -> str | None:
    n = re.sub(r"[_\-:/]+", " ", name.lower()).strip()
    if SKIP.search(n):
        return None
    for pat, cls in RULES:
        if re.search(pat, n):
            return cls
    return None


# ------------------------------------------------------------------ 받기

def fetch(url: str, dst: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        print("받는 중:", url.rsplit("/", 1)[-1], flush=True)
        cmd = ["curl", "-sSfL", "--retry", "3", "-o", str(dst) + ".part", url]
        r = subprocess.run(cmd)
        if r.returncode == 60:   # 서버가 중간 인증서를 안 보냄 → 공식 발급 주소(AIA)에서 받아 보충하고 다시 검증
            bundle = _bundle_with_intermediate(url.split("/")[2])
            if bundle:
                r = subprocess.run(cmd[:1] + ["--cacert", str(bundle)] + cmd[1:])
        if r.returncode:
            raise RuntimeError(f"받기 실패(curl {r.returncode}): {url}")
        Path(str(dst) + ".part").rename(dst)
    return dst


def _bundle_with_intermediate(host: str) -> Path | None:
    """서버 인증서의 'CA Issuers' 주소에서 중간 인증서를 받아 시스템 CA 묶음에 더한 파일. 검증은 그대로 한다."""
    import ssl
    try:
        leaf = ssl.get_server_certificate((host, 443))
        txt = subprocess.run(["openssl", "x509", "-noout", "-text"], input=leaf, capture_output=True, text=True).stdout
        m = re.search(r"CA Issuers - URI:(\S+)", txt)
        if not m:
            return None
        der = Path(f"/tmp/{host}_inter.der")
        subprocess.run(["curl", "-sSfL", "-o", str(der), m.group(1)], check=True)
        pem = subprocess.run(["openssl", "x509", "-inform", "DER", "-in", str(der)], capture_output=True, text=True)
        if pem.returncode:   # 이미 PEM 일 수도 있음
            pem = subprocess.run(["openssl", "x509", "-in", str(der)], capture_output=True, text=True)
        sys_ca = Path(ssl.get_default_verify_paths().cafile or "/etc/ssl/certs/ca-certificates.crt")
        out = Path(f"/tmp/{host}_bundle.pem")
        out.write_text(sys_ca.read_text() + "\n" + pem.stdout)
        print("  중간 인증서 보충:", m.group(1), flush=True)
        return out
    except Exception as e:
        print("  중간 인증서 보충 실패:", type(e).__name__, flush=True)
        return None


def unzip(z: Path, dst: Path) -> Path:
    if not dst.exists() or not any(dst.iterdir()):
        dst.mkdir(parents=True, exist_ok=True)
        zipfile.ZipFile(z).extractall(dst)
    return dst


def download_all(root: Path, which=("hit", "seg", "vwp")) -> dict[str, Path]:
    root = Path(root)
    got = {}
    for key in which:
        try:
            for part, url in URLS[key].items():
                name = url.rsplit("/", 1)[-1]
                f = fetch(url, root / "zips" / key / f"{part}_{name}")
                got[f"{key}_{part}"] = unzip(f, root / key / part) if f.suffix == ".zip" else f
        except Exception as e:   # 한 데이터가 실패해도 나머지로 계속
            print(f"건너뜀 {key}: {e}", flush=True)
            for part in URLS[key]:
                got.pop(f"{key}_{part}", None)
    return got


# ------------------------------------------------------------------ 쓰기

class Writer:
    """사진을 긴 변 max_side 로 줄여 out/images|labels/<split> 에 쓴다(드라이브에 zip 으로 옮기기 쉽게)."""

    def __init__(self, out: Path, max_side: int = 1280):
        self.out = Path(out)
        self.max_side = max_side
        self.counts: dict = defaultdict(int)
        self.skipped: dict = defaultdict(int)

    def add(self, src: Path, split: str, boxes: list[tuple[str, float, float, float, float]], name: str,
            source: str, W: int | None = None, H: int | None = None) -> bool:
        """boxes: (class, x, y, w, h) 원본 픽셀. W·H 는 라벨 기준 크기(없으면 사진 크기)."""
        try:
            im = Image.open(src)
            im = im.convert("RGB")
        except Exception:
            self.skipped[f"{source}:사진 못 읽음"] += 1
            return False
        W, H = W or im.width, H or im.height
        lines = []
        for cls, x, y, w, h in boxes:
            x0, y0 = max(0.0, x), max(0.0, y)
            x1, y1 = min(float(W), x + w), min(float(H), y + h)
            if x1 - x0 < 2 or y1 - y0 < 2:
                continue
            lines.append(f"{CLASSES.index(cls)} {(x0 + x1) / 2 / W:.6f} {(y0 + y1) / 2 / H:.6f} "
                         f"{(x1 - x0) / W:.6f} {(y1 - y0) / H:.6f}")
            self.counts[f"{split}:{cls}"] += 1
            self.counts[f"{source}:{cls}"] += 1
        s = self.max_side / max(im.size)
        if s < 1:
            im = im.resize((round(im.width * s), round(im.height * s)))
        (self.out / "images" / split).mkdir(parents=True, exist_ok=True)
        (self.out / "labels" / split).mkdir(parents=True, exist_ok=True)
        im.save(self.out / "images" / split / f"{name}.jpg", quality=90)
        (self.out / "labels" / split / f"{name}.txt").write_text("\n".join(lines) + ("\n" if lines else ""))
        self.counts[f"{split}:사진"] += 1
        self.counts[f"{source}:사진"] += 1
        return True

    def finish(self) -> dict:
        (self.out / "data.yaml").write_text(
            f"path: {self.out}\ntrain: images/train\nval: images/val\nnames:\n" +
            "".join(f"  {i}: {n}\n" for i, n in enumerate(CLASSES)))
        return {"counts": dict(self.counts), "안 씀": dict(self.skipped)}


def _index(root: Path) -> dict[str, Path]:
    return {Path(p).name: Path(p) for p in glob.glob(f"{root}/**/*", recursive=True)
            if p.lower().endswith((".jpg", ".jpeg", ".png"))}


def _split_of(key: str, val_frac: float) -> str:
    h = int(hashlib.md5(key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return "val" if h < val_frac else "train"


def add_coco(w: Writer, ann: Path, images_root: Path, source: str, *, split: str | None = None,
             val_frac: float = 0.2, frame_step: int = 1, keep_empty: float = 0.1, seed: int = 0,
             only_names: set[str] | None = None) -> None:
    """COCO 형식(bbox 있음). split 을 안 주면 사진 이름 해시로 train/val 을 나눈다.
    frame_step: 영상 프레임이면 n 장에 1장만(이웃 프레임은 거의 같은 사진)."""
    data = json.load(open(ann))
    cats = {c["id"]: c["name"] for c in data.get("categories", [])}
    to_cls = {}
    for cid, nm in cats.items():
        c = map_name(nm) if only_names is None or nm in only_names else None
        if c:
            to_cls[cid] = c
        else:
            w.skipped[f"{source}:이름 '{nm}'"] += 1
    by_img = defaultdict(list)
    for a in data.get("annotations", []):
        if a.get("category_id") in to_cls and a.get("bbox"):
            by_img[a["image_id"]].append((to_cls[a["category_id"]], *map(float, a["bbox"])))
    idx = _index(images_root)
    rng = random.Random(seed)
    for k, im in enumerate(sorted(data.get("images", []), key=lambda i: i["id"])):
        if frame_step > 1 and k % frame_step:
            continue
        boxes = by_img.get(im["id"], [])
        if not boxes and rng.random() > keep_empty:
            continue
        src = idx.get(Path(im["file_name"]).name)
        if src is None:
            w.skipped[f"{source}:사진 없음"] += 1
            continue
        sp = split or _split_of(im["file_name"], val_frac)
        w.add(src, sp, boxes, f"{source}_{Path(im['file_name']).stem}_{im['id']}", source,
              im.get("width"), im.get("height"))


def add_vizwiz_priv(w: Writer, ann_root: Path, images_root: Path, *, keep_empty: float = 0.1, seed: int = 0) -> None:
    """VizWiz-Priv: {"image", "private", "private_regions": [{"class", "polygon": [[x, y], ...]}]} 의 목록(분할별 json)."""
    idx = _index(images_root)
    rng = random.Random(seed)
    for js in sorted(glob.glob(f"{ann_root}/**/*.json", recursive=True)):
        low = Path(js).name.lower()
        split = "val" if "val" in low else ("test" if "test" in low else "train")
        if split == "test":
            split = "val"
        data = json.load(open(js))
        items = data if isinstance(data, list) else (data.get("annotations") or data.get("images") or [])
        for e in items:
            if not isinstance(e, dict) or "image" not in e:
                continue
            boxes = []
            for r in e.get("private_regions") or []:
                c = map_name(r.get("class", ""))
                pts = r.get("polygon") or []
                if not c:
                    w.skipped[f"vizwiz_priv:이름 '{r.get('class')}'"] += 1
                    continue
                if len(pts) >= 2:
                    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                    boxes.append((c, min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)))
            if not boxes and rng.random() > keep_empty:
                continue
            src = idx.get(Path(e["image"]).name)
            if src is None:
                w.skipped["vizwiz_priv:사진 없음"] += 1
                continue
            w.add(src, split, boxes, f"vwp_{Path(e['image']).stem}", "vizwiz_priv")


def add_redactions(w: Writer, vr_root: Path, *, keep_empty: float = 0.15, seed: int = 0) -> None:
    from vision import redactions as rd
    rng = random.Random(seed)
    for sp in ("train2017", "val2017"):
        js = Path(vr_root) / "annotations" / f"{sp}.json"
        if not js.exists():
            continue
        tag = "train" if sp.startswith("train") else "val"
        for r in rd.load(js):
            boxes = []
            for a, (x, y, bw, bh) in r["insts"]:
                c = map_name(a.split("_", 1)[1])
                if c:
                    boxes.append((c, x, y, bw, bh))
            if not boxes and rng.random() > keep_empty:
                continue
            src = rd.find_image(Path(vr_root) / "images" / sp, r["name"]) or rd.find_image(Path(vr_root) / "images", r["name"])
            if src is None:
                w.skipped["redactions:사진 없음"] += 1
                continue
            w.add(src, tag, boxes, f"vr_{Path(r['name']).stem}", "redactions", r["W"], r["H"])


def add_yolo_dir(w: Writer, root: Path, source: str, class_names: dict[int, str]) -> None:
    """이미 YOLO 형식인 폴더(Open Images 내보내기). class_names: 원래 번호 → 이름."""
    from vision.objects_eval import yolo_pairs
    for img, lab in yolo_pairs(Path(root)):
        boxes = []
        with Image.open(img) as im:
            W, H = im.size
        for line in lab.read_text().splitlines():
            p = line.split()
            if len(p) < 5:
                continue
            c = map_name(class_names.get(int(p[0]), ""))
            if not c:
                continue
            cx, cy, bw, bh = (float(v) for v in p[1:5])
            boxes.append((c, (cx - bw / 2) * W, (cy - bh / 2) * H, bw * W, bh * H))
        sp = "val" if "/val" in str(img) else "train"
        w.add(img, sp, boxes, f"{source}_{img.stem}", source, W, H)


def zip_dir(src: Path, dst: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path("/tmp") / dst.name
    shutil.make_archive(str(tmp.with_suffix("")), "zip", root_dir=src)
    shutil.copy(tmp, dst)
    return dst
