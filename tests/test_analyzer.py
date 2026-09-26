"""Ядро анализа: взаимные подписки и динамика между снимками."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from instagram_tracker.analyzer import analyze_followbacks, diff_snapshots, quality_warnings
from instagram_tracker.model import Snapshot, UserRef

NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)


def snap(followers=(), following=(), *, username="me", at=NOW, **kwargs) -> Snapshot:
    return Snapshot(
        username=username,
        captured_at=at,
        followers=list(followers),
        following=list(following),
        **kwargs,
    )


def test_non_followers_direction_is_not_inverted():
    """Я подписан на elena/kirill, они на меня — нет. Это и есть «не подписаны в ответ»."""
    report = analyze_followbacks(snap(followers=["anna"], following=["anna", "elena", "kirill"]))
    assert [u.username for u in report.not_following_back] == ["elena", "kirill"]
    assert [u.username for u in report.followers_not_followed] == []
    assert [u.username for u in report.mutual] == ["anna"]


def test_fans_you_do_not_follow():
    report = analyze_followbacks(snap(followers=["anna", "fan1"], following=["anna"]))
    assert [u.username for u in report.followers_not_followed] == ["fan1"]


def test_usernames_are_normalized_before_comparison():
    """'@Anna' и 'anna' — один человек; иначе анализ выдумывает отписки."""
    report = analyze_followbacks(
        Snapshot(
            username="me",
            captured_at=NOW,
            followers=[UserRef(username="anna"), "https://www.instagram.com/boris/"],
            following=[UserRef(username="Anna", user_id="1"), "@BORIS"],
        )
    )
    assert report.not_following_back == []
    assert len(report.mutual) == 2


def test_diff_new_and_unfollowers():
    old = snap(followers=["anna", "boris", "vera"], following=["anna"])
    new = snap(followers=["anna", "gosha"], following=["anna", "elena"])
    report = diff_snapshots(old, new)
    assert [u.username for u in report.new_followers] == ["gosha"]
    assert [u.username for u in report.unfollowers] == ["boris", "vera"]
    assert [u.username for u in report.new_following] == ["elena"]
    assert [u.username for u in report.unfollowed] == []
    assert report.period_days == 0


def test_rename_is_not_an_unfollow():
    """Смена ника не должна выглядеть как «отписался + подписался заново»."""
    old = snap(followers=[UserRef(username="oldname", user_id="42")], following=[])
    new = snap(followers=[UserRef(username="newname", user_id="42")], following=[])
    report = diff_snapshots(old, new)
    assert report.unfollowers == []
    assert report.new_followers == []
    assert [(r.old_username, r.new_username) for r in report.renames] == [("oldname", "newname")]
    assert any("сменили ник" in w for w in report.warnings)


def test_without_user_id_rename_still_looks_like_unfollow():
    """Честно фиксируем ограничение: в выгрузке id нет — переименование не распознать."""
    old = snap(followers=["oldname"])
    new = snap(followers=["newname"])
    report = diff_snapshots(old, new)
    assert [u.username for u in report.unfollowers] == ["oldname"]
    assert report.renames == []


def test_truncated_snapshot_produces_warning_not_silent_garbage():
    snapshot = snap(followers=["anna"], following=["anna", "elena"], expected_counts={"followers": 900})
    report = analyze_followbacks(snapshot)
    assert any("усечён" in w for w in report.warnings)
    # сам факт усечения не запрещает разбор, но обязан быть виден
    assert report.not_following_back[0].username == "elena"


def test_stale_snapshot_warns():
    old = snap(followers=["a"], at=NOW - timedelta(days=200))
    warnings = quality_warnings(old, now=NOW)
    assert any("200 дн" in w for w in warnings)


def test_empty_data_is_flagged():
    warnings = quality_warnings(snap())
    assert any("Пустой список" in w for w in warnings)


def test_cannot_compare_different_accounts():
    with pytest.raises(ValueError):
        diff_snapshots(snap(["a"], username="me"), snap(["b"], username="someone-else"))


def test_report_serialization_roundtrip():
    old = snap(followers=["anna", "boris"], following=["vera"])
    new = snap(followers=["anna"], following=["vera", "elena"])
    report = diff_snapshots(old, new)
    payload = report.to_dict()
    assert payload["counts"] == {"new_followers": 0, "unfollowers": 1, "new_following": 1, "unfollowed": 0}
    restored = type(report).from_dict(payload)
    assert [u.username for u in restored.unfollowers] == ["boris"]


def test_legacy_comparison_file_can_be_read():
    """Файлы вида username_comparison_*.json из прошлой версии проекта."""
    legacy = {
        "new_followers": ["anna"],
        "unfollowers": ["boris", "vera"],
        "new_following": [],
        "unfollowed": ["kirill"],
        "timestamp": "05_03_2024_14_22",
        "compared_with": "01_02_2024_10_00",
    }
    report = diff_snapshots.__globals__["DiffReport"].from_dict(legacy)
    assert [u.username for u in report.unfollowers] == ["boris", "vera"]
    assert report.new_captured_at.year == 2024


def test_comparing_same_moment_warns():
    at = NOW
    report = diff_snapshots(snap(["a"], ["b"], at=at), snap(["a"], ["b"], at=at))
    assert any("не «свежее»" in w for w in report.warnings)
    assert report.is_empty
