"""OCR 작업 대기열.

OCR 엔진은 한 번에 하나씩만 돌릴 수 있다(PaddleOCR 추론기는 스레드 안전하지
않고, Tesseract 도 CPU 를 통째로 쓴다). 잠금만 걸면 순서가 보장되지 않고
기다리는 사람이 자기가 몇 번째인지 알 수 없다. 그래서 줄을 세운다.

- 들어온 순서대로(FIFO) 처리한다.
- 요청마다 번호표(ticket)를 받는다. 번호표로 '앞에 몇 건, 약 몇 초'를 물을 수 있다.
- 기다리는 동안 사용자가 다른 사진을 넣거나 창을 닫으면 취소할 수 있다.
  취소하지 않으면 아무도 기다리지 않는 사진을 나중에 OCR 하느라 줄이 밀린다.
- 줄이 너무 길면 받지 않는다. 스레드풀이 대기 요청으로 꽉 차면 대기열 조회조차
  응답하지 못한다.

무상태 원칙은 그대로다. 대기열에는 번호표 문자열만 있다. 사진은 각 요청 처리
함수의 지역 변수로만 존재하고, 순서가 오기 전까지는 디코딩도 하지 않는다.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from contextlib import contextmanager
from typing import Iterator, Optional


class QueueFull(Exception):
    pass


class Cancelled(Exception):
    pass


class WorkQueue:
    def __init__(self, *, max_waiting: int = 12, workers: int = 1):
        self.max_waiting = max_waiting
        self._workers = workers
        self._cond = threading.Condition()
        self._waiting: deque[str] = deque()
        self._running: set[str] = set()
        self._cancelled: set[str] = set()
        # 작업 하나에 걸린 시간의 이동평균. 예상 대기시간 계산용.
        self._avg_s: Optional[float] = None

    # ------------------------------------------------------------ 자리 잡기

    @contextmanager
    def slot(self, ticket: str) -> Iterator[None]:
        """차례가 올 때까지 기다렸다가 작업을 돌린다.

        with queue.slot(ticket):
            ...OCR...
        """
        with self._cond:
            if ticket in self._waiting or ticket in self._running:
                raise ValueError("이미 대기열에 있는 번호표입니다.")
            if len(self._waiting) >= self.max_waiting:
                raise QueueFull
            self._waiting.append(ticket)
            try:
                while True:
                    if ticket in self._cancelled:
                        raise Cancelled
                    if self._waiting[0] == ticket and len(self._running) < self._workers:
                        break
                    # 깨워주지 않아도 주기적으로 취소 여부를 다시 본다.
                    self._cond.wait(timeout=1.0)
            except BaseException:
                self._waiting.remove(ticket)
                self._cancelled.discard(ticket)
                self._cond.notify_all()
                raise
            self._waiting.popleft()
            self._running.add(ticket)

        started = time.monotonic()
        try:
            yield
        finally:
            took = time.monotonic() - started
            with self._cond:
                self._running.discard(ticket)
                self._cancelled.discard(ticket)
                self._avg_s = took if self._avg_s is None else 0.7 * self._avg_s + 0.3 * took
                self._cond.notify_all()

    def cancel(self, ticket: str) -> bool:
        """기다리는 중인 작업을 뺀다. 이미 돌고 있으면 멈출 수 없어 False."""
        with self._cond:
            if ticket in self._waiting:
                self._cancelled.add(ticket)
                self._cond.notify_all()
                return True
            return False

    # ------------------------------------------------------------ 상태

    def status(self, ticket: Optional[str] = None) -> dict:
        with self._cond:
            out = {
                "running": len(self._running),
                "waiting": len(self._waiting),
                "max_waiting": self.max_waiting,
                "avg_s": round(self._avg_s, 1) if self._avg_s is not None else None,
            }
            if ticket is None:
                return out
            if ticket in self._running:
                out.update(state="running", ahead=0, eta_s=None)
            elif ticket in self._waiting:
                ahead = list(self._waiting).index(ticket) + len(self._running)
                eta = None
                if self._avg_s is not None:
                    eta = round((ahead + 1) * self._avg_s)
                out.update(state="waiting", ahead=ahead, eta_s=eta)
            else:
                out.update(state="unknown")
            return out
