"""Настройки проекта: всё из окружения, с безопасными значениями по умолчанию.

Раньше `config.py` лежал в корне, и пакет импортировал его как
`from config import ...` — это работало только при запуске из корня репозитория и
ломало любой импорт пакета из другой директории. Настройки переехали внутрь пакета;
корневой `config.py` оставлен тонкой прослойкой для совместимости.

Учётные данные больше не обязательны: по умолчанию анализ идёт по выгрузке Instagram,
и `.env` нужен только если вы решаете использовать живой режим.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

__all__ = ["Settings", "load_settings"]

_TRUE = {"1", "true", "yes", "y", "on"}


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in _TRUE


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


@dataclass
class Settings:
    """Конфигурация одного запуска (именованные поля вместо «звёздного» импорта)."""

    data_dir: Path = Path("data")
    # --- живой режим (опционален) ---
    instagram_username: Optional[str] = None
    instagram_password: Optional[str] = None
    #: cookie `sessionid` из браузера — вход без пароля и без 2FA
    instagram_sessionid: Optional[str] = None
    #: файл сохранённой сессии instagrapi (dump_settings)
    session_file: Path = Path("data/instagram_session.json")
    proxy: Optional[str] = None
    # --- поведение сети ---
    #: задержка между страницами выдачи; слишком маленькая и есть причина лимитов
    delay_range: Tuple[float, float] = (2.0, 5.0)
    max_retries: int = 4
    retry_base_delay: float = 30.0
    #: 0 = без ограничения
    max_items: int = 0
    #: мириться с усечёнными списками (по умолчанию — нет: иначе вывод врёт)
    allow_partial: bool = False
    persist_session: bool = True
    quiet: bool = False
    #: предупреждать, если снимку больше N дней
    staleness_days: float = 45.0

    @property
    def has_credentials(self) -> bool:
        return bool(self.instagram_sessionid or self.session_file.exists()) or bool(
            self.instagram_username and self.instagram_password
        )

    @property
    def has_session_file(self) -> bool:
        return self.session_file.exists()


def load_settings(env_file: Optional[Path] = None) -> Settings:
    """Читает `.env` (если он есть и если установлен python-dotenv) и переменные окружения."""
    if env_file is None:
        candidate = Path.cwd() / ".env"
        if not candidate.is_file():
            candidate = Path(__file__).resolve().parent.parent / ".env"
        env_file = candidate
    _load_dotenv(Path(env_file))

    return Settings(
        data_dir=Path(os.getenv("INSTAGRAM_DATA_DIR") or "data"),
        instagram_username=_empty_to_none(os.getenv("INSTAGRAM_USERNAME")),
        instagram_password=_empty_to_none(os.getenv("INSTAGRAM_PASSWORD")),
        instagram_sessionid=_empty_to_none(os.getenv("INSTAGRAM_SESSIONID")),
        session_file=Path(
            os.getenv("INSTAGRAM_SESSION_FILE") or Path("data") / "instagram_session.json"
        ),
        proxy=_empty_to_none(os.getenv("INSTAGRAM_PROXY")),
        delay_range=_delay_range(),
        max_retries=_env_int("INSTAGRAM_MAX_RETRIES", 4),
        retry_base_delay=_env_float("INSTAGRAM_RETRY_DELAY", 30.0),
        max_items=_env_int("INSTAGRAM_MAX_ITEMS", 0),
        allow_partial=_env_bool("INSTAGRAM_ALLOW_PARTIAL", False),
        persist_session=_env_bool("INSTAGRAM_PERSIST_SESSION", True),
        quiet=_env_bool("INSTAGRAM_QUIET", False),
        staleness_days=_env_float("INSTAGRAM_STALENESS_DAYS", 45.0),
    )


def _empty_to_none(value: Optional[str]) -> Optional[str]:
    value = (value or "").strip()
    return value or None


def _delay_range() -> Tuple[float, float]:
    raw = _empty_to_none(os.getenv("INSTAGRAM_DELAY_RANGE"))
    if not raw:
        return (2.0, 5.0)
    parts = [part.strip() for part in raw.replace(",", " ").split()]
    try:
        if len(parts) == 1:
            low = high = float(parts[0])
        else:
            low, high = float(parts[0]), float(parts[1])
    except ValueError:
        return (2.0, 5.0)
    if low > high:
        low, high = high, low
    return (max(0.0, low), max(0.0, high))


def _load_dotenv(path: Path) -> None:
    """python-dotenv опционален: базовый разбор KEY=VALUE умеем сами."""
    if not path.is_file():
        return
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv(path, override=False)
        return
    except ImportError:
        pass
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip().removeprefix("export").strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value

