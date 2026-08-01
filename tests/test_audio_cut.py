from __future__ import annotations

import numpy as np

from whispertype.audio import SAMPLE_RATE, find_cut_point


def _noisy(seconds: float, level: float = 0.4) -> np.ndarray:
    rng = np.random.default_rng(0)
    return (rng.normal(0, level, int(seconds * SAMPLE_RATE))).astype(np.float32)


MAX = 29 * SAMPLE_RATE


def test_too_short_no_cut() -> None:
    audio = _noisy(2.0)
    assert find_cut_point(audio, 5 * SAMPLE_RATE, MAX) == len(audio)


def test_cut_lands_in_silent_gap() -> None:
    loud_a = _noisy(8.0)
    gap = np.zeros(int(0.5 * SAMPLE_RATE), dtype=np.float32)
    loud_b = _noisy(3.0)
    audio = np.concatenate([loud_a, gap, loud_b])
    cut = find_cut_point(audio, 10 * SAMPLE_RATE, MAX)
    assert len(loud_a) <= cut <= len(loud_a) + len(gap)


def test_waits_when_no_pause_found() -> None:
    # сплошная речь без пауз: режем не сразу, а копим до предела окна
    audio = _noisy(12.0)
    assert find_cut_point(audio, 10 * SAMPLE_RATE, MAX) == len(audio)


def test_cuts_anyway_at_hard_max() -> None:
    audio = _noisy(30.0)
    cut = find_cut_point(audio, 25 * SAMPLE_RATE, MAX)
    assert cut < len(audio)


def test_empty_audio() -> None:
    empty = np.zeros(0, dtype=np.float32)
    assert find_cut_point(empty, SAMPLE_RATE, MAX) == 0


def test_cut_prefers_quietest_of_several_gaps() -> None:
    quiet_gap = (_noisy(0.4, level=0.005)).astype(np.float32)
    silent_gap = np.zeros(int(0.4 * SAMPLE_RATE), dtype=np.float32)
    audio = np.concatenate([_noisy(8.0), quiet_gap, _noisy(1.0), silent_gap, _noisy(1.0)])
    cut = find_cut_point(audio, 9 * SAMPLE_RATE, MAX)
    silent_start = len(audio) - len(silent_gap) - SAMPLE_RATE
    assert silent_start <= cut <= silent_start + len(silent_gap)
