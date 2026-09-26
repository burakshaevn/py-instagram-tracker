"""Наблюдатели прогресса.

Консольный наблюдатель научился двум вещам, без которых разбор на 20 000 подписчиков
превращался в простыню: подавление повторяющихся строк и режим «тишины» (для
машинного чтения/пайпов, где прогресс мешает).
"""

from __future__ import annotations

import sys
import time
from typing import List, Optional, TextIO

from .interfaces import ProgressObserver

__all__ = ["ConsoleProgressObserver", "RecordingObserver", "QuietObserver"]


class ConsoleProgressObserver(ProgressObserver):
    """Печатает прогресс; одинаковые сообщения подряд схлопываются."""

    def __init__(
        self,
        *,
        stream: Optional[TextIO] = None,
        quiet: bool = False,
        min_interval: float = 0.5,
    ) -> None:
        self.stream = stream or sys.stderr
        self.quiet = quiet
        self.min_interval = min_interval
        self._last_message: Optional[str] = None
        self._last_time = 0.0

    def update_progress(self, message: str, percentage: Optional[float] = None) -> None:
        if self.quiet:
            return
        line = message if percentage is None else f"{message} - {percentage:.1f}%"
        now = time.monotonic()
        if line == self._last_message and now - self._last_time < self.min_interval:
            return
        self._last_message, self._last_time = line, now
        print(line, file=self.stream, flush=True)


class RecordingObserver(ProgressObserver):
    """Собирает сообщения в список — для тестов и для отладочного лога."""

    def __init__(self) -> None:
        self.messages: List[str] = []

    def update_progress(self, message: str, percentage: Optional[float] = None) -> None:
        self.messages.append(message if percentage is None else f"{message} - {percentage:.1f}%")

    def __contains__(self, needle: str) -> bool:
        return any(needle in message for message in self.messages)


class QuietObserver(ProgressObserver):
    """Глушитель прогресса (например, при выводе в формате JSON/CSV)."""

    def update_progress(self, message: str, percentage: Optional[float] = None) -> None:
        return None
