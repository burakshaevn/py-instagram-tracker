"""Пакет для анализа подписок и отписок в Instagram.

Публичный API:

    from instagram_tracker import (
        Snapshot, UserRef, analyze_followbacks, diff_snapshots, SnapshotStore,
    )

Данные берутся из официального экспорта Instagram (надёжно, без логина) либо из живой
сессии instagrapi (без пароля, по sessionid/сохранённой сессии) — см. README.
"""

from __future__ import annotations

from .analyzer import DiffReport, FollowBackReport, RenameEvent, analyze_followbacks, diff_snapshots
from .data_manager import SnapshotInfo, SnapshotStore
from .errors import (
    ExportNotFoundError,
    IncompleteDataError,
    LoginRejected,
    RateLimited,
    SessionRequired,
    SnapshotNotFoundError,
    SourceError,
    TrackerError,
)
from .interfaces import InstagramDataSource, ProgressObserver, ProgressSubject
from .model import Snapshot, UserRef, normalize_username, parse_timestamp
from .observers import ConsoleProgressObserver, QuietObserver, RecordingObserver
from .settings import Settings, load_settings

__version__ = "2.0.0"

__all__ = [
    "__version__",
    "analyze_followbacks",
    "diff_snapshots",
    "DiffReport",
    "FollowBackReport",
    "RenameEvent",
    "Snapshot",
    "SnapshotInfo",
    "SnapshotStore",
    "UserRef",
    "normalize_username",
    "parse_timestamp",
    "InstagramDataSource",
    "ProgressObserver",
    "ProgressSubject",
    "ConsoleProgressObserver",
    "QuietObserver",
    "RecordingObserver",
    "Settings",
    "load_settings",
    "TrackerError",
    "SourceError",
    "SessionRequired",
    "LoginRejected",
    "RateLimited",
    "IncompleteDataError",
    "ExportNotFoundError",
    "SnapshotNotFoundError",
]
