"""라벨 없는 이름 후보 판정(kp.name_candidate)을 따로 모은 낱말로 잰다.

판단 평가(eval.judgment)의 장면은 규칙을 만든 사람이 만든 틀이라, 이름 규칙의 성능을
거기서만 재면 부풀려진다. 그래서 이름 후보 판정만 떼어 다음 두 목록으로 다시 잰다.

  NAMES  흔한 한국 이름(세대가 다른 이름을 섞음). 성은 흔한 성씨에서 돌아가며 붙인다
  WORDS  사진에 자주 찍히는 3~4글자 낱말 중 흔한 성씨 글자로 시작하는 것(지명·가게·물건·안내문)

한계: 두 목록도 같은 개발자가 적었다. 실사 OCR 결과로 다시 재야 한다(docs/REAL_PHOTO_GUIDE.md).

    python -m eval.names_check
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import kr_patterns as kp  # noqa: E402

GIVEN = """
민준 서준 도윤 예준 시우 하준 지호 주원 지후 준우 준서 건우 현우 우진 선우 연우 유준 정우 승우 승현
시윤 은우 지환 승민 지훈 민재 현준 서연 서윤 지우 서현 민서 하은 하윤 윤서 지유 채원 수아 지민 지아
예은 다은 수빈 유진 은서 예린 수민 소율 지윤 채윤 가은 나은 하린 서아 지안 아린 시아 다인 예서 수연
혜원 은지 영희 철수 미영 정숙 영수 성훈 상철 경희 순자 옥순 영자 정희 미숙 경숙 은영 현정 지현 수진
동현 상현 성민 재원 태민 한결 도현 재훈 상우 민혁 진우 대현 형준 재민 동욱 종민 기현 윤아 소연 미진
""".split()
SURNAMES_CYCLE = "김이박최정강조윤장임한오서신권황안송류전홍고문양손배백허유남심노하곽성차주우구민"

WORDS = """
강남구 서초동 이마트 신세계 조개구이 장난감 정류장 한라산 오리고기 박물관 최신형 안내문 송도점 문구점
양념치킨 손세정제 배달앱 백화점 허브티 유자차 남대문 노트북 하이마트 곽티슈 성수동 차량용 주차장 우유팩
구로구 민트초코 나이키 진라면 지하철 엄마손 원두커피 천연비누 방문객 공지사항 현관문 함박눈 변경사항
염색약 여름철 추가금 도서관 소화기 선물세트 마스크 길거리 표지판 기념품 반찬가게 왕만두 금요일 옥수수
육개장 인스타 제주도 모바일 탁구장 국밥집 어린이 은행나무 편의점 용산구 예약석 경고문 사진관 석촌호수
설렁탕 마라탕 길고양이 하나로 우리밀 신라면 안경점 고급형 문화센터 양재역 손소독 배송비 백설기 허니버터
유기농 남산타워 노래방 심야영업 하루특가 성인용 차단기 주민센터 구매처 민원실 나들이 진열대
""".split()


def run() -> dict:
    names = [SURNAMES_CYCLE[i % len(SURNAMES_CYCLE)] + g for i, g in enumerate(GIVEN)]
    hit = [n for n in names if kp.name_candidate(n)]
    miss = [n for n in names if not kp.name_candidate(n)]
    fp = [w for w in WORDS if kp.name_candidate(w)]
    return {"names": len(names), "hit": len(hit), "miss": miss, "words": len(WORDS), "fp": fp}


def main() -> None:
    r = run()
    print(f"이름 {r['names']}개 중 후보로 고름 {r['hit']}개 ({100 * r['hit'] / r['names']:.0f}%)")
    print(f"  못 고른 이름: {' '.join(r['miss']) or '없음'}")
    print(f"일반 낱말 {r['words']}개 중 이름 후보로 잘못 고름 {len(r['fp'])}개 ({100 * len(r['fp']) / r['words']:.0f}%)")
    print(f"  잘못 고른 낱말: {' '.join(r['fp']) or '없음'}")
    print("\n※ 이 후보만으로는 가리지 않는다. 연락처·주소 옆이거나 명찰·학생증 단서가 있을 때만 가림 권장,"
          "\n  단서 없는 후보는 PL_UNLABELED_NAMES=all 일 때만 검토 권장(D-12).")


if __name__ == "__main__":
    main()
