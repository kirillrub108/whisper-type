from __future__ import annotations

import numpy as np

from whispertype.stt import normalize_audio, pick_language

CANDIDATES = ["ru", "en"]


def test_quiet_audio_amplified() -> None:
    quiet = (np.sin(np.linspace(0, 20, 1000)) * 0.02).astype(np.float32)
    result = normalize_audio(quiet)
    assert 0.9 < float(np.max(np.abs(result))) <= 0.96


def test_loud_audio_scaled_down() -> None:
    loud = (np.sin(np.linspace(0, 20, 1000)) * 3.0).astype(np.float32)
    assert float(np.max(np.abs(normalize_audio(loud)))) <= 0.96


def test_dc_offset_removed() -> None:
    offset = (np.sin(np.linspace(0, 20, 1000)) * 0.1 + 0.5).astype(np.float32)
    assert abs(float(np.mean(normalize_audio(offset)))) < 1e-3


def test_silence_not_amplified() -> None:
    silence = np.zeros(1000, dtype=np.float32)
    assert float(np.max(np.abs(normalize_audio(silence)))) < 1e-4


def test_empty_audio() -> None:
    assert normalize_audio(np.zeros(0, dtype=np.float32)).size == 0


def test_normalize_keeps_float32() -> None:
    assert normalize_audio(np.array([0.1, -0.2], dtype=np.float32)).dtype == np.float32


def test_detected_language_in_candidates_kept() -> None:
    assert pick_language("ru", [("ru", 0.9), ("en", 0.05)], CANDIDATES) is None
    assert pick_language("en", [("en", 0.8)], CANDIDATES) is None


def test_foreign_language_overridden_by_best_candidate() -> None:
    probs = [("uk", 0.4), ("ru", 0.3), ("en", 0.05)]
    assert pick_language("uk", probs, CANDIDATES) == "ru"


def test_override_without_probs_uses_first_candidate() -> None:
    assert pick_language("de", None, CANDIDATES) == "ru"


def test_override_when_no_candidate_in_probs() -> None:
    assert pick_language("de", [("de", 0.7), ("fr", 0.2)], CANDIDATES) == "ru"


def test_empty_candidates_disables_override() -> None:
    assert pick_language("de", [("de", 0.9)], []) is None


def test_window_disabled_returns_none() -> None:
    from whispertype.stt import window_frames_for

    assert window_frames_for(5.0, False) is None


def test_window_short_phrase_is_narrowed() -> None:
    from whispertype.stt import WINDOW_MARGIN_SECONDS, window_frames_for

    frames = window_frames_for(5.0, True)
    assert frames == int((5.0 + WINDOW_MARGIN_SECONDS) * 100)


def test_window_long_phrase_stays_full() -> None:
    from whispertype.stt import window_frames_for

    # длина + запас уже перекрывают штатные 30 с — сужать нечего
    assert window_frames_for(25.0, True) is None


def test_window_boundary_exactly_full() -> None:
    from whispertype.stt import FULL_WINDOW_FRAMES, WINDOW_MARGIN_SECONDS, window_frames_for

    boundary = FULL_WINDOW_FRAMES / 100 - WINDOW_MARGIN_SECONDS
    assert window_frames_for(boundary, True) is None
    assert window_frames_for(boundary - 1, True) == FULL_WINDOW_FRAMES - 100


def test_encoder_window_restores_original() -> None:
    import faster_whisper.transcribe as ftr

    from whispertype.stt import encoder_window

    original = ftr.pad_or_trim
    with encoder_window(800):
        assert ftr.pad_or_trim is not original
    assert ftr.pad_or_trim is original


def test_encoder_window_restores_after_error() -> None:
    import faster_whisper.transcribe as ftr

    from whispertype.stt import encoder_window

    original = ftr.pad_or_trim
    try:
        with encoder_window(800):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert ftr.pad_or_trim is original
