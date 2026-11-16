import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 테스트가 사용자 폴더의 단계 시간 기록(~/.privacy-lens/timing.json)을 건드리지 않게
import os  # noqa: E402
import tempfile  # noqa: E402

os.environ.setdefault("PL_TIMING_PATH", str(Path(tempfile.mkdtemp(prefix="pl-timing-")) / "timing.json"))
# 개발자 PC 의 .env(판단 모델 키 등)가 테스트 결과를 바꾸지 않게. 테스트는 .env 를 읽지 않는다
os.environ["PL_ENV_FILE"] = str(Path(tempfile.mkdtemp(prefix="pl-env-")) / "none.env")
