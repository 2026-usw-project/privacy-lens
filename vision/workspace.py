"""공유 작업 폴더(구글 드라이브)의 구조와 목록 파일.

사진·라벨·모델은 git 에 넣지 않는다(.gitignore, 실사 이미지 커밋 금지).
팀 공유 폴더 하나에 아래처럼 모으고, 코드는 그 경로만 받는다.

  PrivacyLens-YOLO/              ← 작업 폴더 (PL_YOLO_ROOT 또는 --root)
    inbox/                        ① 새 사진을 넣는 곳. 하위 폴더 하나 = 촬영 묶음
      찬영_학생증A_1007/*.jpg
    review/                       ② 라벨 검수 대기. 라벨링 도구로 이 폴더를 연다
      images/  labels/  done/  classes.json
    dataset/                      ③ 검수가 끝난 학습 데이터
      images/  labels/  train.txt  val.txt  test.txt  data.yaml
    models/                       ④ 학습한 모델
      v001/best.pt  v001/metrics.json  ...
      current.txt                 지금 쓰는 모델 버전 (예: v003)
      history.csv                 학습 기록
    manifest.csv                  사진 한 장당 한 줄. 출처·묶음·상태·분할
    라벨검수도구.html              vision/label_tool.html 사본 (init·ingest 때 갱신)
"""

from __future__ import annotations

import csv
import hashlib
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".bmp"}

# 상태
REVIEW = "review"      # 초벌 라벨이 붙어 검수를 기다림
DONE = "done"          # 검수 끝, dataset 에 들어감
SKIPPED = "skipped"    # 검수 중 '사진 제외'로 빠짐


@dataclass
class Row:
    id: str            # 원본 파일 내용의 해시 앞 12자리. 같은 사진을 두 번 넣으면 같은 id
    group: str         # 촬영 묶음(inbox 하위 폴더 이름). 분할 단위
    source: str        # real(직접 촬영) | synth(합성) | public(공개 데이터셋, 학습 전용)
    split: str         # train | val | test. dataset 에 들어갈 때 정해짐
    status: str        # review | done | skipped
    added_at: str
    orig_name: str     # 원래 파일 이름(확인용)
    prelabel: str      # 초벌 라벨을 만든 모델 버전. 없으면 빈칸


class Workspace:
    def __init__(self, root: str | os.PathLike | None = None):
        root = root or os.environ.get("PL_YOLO_ROOT")
        if not root:
            raise SystemExit(
                "작업 폴더를 알려 주세요.\n"
                "  --root \"G:/내 드라이브/PrivacyLens-YOLO\"  또는\n"
                "  환경변수 PL_YOLO_ROOT"
            )
        self.root = Path(root).expanduser().resolve()

    # ---------------------------------------------------------- 경로
    @property
    def inbox(self) -> Path:
        return self.root / "inbox"

    @property
    def review(self) -> Path:
        return self.root / "review"

    @property
    def dataset(self) -> Path:
        return self.root / "dataset"

    @property
    def models(self) -> Path:
        return self.root / "models"

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.csv"

    def init(self) -> None:
        """폴더가 없으면 만든다. 이미 있으면 건드리지 않는다."""
        for p in (
            self.inbox,
            self.review / "images", self.review / "labels", self.review / "done",
            self.dataset / "images", self.dataset / "labels",
            self.models,
        ):
            p.mkdir(parents=True, exist_ok=True)
        from .classes import as_json
        import json
        (self.review / "classes.json").write_text(
            json.dumps(as_json(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        # 저장소를 받지 않은 팀원도 드라이브에서 바로 열 수 있게 검수 도구를 같이 둔다
        tool = Path(__file__).with_name("label_tool.html")
        if tool.exists():
            import shutil
            shutil.copyfile(tool, self.root / "라벨검수도구.html")

    # ---------------------------------------------------------- 목록 파일
    def load(self) -> dict[str, Row]:
        if not self.manifest_path.exists():
            return {}
        with self.manifest_path.open(encoding="utf-8-sig", newline="") as f:
            names = {fl.name for fl in fields(Row)}
            out = {}
            for r in csv.DictReader(f):
                row = Row(**{k: r.get(k, "") or "" for k in names})
                out[row.id] = row
            return out

    def save(self, rows: dict[str, Row]) -> None:
        tmp = self.manifest_path.with_suffix(".tmp")
        # utf-8-sig: 엑셀에서 열어도 한글이 안 깨진다
        with tmp.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[fl.name for fl in fields(Row)])
            w.writeheader()
            for row in sorted(rows.values(), key=lambda r: (r.added_at, r.id)):
                w.writerow(asdict(row))
        tmp.replace(self.manifest_path)

    # ---------------------------------------------------------- 잠금
    def lock(self, who: str = ""):
        """두 사람이 동시에 ingest·build·train 을 돌리면 manifest.csv 가 꼬인다.

        드라이브에는 파일 잠금이 없어서 잠금 파일로 대신한다. 작업이 비정상
        종료돼 남은 잠금은 3시간이 지나면 무시한다.
        """
        import contextlib
        import datetime as dt
        import socket

        path = self.root / "작업중.lock"

        @contextlib.contextmanager
        def _cm():
            if path.exists():
                age = dt.datetime.now().timestamp() - path.stat().st_mtime
                if age < 3 * 3600:
                    raise SystemExit(
                        "다른 사람이 작업 중입니다:\n  " + path.read_text(encoding="utf-8").strip()
                        + f"\n끝난 뒤 다시 실행하세요. 확실히 아무도 안 쓰면 {path.name} 을 지우세요."
                    )
            path.write_text(f"{who or socket.gethostname()}  {dt.datetime.now():%m-%d %H:%M} 시작\n",
                            encoding="utf-8")
            try:
                yield
            finally:
                path.unlink(missing_ok=True)

        return _cm()

    # ---------------------------------------------------------- 모델
    def current_model(self) -> Path | None:
        p = self.models / "current.txt"
        if not p.exists():
            return None
        ver = p.read_text(encoding="utf-8").strip()
        w = self.models / ver / "best.pt"
        return w if w.exists() else None

    def current_version(self) -> str:
        p = self.models / "current.txt"
        return p.read_text(encoding="utf-8").strip() if p.exists() else ""

    def model_imgsz(self, default: int = 1280) -> int:
        """지금 모델이 학습한 입력 크기. 같은 크기로 검출해야 성능이 나온다."""
        import json
        p = self.models / self.current_version() / "metrics.json"
        try:
            return int(json.loads(p.read_text(encoding="utf-8"))["imgsz"])
        except Exception:
            return default

    def next_version(self) -> str:
        nums = [
            int(p.name[1:]) for p in self.models.glob("v[0-9][0-9][0-9]")
            if p.is_dir() and p.name[1:].isdigit()
        ]
        return f"v{(max(nums) + 1) if nums else 1:03d}"


def file_id(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:12]
