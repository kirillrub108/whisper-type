from __future__ import annotations

from whispertype.config import DEFAULT_HALLUCINATION_PATTERNS
from whispertype.textproc import filter_hallucinations, postprocess

PATTERNS = list(DEFAULT_HALLUCINATION_PATTERNS)


def test_strip_and_collapse_whitespace() -> None:
    assert postprocess("  привет   мир \n", []) == "привет мир"


def test_hallucination_removed_case_insensitive() -> None:
    assert postprocess("Субтитры сделал DimaTorzok", PATTERNS) == ""
    assert postprocess("ПРОДОЛЖЕНИЕ СЛЕДУЕТ...", PATTERNS) == ""
    assert postprocess("Thanks for watching!", PATTERNS) == ""


def test_hallucination_inside_real_text() -> None:
    result = postprocess("запиши это. Спасибо за просмотр", PATTERNS)
    assert result == "запиши это."


def test_pure_silence_output_empty() -> None:
    assert postprocess("", PATTERNS) == ""
    assert postprocess("   ...  ", PATTERNS) == ""
    assert postprocess("—", PATTERNS) == ""


def test_strip_final_period() -> None:
    assert postprocess("привет.", [], strip_final_period=True) == "привет"
    assert postprocess("привет...", [], strip_final_period=True) == "привет..."
    assert postprocess("прив.ет", [], strip_final_period=True) == "прив.ет"


def test_append_space() -> None:
    assert postprocess("привет", [], append_space=True) == "привет "
    assert postprocess("...", [], append_space=True) == ""


def test_filter_keeps_other_text() -> None:
    assert filter_hallucinations("abc", PATTERNS) == "abc"
