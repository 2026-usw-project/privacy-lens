"""YOLO 클래스 목록.

번호가 곧 라벨 파일의 첫 숫자다. **이미 있는 번호는 절대 바꾸거나 지우지 않는다.**
번호를 바꾸면 그동안 만든 라벨 전부가 다른 물건을 가리키게 된다.
새 클래스는 맨 뒤에 붙인다. 붙인 뒤에는 기존 모델로 이어서 학습할 수 없으니
`python -m vision train --base yolo11n.pt` 로 처음부터 다시 학습한다.
"""

from __future__ import annotations

# (영문 이름, 화면에 보일 한글 이름, 라벨링 기준)
CLASSES: list[tuple[str, str, str]] = [
    ("waybill", "송장", "택배 송장·운송장 스티커. 종이 가장자리까지 박스"),
    ("id_card", "학생증·카드", "학생증·사원증·신분증·카드류. 카드 테두리까지"),
    ("name_tag", "명찰", "가슴에 다는 명찰, 책상 이름표"),
    ("screen", "화면", "글자가 보이는 모니터·휴대폰·노트북 화면. 화면 부분만"),
    ("face_photo", "증명사진", "카드·서류에 인쇄된 증명사진만. 실제 사람 얼굴은 박스 안 함"),
    ("barcode", "바코드·QR", "바코드와 QR 코드"),
]

NAMES: dict[int, str] = {i: c[0] for i, c in enumerate(CLASSES)}
LABELS_KO: dict[int, str] = {i: c[1] for i, c in enumerate(CLASSES)}


def as_json() -> list[dict]:
    """라벨링 도구가 읽는 형식."""
    return [
        {"id": i, "name": name, "label": ko, "guide": guide}
        for i, (name, ko, guide) in enumerate(CLASSES)
    ]
