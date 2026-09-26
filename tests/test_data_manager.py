"""Хранилище снимков: имена, история, совместимость со старыми файлами."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from instagram_tracker.data_manager import SnapshotStore
from instagram_tracker.errors import SnapshotNotFoundError
from instagram_tracker.model import Snapshot

NOW = datetime(2026, 9, 26, 11, 20, 30, tzinfo=timezone.utc)


def days_ago(n: int) -> datetime:
    return NOW - timedelta(days=n)


@pytest.fixture
def store(tmp_path) -> SnapshotStore:
    return SnapshotStore(tmp_path / "data")


def make_snap(username="me", at=NOW, **kw) -> Snapshot:
    return Snapshot(username=username, captured_at=at, **kw)


def test_save_and_load_roundtrip(store):
    path = store.save_snapshot(make_snap(followers=["anna", "boris"], following=["vera"]))
    assert path.parent.name == "snapshots"
    assert path.name.startswith("me__20260926T112030Z__")
    loaded = store.load_snapshot(path)
    assert set(loaded.followers) == {"anna", "boris"}
    assert loaded.followers["anna"].full_name == json.loads(path.read_text())["followers"][0]["full_name"]


def test_sorted_filenames_match_chronology(store):
    store.save_snapshot(make_snap(at=days_ago(30)))
    store.save_snapshot(make_snap(at=NOW))
    store.save_snapshot(make_snap(at=days_ago(60)))
    infos = store.list_snapshots("me")
    assert [i.captured_at for i in infos] == sorted((i.captured_at for i in infos), reverse=True)
    assert infos[0].captured_at == NOW


def test_latest_snapshot_skips_reports(store, tmp_path):
    """Раньше файлы сравнения попадали в список снимков и роняли загрузку (KeyError)."""
    store.save_snapshot(make_snap(followers=["a"]))
    report = store.reports_dir
    report.mkdir(parents=True, exist_ok=True)
    (report / "me__20260926T112030Z__diff.json").write_text(json.dumps({"kind": "diff"}))
    legacy_comparison = store.root / "me_comparison_05_03_2024_14_22.json"
    legacy_comparison.write_text(json.dumps({"new_followers": ["x"]}))

    infos = store.list_snapshots()
    assert all("comparison" not in i.path.name for i in infos)
    assert store.latest_snapshot("me").followers.keys() == {"a"}


def test_legacy_snapshot_readable(store):
    store.root.mkdir(parents=True, exist_ok=True)
    legacy = store.root / "me_05_03_2024_14_22.json"
    legacy.write_text(
        json.dumps({"username": "me", "timestamp": "05_03_2024_14_22", "followers": ["a"], "following": ["b"]})
    )
    snapshot = store.load_snapshot(legacy)
    assert snapshot.captured_at.month == 3
    assert store.list_snapshots()  # не падает на legacy-имени


def test_latest_excludes_path_for_autocompare(store):
    """Авто-сравнение должно брать ПРЕДЫДУЩИЙ снимок, а не тот, что сохранили только что."""
    first = store.save_snapshot(make_snap(followers=["a"], following=["b"], at=days_ago(1)))
    second = store.save_snapshot(make_snap(followers=["a"], at=NOW))
    old = store.latest_snapshot("me", exclude=second)
    assert old.meta["loaded_from"] == str(first)
    assert store.latest_snapshot("me").meta["loaded_from"] == str(second)


def test_missing_snapshot_error_is_actionable(store):
    with pytest.raises(SnapshotNotFoundError):
        store.latest_snapshot("nobody")


def test_read_any_accepts_export_folder(store, tmp_path):
    import sys

    sys.path.insert(0, str(Path(__file__).parent))
    from conftest import write_export

    root = write_export(tmp_path / "exp", followers=["anna"], following=["boris"])
    snapshot = store.read_any(root)
    assert set(snapshot.followers) == {"anna"}


def test_no_overwrite_in_same_second(store):
    p1 = store.save_snapshot(make_snap(followers=["a"]))
    p2 = store.save_snapshot(make_snap(followers=["b"]))
    assert p1 != p2
    assert len(store.list_snapshots()) == 2


def test_deduped_filename_keeps_source(tmp_path):
    store = SnapshotStore(tmp_path / "data")
    store.save_snapshot(make_snap(followers=["a"]))
    store.save_snapshot(make_snap(followers=["b"]))
    infos = store.list_snapshots()
    assert {info.source for info in infos} == {"snapshot"}, [i.source for i in infos]
