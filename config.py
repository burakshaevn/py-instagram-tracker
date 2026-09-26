"""Совместимость: прежний корневой config.py теперь тонкая прослойка.

Настоящие настройки — в `instagram_tracker.settings` (читают переменные окружения и
`.env`, если он лежит рядом). Все значения необязательны: для разбора выгрузки
Instagram не нужен ни логин, ни пароль.
"""

from __future__ import annotations

from instagram_tracker.settings import Settings, load_settings

_SETTINGS: Settings = load_settings()

# Прежние имена, чтобы старые импорты (`from config import INSTAGRAM_PASSWORD`) работали.
INSTAGRAM_USERNAME = _SETTINGS.instagram_username
INSTAGRAM_PASSWORD = _SETTINGS.instagram_password
INSTAGRAM_SESSIONID = _SETTINGS.instagram_sessionid
INSTAGRAM_SESSION_FILE = str(_SETTINGS.session_file)
INSTAGRAM_DATA_DIR = str(_SETTINGS.data_dir)
DELAY_BETWEEN_REQUESTS = _SETTINGS.delay_range[0]
MAX_RETRIES = _SETTINGS.max_retries
RETRY_DELAY = _SETTINGS.retry_base_delay

__all__ = [
    "INSTAGRAM_USERNAME",
    "INSTAGRAM_PASSWORD",
    "INSTAGRAM_SESSIONID",
    "INSTAGRAM_SESSION_FILE",
    "INSTAGRAM_DATA_DIR",
    "DELAY_BETWEEN_REQUESTS",
    "MAX_RETRIES",
    "RETRY_DELAY",
    "load_settings",
]
