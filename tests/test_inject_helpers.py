from __future__ import annotations

from whispertype.inject import batched, utf16_units


def test_bmp_chars_single_unit() -> None:
    assert utf16_units("Aж") == [ord("A"), ord("ж")]


def test_non_bmp_surrogate_pair() -> None:
    units = utf16_units("\N{ROCKET}")  # U+1F680
    assert len(units) == 2
    assert units[0] == 0xD83D
    assert units[1] == 0xDE80


def test_mixed_text() -> None:
    units = utf16_units("a\N{ROCKET}b")
    assert len(units) == 4
    assert units[0] == ord("a")
    assert units[3] == ord("b")


def test_empty() -> None:
    assert utf16_units("") == []


def test_batched_splits_evenly() -> None:
    chunks = list(batched(list(range(10)), 4))
    assert chunks == [[0, 1, 2, 3], [4, 5, 6, 7], [8, 9]]


def test_batched_size_never_below_one() -> None:
    assert list(batched([1, 2], 0)) == [[1], [2]]
