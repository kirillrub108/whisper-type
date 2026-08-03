from __future__ import annotations

import json
from pathlib import Path

from whispertype.history import PhraseHistory


def test_add_and_recent_newest_first(tmp_path: Path) -> None:
    history = PhraseHistory(tmp_path / "history.json")
    history.add("первая")
    history.add("вторая")
    history.add("третья")
    assert history.recent() == ["третья", "вторая", "первая"]


def test_consecutive_duplicate_not_added_twice(tmp_path: Path) -> None:
    history = PhraseHistory(tmp_path / "history.json")
    history.add("привет")
    history.add("привет")
    assert history.recent() == ["привет"]


def test_limit_drops_oldest(tmp_path: Path) -> None:
    history = PhraseHistory(tmp_path / "history.json", limit=3)
    for i in range(5):
        history.add(f"фраза {i}")
    assert history.recent() == ["фраза 4", "фраза 3", "фраза 2"]


def test_persists_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    first = PhraseHistory(path)
    first.add("сохранённая фраза")

    second = PhraseHistory(path)
    second.load()
    assert second.recent() == ["сохранённая фраза"]


def test_missing_file_is_empty(tmp_path: Path) -> None:
    history = PhraseHistory(tmp_path / "does_not_exist.json")
    history.load()
    assert history.recent() == []


def test_broken_json_falls_back_to_empty(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    path.write_text("{not json", encoding="utf-8")
    history = PhraseHistory(path)
    history.load()
    assert history.recent() == []


def test_non_list_root_falls_back_to_empty(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    path.write_text(json.dumps({"a": 1}), encoding="utf-8")
    history = PhraseHistory(path)
    history.load()
    assert history.recent() == []


def test_non_string_items_dropped(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    path.write_text(json.dumps(["ok", 5, None, ""]), encoding="utf-8")
    history = PhraseHistory(path)
    history.load()
    assert history.recent() == ["ok"]


def test_utf8_bom_is_read(tmp_path: Path) -> None:
    # Блокнот Windows сохраняет UTF-8 с BOM
    path = tmp_path / "history.json"
    path.write_text(json.dumps(["привет"]), encoding="utf-8-sig")
    history = PhraseHistory(path)
    history.load()
    assert history.recent() == ["привет"]


def test_clear_empties_and_persists(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    history = PhraseHistory(path)
    history.add("что-то")
    history.clear()
    assert history.recent() == []

    reloaded = PhraseHistory(path)
    reloaded.load()
    assert reloaded.recent() == []
