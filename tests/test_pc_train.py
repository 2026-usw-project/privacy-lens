from vision import pc_train as pt


def test_guard_waits_until_cool():
    temps = iter([85, 84, 79, 76, 70])
    slept = []
    g = pt.make_guard(80, read=lambda: next(temps), sleep=slept.append)
    for _ in range(pt.CHECK_EVERY - 1):
        g()
    assert slept == []                       # 50 배치마다만 확인
    g()                                      # 85 → … → 70(≤72) 이 될 때까지 쉼
    assert len(slept) == 4


def test_guard_ignores_missing_gpu():
    g = pt.make_guard(80, read=lambda: None, sleep=lambda s: (_ for _ in ()).throw(AssertionError))
    for _ in range(pt.CHECK_EVERY * 2):
        g()
