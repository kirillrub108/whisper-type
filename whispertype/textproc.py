"""Постобработка распознанного текста и фильтрация галлюцинаций Whisper."""

from __future__ import annotations

import re
from collections.abc import Sequence
from difflib import SequenceMatcher

_WHITESPACE = re.compile(r"\s+")
_PUNCT_ONLY = re.compile(r"""^[\s.,!?…\-—–:;'"«»()\[\]]*$""")
# Осиротевшая пунктуация после вырезанной галлюцинации («…секунды ...»).
# Пробел перед ней обязателен: своё многоточие примыкает к слову вплотную.
_ORPHAN_TAIL = re.compile(r"\s+[.,!?…\-—–:;]+\s*$")


def _duplicate_parts(cleaned: str) -> int | None:
    """На сколько почти одинаковых частей делится текст (2/3), None — не делится."""
    if len(cleaned) < 24:
        return None
    for parts in (3, 2):
        size = len(cleaned) // parts
        if size < 12:
            continue
        head = cleaned[:size]
        rest = (cleaned[i * size : (i + 1) * size] for i in range(1, parts))
        if all(SequenceMatcher(None, head, chunk).ratio() > 0.9 for chunk in rest):
            return parts
    return None


def looks_duplicated(text: str) -> bool:
    """Повторяет ли расшифровка сама себя целиком.

    Узкое окно энкодера иногда заставляет модель добивать текст повторами
    одной и той же фразы.
    """
    return _duplicate_parts(_WHITESPACE.sub(" ", text).strip()) is not None


def collapse_duplicated(text: str) -> str:
    """Схлопывает самоповтор до одного экземпляра фразы.

    Дешёвая замена повторному распознаванию на полном окне (оно стоит секунды).
    Цена — редкий случай, когда пользователь действительно дважды произнёс
    одно и то же длинное предложение, тоже схлопнется.
    """
    cleaned = _WHITESPACE.sub(" ", text).strip()
    parts = _duplicate_parts(cleaned)
    if parts is None:
        return text
    return cleaned[: len(cleaned) // parts].strip()


def menu_label(text: str, limit: int = 45) -> str:
    """Однострочная подпись пункта меню трея.

    Амперсанд удваивается: Win32 считает его префиксом акселератора и съедает,
    показывая следующую букву подчёркнутой (pystray текст не экранирует).
    """
    collapsed = _WHITESPACE.sub(" ", text).strip()
    if len(collapsed) > limit:
        collapsed = collapsed[: limit - 1].rstrip() + "…"
    return collapsed.replace("&", "&&")


def filter_hallucinations(text: str, patterns: Sequence[str]) -> str:
    """Удаляет вхождения паттернов-галлюцинаций (регистронезависимо, как подстроки)."""
    result = text
    for pattern in patterns:
        if not pattern:
            continue
        result = re.sub(re.escape(pattern), "", result, flags=re.IGNORECASE)
    return result


def postprocess(
    text: str,
    patterns: Sequence[str],
    *,
    append_space: bool = False,
    strip_final_period: bool = False,
) -> str:
    """Чистит текст перед вставкой. Пустая строка на выходе — вставлять нечего."""
    cleaned = filter_hallucinations(text, patterns)
    cleaned = _WHITESPACE.sub(" ", cleaned).strip()
    cleaned = _ORPHAN_TAIL.sub("", cleaned)
    if _PUNCT_ONLY.match(cleaned):
        return ""
    if strip_final_period and cleaned.endswith(".") and not cleaned.endswith(".."):
        cleaned = cleaned[:-1].rstrip()
    if append_space and cleaned:
        cleaned += " "
    return cleaned
