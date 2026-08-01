from __future__ import annotations

import pytest

from whispertype.keys import parse_hotkey


def test_single_key_right_ctrl() -> None:
    hk = parse_hotkey("right ctrl")
    assert hk.parts == (frozenset({0xA3}),)
    assert hk.trigger == frozenset({0xA3})


def test_aliases_and_case() -> None:
    assert parse_hotkey("RCtrl") == parse_hotkey("right_ctrl") == parse_hotkey("rcontrol")
    assert parse_hotkey("ESC").trigger == frozenset({0x1B})


def test_combo_ctrl_alt_space() -> None:
    hk = parse_hotkey("ctrl+alt+space")
    assert hk.parts == (frozenset({0xA2, 0xA3}), frozenset({0xA4, 0xA5}), frozenset({0x20}))
    assert hk.trigger == frozenset({0x20})
    assert hk.all_vks() == frozenset({0xA2, 0xA3, 0xA4, 0xA5, 0x20})


def test_letters_digits_fkeys() -> None:
    assert parse_hotkey("f13").trigger == frozenset({0x7C})
    assert parse_hotkey("a").trigger == frozenset({ord("A")})
    assert parse_hotkey("7").trigger == frozenset({ord("7")})
    assert parse_hotkey("numpad5").trigger == frozenset({0x65})


def test_whitespace_tolerated() -> None:
    hk = parse_hotkey(" ctrl + alt + space ")
    assert len(hk.parts) == 3


@pytest.mark.parametrize("bad", ["", "+", "ctrl+", "ctrl+foo", "нечто"])
def test_invalid_raises(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_hotkey(bad)
