"""Нормализация идентификаторов и модель снимка."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from instagram_tracker.model import Snapshot, UserRef, normalize_username, parse_timestamp


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Anna.M", "anna.m"),
        ("@anna", "anna"),
        ("https://www.instagram.com/anna/", "anna"),
        ("https://www.instagram.com/p/ABC123/", ""),      # это пост, не профиль
        ("Имя Фамилия", ""),                              # display name вместо ника
        ("", ""),
        (None, ""),
        ("anna?igsh=abc", "anna"),
    ],
)
def test_normalize_username(raw, expected):
    assert normalize_username(raw) == expected


def test_parse_timestamp_variants():
    assert parse_timestamp(1_700_000_000).year == 2023
    assert parse_timestamp("1700000000000").tzinfo == timezone.utc   # миллисекунды
    assert parse_timestamp("2024-01-30") == datetime(2024, 1, 30, tzinfo=timezone.utc)
    assert parse_timestamp("не дата") is None
    assert parse_timestamp(None) is None


def test_userref_from_export_entry_prefers_href_when_value_is_display_name():
    entry = {
        "title": "Анна",
        "string_list_data": [
            {"href": "https://www.instagram.com/anna/", "value": "Анна", "timestamp": 1}
        ],
    }
    ref = UserRef.from_export_entry(entry)
    assert ref.username == "anna"
    assert ref.full_name == "Анна"


def test_snapshot_from_legacy_dict_and_roundtrip():
    """Старый формат `data/username_DD_MM_YYYY_HH_MM.json` обязан читаться."""
    legacy = {
        "username": "TestUser",
        "timestamp": "05_03_2024_14_22",
        "followers": ["anna", "boris"],
        "following": ["vera"],
        "stats": {"followers_count": 2, "following_count": 1},
    }
    snapshot = Snapshot.from_dict(legacy)
    assert snapshot.username == "testuser"
    assert snapshot.followers.keys() == {"anna", "boris"}
    assert snapshot.captured_at.year == 2024
    assert snapshot.reliable is True            # полнота не оспаривается
    assert snapshot.to_dict()["counts"] == {"followers": 2, "following": 1}


def test_snapshot_truncation_reported():
    snapshot = Snapshot(
        username="u",
        captured_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        followers=["a", "b"],
        expected_counts={"followers": 5000},
    )
    assert snapshot.is_truncated("followers")
    assert snapshot.truncations == {"followers": (2, 5000)}
    assert snapshot.reliable is False


def test_parse_timestamp_supports_z_suffix_on_older_python():
    """3.10 не понимает «Z» в fromisoformat — разбираем сами (instagrapi требует 3.10+)."""
    assert parse_timestamp("2026-01-30T12:00:00Z") == parse_timestamp("2026-01-30T12:00:00+00:00")
    assert parse_timestamp("2026-01-30 12:00:00Z").tzinfo is timezone.utc
