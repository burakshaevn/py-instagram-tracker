"""Модель данных проекта: пользователь, снимок подписок, нормализация идентификаторов.

Здесь нет никакого ввода-вывода: только структуры данных и правила нормализации.
Это сознательное ограничение — вся логика сравнения остаётся проверяемой на обычных
словарях, без сети и без Instagram.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

__all__ = [
    "SCHEMA_VERSION",
    "UserRef",
    "Snapshot",
    "normalize_username",
    "parse_timestamp",
    "username_from_url",
]

SCHEMA_VERSION = 2

# Профиль Instagram: 1-30 символов [a-z0-9. _], начинается и заканчивается на букву/цифру.
_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._]{0,28}[a-z0-9]$")
_INSTAGRAM_URL_RE = re.compile(
    r"(?:www\.)?instagram\.com/([A-Za-z0-9_.]{1,40})", re.IGNORECASE
)
_RESERVED_PATHS = {"p", "reel", "reels", "stories", "explore", "accounts", "director"}
_LEGACY_DATE_FORMATS = ("%d_%m_%Y_%H_%M", "%Y-%m-%d_%H-%M", "%d_%m_%Y")


def username_from_url(value: Any) -> str:
    """Достаёт ник из ссылки на профиль ('https://www.instagram.com/foo/' -> 'foo')."""
    if not value:
        return ""
    match = _INSTAGRAM_URL_RE.search(str(value))
    if not match:
        return ""
    candidate = match.group(1).strip("/")
    if candidate.lower() in _RESERVED_PATHS:
        return ""
    return candidate


def normalize_username(value: Any) -> str:
    """Приводит любой «идентификатор пользователя» к каноничному нику.

    Принимает ник, `@ник`, ссылку на профиль, строку с мусором по краям.
    Возвращает нижний регистр без `@`. Пустую строку — если распознать не удалось.

    Нормализация важна: Instagram отдаёт ники в разном виде (иногда в `value`
    лежит отображаемое имя, а ник только в `href`), а сравнение множеств чувствительно
    к регистру и пробелам.
    """
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    # «nick?igsh=...» и «nick#t=1» — ссылки из сторис/шаринга режем по параметрам
    text = re.split(r"[?#]", text, maxsplit=1)[0].strip()
    if not text:
        return ""
    if "/" in text or ":" in text:
        from_url = username_from_url(text)
        if from_url:
            text = from_url
        else:
            return ""
    text = text.lstrip("@").strip().rstrip("/").strip()
    # В выгрузке в value иногда попадает "Имя Фамилия" вместо ника.
    if " " in text:
        return ""
    return text.lower()


def is_valid_username(value: str) -> bool:
    """Похож ли строка на ник Instagram."""
    return bool(value) and bool(_USERNAME_RE.match(value))


def parse_timestamp(value: Any) -> Optional[datetime]:
    """Парсит метку времени выгрузки: epoch (сек/мс), ISO 8601, datetime.

    Возвращает aware-datetime в UTC либо None, если значение неразбираемо.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _from_epoch(value)
    text = str(value).strip()
    if text.isdigit():
        return _from_epoch(int(text))
    # Даты прежнего формата проекта: 05_03_2024_14_22 / 2024-03-05_14-22
    for fmt in _LEGACY_DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    # «2024-01-30 12:00:00», «2024-01-30T12:00:00+00:00», «2024-01-30»
    # X-суффикс срезаем руками: datetime.fromisoformat() понимает его только с 3.11.
    candidates = (text, text.replace(" ", "T"))
    if text.endswith(("Z", "z")):
        candidates += (text[:-1] + "+00:00", text[:-1].replace(" ", "T") + "+00:00")
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _from_epoch(number: float) -> Optional[datetime]:
    """epoch -> datetime; автоматически определяет миллисекунды."""
    try:
        seconds = float(number)
    except (TypeError, ValueError):
        return None
    if abs(seconds) > 1e11:  # миллисекунды
        seconds /= 1000.0
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _clean_flag(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


@dataclass(frozen=True)
class UserRef:
    """Пользователь в составе списка подписок/подписчиков.

    `username` — нормализованный ник (ключ для сравнения множеств).
    `user_id` — pk аккаунта, если он известен: позволяет пережить смену ника
    (переименованный аккаунт иначе считается «отписавшимся» + «новым подписчиком»).
    """

    username: str
    user_id: str = ""
    full_name: str = ""
    profile_url: str = ""
    is_private: Optional[bool] = None
    is_verified: Optional[bool] = None
    since: Optional[datetime] = None  # дата/время возникновения подписки

    def __post_init__(self) -> None:
        # Инвариант: username всегда нормализован. Иначе «Anna» и «anna» окажутся
        # разными людьми, и анализ начнёт выдумывать подписки/отписки.
        normalized = normalize_username(self.username)
        if normalized != self.username:
            object.__setattr__(self, "username", normalized)

    @property
    def key(self) -> str:
        return self.username

    @property
    def display(self) -> str:
        """Ник с именем, если оно известно — удобно для консоли."""
        if self.full_name and self.full_name.lower() != self.username:
            return f"{self.username} ({self.full_name})"
        return self.username

    # --- конструкторы из внешних форматов --------------------------------

    @classmethod
    def from_export_entry(cls, entry: Mapping[str, Any]) -> Optional["UserRef"]:
        """Запись выгрузки Instagram («Download your information»).

        Формат 2024+ (`string_list_data`) и старый плоский вариант
        (`{"value": "nick"}` / просто строка). Возвращает None, если ник не найден.
        """
        if entry is None:
            return None
        if isinstance(entry, (str, int)):
            username = normalize_username(entry)
            return cls(username=username) if username else None
        if not isinstance(entry, Mapping):
            return None

        holders: List[Mapping[str, Any]] = []
        for holder in (entry.get("string_list_data") or []):
            if isinstance(holder, Mapping):
                holders.append(holder)
        if not holders:
            holders.append(entry)  # плоский формат

        username = normalize_username(entry.get("username"))  # формат Snapshot.to_dict()
        profile_url = str(entry.get("profile_url") or "").strip()
        stamp = entry.get("since")
        for holder in holders:
            href = holder.get("href")
            if href:
                profile_url = profile_url or str(href).strip()
            # В `value` выгрузка кладёт то ник, то отображаемое имя: ником считаем
            # только то, что действительно похоже на handle Instagram.
            candidate = normalize_username(holder.get("value"))
            if candidate and is_valid_username(candidate):
                username = username or candidate
            if not username and href:
                username = normalize_username(href)
            if stamp is None and holder.get("timestamp") is not None:
                stamp = holder.get("timestamp")

        if not username and entry.get("title"):
            # `title` — отображаемое имя; ник извлекаем из href внутри него.
            href = entry.get("href") or entry.get("title")
            username = normalize_username(href)

        if not username:
            return None

        return cls(
            username=username,
            user_id=str(entry.get("pk") or entry.get("user_id") or "").strip(),
            full_name=str(entry.get("title") or entry.get("full_name") or "").strip(),
            profile_url=profile_url or str(entry.get("profile_url") or "").strip(),
            since=parse_timestamp(stamp),
        )

    @classmethod
    def from_instagrapi(cls, user: Any) -> Optional["UserRef"]:
        """Объект `UserShort`/`User` из instagrapi."""
        if user is None:
            return None
        raw_username = getattr(user, "username", None) or (
            user.get("username") if isinstance(user, Mapping) else None
        )
        username = normalize_username(raw_username)
        if not username:
            return None
        get = (
            (lambda k, d=None: getattr(user, k, d))
            if not isinstance(user, Mapping)
            else (lambda k, d=None: user.get(k, d))
        )
        pk = get("pk") or get("id")
        return cls(
            username=username,
            user_id=str(pk).strip() if pk is not None else "",
            full_name=str(get("full_name") or "").strip(),
            profile_url=f"https://www.instagram.com/{username}/",
            is_private=_clean_flag(get("is_private")),
            is_verified=_clean_flag(get("is_verified")),
            since=parse_timestamp(get("follow_date") or get("mutual_followers_count")),
        )

    @classmethod
    def coerce(cls, value: Any) -> Optional["UserRef"]:
        """Принимает UserRef, строку («@nick», ссылку, «nick») или словарь выгрузки."""
        if isinstance(value, UserRef):
            return value
        if isinstance(value, Mapping):
            return cls.from_export_entry(value)
        username = normalize_username(value)
        return cls(username=username) if username else None

    # --- сериализация ----------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "username": self.username,
            "user_id": self.user_id,
            "full_name": self.full_name,
            "profile_url": self.profile_url,
            "is_private": self.is_private,
            "is_verified": self.is_verified,
            "since": self.since.isoformat() if self.since else None,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "UserRef":
        return cls(
            username=normalize_username(data.get("username")),
            user_id=str(data.get("user_id") or ""),
            full_name=str(data.get("full_name") or ""),
            profile_url=str(data.get("profile_url") or ""),
            is_private=_clean_flag(data.get("is_private")),
            is_verified=_clean_flag(data.get("is_verified")),
            since=parse_timestamp(data.get("since")),
        )


UserMap = Dict[str, UserRef]


def _build_map(users: Iterable[Any]) -> UserMap:
    """Список/мап «пользователей» -> {ник: UserRef} с разрешением конфликтов."""
    result: UserMap = {}
    if isinstance(users, Mapping):
        items: Iterable[Any] = list(users.values())
    else:
        items = users
    for raw in items:
        ref = UserRef.coerce(raw)
        if ref is None or not ref.username:
            continue
        existing = result.get(ref.username)
        if existing is None:
            result[ref.username] = ref
        else:  # объединяем известные поля (дубликаты в выгрузке случаются)
            result[ref.username] = _merge_refs(existing, ref)
    return result


def _merge_refs(left: UserRef, right: UserRef) -> UserRef:
    return UserRef(
        username=left.username,
        user_id=left.user_id or right.user_id,
        full_name=left.full_name or right.full_name,
        profile_url=left.profile_url or right.profile_url,
        is_private=left.is_private if left.is_private is not None else right.is_private,
        is_verified=(
            left.is_verified if left.is_verified is not None else right.is_verified
        ),
        since=_earliest(left.since, right.since),
    )


def _earliest(left: Optional[datetime], right: Optional[datetime]) -> Optional[datetime]:
    if left is None:
        return right
    if right is None:
        return left
    return left if left <= right else right


@dataclass
class Snapshot:
    """Снимок подписок одного аккаунта на момент `captured_at`.

    `expected_counts`/`complete` нужны для честного ответа на вопрос «данные полные?».
    Неполный список подписчиков (Instagram режет выдачу — см. README) делает любой
    анализ отписок бессмысленным, поэтому факт неполноты хранится рядом со данными.
    """

    username: str
    captured_at: datetime
    followers: UserMap = field(default_factory=dict)
    following: UserMap = field(default_factory=dict)
    source: str = "unknown"
    expected_counts: Dict[str, int] = field(default_factory=dict)
    complete: Dict[str, bool] = field(default_factory=dict)
    meta: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.username = normalize_username(self.username) or self.username.lower()
        if not isinstance(self.captured_at, datetime):
            self.captured_at = parse_timestamp(self.captured_at) or datetime.now(
                timezone.utc
            )
        self.followers = _build_map(self.followers)
        self.following = _build_map(self.following)

    # --- доступ --------------------------------------------------------

    @property
    def followers_list(self) -> List[UserRef]:
        return sorted(self.followers.values(), key=lambda u: u.username)

    @property
    def following_list(self) -> List[UserRef]:
        return sorted(self.following.values(), key=lambda u: u.username)

    def count(self, kind: str) -> int:
        return len(getattr(self, kind))

    def users(self, kind: str) -> List[UserRef]:
        return getattr(self, f"{kind}_list")

    def is_truncated(self, kind: str) -> bool:
        """True, если известно, что список короче ожидаемого."""
        expected = self.expected_counts.get(kind)
        if expected is None:
            return False
        return self.count(kind) < int(expected)

    @property
    def truncations(self) -> Dict[str, Tuple[int, int]]:
        """{kind: (получено, ожидалось)} для обрезанных списков."""
        return {
            kind: (self.count(kind), int(self.expected_counts[kind]))
            for kind in ("followers", "following")
            if self.is_truncated(kind)
        }

    @property
    def reliable(self) -> bool:
        """Можно ли доверять «отпискам»: оба списка полные (или полнота не проверялась)."""
        explicit = [v for v in self.complete.values() if v is False]
        return not explicit and not self.truncations

    # --- сериализация --------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "username": self.username,
            "captured_at": self.captured_at.isoformat(),
            "source": self.source,
            "counts": {
                "followers": self.count("followers"),
                "following": self.count("following"),
            },
            "expected_counts": dict(self.expected_counts),
            "complete": dict(self.complete),
            "followers": [u.to_dict() for u in self.followers_list],
            "following": [u.to_dict() for u in self.following_list],
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Snapshot":
        """Читает и новый формат, и legacy-файлы `username_DD_MM_YYYY_HH_MM.json`."""
        if not isinstance(data, Mapping):
            raise ValueError("Snapshot: ожидает словарь, получен " + type(data).__name__)
        captured_at = parse_timestamp(
            data.get("captured_at") or data.get("timestamp")
        ) or datetime.now(timezone.utc)
        return cls(
            username=str(data.get("username") or ""),
            captured_at=captured_at,
            followers=data.get("followers") or [],
            following=data.get("following") or [],
            source=str(data.get("source") or "file"),
            expected_counts={
                k: int(v)
                for k, v in (data.get("expected_counts") or {}).items()
                if isinstance(v, (int, float))
            },
            complete={
                k: bool(v) for k, v in (data.get("complete") or {}).items()
            },
            meta=dict(data.get("meta") or {}),
        )
