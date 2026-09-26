"""Хранилище снимков и отчётов (эволюция прежнего `data_manager`).

Что было не так и что исправлено:
  * имена файлов были несортируемыми (`ДД_ММ_ГГГГ`), а имя файла сравнения
    (`ГГГГ-ММ-ДД`) отличалось от обещанного в README;
  * `get_available_files` матчил `username_*.json` и захватывал в т.ч. файлы
    сравнения, после чего `load_data` падал по KeyError;
  * структура файла не проверялась, половина полей молча отсутствовала.

Теперь имя содержит ISO-метку (`20260926T112030Z`) — сортировка совпадает с
хронологией, — а снимок и отчёт лежат в разных подкаталогах.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union

from .analyzer import DiffReport, FollowBackReport
from .errors import SnapshotNotFoundError
from .model import Snapshot, normalize_username

__all__ = ["SnapshotStore", "SnapshotInfo"]

PathLike = Union[str, Path]

_ISO_STAMP = "%Y%m%dT%H%M%SZ"
_NAME_RE = re.compile(
    r"^(?P<user>.+?)__(?P<stamp>\d{8}T\d{6}Z)__(?P<source>.+?)(?:__\d+)?\.json$"
)
_LEGACY_STAMPS = (
    "%d_%m_%Y_%H_%M",   # формат прежнего проекта: username_DD_MM_YYYY_HH_MM.json
    "%Y-%m-%d_%H-%M",   # формат прежних файлов сравнения
)


@dataclass
class SnapshotInfo:
    """Метаданные сохранённого снимка — для `main.py snapshots list`."""

    path: Path
    username: str
    captured_at: Optional[datetime]
    source: str
    kind: str = "snapshot"  # snapshot | diff | followback
    followers: int = 0
    following: int = 0

    @property
    def display_name(self) -> str:
        stamp = self.captured_at.strftime("%Y-%m-%d %H:%M") if self.captured_at else "?"
        return f"{self.username} @ {stamp} [{self.source}]"


class SnapshotStore:
    def __init__(self, data_dir: PathLike = "data") -> None:
        self.root = Path(data_dir).expanduser()
        self.snapshots_dir = self.root / "snapshots"
        self.reports_dir = self.root / "reports"

    # --- запись ---------------------------------------------------------

    def save_snapshot(self, snapshot: Snapshot) -> Path:
        self._ensure(self.snapshots_dir)
        path = self._path_for(
            self.snapshots_dir, snapshot.username, snapshot.captured_at, "snapshot"
        )
        _write_json(path, snapshot.to_dict())
        return path

    def save_report(self, report: Union[DiffReport, FollowBackReport]) -> Path:
        self._ensure(self.reports_dir)
        kind = "diff" if isinstance(report, DiffReport) else "followback"
        moment = (
            report.new_captured_at
            if isinstance(report, DiffReport) and report.new_captured_at
            else report.captured_at
        ) or datetime.now(timezone.utc)
        path = self._path_for(self.reports_dir, report.username, moment, kind)
        _write_json(path, report.to_dict())
        return path

    def save_csv(self, rows: Sequence[Sequence[Any]], path: PathLike) -> Path:
        """CSV «для Excel» — то, что обычно и хотят от такого анализа."""
        target = Path(path).expanduser()
        self._ensure(target.parent)
        with target.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerows(rows)
        return target

    def _path_for(self, directory: Path, username: str, moment: datetime, suffix: str) -> Path:
        safe_user = re.sub(r"[^A-Za-z0-9._-]", "_", normalize_username(username) or "unknown")
        stamp = _as_utc(moment).strftime(_ISO_STAMP)
        base = f"{safe_user}__{stamp}__{suffix}"
        path = directory / f"{base}.json"
        index = 1
        while path.exists():  # не перетираем историю, если два прогона в одну секунду
            path = directory / f"{base}__{index}.json"
            index += 1
        return path

    @staticmethod
    def _ensure(directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)

    # --- чтение ---------------------------------------------------------

    def list_snapshots(self, username: Optional[str] = None) -> List[SnapshotInfo]:
        """Снимки (и, отдельно, отчёты) в порядке от новых к старым.

        Legacy-файлы старого формата тоже видно, но файлы сравнения (`*_comparison_*`,
        `*__diff__*`) в список снимков не попадают — именно они раньше ломали загрузку.
        """
        wanted = normalize_username(username) if username else ""
        found: List[SnapshotInfo] = []
        for path in self._candidate_files():
            if _is_report_file(path):
                continue
            info = self._inspect(path)
            if info is None:
                continue
            if wanted and info.username != wanted:
                continue
            found.append(info)
        found.sort(key=lambda i: i.captured_at or datetime.fromtimestamp(0, tz=timezone.utc), reverse=True)
        return found

    def _candidate_files(self) -> Iterable[Path]:
        for directory in (self.snapshots_dir, self.root):
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*.json")):
                yield path

    def _inspect(self, path: Path) -> Optional[SnapshotInfo]:
        match = _NAME_RE.match(path.name)
        username = match.group("user") if match else ""
        source = match.group("source") if match else "legacy"
        captured_at: Optional[datetime] = None
        if match:
            try:
                captured_at = datetime.strptime(match.group("stamp"), _ISO_STAMP).replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                captured_at = None
        kind = "snapshot"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if isinstance(payload, dict):
            username = normalize_username(payload.get("username")) or username
            captured_at = _parse_any_date(payload.get("captured_at")) or captured_at
            kind = payload.get("kind") or "snapshot"
            counts = payload.get("counts") or {}
            followers = int(counts.get("followers", 0) or 0)
            following = int(counts.get("following", 0) or 0)
        else:
            followers = following = 0
        if captured_at is None:
            captured_at = _file_mtime(path)
        return SnapshotInfo(
            path=path,
            username=username or path.stem.split("__")[0],
            captured_at=captured_at,
            source=source,
            kind=kind,
            followers=followers,
            following=following,
        )

    def load_snapshot(self, path: PathLike) -> Snapshot:
        target = Path(path).expanduser()
        if not target.is_file():
            raise SnapshotNotFoundError(f"Файл снимка не найден: {target}")
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise SnapshotNotFoundError(
                f"{target} не является корректным JSON: {exc}"
            ) from exc
        if not isinstance(payload, dict) or "followers" not in payload:
            raise SnapshotNotFoundError(
                f"В {target} нет структуры снимка (ключи followers/following). "
                "Если это выгрузка Instagram — используйте --export вместо --snapshot."
            )
        snapshot = Snapshot.from_dict(payload)
        # Откуда взят снимок — полезно в отчётах и при авто-сравнении (не брать тот же файл).
        snapshot.meta.setdefault("loaded_from", str(target))
        if not snapshot.username:
            match = _NAME_RE.match(target.name)
            if match:
                snapshot.username = match.group("user")
        return snapshot

    def latest_snapshot(
        self,
        username: Optional[str] = None,
        *,
        exclude: Optional[PathLike] = None,
    ) -> Snapshot:
        """Последний снимок — для «сравни автоматически с предыдущим»."""
        items = self.list_snapshots(username)
        if not items and username:
            # Снимки из выгрузки без восстановленного ника (username == "") остаются
            # кандидатами: иначе история «пропадает» только потому, что ник не угадали.
            # Чужой аккаунт так не подмешается — у него ник всегда записан.
            items = [info for info in self.list_snapshots() if not info.username]
        skip = Path(exclude).expanduser() if exclude else None
        for info in items:
            if skip and info.path == skip:
                continue
            return self.load_snapshot(info.path)
        raise SnapshotNotFoundError(
            "Нет ни одного сохранённого снимка"
            + (f" для @{username}" if username else "")
            + ". Сначала сохраните данные: main.py analyze ... --save."
        )

    # --- разбор внешних форматов ---------------------------------------

    def read_any(self, source: PathLike) -> Snapshot:
        """Один входной путь — много форматов.

        Принимает сохранённый снимок (`.json`), архив выгрузки (`.zip`), каталог
        выгрузки или файл выгрузки (`followers_1.json` / `following.html`).
        """
        target = Path(source).expanduser()
        if not target.exists():
            raise SnapshotNotFoundError(f"Путь не найден: {target}")
        if target.is_file() and target.suffix.lower() == ".json" and not _looks_like_export(target):
            try:
                return self.load_snapshot(target)
            except SnapshotNotFoundError:
                pass  # возможно это JSON-дамп выгрузки (`followers_1.json`)
        from .sources.export import ExportSource

        return ExportSource(target).fetch_snapshot()


def _looks_like_export(path: Path) -> bool:
    name = path.name.lower()
    return name.startswith("followers") or name.startswith("following")


def _is_report_file(path: Path) -> bool:
    name = path.name.lower()
    return "__diff__" in name or "__followback__" in name or "_comparison_" in name


def _parse_any_date(value: Any) -> Optional[datetime]:
    from .model import parse_timestamp

    if isinstance(value, str):
        for fmt in _LEGACY_STAMPS:
            try:
                return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return _as_utc(parse_timestamp(value))


def _as_utc(moment: Optional[datetime]) -> Optional[datetime]:
    if moment is None:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _file_mtime(path: Path) -> Optional[datetime]:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    """Атомарная запись: полузаписанный JSON не должен появляться в истории."""
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)
