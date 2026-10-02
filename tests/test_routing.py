from datetime import time

from app.services.routing import is_in_time_window


def test_route_window_handles_day_and_midnight_ranges():
    assert is_in_time_window(time(12, 0), time(9, 0), time(18, 0))
    assert not is_in_time_window(time(20, 0), time(9, 0), time(18, 0))
    assert is_in_time_window(time(23, 30), time(22, 0), time(2, 0))
    assert is_in_time_window(time(1, 30), time(22, 0), time(2, 0))
    assert not is_in_time_window(time(12, 0), time(22, 0), time(2, 0))
