"""OCR 어댑터.

OCR 엔진을 갈아끼울 수 있게 분리해둔다. 이유가 두 가지 있다.

1. 규칙 엔진(kr_patterns, context, grouping)을 OCR 없이 테스트할 수 있다.
   OCR은 느리고 무겁고 환경을 탄다. 핵심 로직이 거기에 묶이면 안 된다.
2. 비교 실험에서 OCR을 고정한 채 규칙만 바꿔야 한다. 엔진이 섞이면
   무엇 때문에 숫자가 움직였는지 말할 수 없다.

기본 백엔드는 Tesseract다. 배경의 작고 기울어진 한글에는 약하다.
실제 측정에서는 PaddleOCR로 바꿔 끼우고, Tesseract 결과는 베이스라인으로 둔다.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import threading
from pathlib import Path
from typing import Protocol

from PIL import Image

from .types import Box, TextSpan


class OcrBackend(Protocol):
    name: str

    def read(self, image: Image.Image) -> list[TextSpan]: ...


_WINDOWS_TESSERACT = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    str(Path.home() / r"AppData\Local\Programs\Tesseract-OCR\tesseract.exe"),
    str(Path.home() / r"AppData\Local\Tesseract-OCR\tesseract.exe"),
]


def locate_tesseract() -> str | None:
    """PL_TESSERACT 가 있으면 그것을, 없으면 PATH와 기본 설치 경로를 훑는다.

    Windows 설치 프로그램은 PATH를 자동으로 잡아주지 않는 경우가 많다.
    """
    override = os.environ.get("PL_TESSERACT")
    if override:
        return override if Path(override).exists() else None
    found = shutil.which("tesseract")
    if found:
        return found
    if sys.platform == "win32":
        for candidate in _WINDOWS_TESSERACT:
            if Path(candidate).exists():
                return candidate
    return None


class TesseractBackend:
    """설치 필요:
        Windows  https://github.com/UB-Mannheim/tesseract/wiki  (설치 시 Korean 언어 선택)
        macOS    brew install tesseract tesseract-lang
        Linux    sudo apt install tesseract-ocr tesseract-ocr-kor
    """

    name = "tesseract"

    def __init__(self, lang: str = "kor+eng", psm: int = 11):
        self.lang = lang
        self.psm = psm
        self._checked = False

    def _ensure(self) -> None:
        if self._checked:
            return
        import pytesseract

        exe = locate_tesseract()
        if exe is None:
            raise RuntimeError(
                "Tesseract 실행 파일을 찾지 못했습니다.\n"
                "  Windows: https://github.com/UB-Mannheim/tesseract/wiki 에서 설치하고,\n"
                "           설치 중 Additional language data 에서 Korean 을 선택하세요.\n"
                "  macOS:   brew install tesseract tesseract-lang\n"
                "  Linux:   sudo apt install tesseract-ocr tesseract-ocr-kor\n"
                "  이미 설치했다면 PL_TESSERACT 환경변수에 exe 경로를 지정하세요.\n"
                "  (PL_TESSERACT 를 지정했다면 그 경로에 파일이 있는지 확인하세요.)"
            )
        pytesseract.pytesseract.tesseract_cmd = exe

        try:
            langs = pytesseract.get_languages(config="")
        except Exception:
            langs = []
        if langs and "kor" not in langs:
            raise RuntimeError(
                "Tesseract는 찾았지만 한국어 데이터(kor)가 없습니다.\n"
                f"  설치된 언어: {', '.join(sorted(langs)) or '(없음)'}\n"
                "  Windows: 설치 프로그램을 다시 실행해 Korean 을 추가하세요.\n"
                "  Linux:   sudo apt install tesseract-ocr-kor"
            )
        self._checked = True

    def read(self, image: Image.Image) -> list[TextSpan]:
        self._ensure()

        import pytesseract
        from pytesseract import Output

        data = pytesseract.image_to_data(
            image,
            lang=self.lang,
            config=f"--psm {self.psm}",
            output_type=Output.DICT,
        )

        spans: list[TextSpan] = []
        for i, raw in enumerate(data["text"]):
            text = raw.strip()
            if not text:
                continue
            try:
                conf = float(data["conf"][i])
            except (TypeError, ValueError):
                conf = -1.0
            if conf < 0:
                continue
            spans.append(
                TextSpan(
                    text=text,
                    box=Box(
                        int(data["left"][i]),
                        int(data["top"][i]),
                        int(data["width"][i]),
                        int(data["height"][i]),
                    ),
                    ocr_confidence=conf / 100.0,
                )
            )
        return merge_lines(spans)


# 검출은 v6. 한국어 인식은 v6 가 없어 lang 기본값(korean_PP-OCRv5_mobile_rec)으로 채운다.
# 합성 송장 3종 × 원본/책상 × 7각도(126개 정답) 측정, PaddleOCR 3.7 / paddlepaddle 3.2.2:
#   v5 검출 101/126, v6 검출 101/126. 합계는 같고 v6 가 1.5배 빠르다.
#   다만 실패하는 각도가 다르다. 45° 는 v5 10/18 · v6 18/18,
#   135°(비스듬히 뒤집힘) 는 v5 7/18 · v6 0/18. 뒤집힌 사진이 많으면 'auto' 로.
PADDLE_DEFAULT_DET = "PP-OCRv6_medium_det"


class PaddleBackend:
    """PaddleOCR 2.x / 3.x 양쪽 지원.

        pip install paddleocr 'paddlepaddle<3.3'

    3.x에서 API가 크게 바뀌었다.
      - `use_angle_cls` → `use_textline_orientation`
      - `show_log` 삭제
      - `.ocr(img, cls=True)` → `.predict(img)`
      - 결과가 중첩 리스트 → rec_texts / rec_polys / rec_scores 딕셔너리

    버전을 고정하는 대신 생성자 시그니처를 들여다보고 지원하는 인자만 넘긴다.
    결과도 두 형식을 다 받는다. 사용자가 어떤 버전을 깔았는지 알 수 없기 때문이다.

    모델 가중치를 처음 한 번 내려받는다. 오프라인 환경이면 미리 받아둘 것.

    모델은 환경변수로 고른다(3.x 전용).

      PL_PADDLE_LANG  기본 korean
      PL_PADDLE_DET   검출 모델. 기본 PP-OCRv6_medium_det.
                      'auto' 면 PaddleOCR 가 lang 으로 고르는 것(PP-OCRv5_server_det)
      PL_PADDLE_REC   인식 모델. 예: korean_PP-OCRv5_mobile_rec

    주의: PaddleOCR 3.x 는 모델 이름을 **하나라도** 넘기면 lang 을 무시한다.
    검출만 바꾸면 인식이 한국어를 모르는 기본 모델(PP-OCRv6_medium_rec)로
    떨어진다. 그래서 빠진 쪽은 lang 기준 기본값으로 직접 채운다.
    PP-OCRv6 는 한국어를 지원하지 않는다(3.7 기준). 한국어 인식은
    korean_PP-OCRv5_mobile_rec 가 최신이다.
    """

    name = "paddleocr"

    def __init__(
        self,
        lang: str | None = None,
        det_model: str | None = None,
        rec_model: str | None = None,
    ):
        import inspect

        import paddleocr
        from paddleocr import PaddleOCR

        lang = lang or os.environ.get("PL_PADDLE_LANG", "korean")
        det_model = det_model or os.environ.get("PL_PADDLE_DET") or None
        rec_model = rec_model or os.environ.get("PL_PADDLE_REC") or None
        explicit = bool(det_model or rec_model)

        allowed = set(inspect.signature(PaddleOCR.__init__).parameters)
        by_name = "text_detection_model_name" in allowed  # 3.x

        if explicit and not by_name:
            raise RuntimeError(
                "PL_PADDLE_DET / PL_PADDLE_REC 는 PaddleOCR 3.x 에서만 쓸 수 있습니다."
            )
        # 기본 검출기는 3.x 에서만 건다. 2.x 는 모델을 이름으로 고를 수 없다.
        if det_model is None and by_name:
            det_model = PADDLE_DEFAULT_DET
        if det_model == "auto":  # PaddleOCR 가 lang 으로 고르는 조합(v5 검출)으로
            det_model = None
        if bool(det_model) != bool(rec_model):
            default_det, default_rec = _paddle_defaults(PaddleOCR, lang)
            det_model = det_model or default_det
            rec_model = rec_model or default_rec

        wanted = {
            "lang": lang,
            # 3.x 이름
            "text_detection_model_name": det_model,
            "text_recognition_model_name": rec_model,
            "use_textline_orientation": True,
            "use_doc_orientation_classify": False,  # 추가 모델 다운로드 회피
            "use_doc_unwarping": False,             # 스캔 문서용이라 생활 사진에 부적합
            # 2.x 이름
            "use_angle_cls": True,
            "show_log": False,
        }
        kwargs = {k: v for k, v in wanted.items() if k in allowed}

        # 2.x 와 3.x 이름이 동시에 통과하는 일은 없지만, 만약을 대비해 정리한다.
        if "use_textline_orientation" in kwargs:
            kwargs.pop("use_angle_cls", None)
        # 모델을 직접 고르면 lang 은 무시된다. 경고가 뜨지 않게 아예 빼둔다.
        if kwargs.get("text_detection_model_name"):
            kwargs.pop("lang", None)
        else:
            kwargs.pop("text_detection_model_name", None)
            kwargs.pop("text_recognition_model_name", None)

        self._engine = PaddleOCR(**kwargs)
        self._predict = getattr(self._engine, "predict", None) or self._engine.ocr
        self._lock = threading.Lock()

        # 화면과 비교 실험에 실제로 쓴 모델 이름을 남긴다. 'paddleocr' 만으로는
        # 어떤 조합의 숫자인지 알 수 없다.
        self.models = _resolved_models(self._engine)
        version = getattr(paddleocr, "__version__", "?")
        parts = [m for m in (self.models.get("det"), self.models.get("rec")) if m]
        self.name = f"paddleocr {version}"
        if parts:
            self.name += " · " + " + ".join(parts)

    @staticmethod
    def _as_mapping(res):
        """3.x 결과 객체에서 딕셔너리를 꺼낸다. 접근 방식이 버전마다 다르다."""
        for getter in (
            lambda r: r if isinstance(r, dict) and "rec_texts" in r else None,
            lambda r: r["res"] if isinstance(r, dict) and "res" in r else None,
            lambda r: getattr(r, "json", {}).get("res"),
            lambda r: dict(r) if hasattr(r, "keys") else None,
        ):
            try:
                got = getter(res)
            except Exception:
                continue
            if isinstance(got, dict) and "rec_texts" in got:
                return got
        return None

    @staticmethod
    def _box_from_poly(poly) -> Box:
        """외곽선을 감싸는 축 정렬 사각형 + 외곽선 자체(가릴 때 쓴다)."""
        pts = tuple((float(pt[0]), float(pt[1])) for pt in poly)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return Box(int(min(xs)), int(min(ys)),
                   int(max(xs) - min(xs)), int(max(ys) - min(ys)),
                   poly=pts if len(pts) >= 3 else None)

    def read(self, image: Image.Image) -> list[TextSpan]:
        import numpy as np

        # Paddle 추론기는 스레드 안전하지 않다. 서버가 요청을 스레드풀에서 돌리므로
        # 두 요청이 동시에 들어오면 서로의 중간 텐서를 덮어써서
        # 'Broadcast dimension mismatch' 로 죽는다(실제로 겪었다). 한 번에 하나씩.
        with self._lock:
            result = self._predict(np.array(image.convert("RGB")))
        spans: list[TextSpan] = []

        for page in result or []:
            data = self._as_mapping(page)

            if data is not None:  # --- 3.x ---
                # numpy 배열이 섞여 오므로 `or []` 로 기본값을 주면 안 된다.
                # 배열의 진리값 판정은 ValueError 가 난다.
                def _seq(key):
                    v = data.get(key)
                    return [] if v is None else list(v)

                texts = _seq("rec_texts")
                scores = _seq("rec_scores")
                polys = _seq("rec_polys") or _seq("dt_polys")

                for i, text in enumerate(texts):
                    text = (text or "").strip()
                    if not text:
                        continue
                    conf = float(scores[i]) if i < len(scores) else 1.0
                    if i < len(polys):
                        box = self._box_from_poly(polys[i])
                    else:
                        boxes = _seq("rec_boxes")
                        if i >= len(boxes):
                            continue
                        x0, y0, x1, y1 = (int(v) for v in boxes[i])
                        box = Box(x0, y0, x1 - x0, y1 - y0)
                    spans.append(TextSpan(text=text, box=box, ocr_confidence=conf))
                continue

            # --- 2.x: [[quad, (text, conf)], ...] ---
            for line in page or []:
                try:
                    quad, (text, conf) = line
                except (TypeError, ValueError):
                    continue
                text = (text or "").strip()
                if not text:
                    continue
                spans.append(
                    TextSpan(text=text, box=self._box_from_poly(quad),
                             ocr_confidence=float(conf))
                )

        return spans


def _paddle_defaults(PaddleOCR, lang: str) -> tuple[str | None, str | None]:
    """lang 에 해당하는 PaddleOCR 기본 (검출, 인식) 모델 이름.

    PaddleOCR 내부 함수를 빌려 쓴다. self 를 쓰지 않는 함수라 클래스에서 바로
    부른다. 없어지면 둘 다 지정하라고 안내한다.
    """
    resolver = getattr(PaddleOCR, "_get_ocr_model_names", None)
    if resolver is None:
        raise RuntimeError("PL_PADDLE_DET 와 PL_PADDLE_REC 를 둘 다 지정하세요.")
    det, rec = resolver(None, lang, None)
    if det is None or rec is None:
        raise RuntimeError(f"lang={lang!r} 에 맞는 PaddleOCR 기본 모델이 없습니다.")
    return det, rec


def _resolved_models(engine) -> dict:
    """생성된 엔진이 실제로 쓰는 모델 이름. 버전마다 위치가 달라 조심스럽게 꺼낸다."""
    models: dict = {}
    params = getattr(engine, "_params", None) or {}
    models["det"] = params.get("text_detection_model_name")
    models["rec"] = params.get("text_recognition_model_name")
    try:
        sub = engine._merged_paddlex_config["SubModules"]
        models["det"] = models["det"] or sub["TextDetection"]["model_name"]
        models["rec"] = models["rec"] or sub["TextRecognition"]["model_name"]
        if params.get("use_textline_orientation"):
            models["textline"] = sub["TextLineOrientation"]["model_name"]
    except (AttributeError, KeyError, TypeError):
        pass
    return {k: v for k, v in models.items() if v}


class ScriptedBackend:
    """테스트용. 미리 정해둔 결과를 그대로 돌려준다.

    규칙 엔진 단위 테스트와 UI 데모에 쓴다. 실제 성능 측정에는 쓰지 않는다.
    """

    name = "scripted"

    def __init__(self, spans: list[TextSpan]):
        self._spans = spans

    def read(self, image: Image.Image) -> list[TextSpan]:
        return list(self._spans)


def merge_lines(spans: list[TextSpan], gap_em: float = 1.2) -> list[TextSpan]:
    """같은 줄의 낱말 조각을 잇는다.

    Tesseract는 '010', '-', '1234' 를 따로 뱉는 일이 잦다. 그대로 두면
    전화번호 정규식이 하나도 안 걸린다. 줄 단위로 붙여야 패턴이 산다.
    """
    if not spans:
        return []

    # 조각 쌍마다 '같은 줄이고 가깝다'를 판정해 이어 붙인다(union-find).
    # 앞에서부터 한 행씩 채우는 방식은 처리 순서를 탄다. '121 동 1655 호' 에서
    # '호'가 '121'보다 먼저 와서 따로 떨어지는 일이 있었다.
    n = len(spans)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        a = spans[i].box
        for j in range(i + 1, n):
            b = spans[j].box
            # 작은 쪽 높이로 잰다. Tesseract 는 '구', '선로' 같은 글자에
            # 실제보다 두 배 큰 상자를 주기도 해서, 큰 쪽 기준이면
            # 바로 아래 줄(동·호수)까지 한 줄로 섞어버린다.
            same_line = abs(a.cy - b.cy) <= min(a.h, b.h) * 0.6
            # 기울어진 문서에서는 도착 순서가 좌→우가 아니다. 양쪽 방향으로 잰다.
            gap = max(b.x - (a.x + a.w), a.x - (b.x + b.w))
            if same_line and gap <= max(a.h, b.h, 10) * gap_em:
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[rj] = ri

    buckets: dict[int, list[TextSpan]] = {}
    for i in range(n):
        buckets.setdefault(find(i), []).append(spans[i])
    rows = sorted(buckets.values(), key=lambda r: min(p.box.cy for p in r))

    merged: list[TextSpan] = []
    for row in rows:
        row.sort(key=lambda p: p.box.x)  # 읽는 순서로 되돌린다
        text = "".join(
            part.text if re.match(r"^[\-.\s]$", part.text) else part.text + " "
            for part in row
        ).strip()
        x0 = min(p.box.x for p in row)
        y0 = min(p.box.y for p in row)
        x1 = max(p.box.x + p.box.w for p in row)
        y1 = max(p.box.y + p.box.h for p in row)
        merged.append(
            TextSpan(
                text=text,
                box=Box(x0, y0, x1 - x0, y1 - y0),
                ocr_confidence=sum(p.ocr_confidence for p in row) / len(row),
            )
        )
    return merged


def get_backend(name: str | None = None) -> OcrBackend:
    name = (name or os.environ.get("PL_OCR", "paddleocr")).lower()

    if name == "none":
        return ScriptedBackend([])

    if name == "paddleocr":
        try:
            return PaddleBackend()
        except ImportError as exc:
            raise RuntimeError(
                "PaddleOCR 를 불러오지 못했습니다.\n"
                "  pip install paddleocr 'paddlepaddle<3.3'\n"
                f"  원인: {exc}"
            ) from exc
        except Exception as exc:
            raise RuntimeError(
                "PaddleOCR 초기화에 실패했습니다.\n"
                f"  {type(exc).__name__}: {exc}\n"
                "  처음 실행이면 모델 가중치를 내려받는 중 네트워크 문제일 수 있습니다.\n"
                "  'paddle_static' 오류면 추론 엔진이 없는 것입니다: pip install 'paddlepaddle<3.3'\n"
                "  Tesseract 로 돌리려면 PL_OCR=tesseract 로 설정하고 다시 실행하세요."
            ) from exc

    return TesseractBackend()
