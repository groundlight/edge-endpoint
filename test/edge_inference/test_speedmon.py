from app.core.speedmon import SpeedMonitor


def test_speedmon_basics():
    speedmon = SpeedMonitor(window_size=10)

    assert speedmon.average_fps("model1") == 0

    speedmon.update("model1", 100)
    assert speedmon.average_fps("model1") == 10
    speedmon.update("model1", 400)
    # One at 100ms, the other at 400ms - average is 250ms or 4.0fps
    assert speedmon.average_fps("model1") == 4

    for _ in range(20):
        speedmon.update("model1", 50)
    assert speedmon.average_fps("model1") == 20

    assert speedmon.average_fps("model2") == 0
    speedmon.update("model2", 1000)
    assert speedmon.average_fps("model2") == 1

