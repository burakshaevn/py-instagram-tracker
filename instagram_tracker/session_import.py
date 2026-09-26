"""Извлечение `sessionid` из того, что удобно скопировать браузеру.

Пользователю не нужно ничего вводить в скрипт: достаточно один раз отдать либо
значение cookie, либо заголовок Cookie целиком, либо экспорт куки (`cookies.txt`
в netscape-формате или JSON из расширения «Get cookies.txt»). Дальше сессия
сохраняется в файл и скрипт живёт сам.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from .errors import TrackerError

__all__ = ["extract_sessionid"]

# Instagram отдаёт sessionid в виде "<user_id>:<hex>"; в куки-файлах встречается и
# «сырой» hex без разделителя — его тоже принимаем (instagrapi требует только длину > 30).
_SESSIONID_RE = re.compile(r"sessionid[\"'\s=:]+([0-9]{5,}:%s|%s)" % (r"[A-Za-z0-9_\-]{20,}", r"[A-Za-z0-9_\-]{30,}"))
_BARE_RE = re.compile(r"^(?P<value>[0-9]{5,}:[A-Za-z0-9_\-]{20,}|[A-Za-z0-9_\-]{40,})$")


def extract_sessionid(source: str, *, field: str = "sessionid") -> str:
    """Достаёт значение куки из строки, заголовка или файла с куки."""
    if not source:
        raise TrackerError("Пустое значение cookie.")
    candidate = source.strip()
    if len(candidate) < 512 and Path(candidate).expanduser().is_file():
        candidate = Path(candidate).expanduser().read_text(encoding="utf-8", errors="replace")
        return _from_file(candidate, field) or _fail(field)
    if candidate[:1] in {"[", "{"}:  # JSON-экспорт куки прямо в аргументе
        found = _from_file(candidate, field)
        if found:
            return found
    if "\n" in candidate or "=" in candidate:  # заголовок Cookie: a=1; sessionid=2; b=3
        found = _from_text(candidate, field)
        if found:
            return found
    match = _BARE_RE.match(candidate)
    if match:
        return match.group("value")
    return _fail(field)


def _from_file(text: str, field: str) -> Optional[str]:
    stripped = text.lstrip()
    if stripped.startswith("[") or stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
        except ValueError:
            return None
        items = payload if isinstance(payload, list) else payload.get("cookies", [])
        for cookie in items:
            if isinstance(cookie, dict) and cookie.get("name") == field and cookie.get("value"):
                return str(cookie["value"]).strip()
        return None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("# ") or line.startswith("//"):
            continue
        parts = line.split("\t")
        if len(parts) >= 7 and parts[5].strip() == field:
            return parts[6].strip()
    return _from_text(text, field)


def _from_text(text: str, field: str) -> Optional[str]:
    pattern = re.compile(
        r"%s[\"'\s=:]+([0-9]{5,}:[A-Za-z0-9_\-]{20,}|[A-Za-z0-9_\-]{30,})" % re.escape(field)
    )
    match = pattern.search(text)
    return match.group(1) if match else None


def _fail(field: str) -> str:
    raise TrackerError(
        f"Не удалось найти «{field}» в переданном значении. Ожидается либо само "
        f"значение куки (вид «123456789:abcdef…»), либо заголовок Cookie целиком, "
        "либо файл cookies.txt/JSON с экспортом куки."
    )
