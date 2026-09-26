"""Источник данных №1 — официальная выгрузка Instagram («Download your information»).

Почему это основной способ: только он даёт ПОЛНЫЕ списки подписчиков и подписок.
Приватный API Instagram срезает выдачу (флаг `should_limit_list_of_followers`), и
любое «кто отписался», построенное на таком списке, врёт. Выгрузка при этом:

  * не требует логина, пароля, 2FA и сессий вообще (скрипт не трогает аккаунт);
  * не упирается в rate limit и не создаёт риск блокировки;
  * содержит отметки времени подписок, чего не даёт ни один публичный способ.

Минус один: данные статичны на момент выгрузки, и доступна только собственная
выгрузка. Живые данные — см. `sources/session.py`.
"""

from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple

from ..errors import ExportNotFoundError
from ..interfaces import InstagramDataSource, ProgressSubject
from ..model import Snapshot, UserRef, normalize_username

__all__ = ["ExportSource", "ExportBundle"]

_RELATIONSHIP_KEY_RE = re.compile(r"^relationships_(?P<what>.+)$")
# В HTML-выгрузке профилы лежат как <a href="https://www.instagram.com/nick/">
_HTML_ANCHOR_RE = re.compile(
    r"""<a[^>]+href=["'](?P<href>[^"']*instagram\.com/(?P<name>[A-Za-z0-9_.]{1,40}))/?["'][^>]*>""",
    re.IGNORECASE,
)
_HTML_RESERVED = {"p", "reel", "reels", "stories", "explore", "accounts", "static"}

_KIND_PATTERNS: Dict[str, Tuple[str, ...]] = {
    "followers": ("followers*.json", "followers*.html"),
    "following": ("following*.json", "following*.html"),
}
# Доп. списки из папки connections/followers_and_following — полезны для анализа,
# но не участвуют в сравнении «кто не подписан в ответ».
_EXTRA_KINDS: Dict[str, str] = {
    "pending_follow_requests": "pending_follow_requests",
    "close_friends": "close_friends",
    "recently_unfollowed_profiles": "recently_unfollowed",
    "restricted_profiles": "restricted",
    "blocked_profiles": "blocked",
    "hide_story_from": "hidden_from_stories",
    "profiles_you’ve_favorited": "favorited_profiles",
    "profiles_you've_favorited": "favorited_profiles",
    "follow_requests_you’ve_received": "incoming_follow_requests",
    "follow_requests_you've_received": "incoming_follow_requests",
    "recently_unfollowed": "recently_unfollowed",
}


@dataclass
class ExportBundle:
    """Набор файлов выгрузки, найденных в папке/ZIP."""

    followers: List[Tuple[str, str]] = None   # [(имя_файла, содержимое)]
    following: List[Tuple[str, str]] = None
    extras: Dict[str, List[Tuple[str, str]]] = None
    timestamps: List[datetime] = None
    root_label: str = ""

    def __post_init__(self) -> None:
        self.followers = self.followers or []
        self.following = self.following or []
        self.extras = self.extras or {}
        self.timestamps = self.timestamps or []


def _match_kind(name: str) -> Tuple[Optional[str], bool]:
    """Определяет, к какому списку относится файл выгрузки.

    Возвращает (kind, is_html). `kind is None` — файл не наш.
    """
    stem = Path(name).name.lower()
    if not (stem.endswith(".json") or stem.endswith(".html")):
        return None, False
    is_html = stem.endswith(".html")
    base = stem.rsplit(".", 1)[0]
    for kind, patterns in _KIND_PATTERNS.items():
        for pattern in patterns:
            head = pattern.split("*")[0]
            if _glob_like(base, head) and (is_html == pattern.endswith(".html")):
                return kind, is_html
    return None, is_html


def _glob_like(value: str, prefix: str) -> bool:
    """Совпадение с `prefix` + необязательный числовой хвост (_1, _2, ...)."""
    if not value.startswith(prefix):
        return False
    tail = value[len(prefix) :]
    return tail == "" or bool(re.fullmatch(r"_?\d+", tail))


def _entry_kind(name: str) -> Optional[str]:
    stem = Path(name).name.lower()
    base = stem.rsplit(".", 1)[0]
    base = re.sub(r"_?\d+$", "", base)
    for pattern, target in _EXTRA_KINDS.items():
        if base.startswith(pattern.lower()):
            return target
    return None


class ExportSource(InstagramDataSource, ProgressSubject):
    """Читает выгрузку Instagram из ZIP-архива, папки или готовых файлов."""

    name = "export"
    supports_other_accounts = False

    def __init__(
        self,
        path: Optional[Path | str] = None,
        *,
        followers_files: Sequence[Path | str] = (),
        following_files: Sequence[Path | str] = (),
        username: Optional[str] = None,
    ) -> None:
        """path — .zip/.json/.html или каталог (в т.ч. распакованная выгрузка).

        followers_files/following_files — явные пути, когда файлы лежат врозь
        (типичный случай: `followers_1.json` и `following.json` скопированы в папку
        проекта рядом со скриптом).
        """
        super().__init__()
        self.path = Path(path).expanduser() if path else None
        self.followers_files = [Path(p).expanduser() for p in followers_files]
        self.following_files = [Path(p).expanduser() for p in following_files]
        self.username_hint = normalize_username(username) if username else ""

    # --- публичный API стратегии ---------------------------------------

    def fetch_snapshot(self, username: Optional[str] = None) -> Snapshot:
        target = normalize_username(username) if username else self.username_hint
        self.notify("Читаю выгрузку Instagram...")
        bundle = self._collect()
        followers = self._load_list(bundle.followers, "followers")
        following = self._load_list(bundle.following, "following")

        if not followers and not following:
            raise ExportNotFoundError(
                "В выгрузке не найдено ни одного списка подписчиков/подписок. "
                "Проверьте, что при запросе данных была выбрана категория "
                "«Followers and following» и формат JSON.",
                searched=self._searched_labels(bundle),
            )

        detected = target or self._guess_username()
        captured_at = max(bundle.timestamps) if bundle.timestamps else datetime.now(timezone.utc)
        snapshot = Snapshot(
            username=detected,
            captured_at=captured_at,
            followers=followers,
            following=following,
            source=f"export:{bundle.root_label or 'files'}",
            # Выгрузка — полный снимок: полнота не «предполагается», а гарантируется
            # самим Instagram, поэтому явные True важны для последующих проверок.
            complete={"followers": True, "following": True},
            meta={
                "files": {
                    "followers": [n for n, _ in bundle.followers],
                    "following": [n for n, _ in bundle.following],
                },
                "extras": {k: len(v) for k, v in bundle.extras.items()},
            },
        )
        extras = self._load_extras(bundle.extras)
        snapshot.meta.update(extras)
        self.notify(
            f"Выгрузка прочитана: подписчиков {snapshot.count('followers')}, "
            f"подписок {snapshot.count('following')}."
        )
        return snapshot

    # --- поиск файлов ---------------------------------------------------

    def _collect(self) -> ExportBundle:
        bundle = ExportBundle()
        for name, data, stamp, forced_kind in self._iter_files():
            kind = forced_kind or _match_kind(name)[0]
            if kind is not None:
                getattr(bundle, kind).append((Path(name).name, data))
                if stamp:
                    bundle.timestamps.append(stamp)
                continue

            extra = _entry_kind(name)
            if extra:
                bundle.extras.setdefault(extra, []).append((Path(name).name, data))
        if not bundle.timestamps:
            bundle.timestamps = self._own_timestamps()
        bundle.root_label = self._root_label()
        return bundle

    def _iter_files(self) -> Iterator[Tuple[str, str, Optional[datetime], Optional[str]]]:
        """Отдаёт (имя, содержимое, mtime) для всех подходящих файлов выгрузки."""
        if self.path is None:
            yield from self._iter_explicit()
            return
        if self.path.is_file() and self.path.suffix.lower() == ".zip":
            yield from self._iter_zip(self.path)
            return
        if self.path.is_file() and self.path.suffix.lower() in {".json", ".html", ".htm"}:
            # Одиночный файл: заодно ищем «парный» список рядом с ним.
            yield from self._iter_single_file(self.path)
            return
        if self.path.is_dir():
            yield from self._iter_dir(self.path)
            return
        raise ExportNotFoundError(
            f"Путь к выгрузке не найден: {self.path}", searched=[str(self.path)]
        )

    def _iter_explicit(self) -> Iterator[Tuple[str, str, Optional[datetime], Optional[str]]]:
        """Явно переданные файлы: их род важнее имени файла (его мог выбрать человек)."""
        wanted = [("followers", path) for path in self.followers_files] + [
            ("following", path) for path in self.following_files
        ]
        for kind, path in wanted:
            if not path.exists():
                raise ExportNotFoundError(
                    f"Файл выгрузки не найден: {path}", searched=[str(path)]
                )
            if path.suffix.lower() == ".zip":
                for name, data, stamp, _ in self._iter_zip(path):
                    yield name, data, stamp, _match_kind(name)[0] or kind
                continue
            yield path.name, path.read_text(encoding="utf-8", errors="replace"), _mtime(path), kind

    def _iter_single_file(
        self, path: Path
    ) -> Iterator[Tuple[str, str, Optional[datetime], None]]:
        yield path.name, path.read_text(encoding="utf-8", errors="replace"), _mtime(path), None
        # Подхватываем соседей: followers_1.json рядом с following.json
        for sibling in sorted(path.parent.glob("*.js[on]*")):
            if sibling == path:
                continue
            sibling_kind, _ = _match_kind(sibling.name)
            if sibling_kind:
                yield (
                    sibling.name,
                    sibling.read_text(encoding="utf-8", errors="replace"),
                    _mtime(sibling),
                    None,
                )

    def _iter_zip(
        self, zip_path: Path
    ) -> Iterator[Tuple[str, str, Optional[datetime], None]]:
        with zipfile.ZipFile(zip_path) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                name = info.filename
                if Path(name).name.lower().rsplit(".", 1)[-1] not in {"json", "html", "htm"}:
                    continue
                try:
                    raw = archive.read(info)
                except (zipfile.BadZipFile, OSError) as exc:
                    self.notify(f"Не удалось прочитать {name}: {exc}")
                    continue
                stamp = datetime(*info.date_time, tzinfo=timezone.utc) if info.date_time else None
                yield name, _decode(raw), stamp, None

    def _iter_dir(
        self, root: Path
    ) -> Iterator[Tuple[str, str, Optional[datetime], None]]:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".json", ".html", ".htm"}:
                continue
            yield path.name, path.read_text(encoding="utf-8", errors="replace"), _mtime(path), None

    def _own_timestamps(self) -> List[datetime]:
        stamps: List[datetime] = []
        for path in (*self.followers_files, *self.following_files):
            stamp = _mtime(path)
            if stamp:
                stamps.append(stamp)
        if self.path and self.path.exists():
            stamp = _mtime(self.path)
            if stamp:
                stamps.append(stamp)
        return stamps

    def _root_label(self) -> str:
        if self.path:
            return self.path.name
        return "explicit-files"

    def _searched_labels(self, bundle: ExportBundle) -> List[str]:
        if self.path:
            return [str(self.path)]
        return [str(p) for p in (*self.followers_files, *self.following_files)]

    def _guess_username(self) -> str:
        """Ник из структуры выгрузки: `users/<nick>/...` или personal_information.json."""
        if self.path and self.path.is_dir():
            found = self._username_from_dir(self.path)
            if found:
                return found
        if self.path and self.path.suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(self.path) as archive:
                    for info in archive.infolist():
                        found = _username_from_parts(info.filename)
                        if found:
                            return found
                    # выгрузки без каталога users/: ник берём из personal_information.json
                    for info in archive.infolist():
                        if Path(info.filename).name.lower() == "personal_information.json":
                            found = _username_from_personal_info(_decode(archive.read(info)))
                            if found:
                                return found
            except (zipfile.BadZipFile, OSError):
                pass
        if self.path and self.path.is_file():
            return _username_from_parts(self.path.parent.name)
        return ""

    def _username_from_dir(self, root: Path) -> str:
        found = _username_from_parts(root.name) or _username_from_parts(root.parent.name)
        if found:
            return found
        for candidate in (root / "account" / "personal_information.json",):
            if candidate.is_file():
                found = _username_from_personal_info(
                    candidate.read_text(encoding="utf-8", errors="replace")
                )
                if found:
                    return found
        return ""

    # --- парсинг содержимого -------------------------------------------

    def _load_list(self, files: Iterable[Tuple[str, str]], kind: str) -> List[UserRef]:
        users: List[UserRef] = []
        for name, data in files:
            if name.lower().endswith((".html", ".htm")):
                users.extend(_parse_html(data))
                continue
            users.extend(self._parse_json(data, kind, name))
        merged: Dict[str, UserRef] = {}
        for ref in users:
            if ref.username not in merged:
                merged[ref.username] = ref
        return list(merged.values())

    def _parse_json(self, data: str, kind: str, name: str) -> List[UserRef]:
        try:
            payload = json.loads(data.lstrip("\ufeff").strip() or "null")
        except ValueError as exc:
            raise ExportNotFoundError(
                f"Файл выгрузки {name} не является корректным JSON ({exc}). "
                "Запросите выгрузку повторно в формате JSON.",
                searched=[name],
            ) from exc
        users: List[UserRef] = []
        for container in _relationship_containers(payload, kind):
            for entry in container:
                ref = UserRef.from_export_entry(entry)
                if ref is not None:
                    users.append(ref)
        return users

    def _load_extras(
        self, extras: Mapping[str, Sequence[Tuple[str, str]]]
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for kind, files in extras.items():
            users = self._load_list(files, kind)
            if users:
                result[kind] = sorted(u.username for u in users)
        return result


# --- вспомогательные функции (без состояния, легко тестируются) ----------


def _username_from_personal_info(text: str) -> str:
    """Ник из account/personal_information.json (есть в каждой выгрузке)."""
    try:
        payload = json.loads(text.lstrip("\ufeff"))
    except ValueError:
        return ""
    for entry in _walk_dicts(payload):
        value = entry.get("username")
        if isinstance(value, str) and normalize_username(value):
            return normalize_username(value)
    return ""


def _walk_dicts(payload: Any) -> Iterator[Mapping[str, Any]]:
    """Обходит JSON-дерево, отдавая все словари (в выгрузке вложенность гуляет)."""
    if isinstance(payload, Mapping):
        yield payload
        for value in payload.values():
            yield from _walk_dicts(value)
    elif isinstance(payload, (list, tuple)):
        for item in payload:
            yield from _walk_dicts(item)


def _decode(raw: bytes) -> str:
    return raw.decode("utf-8", errors="replace")


def _mtime(path: Path) -> Optional[datetime]:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except (OSError, ValueError):
        return None


def _username_from_parts(value: str) -> str:
    parts = Path(value).parts
    for index, part in enumerate(parts):
        if part.lower() == "users" and index + 1 < len(parts):
            candidate = normalize_username(parts[index + 1])
            if candidate:
                return candidate
    return ""


def _relationship_containers(payload: Any, kind: str) -> Iterator[List[Any]]:
    """Вытаскивает списки связей из JSON любой из известных форм выгрузок.

    Поддерживаются:
      * {"relationships_followers": [ ... ]}            — канонический вид;
      * [ { "string_list_data": [...] }, ... ]          — голый список;
      * {"followers": [...]} / {"following": [...]}     — «самодельные» дампы.
    """
    key = {"followers": "followers", "following": "following"}.get(kind, kind)
    if isinstance(payload, list):
        yield payload
        return
    if not isinstance(payload, Mapping):
        return
    # Вариант выкладки без обёртки relationships_*: {"string_list_data": [...]}
    direct = payload.get("string_list_data")
    if isinstance(direct, list) and not any(
        str(k).lower().startswith("relationships_") for k in payload
    ):
        yield direct
        return

    wanted = f"relationships_{key}"
    matched = False
    for raw_key, value in payload.items():
        if not isinstance(value, list):
            continue
        norm = str(raw_key).lower()
        if norm == wanted or (norm.startswith("relationships_") and key in norm):
            matched = True
            yield value
    if matched:
        return
    for alias in (key, f"{key}_list", f"relationships_{key}"):
        value = payload.get(alias)
        if isinstance(value, list):
            yield value
            return


def _parse_html(data: str) -> List[UserRef]:
    """Ник из HTML-выгрузки: берём все ссылки на профили внутри <a href=...>."""
    found: Dict[str, UserRef] = {}
    for match in _HTML_ANCHOR_RE.finditer(data):
        raw_name = match.group("name")
        if raw_name.lower() in _HTML_RESERVED:
            continue
        username = normalize_username(raw_name)
        if not username or username in found:
            continue
        found[username] = UserRef(
            username=username,
            profile_url=match.group("href"),
            full_name=_html_text(data, match.end()),
        )
    return list(found.values())


_TEXT_TAG_RE = re.compile(r"<[^>]+>")


def _html_text(data: str, start: int) -> str:
    """Текст ссылки (отображаемое имя) — для более понятного вывода в консоли."""
    chunk = data[start : start + 400]
    text, depth, index = [], 0, 0
    while index < len(chunk):
        match = _TEXT_TAG_RE.match(chunk, index)
        if match:
            tag = match.group(0)
            if tag.startswith("</"):
                if depth == 0:
                    break
                depth -= 1
            elif not tag.endswith("/>"):
                depth += 1
            index = match.end()
            continue
        text.append(chunk[index])
        index += 1
    return "".join(text).strip()[:120]
