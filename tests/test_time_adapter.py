import json

import pytest

from helper.tools.time_adapter import simplify_conversion


def result(source, target, diff):
    return json.dumps({
        "source": {"timezone": "Europe/Istanbul", "datetime": source},
        "target": {"timezone": "X", "datetime": target}, "time_difference": diff})


@pytest.mark.parametrize("source, target, day", [
    ("2026-11-23T23:00:00+03:00", "2026-11-23T15:00:00-05:00", "the same day"),
    ("2026-11-23T23:00:00+03:00", "2026-11-24T05:00:00+09:00", "the next day"),
    ("2026-11-23T01:00:00+03:00", "2026-11-22T17:00:00-05:00", "the previous day"),
])
def test_day_shift_and_no_dates(source, target, day):
    text = simplify_conversion(result(source, target, "+6.0h"))
    assert f"on {day}" in text and "2026" not in text and "Monday" not in text
    assert text.startswith(f"{source[11:16]} in Europe/Istanbul is {target[11:16]} in X")


@pytest.mark.parametrize("text", ["Error", "{}", "[]", '{"source": {"datetime": "x"}}'])
def test_unknown_shapes_pass_through(text):
    assert simplify_conversion(text) == text
