"""Постобработка распознанного текста и фильтрация галлюцинаций Whisper."""

from __future__ import annotations

import re
from collections.abc import Sequence

_WHITESPACE = re.compile(r"\s+")
_PUNCT_ONLY = re.compile(r"""^[\s.,!?…\-—–:;'"«»()\[\]]*$""")


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
    if _PUNCT_ONLY.match(cleaned):
        return ""
    if strip_final_period and cleaned.endswith(".") and not cleaned.endswith(".."):
        cleaned = cleaned[:-1].rstrip()
    if append_space and cleaned:
        cleaned += " "
    return cleaned
