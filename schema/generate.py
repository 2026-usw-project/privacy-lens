"""
스키마 산출물 생성 + 예시 검증
  python -m schema.generate        (privacy-lens/ 에서 실행)
"""
import json
from pathlib import Path

from .models import AnalyzeResponse, ErrorResponse, ObjectLabel

HERE = Path(__file__).parent

# 1) JSON Schema 파일 생성
for model, name in [(AnalyzeResponse, "analyze_response"), (ErrorResponse, "error_response")]:
    out = HERE / f"{name}.schema.json"
    out.write_text(json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", out.name)

# 2) YOLO data.yaml 용 클래스 목록 (인덱스 순서 = Enum 순서)
names = [e.value for e in ObjectLabel]
(HERE / "classes.txt").write_text("\n".join(names) + "\n", encoding="utf-8")
print("wrote classes.txt:", names)

# 3) 예시 응답 검증
for f in sorted((HERE / "examples").glob("*.json")):
    AnalyzeResponse.model_validate_json(f.read_text(encoding="utf-8"))
    print("valid", f.name)
