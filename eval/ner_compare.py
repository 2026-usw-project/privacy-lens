"""이름 찾기 비교 — 지금 규칙 vs 한국어 NER(개체명 인식) vs 형태소 분석기.

'규칙이 단어 뜻을 몰라 판단을 못 한다 → 언어 모델을 넣자'는 의견을 숫자로 확인한다.
같은 입력(판단 평가의 가상 장면 + eval.names_check 의 따로 모은 낱말)으로 이름만 잰다.

엔진
  rules  지금 서비스(라벨 + 이름 후보 + 주변 단서). 설치 필요 없음
  kiwi   형태소 분석기 Kiwi 의 고유명사(NNP) 태그 + 흔한 성씨.   pip install kiwipiepy
  hf     Hugging Face 한국어 NER 모델의 사람(PS) 개체.           pip install transformers torch
         기본 모델: soddokayo/koelectra-base-klue-ner (KLUE NER, Apache-2.0, 검증 F1 0.79)
         이 개발 환경에서는 Hugging Face 에 접속할 수 없어 Colab 에서 돌린다(eval/colab_eval.ipynb 6번).

    python -m eval.ner_compare --engine rules kiwi
    python -m eval.ner_compare --engine rules hf --model soddokayo/koelectra-base-klue-ner

세는 것
  이름 정답(가림·확인 필요)을 '이름'으로 잡은 비율, 이름 같은 일반 낱말을 '이름'으로 잘못 잡은 수,
  따로 모은 이름·낱말 목록(문맥 없는 낱말 하나)에서의 결과, 장면 하나당 처리 시간.
주의: 장면은 가상이고 규칙 개발에 쓰인 것이다. 규칙 쪽이 유리하다. 따로 모은 목록 결과를 같이 본다.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval import judgment, names_check  # noqa: E402
from pipeline import context  # noqa: E402
from pipeline import kr_patterns as kp  # noqa: E402

NAME_ITEMS = {"이름"}
NOT_NAME_ITEMS = {"이름 같은 낱말", "상호·간판"}


# ------------------------------------------------------------ 엔진: 조각 목록 → 이름이라고 본 문자열들

class Rules:
    name = "규칙(지금 서비스)"

    def names(self, texts: list[str], spans=None) -> set[str]:
        found = context.evaluate(spans) if spans is not None else []
        return {f.evidence_text for f in found if f.kind == "name" and f.evidence_text}

    def word_is_name(self, word: str) -> bool:
        # 낱말 하나만 있을 때 규칙은 단서가 없어 이름이라고 하지 않는다(context 모드).
        # 'all' 모드의 후보 판정을 대신 보여 준다
        return kp.name_candidate(word)


class KiwiNNP:
    name = "Kiwi 고유명사"

    def __init__(self):
        from kiwipiepy import Kiwi
        self.kiwi = Kiwi()

    def names(self, texts: list[str], spans=None) -> set[str]:
        out = set()
        for t in texts:
            for tok in self.kiwi.tokenize(t):
                if tok.tag == "NNP" and len(tok.form) >= 2 and tok.form[0] in kp.SURNAMES:
                    out.add(tok.form)
        return out

    def word_is_name(self, word: str) -> bool:
        return word in self.names([word])


class HFNER:
    def __init__(self, model: str):
        from transformers import pipeline
        self.pipe = pipeline("token-classification", model=model, aggregation_strategy="simple")
        self.name = f"NER({model.split('/')[-1]})"

    def names(self, texts: list[str], spans=None) -> set[str]:
        out = set()
        for t in texts:
            for ent in self.pipe(t):
                group = str(ent.get("entity_group", "")).upper()
                if group in ("PS", "PER", "PERSON"):
                    out.add(ent["word"].replace(" ", "").replace("##", ""))
        return out

    def word_is_name(self, word: str) -> bool:
        return bool(self.names([word]))


# ------------------------------------------------------------ 채점

def _hit(gold: str, found: set[str]) -> bool:
    g = kp.compact(gold)
    return any(f and (f in g or g in f) for f in (kp.compact(x) for x in found))


def score(engine, scenes) -> dict:
    name_total = name_hit = word_total = word_fp = 0
    t = time.perf_counter()
    for sc in scenes:
        spans = sc.spans()
        found = engine.names([s.text for s in spans], spans)
        for g in sc.gold:
            if g.item in NAME_ITEMS and g.expect != "none":
                name_total += 1
                name_hit += _hit(g.text, found)
            elif g.item in NOT_NAME_ITEMS:
                word_total += 1
                word_fp += _hit(g.text, found)
    per_scene = (time.perf_counter() - t) / max(1, len(scenes))
    names = [names_check.SURNAMES_CYCLE[i % len(names_check.SURNAMES_CYCLE)] + g
             for i, g in enumerate(names_check.GIVEN)]
    words = names_check.WORDS
    return {
        "engine": engine.name, "name_total": name_total, "name_hit": name_hit,
        "word_total": word_total, "word_fp": word_fp, "ms": per_scene * 1000,
        "list_names": sum(engine.word_is_name(n) for n in names), "list_names_total": len(names),
        "list_words": sum(engine.word_is_name(w) for w in words), "list_words_total": len(words),
    }


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m eval.ner_compare")
    ap.add_argument("--engine", nargs="+", default=["rules", "kiwi"], choices=["rules", "kiwi", "hf"])
    ap.add_argument("--model", default="soddokayo/koelectra-base-klue-ner")
    a = ap.parse_args(argv)
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    scenes = judgment.build()
    print(f"가상 장면 {len(scenes)}개 + 따로 모은 이름 {len(names_check.GIVEN)}개·낱말 {len(names_check.WORDS)}개\n")
    print(f"{'방법':<26}{'장면 속 이름':>12}{'이름 같은 낱말 오탐':>16}{'목록 이름':>10}{'목록 낱말 오탐':>14}{'장면당':>9}")
    for key in a.engine:
        try:
            eng = {"rules": Rules, "kiwi": KiwiNNP}.get(key, lambda: HFNER(a.model))()
        except Exception as exc:
            print(f"{key:<26} 준비 실패: {type(exc).__name__}: {str(exc)[:80]}")
            continue
        r = score(eng, scenes)
        print(f"{r['engine']:<26}{r['name_hit']:>6}/{r['name_total']:<5}{r['word_fp']:>10}/{r['word_total']:<5}"
              f"{r['list_names']:>5}/{r['list_names_total']:<4}{r['list_words']:>8}/{r['list_words_total']:<5}"
              f"{r['ms']:>7.1f}ms")
    print("\n'목록'은 낱말 하나만 넣은 결과(문맥 없음). 규칙의 목록 결과는 이름 후보 판정(all 모드)이다.")
    print("장면 결과는 규칙 개발에 쓴 가상 장면이라 규칙이 유리하다. 결론은 실사(eval.failures)로 낸다.")


if __name__ == "__main__":
    main()
