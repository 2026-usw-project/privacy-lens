"""eval.judges(판단 방법 비교, D-23). 네트워크를 쓰지 않는 부분만."""

import pytest

from eval import judges


def test_rules_scene_comparison_runs_offline():
    out = judges.run_scenes([judges.make_judge("rules")], per=1)
    s = out["rules"]
    assert s["scenes"] == len(judges.J.TEMPLATES) and s["errors"] == 0
    assert s["cover_miss"] == 0.0


def test_cloud_judge_needs_key(monkeypatch):
    monkeypatch.delenv("PL_JUDGE_API_KEY", raising=False)
    with pytest.raises(SystemExit):
        judges.make_judge("gemini_decision:gemini-decision-1")
    with pytest.raises(SystemExit):
        judges.make_judge("hybrid:gemini-decision-1")


def test_cloud_judges_marked_and_refused_on_photos_without_virtual(monkeypatch, tmp_path):
    monkeypatch.setenv("PL_JUDGE_API_KEY", "test-key-not-real")
    assert judges.make_judge("gemini_decision:gemini-decision-1").cloud
    assert judges.make_judge("hybrid:gemini-decision-1").cloud
    assert not judges.make_judge("rules").cloud
    with pytest.raises(SystemExit) as err:
        judges.run_photos(tmp_path, [judges.make_judge("gemini_decision:gemini-decision-1")], virtual=False)
    assert "--virtual" in str(err.value)
