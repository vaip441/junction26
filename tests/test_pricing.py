from terminal.pricing import nudge


def test_nudge_moves_a_strong_up_tick_a_few_points():
    assert abs(nudge(20, 0.8) - 25.61) < 0.01


def test_nudge_is_symmetric_and_bounded():
    assert nudge(50, 0) == 50
    assert abs(nudge(50, 0.9) + nudge(50, -0.9) - 100) < 1e-9
    assert nudge(99, 1) <= 99 and nudge(1, -1) >= 1
    assert abs(nudge(150, 0) - 99) < 1e-9
