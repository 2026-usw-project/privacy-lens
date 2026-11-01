"""가상 개인정보 생성기. 판단 평가(eval.judgment)와 촬영용 소품(samples.props)이 같이 쓴다.

전부 가짜다. 이름은 흔한 성씨 + 이름 글자를 섞고, 번호는 무작위,
메일은 예약 도메인(example.com), 카드는 실제 카드사에 없는 9로 시작하는 번호다.
주민번호·카드·사업자번호는 형식 검증(체크섬)을 통과하게 만든다. 검증을 통과해야
판단 코드가 실제와 같은 경로로 처리하기 때문이다.
"""

from __future__ import annotations

import random

from pipeline import kr_patterns as kp

SURN = "김이박최정강조윤장임한오서신권황안송"
GIVEN = "민서지현우준수연하은도윤예성진유아원호영"
ROADS = ["가온로", "누리로", "한빛로", "새솔길", "다온로", "푸른숲길", "별빛로", "이음로"]
CITIES = [("수원시", "팔달구"), ("용인시", "기흥구"), ("화성시", "동탄구"), ("성남시", "분당구"),
          ("서울특별시", "마포구"), ("안양시", "동안구")]
SCHOOLS = ["한빛대학교", "누리대학교", "다온대학교"]
COMPANIES = ["누리전자", "가온물산", "한빛시스템"]
BANKS = ["국민", "신한", "우리", "하나", "농협"]
# 이름처럼 생긴(흔한 성씨로 시작하는 2~4글자) 일반 낱말. 오탐 시험용
NAME_LIKE_WORDS = ["김밥나라", "정성식당", "조은약국", "한우리", "강남역", "박하사탕", "이마트",
                   "최고급", "장보기", "임대문의", "오늘특가", "신상품"]


class Fake:
    def __init__(self, seed: int):
        self.r = random.Random(seed)

    def name(self) -> str:
        return self.r.choice(SURN) + self.r.choice(GIVEN) + self.r.choice(GIVEN)

    def mobile(self) -> str:
        return f"010-{self.r.randint(2000, 9999)}-{self.r.randint(1000, 9999)}"

    def landline(self) -> str:
        return f"031-{self.r.randint(200, 999)}-{self.r.randint(1000, 9999)}"

    def road(self) -> str:
        city, gu = self.r.choice(CITIES)
        return f"{city} {gu} {self.r.choice(ROADS)} {self.r.randint(3, 280)}"

    def unit(self) -> str:
        return f"{self.r.randint(101, 115)}동 {self.r.randint(1, 25)}{self.r.randint(1, 4):02d}호"

    def rrn(self) -> str:
        while True:
            yy, mm, dd = self.r.randint(80, 99), self.r.randint(1, 12), self.r.randint(1, 28)
            body = f"{yy:02d}{mm:02d}{dd:02d}{self.r.choice('12')}{self.r.randint(0, 99999):05d}"
            w = [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5]
            check = (11 - sum(int(body[i]) * w[i] for i in range(12)) % 11) % 10
            full = body + str(check)
            if kp.valid_rrn(full):
                return f"{full[:6]}-{full[6:]}"

    def card(self) -> str:
        digits = [9] + [self.r.randint(0, 9) for _ in range(14)]
        for last in range(10):
            d = "".join(map(str, digits + [last]))
            if kp.valid_luhn(d):
                return "-".join(d[i:i + 4] for i in range(0, 16, 4))
        raise AssertionError

    def account(self) -> str:
        return f"{self.r.randint(100, 999)}-{self.r.randint(100000, 999999)}-{self.r.randint(10, 99)}-{self.r.randint(100, 999)}"

    def tracking(self) -> str:
        return "".join(str(self.r.randint(0, 9)) for _ in range(12))

    def brn(self) -> str:
        while True:
            d = "".join(str(self.r.randint(0, 9)) for _ in range(10))
            if kp.valid_brn(d):
                return f"{d[:3]}-{d[3:5]}-{d[5:]}"

    def email(self) -> str:
        return f"{self.r.choice(['minsu', 'jiyoon', 'hana', 'dohyun'])}{self.r.randint(10, 99)}@example.com"

    def pick(self, seq):
        return self.r.choice(seq)
