"""Импорт живучей сессии без пароля: что угодно, что умеет копировать браузер."""

from __future__ import annotations

import json

import pytest

from instagram_tracker.errors import TrackerError
from instagram_tracker.session_import import extract_sessionid

SID = "58645670417:" + "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8"


def test_bare_value():
    assert extract_sessionid(SID) == SID


def test_from_request_header():
    header = f"mid=abc; csrftoken=deadbeef; sessionid={SID}; ds_user_id=58645670417"
    assert extract_sessionid(header) == SID


def test_from_json_cookie_export(tmp_path):
    payload = [{"name": "ds_user_id", "value": "58645670417"}, {"name": "sessionid", "value": SID}]
    path = tmp_path / "cookies.json"
    path.write_text(json.dumps(payload))
    assert extract_sessionid(str(path)) == SID


def test_from_netscape_cookies_txt(tmp_path):
    line = f".instagram.com\tTRUE\t/\tTRUE\t1893456000\tsessionid\t{SID}"
    path = tmp_path / "cookies.txt"
    path.write_text("# Netscape HTTP Cookie File\n" + line + "\n")
    assert extract_sessionid(str(path)) == SID


def test_json_inside_text_not_file():
    assert extract_sessionid(json.dumps([{"name": "sessionid", "value": SID}])) == SID


def test_garbage_explains_what_is_expected():
    with pytest.raises(TrackerError, match="Не удалось найти"):
        extract_sessionid("нет-такого-кука")
