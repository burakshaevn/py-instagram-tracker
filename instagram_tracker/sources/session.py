"""Источник данных №2 — живая сессия Instagram через instagrapi 3.x.

Задача модуля — убрать главные «руки-из-ног» прошлого подхода:

1. **Без пароля.** Сессия переиспользуется: `sessionid` из браузера (кук
   `instagram.com → sessionid`) либо сохранённый файл настроек instagrapi.
   Instagram видит знакомое устройство, поэтому чекпоинты/2FA при каждом запуске
   не сыпятся (это и была основная жалоба: «сессия теряется»).
2. **Без вранья.** Неполный список подписчиков больше не выдаётся за полный:
   сверка с `follower_count`/`following_count` + флаг `should_limit_list_of_followers`.
   Если данные обрезаны — `IncompleteDataError`, а не «0 отписавшихся».
3. **Без «тихих» пустых ответов.** Любая сетевая ошибка либо ретраится с
   экспоненциальной паузой, либо бросает исключение.
"""

from __future__ import annotations

import os
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..errors import (
    IncompleteDataError,
    LoginRejected,
    RateLimited,
    SessionRequired,
    SourceError,
)
from ..interfaces import InstagramDataSource, ProgressSubject
from ..model import Snapshot, UserRef, normalize_username, parse_timestamp

__all__ = ["SessionSource"]

#: Instagram отдаёт по 200 записей на запрос; больше request_timeout не имеет смысла.
PAGE_SIZE = 200
_RATE_HINT_RE = re.compile(r"wait a few|try again later|rate", re.IGNORECASE)
_RETRY_AFTER_RE = re.compile(r"(\d{1,5})\s*(?:seconds?|сек)", re.IGNORECASE)


def _load_instagrapi() -> Tuple[Any, Dict[str, Any]]:
    """Импортирует instagrapi здесь, а не на уровне модуля.

    Так «холодный» разбор выгрузки работает вообще без установленных зависимостей,
    и отсутствие либы не ломает весь пакет (в старой версии `import instagrapi`
    стоял в шапке strategies.py — из-за чего не работало даже `--help`).
    """
    try:
        from instagrapi import Client  # type: ignore
        from instagrapi import exceptions as ex  # type: ignore
    except ImportError as exc:  # pragma: no cover - зависит от окружения
        raise SourceError(
            "Для живого режима нужна библиотека instagrapi>=2.0: "
            "pip install -r requirements-live.txt\n"
            "Для анализа без установки зависимостей используйте выгрузку Instagram: "
            "python main.py analyze --export <путь к zip или папке>"
        ) from exc
    return Client, {
        "TwoFactorRequired": getattr(ex, "TwoFactorRequired", None),
        "ChallengeRequired": getattr(ex, "ChallengeRequired", None),
        "FeedbackRequired": getattr(ex, "FeedbackRequired", None),
        "PleaseWaitFewMinutes": getattr(ex, "PleaseWaitFewMinutes", None),
        "ClientThrottledError": getattr(ex, "ClientThrottledError", None),
        "ClientConnectionError": getattr(ex, "ClientConnectionError", None),
        "ClientBadRequestError": getattr(ex, "ClientBadRequestError", None),
        "ClientError": getattr(ex, "ClientError", None),
        "NotFoundError": getattr(ex, "NotFoundError", None),
        "PrivateError": getattr(ex, "PrivateError", None),
        "ProxyAddressIsBlocked": getattr(ex, "ProxyAddressIsBlocked", None),
    }


class SessionSource(InstagramDataSource, ProgressSubject):
    """Живые данные подписок: сессия из cookie/файла, пагинация, детект обрезки."""

    name = "session"
    supports_other_accounts = True

    def __init__(
        self,
        *,
        session_file: Optional[Path | str] = None,
        sessionid: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        proxy: Optional[str] = None,
        delay_range: Tuple[float, float] = (2.0, 5.0),
        page_size: int = PAGE_SIZE,
        max_items: int = 0,
        max_retries: int = 4,
        retry_base_delay: float = 30.0,
        allow_partial: bool = False,
        persist_session: bool = True,
        interactive: bool = True,
    ) -> None:
        super().__init__()
        self.session_file = Path(session_file).expanduser() if session_file else None
        self.sessionid = (sessionid or "").strip() or None
        self.username_hint = normalize_username(username) if username else ""
        self.password = password or None
        self.proxy = proxy or None
        self.delay_range = delay_range
        self.page_size = max(1, min(int(page_size), PAGE_SIZE))
        self.max_items = int(max_items or 0)
        self.max_retries = int(max_retries)
        self.retry_base_delay = float(retry_base_delay)
        self.allow_partial = allow_partial
        self.persist_session = persist_session
        self.interactive = interactive
        self.own_username = ""
        self._client = None
        self._exc: Dict[str, Any] = {}
        self._connect_method = ""

    # --- подключение ----------------------------------------------------

    @property
    def client(self) -> Any:
        if self._client is None:
            self.connect()
        return self._client

    def connect(self) -> bool:
        """Восстанавливает сессию. Порядок: файл сессии → sessionid → логин с паролем."""
        client_cls, exc_map = _load_instagrapi()
        self._exc = exc_map
        self._client = client_cls(delay_range=list(self.delay_range))
        if self.proxy:
            self._client.proxy = self.proxy

        if self.session_file and Path(self.session_file).is_file():
            if self._try_session_file():
                return True
            self.notify("Сохранённая сессия не подошла — пробую sessionid/пароль.")

        if self.sessionid:
            self._login_by_sessionid(self.sessionid)
            return True

        if self.username_hint and self.password:
            self._login_by_password()
            return True

        raise SessionRequired()

    def _try_session_file(self) -> bool:
        try:
            self._client.load_settings(str(self.session_file))
        except Exception as exc:  # битый/устаревший формат настроек
            self.notify(f"Не удалось загрузить файл сессии: {exc}")
            return False
        if not getattr(self._client, "user_id", None):
            return False
        try:
            self._verify()
        except LoginRejected as exc:
            self.notify(f"Сессия протухла: {exc}")
            return False
        self._connect_method = f"session_file:{self.session_file.name}"
        return True

    def _login_by_sessionid(self, sessionid: str) -> None:
        if len(sessionid) < 32 or ":" not in sessionid:
            raise LoginRejected(
                "Похоже, это не sessionid. Ожидается значение cookie sessionid для "
                "домена instagram.com (формат '<user_id>:<hex>', длина > 30 символов)."
            )
        try:
            self._client.login_by_sessionid(sessionid)
        except self._exc.get("FeedbackRequired", ()) as exc:  # type: ignore[arg-type]
            raise LoginRejected(
                "Instagram заблокировал вход по этой сессии (feedback_required). "
                "Откройте Instagram в браузере, пройдите проверку и возьмите "
                "актуальный cookie sessionid."
            ) from exc
        except Exception as exc:
            raise LoginRejected(f"Не удалось войти по sessionid: {exc}") from exc
        self._connect_method = "sessionid"
        self._after_login()

    def _login_by_password(self) -> None:
        """Крайний случай: пароль нужен один раз, чтобы сохранить живучую сессию."""
        code = ""
        for attempt in range(2):
            try:
                self._client.login(self.username_hint, self.password, verification_code=code)
                break
            except self._exc.get("TwoFactorRequired", ()) as exc:  # type: ignore[arg-type]
                code = self._ask_code("2FA")
                if not code:
                    raise LoginRejected(
                        "Требуется код 2FA. Проще один раз взять sessionid из браузера — "
                        "тогда коды больше не понадобятся."
                    ) from exc
            except self._exc.get("ChallengeRequired", ()) as exc:  # type: ignore[arg-type]
                raise LoginRejected(
                    "Instagram требует пройти проверку (challenge). Автоматически она "
                    "не проходит; выполните вход в браузере и используйте sessionid."
                ) from exc
            except Exception as exc:
                if attempt == 0 and _RETRY_AFTER_RE.search(str(exc)):
                    time.sleep(self.retry_base_delay)
                    continue
                raise LoginRejected(f"Вход не удался: {exc}") from exc
        else:  # pragma: no cover - защита от изменения числа попыток
            raise LoginRejected("Вход не удался.")
        self._connect_method = "password"
        self._after_login()

    def _after_login(self) -> None:
        self._verify()
        if self.persist_session and self.session_file:
            self._dump_session()

    def _dump_session(self) -> None:
        """Сохраняет сессию, чтобы дальше работать без пароля и без cookie-выдумок."""
        try:
            path = Path(self.session_file)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._client.dump_settings(str(path))
            try:
                os.chmod(path, 0o600)  # sessionid = право входа в аккаунт
            except OSError:
                pass
            self.notify(f"Сессия сохранена в {path} — дальше можно работать без пароля.")
        except Exception as exc:  # не критично для текущего запуска
            self.notify(f"Не удалось сохранить сессию: {exc}")

    def _verify(self) -> None:
        user_id = getattr(self._client, "user_id", None)
        if not user_id:
            raise LoginRejected("В сессии нет user_id: похоже, куки не подходят.")
        try:
            info = self._client.user_info(str(user_id), use_cache=False)
        except Exception as exc:
            raise LoginRejected(
                f"Сессия не passes проверку профиля ({exc}). "
                "Обновите sessionid или запросите новую выгрузку."
            ) from exc
        self.own_username = normalize_username(getattr(info, "username", "")) or str(
            getattr(self._client, "username", "") or ""
        )

    def _ask_code(self, kind: str) -> str:
        import sys

        if not (self.interactive and sys.stdin is not None and sys.stdin.isatty()):
            return ""
        try:
            return input(f"Введите код {kind}: ").strip()
        except (EOFError, KeyboardInterrupt):
            return ""

    def session_status(self) -> Dict[str, Any]:
        """Диагностика для `main.py session status` — жива ли сохранённая сессия."""
        info: Dict[str, Any] = {
            "session_file": str(self.session_file) if self.session_file else None,
            "session_file_exists": bool(self.session_file and Path(self.session_file).is_file()),
            "has_sessionid": bool(self.sessionid),
            "connected": False,
            "username": "",
            "last_login": None,
            "method": "",
        }
        try:
            if (
                self.sessionid
                or info["session_file_exists"]
                or (self.username_hint and self.password)
            ):
                self.connect()
                info["connected"] = True
                info["username"] = self.own_username
                info["method"] = self._connect_method
                settings = self._client.get_settings() if self._client else {}
                last_login = settings.get("last_login")
                stamp = parse_timestamp(last_login) if last_login else None
                info["last_login"] = stamp.isoformat() if stamp else last_login
        except Exception as exc:
            info["error"] = str(exc)
        return info

    # --- публичный API стратегии ---------------------------------------

    def fetch_snapshot(self, username: Optional[str] = None) -> Snapshot:
        client = self.client
        target = normalize_username(username) if username else (self.username_hint or self.own_username)
        target = target or self.own_username
        if not target:
            raise SourceError("Не указано, чей аккаунт читать.")

        self.notify(f"Читаю подписки живьём для @{target} (источник: {self._connect_method})...")
        try:
            user_id = str(client.user_id_from_username(target))
        except self._exc.get("NotFoundError", ()) as exc:  # type: ignore[arg-type]
            raise SourceError(f"Профиль @{target} не найден.") from exc
        except Exception as exc:
            raise SourceError(f"Не удалось получить id профиля @{target}: {exc}") from exc

        expected = self._expected_counts(user_id, target)
        followers, followers_limited = self._fetch("followers", user_id, expected.get("followers"))
        following, following_limited = self._fetch("following", user_id, expected.get("following"))

        complete = {"followers": not followers_limited, "following": not following_limited}
        snapshot = Snapshot(
            username=target,
            captured_at=datetime.now(timezone.utc),
            followers=followers,
            following=following,
            source=f"session:{self._connect_method or 'live'}",
            expected_counts=expected,
            complete=complete,
            meta={
                "user_id": user_id,
                "truncated": {
                    kind: {"got": len(users), "expected": expected.get(kind)}
                    for kind, users, limited in (
                        ("followers", followers, followers_limited),
                        ("following", following, following_limited),
                    )
                    if limited
                },
            },
        )
        self._enforce_completeness(snapshot, target)
        return snapshot

    def _expected_counts(self, user_id: str, target: str) -> Dict[str, int]:
        """Счётчики из профиля — наш ориентир для проверки полноты списков."""
        for call in (
            lambda: self._client.user_info(user_id, use_cache=False),
            lambda: self._client.user_info_by_username(target, use_cache=False),
        ):
            try:
                info = call()
            except Exception as exc:
                self.notify(f"Счётчики профиля не получены ({exc}) — полноту не проверить.")
                continue
            counts = {
                "followers": int(getattr(info, "follower_count", 0) or 0),
                "following": int(getattr(info, "following_count", 0) or 0),
            }
            return {k: v for k, v in counts.items() if v > 0}
        return {}

    def _enforce_completeness(self, snapshot: Snapshot, target: str) -> None:
        if snapshot.reliable:
            return
        if self.allow_partial:
            self.notify(
                "⚠ Данные обрезаны Instagram'ом, но вы разрешили неполный разбор "
                "(--allow-partial). Отписки будут неточны."
            )
            return
        kind, (got, want) = next(iter(snapshot.truncations.items()))
        raise IncompleteDataError.from_truncation(
            kind=kind,
            username=target,
            got=got,
            expected=want,
            hints=(
                "используйте выгрузку Instagram (--export): она всегда полная;",
                "повторите позже — лимиты на перечисление подписчиков мягкие;",
                "--allow-partial, если неполный список вас устраивает.",
            ),
        )

    # --- пагинация и лимиты --------------------------------------------

    def _fetch(
        self, kind: str, user_id: str, expected: Optional[int]
    ) -> Tuple[List[UserRef], bool]:
        """Собирает список постранично.

        Приватный mobile-эндпоинд (он полнее) с автоматическим откатом на публичный
        GraphQL, если Instagram не даёт приватный доступ к этому профилю.
        """
        transports = ["private", "gql"]
        if not self._has_private_auth():
            transports = ["gql", "private"]
        last_error: Optional[BaseException] = None
        for transport in transports:
            try:
                return self._fetch_with(kind, user_id, expected, transport)
            except SourceError as exc:
                last_error = exc
                if not isinstance(exc.__cause__, self._private_error_types()):
                    raise
                self.notify(
                    f"  {kind}: приватный эндпоинт недоступен ({exc}); пробую публичный GraphQL."
                )
        raise SourceError(f"Не удалось получить список «{kind}» ни одним транспортом: {last_error}")

    def _private_error_types(self) -> Tuple[type, ...]:
        names = ("PrivateError", "ClientError", "NotFoundError")
        return tuple(t for t in (self._exc.get(n) for n in names) if isinstance(t, type))

    def _has_private_auth(self) -> bool:
        try:
            return bool(self._client and (getattr(self._client, "authorization", "") or getattr(self._client, "sessionid", "")))
        except Exception:
            return False

    def _fetch_with(
        self, kind: str, user_id: str, expected: Optional[int], transport: str
    ) -> Tuple[List[UserRef], bool]:
        collected: Dict[str, UserRef] = {}
        follow_dates: Dict[str, datetime] = {}
        cursor = ""
        limited_by_instagram = False
        pages = 0

        while True:
            users, cursor_next = self._call_with_retries(transport, kind, user_id, cursor)
            pages += 1
            for raw in users:
                ref = UserRef.from_instagrapi(raw)
                if ref is not None and ref.username and ref.username not in collected:
                    collected[ref.username] = ref
            follow_dates.update(self._follow_dates_by_pk())
            if self._last_json_limited():
                # Instagram сам сообщил, что список подписчиков урезан намеренно.
                limited_by_instagram = True

            percent = min(100.0, len(collected) / expected * 100.0) if expected else None
            self.notify(
                f"  {kind}: собрано {len(collected)}"
                + (f" из ~{expected}" if expected else "")
                + f" (страница {pages})",
                percent,
            )
            if not cursor_next:
                break
            if self.max_items and len(collected) >= self.max_items:
                self.notify(f"  {kind}: достигнут лимит --limit={self.max_items}, останавливаюсь.")
                break
            if expected and len(collected) >= expected:
                break  # дальше Instagram отдаёт дубликаты
            cursor = str(cursor_next)
            self._polite_pause()

        if expected and len(collected) < expected:
            # Считаем обрезанным и случай, когда Instagram явно не дал список целиком
            # (флаг should_limit_list_of_followers), и когда курсор кончился раньше
            # счётчика профиля: и то, и другое = «неполные данные» для анализа отписок.
            limited_by_instagram = True

        if follow_dates:
            for username, ref in list(collected.items()):
                date = follow_dates.get(ref.user_id)
                if date is not None and ref.since is None:
                    collected[username] = UserRef(
                        username=ref.username,
                        user_id=ref.user_id,
                        full_name=ref.full_name,
                        profile_url=ref.profile_url,
                        is_private=ref.is_private,
                        is_verified=ref.is_verified,
                        since=date,
                    )
        return list(collected.values()), limited_by_instagram

    def _call_with_retries(
        self, transport: str, kind: str, user_id: str, cursor: str
    ) -> Tuple[List[Any], str]:
        """Один шаг пагинации с ретраями.

        Ключевое отличие от прежнего кода: ошибка не превращается в пустой список.
        """
        method = f"user_{kind}_{'v1' if transport == 'private' else 'gql'}_chunk"
        last_error: Optional[BaseException] = None
        retriable = self._retriable()
        for attempt in range(self.max_retries + 1):
            try:
                call = getattr(self._client, method)
                if transport == "private":
                    result = call(user_id, self.page_size, cursor or "")
                else:
                    result = call(user_id, self.page_size, end_cursor=cursor or None)
                users, next_cursor = result[0], result[1]
                return list(users), (next_cursor or "")
            except retriable as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                delay = self._backoff(attempt, exc)
                self.notify(
                    f"Instagram ограничил частоту ({type(exc).__name__}); "
                    f"жду {delay:.0f} с и повторяю страницу "
                    f"({attempt + 1}/{self.max_retries})."
                )
                time.sleep(delay)
            except self._exc.get("ClientError", ()) as exc:
                if _RATE_HINT_RE.search(str(exc)) and attempt < self.max_retries:
                    delay = self._backoff(attempt, exc)
                    self.notify(f"Похоже на rate limit ({exc}); пауза {delay:.0f} с.")
                    time.sleep(delay)
                    continue
                raise SourceError(f"Instagram вернул ошибку для {method}: {exc}") from exc
            except Exception as exc:
                raise SourceError(f"Сбой чтения {method}: {exc}") from exc
        raise RateLimited(
            f"Лимит запросов Instagram исчерпан после {self.max_retries} попыток "
            f"(последняя ошибка: {last_error}).",
            retry_after=int(self.retry_base_delay * (2 ** (self.max_retries + 1))),
        )

    def _retriable(self) -> Tuple[type, ...]:
        names = (
            "PleaseWaitFewMinutes",
            "ClientThrottledError",
            "ClientConnectionError",
            "ProxyAddressIsBlocked",
        )
        return tuple(t for t in (self._exc.get(n) for n in names) if isinstance(t, type))

    def _backoff(self, attempt: int, exc: BaseException) -> float:
        explicit = _RETRY_AFTER_RE.search(str(exc))
        if explicit:
            return min(900.0, max(1.0, float(explicit.group(1))))
        return min(600.0, self.retry_base_delay * (2**attempt) + random.uniform(0, 3))

    def _polite_pause(self) -> None:
        low, high = self.delay_range
        time.sleep(random.uniform(low, high))

    def _last_json_limited(self) -> bool:
        try:
            payload = self._client.last_json or {}
        except Exception:
            return False
        return bool(payload.get("should_limit_list_of_followers"))

    def _follow_dates_by_pk(self) -> Dict[str, datetime]:
        """Даты подписки из «сырого» ответа, если Instagram их отдаёт."""
        out: Dict[str, datetime] = {}
        try:
            payload = self._client.last_json or {}
            entries = payload.get("users") or []
        except Exception:
            return out
        if not isinstance(entries, list):
            return out
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            pk = entry.get("pk") or (entry.get("user") or {}).get("pk")
            stamp = (
                entry.get("follow_date")
                or entry.get("following_date")
                or entry.get("date_followed")
            )
            if pk is None or stamp is None:
                continue
            moment = parse_timestamp(stamp)
            if moment:
                out[str(pk)] = moment
        return out
