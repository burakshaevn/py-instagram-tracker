"""Исключения пакета.

Главной причиной «тихой» неработоспособности анализа была молчаливая отдача пустого
списка при любой ошибке сети/лимитов: `following - followers` на пустом `followers`
выглядит как «подписчики не подписаны в ответ», хотя данных просто нет.
Здесь ошибки — отдельные типы, которые нельзя перепутать с пустым результатом.
"""

from __future__ import annotations

from typing import Iterable, Optional

__all__ = [
    "TrackerError",
    "SourceError",
    "SessionRequired",
    "LoginRejected",
    "RateLimited",
    "ExportNotFoundError",
    "IncompleteDataError",
    "SnapshotNotFoundError",
]


class TrackerError(Exception):
    """Базовая ошибка проекта. От неё «вежливо» печатают подсказку, не трейсбек."""


class SourceError(TrackerError):
    """Источник данных (выгрузка/сессия) не смог отдать данные."""


class SessionRequired(SourceError):
    """Нет ни сохранённой сессии, ни пароля: жить не на чем."""

    def __init__(self, message: Optional[str] = None) -> None:
        super().__init__(
            message
            or (
                "Не найдено ни sessionid, ни сохранённой сессии, ни логина с паролем.\n"
                "Варианты: 1) взять cookie sessionid из браузера (см. README, раздел "
                "«Сессия без пароля»); 2) сохранить сессию один раз --save-session; "
                "3) не использовать живой режим вовсе и анализировать выгрузку "
                "Instagram (--export)."
            )
        )


class LoginRejected(SourceError):
    """Instagram отклонил попытку входа/восстановления сессии."""


class RateLimited(SourceError):
    """Instagram ограничил частоту запросов (soft/hard limit)."""

    def __init__(self, message: str, retry_after: Optional[int] = None) -> None:
        self.retry_after = retry_after
        suffix = f" Повторить не раньше, чем через {retry_after} с." if retry_after else ""
        super().__init__(f"{message}{suffix}")


class IncompleteDataError(SourceError):
    """Данные получены, но заведомо неполные — выводы по ним делать нельзя.

    Именно это и происходит с API Instagram: списки подписчиков обрезаются на
    стороне сервера (`should_limit_list_of_followers`), и анализ начинает придумывать
    отписки.
    """

    def __init__(
        self,
        message: str,
        username: str = "",
        got: Optional[int] = None,
        expected: Optional[int] = None,
    ) -> None:
        self.username = username
        self.got = got
        self.expected = expected
        super().__init__(message)

    @classmethod
    def from_truncation(
        cls,
        kind: str,
        username: str,
        got: int,
        expected: int,
        hints: Iterable[str] = (),
    ) -> "IncompleteDataError":
        extra = f"\n{''.join('  - ' + h + chr(10) for h in hints)}" if hints else ""
        return cls(
            f"Список «{kind}» для {username or 'аккаунта'} усечён Instagram'ом: "
            f"получено {got} из {expected}. Анализ отписок по такому списку неверен: "
            f"отсутствующие записи будут выглядеть как отписка/подписка."
            f"{extra}",
            username=username,
            got=got,
            expected=expected,
        )


class ExportNotFoundError(SourceError):
    """В выгрузке Instagram не найдены файлы подписчиков/подписок."""

    def __init__(self, message: str, searched: Iterable[str] = ()) -> None:
        self.searched = list(searched)
        if self.searched:
            message += "\nИскал здесь: " + ", ".join(self.searched)
        super().__init__(message)


class SnapshotNotFoundError(TrackerError):
    """Нет сохранённого снимка для сравнения."""
