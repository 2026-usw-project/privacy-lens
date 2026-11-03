"""처리 단계별 걸린 시간 기록과 추정.

'요청 하나'의 평균으로는 남은 시간을 맞힐 수 없다. 규칙 판단과 LLM 판단, 작은 사진과
큰 사진이 한 평균에 섞인다. 그래서 단계(OCR·YOLO·판단 …)마다, 그리고 그 단계의 크기
(메가픽셀·조각 수)에 맞춰 따로 잰다.

  걸린 시간 ≈ a + b × 크기      (단계마다 감쇠 최소제곱. 오래된 기록일수록 덜 반영)

기록이 적으면(3건 미만) '평균 시간 × 크기 비율'로 대신한다. 처음 쓰는 모델은 기록이
있는 넓은 범위의 값을 빌린다.

  judge:llm:gemini:gemini-flash-latest → judge:llm:gemini → judge:llm

판단 단계는 judge:llm 아래로 내려가지 않는다. 규칙 판단(judge:rules)은 LLM 보다
수십 배 빨라서 서로 빌려 쓰면 틀린다.

저장: DB 없이 JSON 파일 하나(PL_TIMING_PATH, 기본 ~/.privacy-lens/timing.json).
단계 키와 숫자만 담는다. 사진·OCR 원문·API 키·번호표는 넣지 않는다(DECISIONS D-17).
임시 파일에 쓰고 바꿔 끼워서, 쓰다가 꺼져도 파일이 깨지지 않는다. 깨졌거나 버전이
다르면 버리고 새로 시작한다.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

VERSION = 1
DECAY = 0.9            # 새 기록이 들어올 때 이전 기록에 곱하는 비율
MIN_FIT = 3            # 이만큼 쌓이면 a + b × 크기 로 추정한다
OUTLIER = 5.0          # 추정의 이 배수를 넘게 걸린 기록은
OUTLIER_WEIGHT = 0.3   # 이만큼만 반영한다(엔진 재시작·네트워크 지연 같은 한 번의 사고)
SAVE_EVERY_S = 5.0     # 파일에 쓰는 최소 간격
MAX_KEYS = 200         # 모델 이름이 끝없이 늘어 파일이 커지지 않게


def default_path() -> Path:
    raw = os.environ.get("PL_TIMING_PATH")
    return Path(raw).expanduser() if raw else Path.home() / ".privacy-lens" / "timing.json"


def fallback_chain(key: str) -> list[str]:
    """좁은 키부터 넓은 키까지. 판단은 judge:llm / judge:rules 에서 멈춘다."""
    parts = key.split(":")
    floor = 2 if parts[0] == "judge" else 1
    return [":".join(parts[:n]) for n in range(len(parts), floor - 1, -1)]


class Estimator:
    """한 단계 키의 기록. 감쇠한 합계 다섯 개만 들고 있다."""

    __slots__ = ("n", "sx", "sy", "sxx", "sxy", "count")

    def __init__(self, n=0.0, sx=0.0, sy=0.0, sxx=0.0, sxy=0.0, count=0):
        self.n, self.sx, self.sy, self.sxx, self.sxy, self.count = n, sx, sy, sxx, sxy, int(count)

    def predict(self, units: Optional[float] = None) -> Optional[float]:
        if self.count == 0 or self.n <= 0:
            return None
        mean_x, mean_y = self.sx / self.n, self.sy / self.n
        if units is None:
            return mean_y
        if self.count >= MIN_FIT:
            var = self.n * self.sxx - self.sx * self.sx
            if var > 1e-9 * max(1.0, self.n * self.sxx):
                b = max(0.0, (self.n * self.sxy - self.sx * self.sy) / var)
                a = max(0.0, (self.sy - b * self.sx) / self.n)
                return a + b * units
        # 크기가 거의 같은 기록뿐이거나 기록이 적다: 평균을 크기 비율로 늘이고 줄인다
        if mean_x > 0:
            return mean_y * units / mean_x
        return mean_y

    def update(self, units: float, seconds: float) -> None:
        guess = self.predict(units)
        w = OUTLIER_WEIGHT if guess and seconds > OUTLIER * guess else 1.0
        self.n = self.n * DECAY + w
        self.sx = self.sx * DECAY + w * units
        self.sy = self.sy * DECAY + w * seconds
        self.sxx = self.sxx * DECAY + w * units * units
        self.sxy = self.sxy * DECAY + w * units * seconds
        self.count += 1

    def as_dict(self) -> dict:
        return {k: round(getattr(self, k), 6) if k != "count" else self.count for k in self.__slots__}

    @classmethod
    def from_dict(cls, data: dict) -> "Estimator":
        n, sx, sy, sxx, sxy = (float(data[k]) for k in ("n", "sx", "sy", "sxx", "sxy"))
        count = int(data["count"])
        finite = all(abs(v) < 1e12 for v in (n, sx, sy, sxx, sxy))  # NaN 도 여기서 걸린다
        if not finite or min(n, sx, sy, sxx) < 0 or count < 0:
            raise ValueError("bad estimator")
        return cls(n, sx, sy, sxx, sxy, count=count)


class TimingStore:
    """단계별 추정기 모음. 스레드 안전. 기록은 바로 메모리에, 파일에는 몰아서 쓴다."""

    def __init__(self, path: Optional[Path] = None, *, autosave: bool = True):
        self.path = path
        self.autosave = autosave and path is not None
        self._lock = threading.Lock()
        self._keys: dict[str, Estimator] = {}
        self._dirty = False
        self._saved_at = 0.0
        if path is not None:
            self._load()

    # ------------------------------------------------------------ 파일

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("version") != VERSION:
                return
            keys = {str(k): Estimator.from_dict(v) for k, v in data["keys"].items()}
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return  # 없거나 깨졌다: 새로 시작
        self._keys = dict(list(keys.items())[:MAX_KEYS])

    def flush(self) -> None:
        """바뀐 것이 있으면 파일에 쓴다. 임시 파일 → 바꿔 끼우기."""
        if self.path is None:
            return
        with self._lock:
            if not self._dirty:
                return
            payload = json.dumps({"version": VERSION, "keys": {k: e.as_dict() for k, e in self._keys.items()}},
                                 ensure_ascii=False, indent=1)
            self._dirty = False
            self._saved_at = time.monotonic()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".timing-", suffix=".json", dir=self.path.parent)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp, self.path)
        except OSError:
            with self._lock:
                self._dirty = True  # 다음에 다시 시도한다. 기록은 메모리에 남아 있다
            try:
                os.unlink(tmp)  # type: ignore[possibly-undefined]
            except (OSError, NameError):
                pass

    # ------------------------------------------------------------ 기록·추정

    def record(self, key: str, units: float, seconds: float) -> None:
        """한 단계가 끝났을 때. 좁은 키부터 넓은 키까지 모두에 쌓는다."""
        if not key or seconds < 0 or units < 0 or seconds != seconds:
            return
        with self._lock:
            for k in fallback_chain(key):
                est = self._keys.get(k)
                if est is None:
                    if len(self._keys) >= MAX_KEYS:
                        continue
                    est = self._keys[k] = Estimator()
                est.update(float(units), float(seconds))
            self._dirty = True
            due = self.autosave and time.monotonic() - self._saved_at >= SAVE_EVERY_S
        if due:
            self.flush()

    def estimate(self, key: str, units: Optional[float] = None) -> tuple[Optional[float], Optional[str]]:
        """(추정 초, 근거가 된 키). 기록이 하나도 없으면 (None, None) — 숫자를 지어내지 않는다.

        좁은 키에 기록이 MIN_FIT 건 미만이면 넓은 키가 더 많이 알면 그쪽을 쓴다.
        """
        with self._lock:
            best = None
            for k in fallback_chain(key):
                est = self._keys.get(k)
                if est is None or est.count == 0:
                    continue
                if best is None:
                    best = (k, est)
                if est.count >= MIN_FIT:
                    best = (k, est)
                    break
            if best is None:
                return None, None
            k, est = best
            return est.predict(units), k

    def snapshot(self) -> dict[str, dict]:
        """테스트·디버그용. 키별 기록 수와 평균."""
        with self._lock:
            return {k: {"count": e.count, "mean_s": round(e.sy / e.n, 3) if e.n else None}
                    for k, e in self._keys.items()}
