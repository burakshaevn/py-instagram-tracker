"""Совместимость со старым API: `from instagram_tracker.strategies import InstagrapiStrategy`.

Новые источники живут в `instagram_tracker.sources` (Strategy-паттерн сохранён, но
контракт стал честным: снимок либо исключение, а не пустое множество). Здесь только
тонкие прослойки — чтобы существовавшие ранее сценарии запуска не сломались.
"""

from __future__ import annotations

from typing import Optional, Set

from .interfaces import ProgressSubject
from .model import Snapshot
from .sources import ExportSource, SessionSource

__all__ = [
    "InstagrapiStrategy",
    "InstagramExportStrategy",
    "ExportSource",
    "SessionSource",
]

# Новое имя основного способа чтения выгрузки Instagram.
InstagramExportStrategy = ExportSource


class InstagrapiStrategy(SessionSource, ProgressSubject):
    """Адаптер под старый интерфейс (`get_followers` / `get_following` / `login`).

    Отличия от прежней реализации, из-за которых анализ и «не работал»:
      * пустой список больше не является допустимым ответом — летит исключение;
      * усечённый Instagram'ом список не принимается за полный (`allow_partial=True`
        возвращает старое «терпимое» поведение);
      * сессия переиспользуется (sessionid/файл), а не логин с паролем каждый запуск.
    """

    def __init__(self, *args, **kwargs) -> None:  # noqa: D107 - прослойка
        super().__init__(*args, **kwargs)

    def login(self, username: Optional[str] = None, password: Optional[str] = None) -> bool:
        """Старое поведение: True/False вместо исключения — только ради совместимости."""
        if username:
            self.username_hint = username
        if password:
            self.password = password
        try:
            return self.connect()
        except Exception as exc:  # совпадаем с прежним «напечатал и вернул False»
            self.notify(f"Ошибка входа: {exc}")
            return False

    def get_followers(self, username: Optional[str] = None) -> Set[str]:
        return set(self._snapshot(username).followers)

    def get_following(self, username: Optional[str] = None) -> Set[str]:
        return set(self._snapshot(username).following)

    def find_non_followers(self, username: Optional[str] = None) -> Set[str]:
        snapshot = self._snapshot(username)
        return set(snapshot.following) - set(snapshot.followers)

    def _snapshot(self, username: Optional[str]) -> Snapshot:
        return self.fetch_snapshot(username)
