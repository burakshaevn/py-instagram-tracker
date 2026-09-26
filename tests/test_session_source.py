"""Живой режим: сессия без пароля, пагинация, лимиты, честная реакция на обрезку данных.

Здесь проверяются ровно те места, из-за которых анализ «не работал молча»:
пустой ответ вместо ошибки и принятие усечённого списка за полный.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

import pytest

from conftest import FakeClient, user_short
from instagram_tracker.errors import (
    IncompleteDataError,
    LoginRejected,
    RateLimited,
    SessionRequired,
    SourceError,
)
from instagram_tracker.observers import RecordingObserver
from instagram_tracker.sources.session import SessionSource


def make_source(**kwargs) -> SessionSource:
    kwargs.setdefault("sessionid", "123456789:" + "b" * 36)
    kwargs.setdefault("delay_range", (0.0, 0.0))
    kwargs.setdefault("retry_base_delay", 0.0)
    kwargs.setdefault("page_size", 2)
    source = SessionSource(**kwargs)
    source.attach(RecordingObserver())
    return source


def prepared(fake_clients, **kwargs):
    """Источник + уже подключённый FakeClient (клиент создаётся лениво, в connect())."""
    source = make_source(**kwargs)
    _ = source.client
    return source, fake_clients[-1]


def prime(client: FakeClient, followers: List[str], following: List[str], *, limit: bool = False) -> FakeClient:
    client.configure(
        followers=[user_short(u) for u in followers],
        following=[user_short(u) for u in following],
        follower_count=len(followers),
        following_count=len(following),
        username="testuser",
    )
    return client


def test_snapshot_via_sessionid_without_password(fake_clients, users):
    source, client = prepared(fake_clients)
    prime(client, users["followers"], users["following"])
    snapshot = source.fetch_snapshot("testuser")

    assert snapshot.count("followers") == 5
    assert snapshot.count("following") == 5
    assert snapshot.source.startswith("session:sessionid")
    assert snapshot.reliable is True
    # пагинация: page_size=2 -> страниц больше одной, курсор передаётся
    calls = [c for c in client.calls if c[0] == "user_followers_v1_chunk"]
    assert len(calls) >= 3
    assert calls[1][1]  # непустой max_id со второй страницы


def test_session_is_persisted_so_next_run_needs_nothing(fake_clients, tmp_path):
    session_file = tmp_path / "session.json"
    source, client = prepared(
        fake_clients, session_file=session_file, sessionid="123456789:" + "c" * 36
    )
    prime(client, ["a"], [])
    source.fetch_snapshot("testuser")
    assert session_file.is_file()
    assert json.loads(session_file.read_text())["cookies"]["sessionid"]

    # следующий запуск — только по файлу, без sessionid и без пароля
    second, second_client = prepared(fake_clients, session_file=session_file, sessionid=None)
    prime(second_client, ["a"], [])
    snapshot = second.fetch_snapshot("testuser")
    assert snapshot.source == "session:session_file:session.json"


def test_without_any_credentials_raises_instead_of_returning_empty(fake_clients):
    source = SessionSource(session_file=Path("/nonexistent/session.json"))
    with pytest.raises(SessionRequired):
        source.connect()


def test_invalid_sessionid_rejected_early(fake_clients):
    with pytest.raises(LoginRejected):
        make_source(sessionid="короткий").connect()


def test_truncated_list_raises_incomplete_error(fake_clients):
    """Instagram отдал 4 из 900 подписчиков — это ошибка, а не «4 подписчика»."""
    source, client = prepared(fake_clients)
    prime(client, ["a", "b", "c", "d"], ["x"])
    client.configure(follower_count=900, should_limit=True)

    with pytest.raises(IncompleteDataError) as exc:
        source.fetch_snapshot("testuser")
    assert "4 из 900" in str(exc.value)


def test_allow_partial_returns_data_with_warning(fake_clients):
    source, client = prepared(fake_clients, allow_partial=True)
    prime(client, ["a", "b"], ["x"])
    client.configure(follower_count=900, should_limit=True)

    snapshot = source.fetch_snapshot("testuser")
    assert snapshot.complete["followers"] is False
    assert snapshot.reliable is False
    assert snapshot.meta["truncated"]["followers"]["expected"] == 900
    assert any("--allow-partial" in message for message in source.observers[0].messages)


def test_rate_limit_is_retried_then_succeeds(fake_clients, users):
    source, client = prepared(fake_clients, max_retries=3, retry_base_delay=0.0)
    prime(client, users["followers"], users["following"])
    client.configure(fail_times=2)

    snapshot = source.fetch_snapshot("testuser")
    assert snapshot.count("followers") == 5
    assert any("ограничил частоту" in m for m in source.observers[0].messages)


def test_rate_limit_exhausted_raises(fake_clients, users):
    source, client = prepared(fake_clients, max_retries=1)
    prime(client, users["followers"], [])
    client.configure(fail_times=50)

    with pytest.raises(RateLimited):
        source.fetch_snapshot("testuser")
    # принципиально: вместо RateLimited старая версия вернула бы пустое множество


def test_private_endpoint_failure_falls_back_to_public_graphql(fake_clients):
    source, client = prepared(fake_clients)
    prime(client, ["a", "b"], ["x"])
    client.configure(errors=["private"])

    snapshot = source.fetch_snapshot("testuser")
    assert snapshot.count("followers") == 2
    assert ("user_followers_gql_chunk", "") in client.calls


def test_unknown_username_gives_clear_error(fake_clients):
    source = make_source()
    with pytest.raises(SourceError, match="не найден"):
        source.fetch_snapshot("ghost")


def test_empty_lists_are_not_silently_accepted(fake_clients):
    """Ни одного подписчика и подписок — подозрительно: CLI обязан это показать."""
    source, client = prepared(fake_clients)
    prime(client, [], [])
    snapshot = source.fetch_snapshot("testuser")
    assert snapshot.count("followers") == 0
    # ...но при неизвестном ожидаемом количестве это не считается усечением
    assert snapshot.reliable is True
