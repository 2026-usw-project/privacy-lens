"""실제 OCR 없이 생성·추론의 스레드 일치와 실패 복구를 검증한다."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from PIL import Image

from pipeline.worker import OcrUnavailable, ThreadBoundBackend


def test_creation_and_concurrent_reads_use_one_thread():
    owners, calls = [], []

    class Engine:
        name = "가상 엔진"

        def __init__(self):
            self.owner = threading.get_ident()
            owners.append(self.owner)

        def read(self, image):
            calls.append(threading.get_ident())
            assert threading.get_ident() == self.owner
            return []

    backend = ThreadBoundBackend(Engine)
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(backend.read, [Image.new("RGB", (2, 2)) for _ in range(24)]))
        assert results == [[]] * 24
        assert len(owners) == 1
        assert set(calls) == set(owners)
        assert owners[0] != threading.get_ident()
    finally:
        backend.close()


def test_failed_engine_is_rebuilt_on_same_thread():
    owners = []

    class Engine:
        name = "가상 엔진"

        def __init__(self):
            owners.append(threading.get_ident())
            self.fail = len(owners) == 1

        def read(self, image):
            if self.fail:
                raise RuntimeError("가상 비공개 원문")
            return []

    backend = ThreadBoundBackend(Engine)
    try:
        with pytest.raises(OcrUnavailable) as error:
            backend.read(Image.new("RGB", (2, 2)))
        assert str(error.value) == ""
        assert backend.read(Image.new("RGB", (2, 2))) == []
        assert len(owners) == 2 and owners[0] == owners[1]
    finally:
        backend.close()


def test_initialization_failure_is_sanitized():
    def fail():
        raise RuntimeError("가상 비공개 원문")

    with pytest.raises(OcrUnavailable) as error:
        ThreadBoundBackend(fail)
    assert str(error.value) == ""
