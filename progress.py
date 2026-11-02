"""번호표별 진행 상태와 남은 시간.

요청이 들어오면 처리 단계 계획(사진 열기 → 글자 읽기 → … )을 세우고, 단계마다 timing.py 의
추정 시간을 붙인다. 단계가 시작·끝날 때마다 계획을 고친다.

  남은 시간 = max(지금 단계 추정 − 흐른 시간, 0) + 뒤 단계 추정의 합

- 단계가 시작할 때 그 단계의 실제 크기로 다시 추정한다. LLM 판단은 OCR 이 끝나야 조각 수를
  알 수 있으므로, 처음에는 평균으로 잡았다가 판단이 시작되는 순간 실제 조각 수로 고친다.
- 지금 단계가 추정을 넘기면 남은 몫은 0 으로 두고 '추정보다 N초 늦음'(overdue_s)을 알린다.
- 기다리는 동안: 처리 중인 작업의 남은 시간 + 내 앞 작업 각각의 전체 추정 + 내 전체 추정.
- 기록이 없는 단계가 하나라도 있으면 남은 시간은 None 이다. 숫자를 지어내지 않는다.

시간은 모두 서버 시계로 잰다(time.monotonic). 화면은 받은 값을 기준으로 1초씩 줄여 보여 주다가
다음 이벤트로 다시 맞춘다. 상태에는 단계 이름과 숫자만 있다. 사진·원문은 없다.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from pipeline import wording
from timing import TimingStore

KEEP_DONE_S = 60.0   # 끝난 번호표를 이만큼 들고 있는다(SSE 가 마지막 상태를 보낼 수 있게)
MAX_TICKETS = 200


def stage_label(key: str) -> str:
    """단계 키 → 화면 이름. 'judge:llm:gemini:…' 는 'judge:llm' 으로 본다."""
    parts = key.split(":")
    base = ":".join(parts[:2]) if parts[0] == "judge" else parts[0]
    return wording.STAGE_LABEL.get(base, wording.STAGE_LABEL["other"])


@dataclass
class Stage:
    key: str
    units: Optional[float] = None
    estimate: Optional[float] = None
    basis: Optional[str] = None      # 추정에 쓴 기록의 키(빌려 쓴 값인지 화면이 알 수 있게)
    started: Optional[float] = None
    took: Optional[float] = None     # 끝났으면 실제로 걸린 시간
    repeat: int = 0                  # 재검사처럼 같은 키가 두 번 나올 때 구분


@dataclass
class Job:
    kind: str                        # analyze | redact
    stages: list[Stage]
    created: float = field(default_factory=time.monotonic)
    started: Optional[float] = None  # 차례가 온 시각
    finished: Optional[float] = None
    ok: Optional[bool] = None
    current: Optional[int] = None    # 지금 단계 번호

    def remaining(self, now: float) -> Optional[float]:
        total = 0.0
        for i, st in enumerate(self.stages):
            if st.took is not None:
                continue
            if st.estimate is None:
                return None
            if i == self.current and st.started is not None:
                total += max(st.estimate - (now - st.started), 0.0)
            else:
                total += st.estimate
        return total

    def total(self) -> Optional[float]:
        if any(st.estimate is None for st in self.stages if st.took is None):
            return None
        return sum(st.took if st.took is not None else st.estimate for st in self.stages)


def plan(kind: str, *, ocr_key: str, judge_key: str, megapixels: Optional[float], detector: bool) -> list[Stage]:
    """요청 종류별 단계 계획. 재판독(reread)은 YOLO 가 문서를 찾아야 생기므로 계획에 넣지 않고 시작할 때 끼운다."""
    analysis = [Stage(ocr_key, megapixels)] + ([Stage("detect", megapixels)] if detector else []) \
        + [Stage(judge_key), Stage("codes", megapixels)]
    if kind == "redact":
        head = [Stage("decode", megapixels), Stage("mask", megapixels), Stage("export", megapixels)]
        return head + analysis
    return [Stage("decode", megapixels)] + analysis


class ProgressBoard:
    """번호표 → 진행 상태. 요청 처리 스레드가 쓰고, SSE·/queue 가 읽는다. 스레드 안전."""

    def __init__(self, timing: TimingStore):
        self.timing = timing
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}

    # ------------------------------------------------------------ 쓰기

    def register(self, ticket: str, kind: str, *, ocr_key: str, judge_key: str,
                 megapixels: Optional[float], detector: bool) -> bool:
        """계획을 세운다. 같은 번호표가 아직 끝나지 않았으면 덮지 않고 False(그 요청은 대기열에서 거절된다)."""
        stages = plan(kind, ocr_key=ocr_key, judge_key=judge_key, megapixels=megapixels, detector=detector)
        for st in stages:
            st.estimate, st.basis = self.timing.estimate(st.key, st.units)
        with self._lock:
            self._sweep()
            old = self._jobs.get(ticket)
            if old is not None and old.finished is None:
                return False
            self._jobs[ticket] = Job(kind, stages)
            return True

    def begin(self, ticket: Optional[str]) -> None:
        if not ticket:
            return
        with self._lock:
            job = self._jobs.get(ticket)
            if job:
                job.started = time.monotonic()

    def stage(self, ticket: Optional[str], event: str, key: str, units: Optional[float]) -> None:
        """단계 시작·끝. 시작이면 실제 크기로 다시 추정한다."""
        if not ticket:
            return
        estimate = basis = None
        if event == "start":
            estimate, basis = self.timing.estimate(key, units)
        now = time.monotonic()
        with self._lock:
            job = self._jobs.get(ticket)
            if job is None:
                return
            if event == "start":
                i = self._find(job, key)
                if i is None:  # 계획에 없던 단계(재판독 등): 지금 단계 바로 뒤에 끼운다
                    i = (job.current + 1) if job.current is not None else 0
                    job.stages.insert(i, Stage(key))
                st = job.stages[i]
                st.units, st.estimate, st.basis, st.started = units, estimate, basis, now
                job.current = i
            elif event == "end" and job.current is not None:
                st = job.stages[job.current]
                if st.key == key and st.started is not None:
                    st.took, st.units = now - st.started, units

    def finish(self, ticket: Optional[str], ok: bool) -> None:
        if not ticket:
            return
        with self._lock:
            job = self._jobs.get(ticket)
            if job and job.finished is None:
                job.finished, job.ok, job.current = time.monotonic(), ok, None

    @staticmethod
    def _find(job: Job, key: str) -> Optional[int]:
        """아직 시작하지 않은 같은 단계. 재검사의 OCR 은 이미 지난 ocr 과 다르게 다음 것을 찾는다.
        판단 키는 계획 때와 모델 이름까지 같아야 하므로 'judge' 머리만 맞춰 본다."""
        head = key.split(":")[0]
        for i, st in enumerate(job.stages):
            if st.started is None and (st.key == key or (head == "judge" and st.key.startswith("judge"))
                                       or (head == "ocr" and st.key.startswith("ocr"))):
                if st.key != key:
                    st.key = key
                return i
        return None

    def _sweep(self) -> None:
        now = time.monotonic()
        for t in [t for t, j in self._jobs.items() if j.finished and now - j.finished > KEEP_DONE_S]:
            del self._jobs[t]
        while len(self._jobs) >= MAX_TICKETS:  # 끝나지 않은 채 버려진 번호표가 쌓이지 않게
            del self._jobs[next(iter(self._jobs))]

    # ------------------------------------------------------------ 읽기

    def snapshot(self, ticket: str, *, running: list[str], waiting: list[str]) -> Optional[dict]:
        """화면에 보낼 상태. 대기 순서는 jobqueue 가 준다."""
        now = time.monotonic()
        with self._lock:
            job = self._jobs.get(ticket)
            if job is None:
                return None
            stages = []
            for i, st in enumerate(job.stages):
                state = "done" if st.took is not None else "running" if i == job.current else "todo"
                stages.append({
                    "key": st.key.split(":")[0] if not st.key.startswith("judge") else ":".join(st.key.split(":")[:2]),
                    "label": stage_label(st.key),
                    "state": state,
                    "estimate_s": _r(st.estimate),
                    "took_s": _r(st.took),
                    "borrowed": bool(st.basis and st.basis != st.key),
                })
            out = {"stages": stages, "total_s": _r(job.total())}
            if job.finished is not None:
                out.update(state="done" if job.ok else "failed",
                           took_s=_r(job.finished - (job.started or job.created)))
                return out
            if ticket in waiting:
                ahead_eta: Optional[float] = 0.0
                for t in running + waiting[:waiting.index(ticket)]:
                    other = self._jobs.get(t)
                    part = None if other is None else (other.remaining(now) if t in running else other.total())
                    ahead_eta = None if part is None or ahead_eta is None else ahead_eta + part
                mine = job.total()
                out.update(state="waiting", ahead=len(running) + waiting.index(ticket),
                           eta_s=_r(None if ahead_eta is None or mine is None else ahead_eta + mine))
                return out
            if job.started is None:
                out.update(state="uploading")
                return out
            cur = job.stages[job.current] if job.current is not None else None
            elapsed = now - cur.started if cur and cur.started is not None else 0.0
            out.update(state="running", current=job.current,
                       stage_elapsed_s=_r(elapsed),
                       overdue_s=_r(max(elapsed - cur.estimate, 0.0)) if cur and cur.estimate is not None else None,
                       remaining_s=_r(job.remaining(now)),
                       elapsed_s=_r(now - job.started))
            return out


def _r(v: Optional[float]) -> Optional[float]:
    return None if v is None else round(v, 1)
