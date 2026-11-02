"""단계별 시간 기록과 추정(timing.py), 파이프라인 단계 알림, 서버 기록."""

import json

import pytest
from PIL import Image

from pipeline import analyze, llm_judge, ocr
from pipeline.types import Box, TextSpan
from timing import Estimator, TimingStore, fallback_chain


# ------------------------------------------------------------------ 추정기

def test_no_records_no_number():
    store = TimingStore(None)
    assert store.estimate("ocr:paddleocr", 3.0) == (None, None)


def test_few_records_scale_by_size():
    est = Estimator()
    est.update(2.0, 4.0)
    est.update(2.0, 4.0)
    assert est.predict(4.0) == pytest.approx(8.0)   # 기록이 적으면 평균 × 크기 비율
    assert est.predict() == pytest.approx(4.0)


def test_fit_fixed_plus_per_unit():
    est = Estimator()
    for units in (10, 20, 40, 80):                   # 걸린 시간 = 2초 + 0.1초 × 조각 수
        est.update(units, 2 + 0.1 * units)
    assert est.predict(100) == pytest.approx(12.0, rel=1e-6)
    assert est.predict(0) == pytest.approx(2.0, rel=1e-6)


def test_recent_records_weigh_more():
    est = Estimator()
    for _ in range(10):
        est.update(1.0, 10.0)
    for _ in range(10):
        est.update(1.0, 2.0)
    assert est.predict(1.0) < 5.0                    # 그냥 평균이면 6초. 최근 쪽(2초)으로 기운다


def test_one_off_spike_damped():
    est = Estimator()
    for _ in range(5):
        est.update(1.0, 2.0)
    est.update(1.0, 60.0)                            # 엔진 재시작 같은 한 번의 사고
    plain = Estimator()
    for _ in range(5):
        plain.update(1.0, 2.0)
    plain.n, plain.sy = plain.n * 0.9 + 1, plain.sy * 0.9 + 60   # 감쇠 없이 그대로 넣었다면
    assert est.predict(1.0) < plain.sy / plain.n


# ------------------------------------------------------------------ 빌려 쓰기

def test_fallback_chain_stops_at_llm():
    assert fallback_chain("judge:llm:gemini:gemini-flash-latest") == [
        "judge:llm:gemini:gemini-flash-latest", "judge:llm:gemini", "judge:llm"]
    assert fallback_chain("judge:rules") == ["judge:rules"]
    assert fallback_chain("ocr:paddleocr") == ["ocr:paddleocr", "ocr"]


def test_new_model_borrows_then_uses_its_own():
    store = TimingStore(None)
    for _ in range(3):
        store.record("judge:llm:openai:gpt-x", 20, 10.0)
    secs, basis = store.estimate("judge:llm:gemini:flash", 20)
    assert basis == "judge:llm" and secs == pytest.approx(10.0)        # 처음 쓰는 공급자: LLM 전체 기록

    store.record("judge:llm:gemini:flash", 20, 4.0)
    assert store.estimate("judge:llm:gemini:flash", 20)[1] == "judge:llm"   # 한 건으로는 아직 넓은 쪽
    store.record("judge:llm:gemini:flash", 20, 4.0)
    store.record("judge:llm:gemini:flash", 20, 4.0)
    secs, basis = store.estimate("judge:llm:gemini:flash", 20)
    assert basis == "judge:llm:gemini:flash" and secs == pytest.approx(4.0)  # 3건이 쌓이면 자기 값


def test_rules_never_borrow_llm():
    store = TimingStore(None)
    for _ in range(3):
        store.record("judge:llm:openai:gpt-x", 20, 10.0)
    assert store.estimate("judge:rules", 20) == (None, None)


def test_narrow_key_used_when_nothing_broader_is_solid():
    store = TimingStore(None)
    store.record("ocr:tesseract", 2.0, 1.0)
    secs, basis = store.estimate("ocr:tesseract", 2.0)
    assert basis == "ocr:tesseract" and secs == pytest.approx(1.0)


def test_bad_inputs_ignored():
    store = TimingStore(None)
    store.record("ocr", 1.0, -1.0)
    store.record("ocr", -1.0, 1.0)
    store.record("ocr", 1.0, float("nan"))
    store.record("", 1.0, 1.0)
    assert store.snapshot() == {}


# ------------------------------------------------------------------ 파일

def test_saved_and_loaded(tmp_path):
    path = tmp_path / "sub" / "timing.json"
    store = TimingStore(path, autosave=False)
    for _ in range(3):
        store.record("judge:llm:gemini:m", 10, 5.0)
    store.flush()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == 1 and set(data["keys"]) == {"judge:llm:gemini:m", "judge:llm:gemini", "judge:llm"}
    again = TimingStore(path)
    assert again.estimate("judge:llm:gemini:m", 10)[0] == pytest.approx(5.0)
    assert not list(path.parent.glob(".timing-*"))   # 임시 파일이 남지 않는다


def test_only_numbers_and_stage_keys_saved(tmp_path):
    path = tmp_path / "timing.json"
    store = TimingStore(path, autosave=False)
    store.record("ocr:paddleocr", 3.2, 2.5)
    store.flush()
    data = json.loads(path.read_text(encoding="utf-8"))
    entry = data["keys"]["ocr:paddleocr"]
    assert set(entry) == {"n", "sx", "sy", "sxx", "sxy", "count"}
    assert all(isinstance(v, (int, float)) for v in entry.values())


@pytest.mark.parametrize("content", ["not json", '{"version": 99, "keys": {}}', '{"version": 1, "keys": {"a": {"n": "x"}}}',
                                     '{"version": 1, "keys": {"a": {"n": -1, "sx": 0, "sy": 0, "sxx": 0, "sxy": 0, "count": 1}}}'])
def test_broken_file_starts_fresh(tmp_path, content):
    path = tmp_path / "timing.json"
    path.write_text(content, encoding="utf-8")
    store = TimingStore(path)
    assert store.snapshot() == {}
    store.record("ocr", 1.0, 1.0)                    # 그대로 기록하고 저장할 수 있다
    store.flush()
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1


def test_unwritable_location_keeps_memory(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    store = TimingStore(blocker / "timing.json", autosave=False)   # 부모가 파일이라 쓸 수 없다
    store.record("ocr", 1.0, 1.0)
    store.flush()
    assert store.estimate("ocr", 1.0)[0] == pytest.approx(1.0)


def test_autosave_throttled(tmp_path, monkeypatch):
    import timing
    path = tmp_path / "timing.json"
    store = TimingStore(path)
    store.record("ocr", 1.0, 1.0)
    assert path.exists()                             # 처음 기록은 바로 쓴다
    first = path.read_text(encoding="utf-8")
    store.record("ocr", 1.0, 3.0)
    assert path.read_text(encoding="utf-8") == first # 5초 안에는 다시 쓰지 않는다
    monkeypatch.setattr(timing, "SAVE_EVERY_S", 0.0)
    store.record("ocr", 1.0, 3.0)
    assert path.read_text(encoding="utf-8") != first


# ------------------------------------------------------------------ 파이프라인 단계

SPANS = [TextSpan("받는분 010-1234-5678", Box(10, 10, 200, 20), 0.95),
         TextSpan("고객센터 1588-0000", Box(10, 40, 200, 20), 0.95)]


def test_analyze_reports_stages_with_sizes():
    events = []
    img = Image.new("RGB", (2000, 1000), "white")
    analyze.analyze(img, backend=ocr.ScriptedBackend(SPANS), detector=None,
                    on_stage=lambda *e: events.append(e))
    ends = {name: (units, secs) for ev, name, units, secs in events if ev == "end"}
    starts = [name for ev, name, *_ in events if ev == "start"]
    assert starts == ["ocr:scripted", "judge:rules", "codes"]
    assert ends["ocr:scripted"][0] == pytest.approx(2.0)          # 메가픽셀
    assert ends["judge:rules"][0] == 2                             # 조각 수
    assert all(secs >= 0 for _, secs in ends.values())


def test_llm_stage_key_and_failed_stage_not_reported():
    events = []

    def boom(*_):
        raise llm_judge.LlmJudgeError("x")

    cfg = llm_judge.JudgeConfig("gemini", "m-1", "k")
    with pytest.raises(llm_judge.LlmJudgeError):
        analyze.analyze(Image.new("RGB", (100, 100)), backend=ocr.ScriptedBackend(SPANS), detector=None,
                        judge=cfg, llm_transport=boom, on_stage=lambda *e: events.append(e))
    assert ("start", "judge:llm:gemini:m-1", 2, None) in events
    assert not any(ev == "end" and name.startswith("judge") for ev, name, *_ in events)


def test_broken_callback_does_not_break_analysis():
    def bad(*_):
        raise RuntimeError("시간 기록 실패")
    report = analyze.analyze(Image.new("RGB", (100, 100)), backend=ocr.ScriptedBackend(SPANS),
                             detector=None, on_stage=bad)
    assert any(f.kind == "mobile" for f in report.findings)


# ------------------------------------------------------------------ 서버

def test_server_records_stages(monkeypatch):
    pytest.importorskip("httpx")
    import io

    from fastapi.testclient import TestClient

    import server

    store = TimingStore(None)
    monkeypatch.setattr(server, "TIMING", store)
    monkeypatch.setattr(server, "_backend", ocr.ScriptedBackend(SPANS))
    buf = io.BytesIO()
    Image.new("RGB", (300, 200), "white").save(buf, "PNG")
    client = TestClient(server.app)
    assert client.post("/analyze", files={"image": ("a.png", buf.getvalue())}).status_code == 200
    keys = set(store.snapshot())
    assert {"decode", "ocr:scripted", "ocr", "judge:rules", "codes"} <= keys

    r = client.post("/redact", files={"image": ("a.png", buf.getvalue())}, data={"boxes": "[]"})
    assert r.status_code == 200
    assert {"mask", "export"} <= set(store.snapshot())


def test_cold_engine_ocr_not_recorded():
    import server

    class Cold:
        ready = False

    store = TimingStore(None)
    original = server.TIMING
    server.TIMING = store
    try:
        rec = server._recorder(Cold())
        rec("end", "ocr:paddleocr", 1.0, 70.0)       # 엔진 만드는 시간까지 먹은 OCR
        rec("end", "judge:rules", 3, 0.01)
    finally:
        server.TIMING = original
    assert set(store.snapshot()) == {"judge:rules"}
