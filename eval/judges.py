"""판단 방법 비교 — 규칙 / LLM / Gemini Decision / 규칙+Decision 혼합(시험용). DECISIONS D-15·D-23.

같은 OCR 결과(또는 가상 장면)에 판단 방법만 바꿔 넣고 채점한다. 판단은 제품 코드(llm_judge.evaluate)를 그대로 쓴다.

판단 지정(--judge, 여러 번)
  rules                              규칙 기반(context.evaluate)
  <공급자>:<모델>                     판단 모델 창과 같은 공급자. 예: gemini_decision:gemini-decision-1,
                                     gemini:gemini-3.8-flash, ollama:qwen2.5:7b
  hybrid:<모델>                       시험용. 규칙이 '확인 필요·참고'로 낸 항목만 Gemini Decision 에 다시 물어
                                     확신이 높을 때만 등급을 바꾼다(제품에는 없음, D-23 미결)
  API 키는 환경 변수로만 받는다(기본 PL_JUDGE_API_KEY, --key-env 로 바꿈). 키는 출력하지 않는다.

사용법
  python -m eval.judges scenes --judge rules --judge gemini_decision:gemini-decision-1
  python -m eval.judges scenes --per 4 --judge gemini:gemini-3.8-flash          # 장면 수 줄이기(종류마다 4개)
  PL_OCR=paddleocr python -m eval.judges photos <폴더> --virtual --judge rules --judge gemini_decision:gemini-decision-1

photos 는 eval.failures 와 같은 정답(<사진 이름>.json, items 의 text·expect·item)을 쓴다.
**클라우드 판단은 OCR 원문을 외부로 보낸다.** 가상 소품·합성 사진 폴더에만 쓰고, --virtual 로 그렇다고 밝혀야 돈다.
결과에는 숫자와 항목 이름만 찍는다(글자는 찍지 않음). 사진·정답은 커밋하지 않는다(팀 드라이브 PrivacyLens-Eval/).

주의: 가상 장면 숫자는 OCR 이 완벽하다고 가정한 판단만의 숫자다. 발표 숫자는 실사로 다시 잰다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval import judgment as J  # noqa: E402
from pipeline import context, decision_judge, llm_judge  # noqa: E402
from pipeline.types import Severity, TextSpan  # noqa: E402

RETRY_STATUS = (429, 500, 503)
LOCAL = {"rules", "ollama"}  # 글자가 이 컴퓨터 밖으로 나가지 않는 판단(ollama 는 기본 주소일 때)


@dataclass
class Judge:
    spec: str
    run: Callable[[list[TextSpan], int, int], list]
    cloud: bool


def _retry(call: Callable[[], list], tries: int = 6) -> list:
    """사용 한도(429)·일시 오류는 기다렸다가 다시. Tier 1 키는 분당 입력 토큰 한도에 자주 걸린다."""
    for k in range(tries):
        try:
            return call()
        except llm_judge.LlmJudgeError as exc:
            if exc.status in RETRY_STATUS and k < tries - 1:
                time.sleep(min(60, 4 * 2 ** k))
                continue
            raise
    raise AssertionError("unreachable")


def _hybrid(cfg: llm_judge.JudgeConfig) -> Callable[[list[TextSpan], int, int], list]:
    """규칙 판단 뒤, 확인 필요·참고 항목만 Decision 에 등급을 다시 묻는다(시험용)."""
    def run(spans, width, height):
        findings = context.evaluate(spans)
        ask = [n for n, f in enumerate(findings)
               if f.severity in (Severity.REVIEW, Severity.INFO) and f.span_index is not None and f.evidence_text]
        if not ask:
            return findings
        sent = spans[:llm_judge.MAX_SPANS]
        qs = {}
        for n in ask:
            f = findings[n]
            where = ", ".join(f"i={k}" for k in (f.detail.get("span_indices") or [f.span_index]))
            qs[f"f{n}"] = {"type": "choice", "criteria": decision_judge.SEV_CRITERIA, "instructions":
                           f"규칙 검사기가 spans 의 {where} 조각에서 값 \"{f.evidence_text}\" 를 종류 '{f.kind}', 등급 "
                           f"'{f.severity.value}' 로 표시했다. 주변 조각(같은 줄 앞·윗줄 라벨, 문서 종류)과 기준표로 볼 때 이 값의 등급은?"}
        body = {"model": cfg.model, "input": decision_judge.RUBRIC + "\n" + llm_judge._user_message(sent, width, height),
                "questions": qs}
        data = _retry(lambda: [llm_judge._http_post(decision_judge.URL, {"x-goog-api-key": cfg.api_key}, body,
                                                    decision_judge.TIMEOUT_S)])[0]
        answers = data.get("answers") or {}
        for n in ask:
            a, f = answers.get(f"f{n}") or {}, findings[n]
            choice, conf = a.get("choice"), a.get("confidence") or 0
            if choice == "cover" and conf >= 0.8:
                f.severity = Severity.COVER
            elif choice in ("public", "none") and conf >= 0.9:
                f.severity = Severity.INFO
        return findings
    return run


def make_judge(spec: str, key_env: str = "PL_JUDGE_API_KEY") -> Judge:
    if spec == "rules":
        return Judge(spec, lambda spans, w, h: context.evaluate(spans), cloud=False)
    provider, _, model = spec.partition(":")
    key = os.environ.get(key_env, "")
    if provider == "hybrid":
        cfg = llm_judge.JudgeConfig("gemini_decision", model or decision_judge.DEFAULT_MODEL, key)
        if not key:
            raise SystemExit(f"{spec}: API 키가 없습니다. 환경 변수 {key_env} 에 넣어 주세요.")
        return Judge(spec, _hybrid(cfg), cloud=True)
    try:
        cfg = llm_judge.parse_config(json.dumps({"provider": provider, "model": model, "api_key": key}))
    except ValueError as exc:
        raise SystemExit(f"{spec}: {exc} (키는 환경 변수 {key_env})") from None
    if cfg is None:
        return make_judge("rules")
    outside = cfg.sends_outside or provider not in LOCAL
    return Judge(spec, lambda spans, w, h: _retry(lambda: llm_judge.evaluate(spans, cfg, width=w, height=h)),
                 cloud=outside)


def _timed(judge: Judge, spans, width, height) -> tuple[list, float, str | None]:
    t = time.perf_counter()
    try:
        return judge.run(spans, width, height), time.perf_counter() - t, None
    except Exception as exc:  # noqa: BLE001 — 실패한 장면은 '놓침'으로 세고 개수를 알린다
        return [], time.perf_counter() - t, type(exc).__name__ + ": " + str(exc)[:120]


# ------------------------------------------------------------------ 가상 장면

def run_scenes(judges: list[Judge], per: int = 14, workers: int = 4) -> dict:
    scenes = J.build(per_template=per)
    out = {}
    for judge in judges:
        def one(sc):
            spans = sc.spans()
            findings, lat, err = _timed(judge, spans, 1000, 1000)
            rows = [{"category": sc.category, "item": g.item, "expect": g.expect, "got": got,
                     "verdict": J.verdict(g.expect, got)} for g, got, _ in J.predict(sc, spans, findings)]
            return rows, lat, err
        with ThreadPoolExecutor(1 if judge.spec == "rules" else workers) as ex:
            res = list(ex.map(one, scenes))
        rows = [r for rs, _, _ in res for r in rs]
        lats = sorted(lat for _, lat, _ in res)
        errors = [e for _, _, e in res if e]
        s = J.summarize(rows)
        s.update(correct=sum(r["verdict"] == "맞음" for r in rows), scenes=len(scenes),
                 lat_median_s=round(lats[len(lats) // 2], 3), errors=len(errors))
        out[judge.spec] = s
        _print_scene_summary(judge.spec, s, errors)
        wrong = Counter((r["category"], r["item"], r["verdict"]) for r in rows if r["verdict"] != "맞음")
        for (cat, item, why), n in wrong.most_common(6):
            print(f"    {n:>3}  {cat} · {item} · {why}")
    return out


def _print_scene_summary(spec: str, s: dict, errors: list[str]) -> None:
    print(f"\n{spec}: 맞음 {s['correct']}/{s['items']}  가림 {s['cover_hit']}% · 확인 필요로만 {s['cover_weak']}% · "
          f"놓침 {s['cover_miss']}%  잘못 가림 {s['false_cover']}% · 잘못 확인 요청 {s['false_review']}%  "
          f"장면당 {s['lat_median_s']}초" + (f"  실패한 장면 {len(errors)}개(놓침으로 셈): {errors[0]}" if errors else ""))


# ------------------------------------------------------------------ 사진

def run_photos(folder: Path, judges: list[Judge], virtual: bool = False) -> dict:
    from PIL import Image, ImageOps

    from eval import failures as F
    from pipeline import ocr

    cloud = [j.spec for j in judges if j.cloud]
    if cloud and not virtual:
        raise SystemExit(f"{', '.join(cloud)} 는 OCR 원문을 외부로 보냅니다(D-15). 가상 소품·합성 사진 폴더라면 --virtual 을 붙이세요.")
    F._heif()
    backend = ocr.get_backend()
    photos = []
    for img in F._images(folder):
        js = img.with_suffix(".json")
        items = F.load_gold(js) if js.exists() else None
        if items is None:
            continue
        with Image.open(img) as im:
            image = ImageOps.exif_transpose(im).convert("RGB")
        spans, _ = ocr.read_with_raw(backend, ocr.ocr_ready(image))  # OCR 은 한 번만, 판단만 바꾼다
        photos.append((img.name, image.width, image.height, spans, items))
    if not photos:
        raise SystemExit("채점할 정답이 없습니다. eval.failures init 또는 eval/gold_tool.html 로 정답을 만드세요.")
    print(f"사진 {len(photos)}장 (OCR {backend.name}, 검출 없음 — 판단만 비교)")
    out = {}
    for judge in judges:
        rows, extra, lats, errors = [], 0, [], []
        for name, w, h, spans, items in photos:
            findings, lat, err = _timed(judge, spans, w, h)
            lats.append(lat)
            if err:
                errors.append(err)
            texts = [s.text for s in spans]
            extra += F.extra_covers(items, texts, findings)
            for it in items:
                cause, got, _ = F.classify(it, texts, findings)
                rows.append({"photo": name, "item": it.get("item") or "?", "expect": it["expect"], "got": got, "cause": cause})
        cov = [r for r in rows if r["expect"] == J.COVER]
        rev = [r for r in rows if r["expect"] == J.REVIEW]
        neg = [r for r in rows if r["expect"] == J.NONE]
        s = {"items": len(rows), "correct": sum(r["cause"] == "맞음" for r in rows),
             "judge_fail": sum(r["cause"] == "③ 판단 실패" for r in rows),
             "cover_total": len(cov), "cover_hit": sum(r["got"] == J.COVER for r in cov),
             "cover_weak": sum(r["got"] == J.REVIEW for r in cov),
             "review_total": len(rev), "review_ok": sum(r["got"] != J.NONE for r in rev),
             "none_total": len(neg), "false_cover": sum(r["got"] == J.COVER for r in neg),
             "extra_cover": extra, "lat_median_s": round(sorted(lats)[len(lats) // 2], 2), "errors": len(errors)}
        out[judge.spec] = s
        print(f"\n{judge.spec}: 맞음 {s['correct']}/{s['items']} (③ 판단 실패 {s['judge_fail']})  "
              f"가림 {s['cover_hit']}/{s['cover_total']} · 확인 필요로만 {s['cover_weak']}  "
              f"확인 필요 잡음 {s['review_ok']}/{s['review_total']}  잘못 가림 {s['false_cover']}/{s['none_total']}  "
              f"정답 밖 가림 {s['extra_cover']}  사진당 {s['lat_median_s']}초"
              + (f"  실패 {len(errors)}장(놓침으로 셈): {errors[0]}" if errors else ""))
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m eval.judges", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("scenes", "photos"):
        p = sub.add_parser(name)
        if name == "photos":
            p.add_argument("folder", type=Path)
            p.add_argument("--virtual", action="store_true", help="가상 소품·합성 사진뿐임을 확인(클라우드 판단에 필요)")
        else:
            p.add_argument("--per", type=int, default=14, help="장면 종류마다 몇 개(기본 14 = 308장면)")
            p.add_argument("--workers", type=int, default=4)
        p.add_argument("--judge", action="append", required=True, help="rules · <공급자>:<모델> · hybrid:<모델>")
        p.add_argument("--key-env", default="PL_JUDGE_API_KEY", help="API 키를 담은 환경 변수 이름")
        p.add_argument("--json", help="요약을 JSON 파일로(글자는 넣지 않음)")
    a = ap.parse_args(argv)
    judges = [make_judge(s, a.key_env) for s in a.judge]
    out = run_scenes(judges, a.per, a.workers) if a.cmd == "scenes" else run_photos(a.folder, judges, a.virtual)
    if a.json:
        Path(a.json).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
