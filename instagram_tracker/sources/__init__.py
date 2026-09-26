"""Выбор источника данных.

Порядок такой, чтобы «ничего не указывать» тоже работало:
явно заданная выгрузка → найденная рядом выгрузка → живая сессия → внятная ошибка.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

from ..errors import TrackerError
from ..interfaces import InstagramDataSource
from ..settings import Settings
from .export import ExportSource
from .session import SessionSource

__all__ = ["build_source", "discover_export", "ExportSource", "SessionSource"]

_EXPORT_ZIP_HINTS = re.compile(r"(instagram|export|data.?dump|connections)", re.IGNORECASE)
_EXPORT_FILE_HINTS = re.compile(r"^(followers|following)_?\d*\.(json|html?|htm)$", re.IGNORECASE)


def discover_export(where: Optional[Path] = None) -> Optional[Path]:
    """Ищет выгрузку рядом со скриптом: zip-архив или папку с connections/.

    Возвращает None, если ничего похожего нет — тогда решение о источнике принимает
    вызывающий код (например, переходит к живой сессии).
    """
    root = Path(where or Path.cwd())
    candidates: List[Path] = []

    direct = [
        path
        for path in sorted(root.glob("*.*"))
        if path.is_file() and _EXPORT_FILE_HINTS.match(path.name)
    ]
    if direct:
        candidates.append(direct[0].parent)

    for path in sorted(root.glob("*.zip")):
        if _EXPORT_ZIP_HINTS.search(path.name):
            candidates.append(path)

    for subdir in ("connections", "followers_and_following"):
        nested = root / subdir
        if nested.is_dir():
            candidates.append(nested)
        elif (root / "users").is_dir():
            candidates.append(root)

    exports_dir = root / "data" / "exports"
    if exports_dir.is_dir():
        candidates.extend(sorted(exports_dir.glob("*.zip"), reverse=True))

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def build_source(
    settings: Settings,
    *,
    export: Optional[Path] = None,
    force_session: bool = False,
    username: Optional[str] = None,
) -> InstagramDataSource:
    """Создаёт источник данных по настройкам и аргументам пользователя."""
    if export and force_session:
        raise TrackerError("--export и --live mutually exclusive: выберите один источник.")

    if force_session:
        return _session_source(settings, username)

    export_path = Path(export).expanduser() if export else discover_export()
    if export_path is not None:
        return ExportSource(export_path, username=username)

    if settings.has_credentials:
        return _session_source(settings, username)

    raise TrackerError(
        "Нечем читать данные. Выберите источник:\n"
        "  1) Выгрузка Instagram (надежнее всего, логин не нужен):\n"
        "       Accounts Center → Your information and permissions → Download or "
        "transfer information → «Followers and following» → формат JSON → All time.\n"
        "       Затем: python main.py analyze --export путь/к/архиву.zip\n"
        "     (или распакуйте в текущую папку файлы followers_1.json и following.json — "
        "они найдутся сами)\n"
        "  2) Живая сессия без пароля (cookie sessionid из браузера):\n"
        "       python main.py session login --sessionid <sessionid>\n"
        "       python main.py analyze --live\n"
        "  3) Уже сохранённый снимок: python main.py analyze --snapshot data/snapshots/....json"
    )


def _session_source(settings: Settings, username: Optional[str]) -> SessionSource:
    if not settings.has_credentials:
        raise TrackerError(
            "Живой режим недоступен: нет ни INSTAGRAM_SESSIONID, ни файла сессии "
            f"({settings.session_file}), ни пары INSTAGRAM_USERNAME/PASSWORD.\n"
            "sessionid берётся в браузере: DevTools → Application → Cookies → "
            "https://www.instagram.com → sessionid (значение вида «123456789:abcd…»). "
            "Пароль — крайний вариант: он каждый раз рискованнее для аккаунта."
        )
    return SessionSource(
        session_file=settings.session_file,
        sessionid=settings.instagram_sessionid,
        username=username or settings.instagram_username,
        password=settings.instagram_password,
        proxy=settings.proxy,
        delay_range=settings.delay_range,
        page_size=200,
        max_items=settings.max_items,
        max_retries=settings.max_retries,
        retry_base_delay=settings.retry_base_delay,
        allow_partial=settings.allow_partial,
        persist_session=settings.persist_session,
    )
