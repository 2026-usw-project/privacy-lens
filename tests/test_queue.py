"""대기열. 실제 스레드로 순서·취소·한도를 확인한다."""

import threading
import time

import pytest

from jobqueue import Cancelled, QueueFull, WorkQueue


def wait_until(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return
        time.sleep(0.01)
    raise AssertionError("시간 안에 조건이 만족되지 않음")


def hold(q, ticket, gate, log, errors=None):
    """차례가 오면 log 에 이름을 남기고 gate 가 열릴 때까지 자리를 붙잡는다."""
    try:
        with q.slot(ticket):
            log.append(ticket)
            gate.wait(3)
    except Exception as exc:  # noqa: BLE001
        if errors is not None:
            errors.append((ticket, exc))


def test_fifo_and_position():
    q = WorkQueue(max_waiting=5)
    gate = threading.Event()
    log: list[str] = []
    threads = []
    for name in ("a", "b", "c"):
        t = threading.Thread(target=hold, args=(q, name, gate, log))
        t.start()
        threads.append(t)
        # 들어온 순서를 확정하려고 한 명씩 줄에 세운다
        wait_until(lambda n=name: q.status(n)["state"] in ("running", "waiting"))

    assert q.status("a")["state"] == "running"
    assert q.status("b")["ahead"] == 1
    assert q.status("c")["ahead"] == 2
    assert q.status()["waiting"] == 2

    gate.set()
    for t in threads:
        t.join(3)
    assert log == ["a", "b", "c"]
    assert q.status()["avg_s"] is not None


def test_cancel_waiting():
    q = WorkQueue()
    gate = threading.Event()
    log, errors = [], []
    first = threading.Thread(target=hold, args=(q, "first", gate, log))
    first.start()
    wait_until(lambda: q.status("first")["state"] == "running")
    second = threading.Thread(target=hold, args=(q, "second", gate, log, errors))
    second.start()
    wait_until(lambda: q.status("second")["state"] == "waiting")

    assert q.cancel("second") is True
    second.join(3)
    assert errors and isinstance(errors[0][1], Cancelled)
    assert q.status("second")["state"] == "unknown"

    assert q.cancel("first") is False  # 이미 도는 작업은 멈출 수 없다
    gate.set()
    first.join(3)
    assert log == ["first"]


def test_full_queue_rejects():
    q = WorkQueue(max_waiting=1)
    gate = threading.Event()
    log = []
    t1 = threading.Thread(target=hold, args=(q, "run", gate, log))
    t1.start()
    wait_until(lambda: q.status("run")["state"] == "running")
    t2 = threading.Thread(target=hold, args=(q, "wait", gate, log))
    t2.start()
    wait_until(lambda: q.status("wait")["state"] == "waiting")

    with pytest.raises(QueueFull):
        with q.slot("third"):
            pass
    gate.set()
    t1.join(3)
    t2.join(3)


def test_duplicate_ticket_rejected():
    q = WorkQueue()
    gate = threading.Event()
    t = threading.Thread(target=hold, args=(q, "dup", gate, []))
    t.start()
    wait_until(lambda: q.status("dup")["state"] == "running")
    with pytest.raises(ValueError):
        with q.slot("dup"):
            pass
    gate.set()
    t.join(3)


def test_slot_released_on_error():
    q = WorkQueue()
    with pytest.raises(RuntimeError):
        with q.slot("boom"):
            raise RuntimeError
    assert q.status()["running"] == 0
    with q.slot("next"):
        pass
