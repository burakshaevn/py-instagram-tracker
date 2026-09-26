"""Фикстуры: реалистичные «выгрузки Instagram» и подставной клиент instagrapi."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pytest

# --- построение выгрузки ------------------------------------------------


def export_entry(
    username: str,
    *,
    timestamp: int = 1_700_000_000,
    full_name: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Одна запись в каноничном формате `string_list_data`."""
    entry: Dict[str, Any] = {
        "title": full_name or username.title(),
        "media_list_data": [],
        "string_list_data": [
            {
                "href": f"https://www.instagram.com/{username}",
                "value": username,
                "timestamp": timestamp,
            }
        ],
    }
    if user_id:
        entry["pk"] = user_id
    return entry


def write_export(
    directory: Path,
    *,
    followers: Sequence[str] = (),
    following: Sequence[str] = (),
    username: str = "testuser",
    chunk_size: int = 0,
    extra_files: Optional[Dict[str, Any]] = None,
    flat_list: bool = False,
) -> Path:
    """Пишет дерево файлов как в настоящей выгрузке (connections/followers_and_following)."""
    target = directory / "connections" / "followers_and_following"
    target.mkdir(parents=True, exist_ok=True)

    def dump(names: Sequence[str], key: str, pattern: str) -> None:
        chunks: List[Sequence[str]] = (
            [names] if not chunk_size else [names[i : i + chunk_size] for i in range(0, len(names), chunk_size)]
        )
        for index, chunk in enumerate(chunks, start=1):
            entries = [export_entry(name) for name in chunk]
            payload: Any = entries if flat_list else {key: entries}
            suffix = f"_{index}" if len(chunks) > 1 or pattern == "followers" else ""
            (target / f"{pattern}{suffix}.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )

    dump(list(followers), "relationships_followers", "followers")
    dump(list(following), "relationships_following", "following")

    for name, payload in (extra_files or {}).items():
        (target / name).write_text(json.dumps(payload), encoding="utf-8")

    info = directory / "account" / "personal_information.json"
    info.parent.mkdir(parents=True, exist_ok=True)
    info.write_text(
        json.dumps({"personal_information": {"username": username}}), encoding="utf-8"
    )
    return directory


def zip_export(directory: Path, zip_path: Path) -> Path:
    with zipfile.ZipFile(zip_path, "w") as archive:
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=str(path.relative_to(directory)))
    return zip_path


def html_export(directory: Path, *, followers: Sequence[str], following: Sequence[str]) -> Path:
    """HTML-вариант выгрузки: те же списки, но размеченные ссылками."""
    target = directory / "connections" / "followers_and_following"
    target.mkdir(parents=True, exist_ok=True)
    for name, users in (("followers_1.html", followers), ("following.html", following)):
        links = "\n".join(
            f'<li><a href="https://www.instagram.com/{u}/" target="_blank">{u.title()}</a></li>'
            for u in users
        )
        (target / name).write_text(
            f"<html><body><ul>{links}</ul></body></html>", encoding="utf-8"
        )
    return directory


# --- подставной клиент instagrapi ---------------------------------------


class FakeClientError(Exception):
    """Аналог instagrapi.exceptions.ClientError — база для всего остального."""


class FakePleaseWaitFewMinutes(FakeClientError):
    pass


class FakeClientThrottledError(FakeClientError):
    pass


class FakeClientConnectionError(Exception):
    pass


class FakeProxyAddressIsBlocked(Exception):
    pass


class FakePrivateError(FakeClientError):
    pass


class FakeNotFoundError(FakeClientError):
    pass


class FakeFeedbackRequired(FakeClientError):
    pass


class FakeChallengeRequired(FakeClientError):
    pass


class FakeTwoFactorRequired(Exception):
    pass


#: как instagrapi раскладывает имена исключений — тестируем ветки обработки честно
FAKE_EXCEPTIONS = {
    "TwoFactorRequired": FakeTwoFactorRequired,
    "ChallengeRequired": FakeChallengeRequired,
    "FeedbackRequired": FakeFeedbackRequired,
    "PleaseWaitFewMinutes": FakePleaseWaitFewMinutes,
    "ClientThrottledError": FakeClientThrottledError,
    "ClientConnectionError": FakeClientConnectionError,
    "ClientBadRequestError": FakeClientError,
    "ClientError": FakeClientError,
    "NotFoundError": FakeNotFoundError,
    "PrivateError": FakePrivateError,
    "ProxyAddressIsBlocked": FakeProxyAddressIsBlocked,
}


class FakeUser:
    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)


def user_short(username: str, pk: Optional[str] = None) -> FakeUser:
    return FakeUser(
        pk=pk or str(abs(hash(username)) % 10**10),
        username=username,
        full_name=username.title(),
        is_private=False,
        is_verified=False,
    )


class FakeClient:
    """Мини-INSTAGRAPI: пагинация, лимиты, обрезка списка по воле сервера."""

    instances: List["FakeClient"] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.followers: List[FakeUser] = []
        self.following: List[FakeUser] = []
        self.follower_count = 0
        self.following_count = 0
        self.page_size = 200
        self.should_limit = False
        self.fail_times = 0
        self.fail_with: type = FakePleaseWaitFewMinutes
        self.errors: List[str] = []
        self.calls: List[Tuple[str, str]] = []
        self.dumped_to: Optional[str] = None
        self.loaded_from: Optional[str] = None
        self.user_id = "123456789"
        self.username = "testuser"
        self.sessionid = "123456789:" + "a" * 36
        self.authorization = ""
        self.last_json: Dict[str, Any] = {}
        self.settings: Dict[str, Any] = {}
        self.private_auth = True
        FakeClient.instances.append(self)

    # конфигурация под тест
    def configure(self, **kwargs: Any) -> "FakeClient":
        for key, value in kwargs.items():
            setattr(self, key, value)
        return self

    # --- auth ---
    def load_settings(self, path: str, **kwargs: Any) -> Dict[str, Any]:
        self.loaded_from = path
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        self.settings = payload
        if payload.get("expired"):
            self.user_id = None
        return payload

    def dump_settings(self, path: str) -> bool:
        self.dumped_to = path
        Path(path).write_text(json.dumps({"cookies": {"sessionid": self.sessionid}}), encoding="utf-8")
        return True

    def get_settings(self) -> Dict[str, Any]:
        return {"last_login": 1_700_000_000}

    def login_by_sessionid(self, sessionid: str) -> bool:
        self.calls.append(("login_by_sessionid", sessionid[:12]))
        return True

    def login(self, username=None, password=None, **kwargs: Any) -> bool:
        self.calls.append(("login", str(username)))
        return True

    # --- users ---
    def user_info(self, user_id: str, use_cache: bool = True) -> FakeUser:
        return FakeUser(
            pk=user_id,
            username=self.username,
            follower_count=self.follower_count,
            following_count=self.following_count,
        )

    def user_info_by_username(self, username: str, use_cache: bool = True) -> FakeUser:
        return self.user_info(self.user_id)

    def user_id_from_username(self, username: str) -> str:
        if username == "ghost":
            raise FakeNotFoundError("User not found")
        self.username = username
        return self.user_id

    def _chunk(
        self, method: str, kind: str, user_id: str, max_amount: int, cursor: str
    ) -> Tuple[List[FakeUser], str]:
        self.calls.append((method, cursor))
        if self.errors and self.errors[0] == "private":
            self.errors.pop(0)
            raise FakePrivateError("Login required to access this endpoint")
        if self.fail_times > 0:
            self.fail_times -= 1
            raise self.fail_with("Please wait a few minutes before you try again.")
        source = getattr(self, kind)
        start = int(cursor) if cursor else 0
        page = source[start : start + (max_amount or self.page_size)]
        next_start = start + len(page)
        next_cursor = str(next_start) if next_start < len(source) else ""
        self.last_json = (
            {"should_limit_list_of_followers": True} if self.should_limit else {}
        )
        return page, next_cursor

    def user_followers_v1_chunk(self, user_id, max_amount=0, max_id="", order=None):
        return self._chunk("user_followers_v1_chunk", "followers", user_id, max_amount, max_id)

    def user_following_v1_chunk(self, user_id, max_amount=0, max_id=""):
        return self._chunk("user_following_v1_chunk", "following", user_id, max_amount, max_id)

    def user_followers_gql_chunk(self, user_id, max_amount=0, end_cursor=None):
        return self._chunk(
            "user_followers_gql_chunk", "followers", user_id, max_amount, end_cursor or ""
        )

    def user_following_gql_chunk(self, user_id, max_amount=0, end_cursor=None):
        return self._chunk(
            "user_following_gql_chunk", "following", user_id, max_amount, end_cursor or ""
        )


@pytest.fixture
def fake_clients(monkeypatch: pytest.MonkeyPatch):
    """Подменяет импорт instagrapi в SessionSource на FakeClient."""
    from instagram_tracker.sources import session as session_module

    created: List[FakeClient] = []
    original_init = FakeClient.__init__

    def tracked_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        created.append(self)

    monkeypatch.setattr(FakeClient, "__init__", tracked_init)
    monkeypatch.setattr(session_module, "_load_instagrapi", lambda: (FakeClient, dict(FAKE_EXCEPTIONS)))
    # сеть в тестах не нужна: ретраи мгновенные
    monkeypatch.setattr(session_module.time, "sleep", lambda *_: None)
    return created


@pytest.fixture
def run_cli():
    """Вызов CLI как функции — без подпроцесса, но через ту же точку входа."""
    from instagram_tracker.cli import main

    def _run(*argv: str) -> int:
        return main(list(argv))

    return _run


@pytest.fixture
def users() -> Dict[str, List[str]]:
    return {
        "followers": ["anna", "boris", "vera", "gosha", "dima"],
        "following": ["anna", "boris", "vera", "elena", "kirill"],
    }
