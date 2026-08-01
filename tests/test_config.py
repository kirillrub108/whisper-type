from __future__ import annotations

import json
from pathlib import Path

from whispertype.config import Config, load_config, write_config


def test_missing_file_creates_defaults(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    cfg, warnings = load_config(path)
    assert warnings == []
    assert path.exists()
    assert cfg.model.beam_size == 1
    assert cfg.hotkey.mode == "push_to_talk"


def test_broken_json_falls_back(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{not json", encoding="utf-8")
    cfg, warnings = load_config(path)
    assert len(warnings) == 1
    assert cfg == Config()


def test_partial_override(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"model": {"beam_size": 3}, "hotkey": {"combo": "ctrl+alt+space"}}),
        encoding="utf-8",
    )
    cfg, warnings = load_config(path)
    assert warnings == []
    assert cfg.model.beam_size == 3
    assert cfg.hotkey.combo == "ctrl+alt+space"
    assert cfg.model.compute_type == "int8"  # остальное — дефолты


def test_wrong_type_keeps_default(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"model": {"cpu_threads": "six"}, "sounds": 1}), encoding="utf-8")
    cfg, warnings = load_config(path)
    assert cfg.model.cpu_threads == 6
    assert cfg.sounds is True
    assert len(warnings) == 2


def test_out_of_range_values_clamped(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"model": {"beam_size": 99}, "hotkey": {"mode": "weird"}}), encoding="utf-8"
    )
    cfg, warnings = load_config(path)
    assert cfg.model.beam_size == 1
    assert cfg.hotkey.mode == "push_to_talk"
    assert len(warnings) == 2


def test_non_dict_root(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("[1, 2]", encoding="utf-8")
    cfg, warnings = load_config(path)
    assert cfg == Config()
    assert len(warnings) == 1


def test_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    cfg = Config()
    cfg.inject.append_space = True
    cfg.audio.input_device = "Микрофон (USB)"
    write_config(cfg, path)
    loaded, warnings = load_config(path)
    assert warnings == []
    assert loaded == cfg


def test_bad_hallucination_items_dropped(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"hallucination_patterns": ["ok", 5, None]}), encoding="utf-8")
    cfg, warnings = load_config(path)
    assert cfg.hallucination_patterns == ["ok"]
    assert len(warnings) == 1
