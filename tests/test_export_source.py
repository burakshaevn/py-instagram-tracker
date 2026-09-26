"""Разбор официальной выгрузки Instagram — основной источник данных."""

from __future__ import annotations

import json

import pytest

from instagram_tracker.errors import ExportNotFoundError
from instagram_tracker.sources.export import ExportSource
from conftest import html_export, write_export, zip_export


def test_parses_canonical_export(tmp_path, users):
    root = write_export(tmp_path, followers=users["followers"], following=users["following"], username="tester")
    snapshot = ExportSource(root).fetch_snapshot()

    assert snapshot.username == "tester"
    assert set(snapshot.followers) == set(users["followers"])
    assert set(snapshot.following) == set(users["following"])
    # даты подписки из выгрузки — то, чего живой API не даёт
    assert snapshot.followers["anna"].since is not None
    assert snapshot.followers["anna"].full_name == "Anna"
    assert snapshot.reliable is True


def test_handles_chunked_followers_files(tmp_path):
    names = [f"user{i}" for i in range(7)]
    root = write_export(tmp_path, followers=names, following=[], chunk_size=3)
    files = sorted(p.name for p in (root / "connections" / "followers_and_following").glob("followers*"))
    assert len(files) == 3
    snapshot = ExportSource(root).fetch_snapshot()
    assert len(snapshot.followers) == 7


def test_reads_bare_list_format(tmp_path):
    """Старый/самодельный формат: голый JSON-массив без обёртки relationships_*."""
    folder = tmp_path / "followers_and_following"
    folder.mkdir()
    (folder / "followers_1.json").write_text(
        json.dumps([{"string_list_data": [{"href": f"https://www.instagram.com/u{i}/", "value": f"u{i}", "timestamp": 1}]} for i in range(4)])
    )
    (folder / "following.json").write_text(json.dumps([{"string_list_data": [{"value": "x1"}]}]))
    snapshot = ExportSource(folder).fetch_snapshot()
    assert set(snapshot.followers) == {f"u{i}" for i in range(4)}
    assert set(snapshot.following) == {"x1"}


def test_reads_zip_archive(tmp_path, users):
    root = write_export(tmp_path / "src", followers=users["followers"], following=users["following"])
    archive = zip_export(root, tmp_path / "instagram-export.zip")
    snapshot = ExportSource(archive).fetch_snapshot()
    assert snapshot.count("followers") == len(users["followers"])
    # ник восстанавливается и из users/<nick>/, и из account/personal_information.json
    assert snapshot.username == "testuser"
    assert snapshot.meta["files"]["followers"] == ["followers_1.json"]


def test_reads_html_export(tmp_path):
    root = html_export(tmp_path, followers=["anna", "boris"], following=["vera"])
    snapshot = ExportSource(root).fetch_snapshot()
    assert set(snapshot.followers) == {"anna", "boris"}
    assert snapshot.following["vera"].full_name == "Vera"


def test_single_file_next_to_script(tmp_path, monkeypatch):
    """Распространённый сценарий: два файла скопированы рядом со скриптом."""
    folder = tmp_path
    (folder / "followers_1.json").write_text(json.dumps({"relationships_followers": [{"string_list_data": [{"value": "anna"}]}]}))
    (folder / "following.json").write_text(json.dumps({"relationships_following": [{"string_list_data": [{"value": "boris"}]}]}))
    snapshot = ExportSource(folder / "followers_1.json").fetch_snapshot()
    assert set(snapshot.followers) == {"anna"}
    assert set(snapshot.following) == {"boris"}


def test_extra_lists_are_collected(tmp_path):
    root = write_export(
        tmp_path,
        followers=["a"],
        following=["b"],
        extra_files={
            "pending_follow_requests.json": {"relationships_pending_follow_requests": [{"string_list_data": [{"value": "waiting1"}]}]},
            "recently_unfollowed_profiles.json": {"string_list_data": [{"value": "oldfriend"}]},
        },
    )
    snapshot = ExportSource(root).fetch_snapshot()
    assert snapshot.meta["pending_follow_requests"] == ["waiting1"]
    assert snapshot.meta["recently_unfollowed"] == ["oldfriend"]


def test_explicit_files_ignore_their_names(tmp_path):
    """ExportSource(followers_files=..., following_files=...) — имена файлов не важны."""
    folder = tmp_path
    (folder / "my_followers_dump.json").write_text(
        json.dumps([{"string_list_data": [{"value": "anna"}]}])
    )
    (folder / "step1.json").write_text(json.dumps([{"string_list_data": [{"value": "boris"}]}]))
    source = ExportSource(
        followers_files=[folder / "my_followers_dump.json"],
        following_files=[folder / "step1.json"],
        username="tester",
    )
    snapshot = source.fetch_snapshot()
    assert set(snapshot.followers) == {"anna"}
    assert set(snapshot.following) == {"boris"}
    assert snapshot.username == "tester"


def test_missing_lists_raise(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ExportNotFoundError) as exc:
        ExportSource(empty).fetch_snapshot()
    assert "Followers and following" in str(exc.value)


def test_broken_json_explains_itself(tmp_path):
    folder = tmp_path / "connections" / "followers_and_following"
    folder.mkdir(parents=True)
    (folder / "followers_1.json").write_text("{oops")
    with pytest.raises(ExportNotFoundError):
        ExportSource(tmp_path).fetch_snapshot()
