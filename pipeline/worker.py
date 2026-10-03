"""서버 OCR 엔진의 생성과 추론을 같은 전용 스레드에서 실행한다."""

from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from PIL import Image

from .ocr import OcrBackend


class OcrUnavailable(Exception):
    """원문을 노출하지 않고 서버에 OCR 실패를 알린다."""


class ThreadBoundBackend:
    """외부 FIFO 대기열에서 차례를 얻은 요청만 read를 호출한다.

    잠금은 동시 호출만 막는다. Paddle 추론기의 스레드 전환도 막기 위해
    엔진 생성, 추론, 실패한 엔진 해제를 모두 단일 작업자에게 맡긴다.
    """

    def __init__(self, factory: Callable[[], OcrBackend]):
        self._factory = factory
        self._engine = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="privacy-ocr")
        try:
            self.name = self._executor.submit(self._initialize).result()
        except Exception:
            self._executor.shutdown(wait=True)
            raise OcrUnavailable() from None

    def _initialize(self):
        self._engine = self._factory()
        return self._engine.name

    def _read(self, image):
        try:
            if self._engine is None:
                self.name = self._initialize()
            return self._engine.read(image)
        except Exception:
            # 손상됐을 수 있는 추론기는 다음 요청에서 다시 만든다.
            # 이미지나 예외 원문은 로그·응답에 남기지 않는다.
            self._engine = None
            raise OcrUnavailable() from None

    def read(self, image: Image.Image):
        return self._executor.submit(self._read, image).result()

    def _release(self):
        self._engine = None

    def close(self):
        try:
            self._executor.submit(self._release).result()
        finally:
            self._executor.shutdown(wait=True)
