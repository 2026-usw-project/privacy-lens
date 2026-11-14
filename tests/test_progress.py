"""번호표별 진행 상태(progress.py)와 SSE(/progress). 시계는 가짜로 돌린다."""

import io
import json
import threading

import pytest
from PIL import Image

import progress
from progress import ProgressBoard
from timing import TimingStore


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(progress.time, "monotonic", c)
    return c


def store_with(**secs) -> TimingStore:
    """단계 키 → 걸린 시간(크기 1 기준, 3건씩)."""
    store = TimingStore(None)
    for key, s in secs.items():
        for _ in range(3):
            store.record(key.replace("__", ":"), 1.0, s)
    return store


def board(**secs) -> ProgressBoard:
    return ProgressBoard(store_with(**secs))


def register(b, ticket="t1", kind="analyze", judge="judge:rules", detector=False, mp=1.0):
    assert b.register(ticket, kind, ocr_key="ocr:paddleocr", judge_key=judge, megapixels=mp, detector=detector)


def snap(b, ticket="t1", running=(), waiting=()):
    return b.snapshot(ticket, running=list(running), waiting=list(waiting))


# ------------------------------------------------------------------ 계획과 남은 시간

def test_plan_and_remaining_counts_down_by_stage(clock):
    b = board(decode=0.5, ocr__paddleocr=3.0, judge__rules=0.5, codes=1.0)
    register(b)
    s = snap(b, waiting=["t1"])
    assert s["state"] == "waiting" and [x["label"] for x in s["stages"]] == ["사진 열기", "글자 읽기", "개인정보 판단", "QR·바코드 검사"]
    assert s["eta_s"] == 5.0

    b.begin("t1")
    b.stage("t1", "start", "decode", 1.0)
    clock.t += 0.5
    b.stage("t1", "end", "decode", 1.0)
    b.stage("t1", "start", "ocr:paddleocr", 1.0)
    clock.t += 1.0
    s = snap(b, running=["t1"])
    assert s["state"] == "running" and s["stages"][1]["state"] == "running"
    assert s["remaining_s"] == 3.5            # OCR 남은 2초 + 판단 0.5 + QR 1
    assert s["stage_elapsed_s"] == 1.0 and s["overdue_s"] == 0.0


def test_llm_estimate_corrected_when_stage_starts(clock):
    store = TimingStore(None)
    for units, secs in ((10, 7.0), (20, 12.0), (40, 22.0)):    # 2초 + 0.5초 × 조각
        store.record("judge:llm:gemini:m", units, secs)
    store.record("ocr:paddleocr", 1.0, 2.0)
    b = ProgressBoard(store)
    register(b, judge="judge:llm:gemini:m")
    before = snap(b, waiting=["t1"])["stages"][2]["estimate_s"]   # 조각 수를 모를 때: 평균
    b.begin("t1")
    b.stage("t1", "start", "ocr:paddleocr", 1.0)
    clock.t += 2
    b.stage("t1", "end", "ocr:paddleocr", 1.0)
    b.stage("t1", "start", "judge:llm:gemini:m", 4)              # OCR 이 끝나 보니 조각이 4개뿐
    after = snap(b, running=["t1"])
    assert after["stages"][2]["estimate_s"] < before
    assert after["stages"][2]["estimate_s"] == pytest.approx(4.0, abs=0.2)


def test_overdue_stage_keeps_zero_remaining(clock):
    b = board(ocr__paddleocr=2.0, judge__rules=1.0, codes=1.0, decode=0.1)
    register(b)
    b.begin("t1")
    b.stage("t1", "start", "ocr:paddleocr", 1.0)
    clock.t += 5
    s = snap(b, running=["t1"])
    assert s["overdue_s"] == 3.0
    assert s["remaining_s"] == 2.1            # 지금 단계 몫은 0, 남은 단계(사진 열기 0.1 + 판단 1 + QR 1)만


def test_unknown_stage_means_no_number(clock):
    b = board(ocr__paddleocr=2.0)               # 판단·QR 기록이 없다
    register(b)
    b.begin("t1")
    s = snap(b, running=["t1"])
    assert s["remaining_s"] is None and s["total_s"] is None


def test_borrowed_estimate_flagged(clock):
    store = TimingStore(None)
    for _ in range(3):
        store.record("judge:llm:openai:gpt", 1.0, 9.0)
    b = ProgressBoard(store)
    register(b, judge="judge:llm:gemini:new")
    judge = snap(b, waiting=["t1"])["stages"][2]
    assert judge["label"] == "LLM 판단" and judge["estimate_s"] == 9.0 and judge["borrowed"] is True


def test_reread_inserted_after_current(clock):
    b = board(ocr__paddleocr=1.0, detect=1.0, reread=2.0, judge__rules=1.0, codes=1.0, decode=0.1)
    register(b, detector=True)
    b.begin("t1")
    for key in ("decode", "ocr:paddleocr", "detect"):
        b.stage("t1", "start", key, 1.0)
        b.stage("t1", "end", key, 1.0)
    b.stage("t1", "start", "reread", 0)
    labels = [x["label"] for x in snap(b, running=["t1"])["stages"]]
    assert labels.index("작은 문서 확대해 다시 읽기") == labels.index("문서·객체 찾기") + 1


def test_redact_plan_has_only_save_stages(clock):
    b = board()
    register(b, kind="redact")
    keys = [x["key"] for x in snap(b, waiting=["t1"])["stages"]]
    assert keys == ["decode", "mask", "export"]


def test_waiting_eta_adds_running_remainder_and_each_job(clock):
    b = board(decode=1.0, ocr__paddleocr=4.0, judge__rules=1.0, codes=1.0)   # 작업 하나 = 7초
    for t in ("a", "b", "c"):
        register(b, ticket=t)
    b.begin("a")
    b.stage("a", "start", "decode", 1.0)
    clock.t += 1
    b.stage("a", "end", "decode", 1.0)
    b.stage("a", "start", "ocr:paddleocr", 1.0)
    clock.t += 3                                # a 의 남은 시간 = 1 + 1 + 1 = 3
    s = snap(b, "c", running=["a"], waiting=["b", "c"])
    assert s["ahead"] == 2 and s["eta_s"] == 3 + 7 + 7


def test_finish_and_duplicate(clock):
    b = board(decode=1.0)
    register(b)
    assert not b.register("t1", "analyze", ocr_key="ocr", judge_key="judge:rules", megapixels=1, detector=False)
    b.begin("t1")
    clock.t += 2.5
    b.finish("t1", ok=True)
    s = snap(b)
    assert s["state"] == "done" and s["took_s"] == 2.5
    assert b.register("t1", "analyze", ocr_key="ocr", judge_key="judge:rules", megapixels=1, detector=False)


def test_old_finished_swept(clock):
    b = board()
    register(b)
    b.finish("t1", ok=False)
    clock.t += progress.KEEP_DONE_S + 1
    register(b, ticket="t2")
    assert snap(b) is None


def test_no_ticket_is_harmless():
    b = board()
    b.stage(None, "start", "ocr", 1.0)
    b.begin(None)
    b.finish(None, True)


# ------------------------------------------------------------------ 서버

@pytest.fixture
def client(monkeypatch):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    import server
    from pipeline import ocr
    from pipeline.types import Box, TextSpan

    store = TimingStore(None)
    monkeypatch.setattr(server, "TIMING", store)
    monkeypatch.setattr(server, "BOARD", ProgressBoard(store))
    monkeypatch.setattr(server, "_backend", ocr.ScriptedBackend([TextSpan("받는분 010-1234-5678", Box(10, 10, 200, 20), 0.95)]))
    return TestClient(server.app)


def png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (300, 200), "white").save(buf, "PNG")
    return buf.getvalue()


def sse_events(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in lines:
            out.append((lines["event"], json.loads(lines["data"])))
    return out


def test_queue_poll_carries_progress(client):
    client.post("/analyze", files={"image": ("a.png", png())}, data={"ticket": "tick-0001"})
    out = client.get("/queue", params={"ticket": "tick-0001"}).json()
    prog = out["progress"]
    assert prog["state"] == "done" and [s["state"] for s in prog["stages"]] == ["done"] * len(prog["stages"])
    assert {s["key"] for s in prog["stages"]} >= {"decode", "ocr", "judge:rules", "codes"}


def test_sse_done_for_finished_ticket(client):
    client.post("/analyze", files={"image": ("a.png", png())}, data={"ticket": "tick-0002"})
    r = client.get("/progress", params={"ticket": "tick-0002"})
    assert r.headers["content-type"].startswith("text/event-stream")
    events = sse_events(r.text)
    assert events[-1][0] == "done" and events[-1][1]["state"] == "done"


def test_sse_gives_up_on_unknown_ticket(client, monkeypatch):
    import server
    monkeypatch.setattr(server, "SSE_UNKNOWN_GIVEUP_S", 0.0)
    events = sse_events(client.get("/progress", params={"ticket": "nobody-123"}).text)
    assert events == [("gone", {})]


def test_sse_bad_ticket_400(client):
    assert client.get("/progress", params={"ticket": "../x"}).status_code == 400


def test_sse_streams_running_then_done(client, monkeypatch):
    """분석이 도는 동안 SSE 가 진행 상태를 보내고, 끝나면 done 으로 닫는다."""
    import server
    from pipeline.types import Box, TextSpan

    gate = threading.Event()

    class Slow:
        name = "slow"
        ready = True

        def read(self, image):
            gate.wait(5)
            return [TextSpan("받는분 010-1234-5678", Box(10, 10, 200, 20), 0.95)]

    monkeypatch.setattr(server, "_backend", Slow())
    monkeypatch.setattr(server, "SSE_POLL_S", 0.05)
    worker = threading.Thread(target=lambda: client.post(
        "/analyze", files={"image": ("a.png", png())}, data={"ticket": "tick-0003"}))
    worker.start()
    seen = []
    with client.stream("GET", "/progress", params={"ticket": "tick-0003"}) as r:
        buf = ""
        for chunk in r.iter_text():
            buf += chunk
            seen = sse_events(buf)
            if any(e == "progress" and d["state"] == "running" for e, d in seen):
                gate.set()
            if seen and seen[-1][0] == "done":
                break
    worker.join(5)
    running = [d for e, d in seen if e == "progress" and d["state"] == "running"]
    assert running and running[0]["stages"][running[0]["current"]]["label"] in ("사진 열기", "글자 읽기")
    assert seen[-1] == ("done", seen[-1][1]) and seen[-1][1]["state"] == "done"
    assert "010" not in json.dumps(seen, ensure_ascii=False)       # 내용은 보내지 않는다


def test_failed_request_marked_failed(client):
    client.post("/analyze", files={"image": ("a.txt", b"not an image")}, data={"ticket": "tick-0004"})
    assert client.get("/queue", params={"ticket": "tick-0004"}).json()["progress"]["state"] == "failed"
