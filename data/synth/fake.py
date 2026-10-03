"""
가짜 개인정보 생성기 — 실제 사람과 무관한 무작위 값만 만듭니다.
전화번호는 실제 번호와 겹치지 않도록 국번을 010-0xxx 대역(미할당)으로 고정합니다.
"""
import random

SURNAMES = list("김이박최정강조윤장임한오서신권황안송류홍")
GIVEN = list("민서지현우준예하윤도은수채유진영호연아재건태희성")

ADDR_SI = [
    ("경기도", "수원시", "권선구"), ("경기도", "화성시", None), ("경기도", "용인시", "기흥구"),
    ("경기도", "성남시", "분당구"), ("서울특별시", "강남구", None), ("서울특별시", "마포구", None),
    ("인천광역시", "연수구", None), ("경기도", "오산시", None),
]
ROADS = ["와우안길", "봉담로", "중부대로", "판교역로", "테헤란로", "월드컵북로", "센트럴로", "경기대로", "수성로", "동탄대로"]
COURIERS = ["한빛택배", "새솔로지스", "가람익스프레스"]          # 가상의 택배사
SCHOOLS = ["한빛대학교", "새솔대학교", "가람대학교"]              # 가상의 학교
DEPTS = ["정보보호학과", "컴퓨터공학과", "경영학과", "디자인학과"]
ITEMS = ["의류", "도서", "생활용품", "전자기기", "식품"]


SHOPS = ["맛나식당", "행복약국", "한빛안경", "새솔문구", "가람분식"]           # 가상의 상호


def biz_phone(rng: random.Random) -> str:
    """사업장 유선전화 (02-xxxx-xxxx · 031-xxx-xxxx 등) — 가상 번호"""
    area = rng.choice(["02", "031", "032", "041"])
    mid = rng.randint(2000, 9999) if area == "02" else rng.randint(200, 999)
    return f"{area}-{mid}-{rng.randint(1000, 9999)}"


def biz_address(rng: random.Random) -> str:
    """사업장 주소 (동·호 없음)"""
    do, si, gu = rng.choice(ADDR_SI)
    return " ".join([do, si] + ([gu] if gu else [])) + f" {rng.choice(ROADS)} {rng.randint(1, 399)}"


def name(rng: random.Random) -> str:
    return rng.choice(SURNAMES) + rng.choice(GIVEN) + rng.choice(GIVEN)


def phone(rng: random.Random) -> str:
    return f"010-0{rng.randint(100, 999)}-{rng.randint(1000, 9999)}"


def address(rng: random.Random) -> str:
    do, si, gu = rng.choice(ADDR_SI)
    parts = [do, si] + ([gu] if gu else [])
    detail = f"{rng.randint(1, 30)}동 {rng.randint(101, 1504)}호" if rng.random() < 0.6 else ""
    return " ".join(parts) + f" {rng.choice(ROADS)} {rng.randint(1, 399)}" + (f", {detail}" if detail else "")


def tracking(rng: random.Random) -> str:
    return "".join(str(rng.randint(0, 9)) for _ in range(12))


def student_number(rng: random.Random) -> str:
    return f"20{rng.randint(19, 26)}{rng.randint(1000, 9999)}"


def parcel(rng: random.Random) -> dict:
    return {
        "courier": rng.choice(COURIERS),
        "tracking": tracking(rng),
        "to_name": name(rng), "to_phone": phone(rng), "to_addr": address(rng),
        "from_name": name(rng), "from_phone": phone(rng),
        "item": rng.choice(ITEMS),
    }


def student_card(rng: random.Random) -> dict:
    return {"school": rng.choice(SCHOOLS), "dept": rng.choice(DEPTS),
            "name": name(rng), "number": student_number(rng)}
