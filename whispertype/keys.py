"""Разбор строки хоткея ("ctrl+alt+space") в наборы виртуальных кодов клавиш."""

from __future__ import annotations

import re
from typing import NamedTuple


def _fs(*codes: int) -> frozenset[int]:
    return frozenset(codes)


_ALIASES: dict[str, str] = {
    "control": "ctrl",
    "lcontrol": "lctrl",
    "rcontrol": "rctrl",
    "leftctrl": "lctrl",
    "rightctrl": "rctrl",
    "leftalt": "lalt",
    "rightalt": "ralt",
    "menu": "alt",
    "altgr": "ralt",
    "leftshift": "lshift",
    "rightshift": "rshift",
    "escape": "esc",
    "return": "enter",
    "spacebar": "space",
    "windows": "win",
    "super": "win",
    "capslock": "caps",
    "break": "pause",
    "pgup": "pageup",
    "pgdn": "pagedown",
    "del": "delete",
    "ins": "insert",
}

_KEYS: dict[str, frozenset[int]] = {
    "ctrl": _fs(0xA2, 0xA3),
    "lctrl": _fs(0xA2),
    "rctrl": _fs(0xA3),
    "alt": _fs(0xA4, 0xA5),
    "lalt": _fs(0xA4),
    "ralt": _fs(0xA5),
    "shift": _fs(0xA0, 0xA1),
    "lshift": _fs(0xA0),
    "rshift": _fs(0xA1),
    "win": _fs(0x5B, 0x5C),
    "lwin": _fs(0x5B),
    "rwin": _fs(0x5C),
    "space": _fs(0x20),
    "esc": _fs(0x1B),
    "enter": _fs(0x0D),
    "tab": _fs(0x09),
    "backspace": _fs(0x08),
    "caps": _fs(0x14),
    "pause": _fs(0x13),
    "scrolllock": _fs(0x91),
    "numlock": _fs(0x90),
    "insert": _fs(0x2D),
    "delete": _fs(0x2E),
    "home": _fs(0x24),
    "end": _fs(0x23),
    "pageup": _fs(0x21),
    "pagedown": _fs(0x22),
    "up": _fs(0x26),
    "down": _fs(0x28),
    "left": _fs(0x25),
    "right": _fs(0x27),
}
_KEYS.update({f"f{i}": _fs(0x6F + i) for i in range(1, 25)})
_KEYS.update({chr(c): _fs(c - 32) for c in range(ord("a"), ord("z") + 1)})  # VK A–Z = ASCII заглавных
_KEYS.update({chr(c): _fs(c) for c in range(ord("0"), ord("9") + 1)})
_KEYS.update({f"numpad{i}": _fs(0x60 + i) for i in range(10)})


class Hotkey(NamedTuple):
    """parts — все части комбинации; trigger — последняя (несущая) клавиша."""

    parts: tuple[frozenset[int], ...]
    trigger: frozenset[int]

    def all_vks(self) -> frozenset[int]:
        result: frozenset[int] = frozenset()
        for part in self.parts:
            result |= part
        return result


def parse_hotkey(spec: str) -> Hotkey:
    """Разбирает строку вида "ctrl+alt+space" / "right ctrl". ValueError при неизвестной клавише."""
    tokens = [part.strip() for part in spec.split("+")]
    if not tokens or any(not t for t in tokens):
        raise ValueError(f"некорректный хоткей: {spec!r}")
    parts: list[frozenset[int]] = []
    for token in tokens:
        norm = re.sub(r"[\s_\-]+", "", token.lower())
        norm = _ALIASES.get(norm, norm)
        if norm not in _KEYS:
            raise ValueError(f"неизвестная клавиша: {token!r}")
        parts.append(_KEYS[norm])
    return Hotkey(tuple(parts), parts[-1])
