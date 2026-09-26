"""Интерфейсы: Strategy (источник данных) и Observer (прогресс).

Архитектура оставлена как в исходном проекте — Strategy + Observer, — но контракт
стратегии изменён. Раньше стратегия обязывала вернуть `Set[str]`, из-за чего любая
ошибка превращалась в пустое множество (молчаливый неверный ответ). Теперь контракт
такой: либо `Snapshot` с известной полнотой, либо исключение.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from .model import Snapshot

__all__ = ["InstagramDataSource", "ProgressObserver", "ProgressSubject"]


class InstagramDataSource(ABC):
    """Источник снимка подписок (выгрузка Instagram, живая сессия, файл)."""

    #: человекочитаемое имя источника для отчётов и логов
    name: str = "unknown"

    #: умеет ли источник читать чужие аккаунты (выгрузка — только свои)
    supports_other_accounts: bool = False

    @abstractmethod
    def fetch_snapshot(self, username: Optional[str] = None) -> Snapshot:
        """Возвращает снимок подписок либо бросает `SourceError`.

        Пустой список — это тоже ошибка, а не «ноль отписок»: молча возвращать
        пустое множество запрещено контрактом.
        """
        raise NotImplementedError

    def describe(self) -> str:  # pragma: no cover - cosmetic
        return self.name


class ProgressObserver(ABC):
    """Наблюдатель за прогрессом."""

    @abstractmethod
    def update_progress(self, message: str, percentage: Optional[float] = None) -> None:
        raise NotImplementedError


class ProgressSubject:
    """Subject паттерна Observer: рассылает прогресс подписчикам.

    `notify` не должен ронять разбор данных из-за поведения консольного наблюдателя,
    поэтому исключения наблюдателей глушатся (в отличие от ошибок источника данных).
    """

    def __init__(self) -> None:
        self._observers: List[ProgressObserver] = []

    def attach(self, observer: ProgressObserver) -> None:
        if observer not in self._observers:
            self._observers.append(observer)

    def detach(self, observer: ProgressObserver) -> None:
        if observer in self._observers:
            self._observers.remove(observer)

    @property
    def observers(self) -> List[ProgressObserver]:
        return list(self._observers)

    def notify(self, message: str, percentage: Optional[float] = None) -> None:
        for observer in list(self._observers):
            try:
                observer.update_progress(message, percentage)
            except Exception:  # прогресс не должен влиять на результат анализа
                pass
