import pytest

from pcb_pipeline.values import parse_value


@pytest.mark.parametrize("text,expected", [
    ("10k", 10e3), ("4k7", 4.7e3), ("100n", 100e-9), ("100nF", 100e-9),
    ("10u", 10e-6), ("2R2", 2.2), ("25V", 25.0), ("0.1uF", 0.1e-6), ("1M", 1e6),
])
def test_parse_value(text, expected):
    assert parse_value(text) == pytest.approx(expected)


def test_unparseable():
    assert parse_value("DNP") is None
    assert parse_value("") is None
