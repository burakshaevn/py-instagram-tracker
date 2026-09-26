"""Анализ снимков: «кто не подписан в ответ» и динамика подписок/отписок.

Модуль ничего не знает ни про Instagram, ни про файлы: вход — два `Snapshot`,
выход — структурированный отчёт. Поэтому он целиком покрыт тестами без сети.

Важное отличие от прежней реализации: результат никогда не строится по неполным
данным молча. Если списки усечены или снимки разделены слишком большим интервалом,
в отчёте появляются предупреждения, а CLI выводит их отдельным блоком.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set

from .model import Snapshot, UserRef, normalize_username, parse_timestamp

__all__ = [
    "FollowBackReport",
    "RenameEvent",
    "DiffReport",
    "analyze_followbacks",
    "diff_snapshots",
    "quality_warnings",
]

#: Если между снимками больше этого числа дней, «отписки» могут быть не отписками,
#: а удалёнными/заблокированными/переименованными аккаунтами.
STALENESS_DAYS = 45


def _sorted_refs(refs: Iterable[UserRef]) -> List[UserRef]:
    return sorted(refs, key=lambda u: u.username)


def _by_id(refs: Mapping[str, UserRef]) -> Dict[str, UserRef]:
    return {ref.user_id: ref for ref in refs.values() if ref.user_id}


@dataclass
class FollowBackReport:
    """Кто с кем подписан: взаимные и односторонние подписки.

    Терминология (от лица целевого аккаунта `username`):
      * `not_following_back` — на них аккаунт подписан, они в ответ нет;
      * `followers_not_followed` — они подписаны на аккаунт, он на них нет;
      * `mutual` — взаимные подписки.
    """

    username: str
    not_following_back: List[UserRef] = field(default_factory=list)
    followers_not_followed: List[UserRef] = field(default_factory=list)
    mutual: List[UserRef] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    captured_at: Optional[datetime] = None

    @property
    def counts(self) -> Dict[str, int]:
        return {
            "not_following_back": len(self.not_following_back),
            "followers_not_followed": len(self.followers_not_followed),
            "mutual": len(self.mutual),
        }

    @property
    def is_empty(self) -> bool:
        return not (self.not_following_back or self.followers_not_followed or self.mutual)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": "followback",
            "username": self.username,
            "captured_at": self.captured_at.isoformat() if self.captured_at else None,
            "counts": self.counts,
            "not_following_back": [u.to_dict() for u in self.not_following_back],
            "followers_not_followed": [u.to_dict() for u in self.followers_not_followed],
            "mutual": [u.to_dict() for u in self.mutual],
            "warnings": self.warnings,
        }


@dataclass
class RenameEvent:
    """Аккаунт сменил ник: это НЕ отписка и НЕ новая подписка."""

    user_id: str
    old_username: str
    new_username: str
    kind: str  # "followers" | "following"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "old_username": self.old_username,
            "new_username": self.new_username,
            "kind": self.kind,
        }


@dataclass
class DiffReport:
    """Что изменилось между двумя снимками.

      * `new_followers` / `unfollowers` — пришли / ушли подписчики (те, кто на нас);
      * `new_following` / `unfollowed` — мы подписались / отписались.
    """

    username: str
    new_followers: List[UserRef] = field(default_factory=list)
    unfollowers: List[UserRef] = field(default_factory=list)
    new_following: List[UserRef] = field(default_factory=list)
    unfollowed: List[UserRef] = field(default_factory=list)
    renames: List[RenameEvent] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    old_captured_at: Optional[datetime] = None
    new_captured_at: Optional[datetime] = None
    old_source: str = ""
    new_source: str = ""

    @property
    def counts(self) -> Dict[str, int]:
        return {
            "new_followers": len(self.new_followers),
            "unfollowers": len(self.unfollowers),
            "new_following": len(self.new_following),
            "unfollowed": len(self.unfollowed),
        }

    @property
    def is_empty(self) -> bool:
        return not any(self.counts.values())

    @property
    def period_days(self) -> Optional[float]:
        if not (self.old_captured_at and self.new_captured_at):
            return None
        return (self.new_captured_at - self.old_captured_at).total_seconds() / 86400.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": "diff",
            "username": self.username,
            "period_days": self.period_days,
            "old": {
                "captured_at": self.old_captured_at.isoformat() if self.old_captured_at else None,
                "source": self.old_source,
            },
            "new": {
                "captured_at": self.new_captured_at.isoformat() if self.new_captured_at else None,
                "source": self.new_source,
            },
            "counts": self.counts,
            "new_followers": [u.to_dict() for u in self.new_followers],
            "unfollowers": [u.to_dict() for u in self.unfollowers],
            "new_following": [u.to_dict() for u in self.new_following],
            "unfollowed": [u.to_dict() for u in self.unfollowed],
            "renames": [r.to_dict() for r in self.renames],
            "warnings": self.warnings,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DiffReport":
        """Читает и новый формат, и legacy-файлы `*_comparison_*.json` (списки строк)."""

        def refs(key: str) -> List[UserRef]:
            return _sorted_refs(
                ref for ref in (UserRef.coerce(item) for item in data.get(key, [])) if ref
            )

        return cls(
            username=normalize_username(data.get("username", "")),
            new_followers=refs("new_followers"),
            unfollowers=refs("unfollowers"),
            new_following=refs("new_following"),
            unfollowed=refs("unfollowed"),
            warnings=list(data.get("warnings", [])),
            old_captured_at=_parse_dt((data.get("old") or {}).get("captured_at"))
            or _parse_dt(data.get("compared_with")),
            new_captured_at=_parse_dt((data.get("new") or {}).get("captured_at"))
            or _parse_dt(data.get("timestamp")),
        )


def _parse_dt(value: Any) -> Optional[datetime]:
    return parse_timestamp(value)


def quality_warnings(
    snapshot: Snapshot,
    *,
    now: Optional[datetime] = None,
    staleness_days: float = STALENESS_DAYS,
) -> List[str]:
    """Что известно о качестве данных снимка — читать до того, как верить цифрам."""
    warnings: List[str] = []
    for kind, (got, expected) in snapshot.truncations.items():
        warnings.append(
            f"Список «{kind}» усечён Instagram'ом: {got} из {expected}. "
            "Часть подписчиков физически отсутствует в данных, поэтому они будут "
            "выглядеть как отписавшиеся. Надёжный источник — выгрузка (--export)."
        )
    for kind, complete in snapshot.complete.items():
        if complete is False and not snapshot.is_truncated(kind):
            warnings.append(
                f"Список «{kind}» помечен источником как неполный — выводы по нему "
                "нельзя считать достоверными."
            )
    if not snapshot.count("followers") or not snapshot.count("following"):
        missing = [
            kind for kind in ("followers", "following") if not snapshot.count(kind)
        ]
        warnings.append(
            "Пустой список: " + ", ".join(missing) + ". Сравнение с пустотой даёт "
            "ложные «отписки» — проверьте источник данных."
        )
    stamp = snapshot.captured_at
    if stamp is not None and staleness_days:
        now = now or datetime.now(timezone.utc)
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        age = (now - stamp).total_seconds() / 86400.0
        if age > staleness_days:
            warnings.append(
                f"Снимку {age:.0f} дн. (> {staleness_days:.0f}) — за такой срок аккаунты "
                "могли быть удалены или заблокированы: это не всегда «отписка»."
            )
    return warnings


def analyze_followbacks(
    snapshot: Snapshot, *, staleness_days: float = STALENESS_DAYS
) -> FollowBackReport:
    """Взаимные и односторонние подписки по одному снимку."""
    followers = snapshot.followers
    following = snapshot.following
    not_back = [ref for key, ref in following.items() if key not in followers]
    not_followed = [ref for key, ref in followers.items() if key not in following]
    mutual = [ref for key, ref in followers.items() if key in following]
    return FollowBackReport(
        username=snapshot.username,
        not_following_back=_sorted_refs(not_back),
        followers_not_followed=_sorted_refs(not_followed),
        mutual=_sorted_refs(mutual),
        warnings=quality_warnings(snapshot, staleness_days=staleness_days),
        captured_at=snapshot.captured_at,
    )


def diff_snapshots(
    old: Snapshot,
    new: Snapshot,
    *,
    staleness_days: float = STALENESS_DAYS,
) -> DiffReport:
    """Сравнение двух снимков: новые подписчики, отписки, новые подписки, отписки мои.

    Сравнение идёт по нормализованному нику; если у записей известен `user_id`
    (живой источник либо выкладка с id), смена ника не будет ошибкой «отписался +
    подписались заново».
    """
    if old.username and new.username and old.username != new.username:
        raise ValueError(
            f"Нельзя сравнивать снимки разных аккаунтов: {old.username} и {new.username}"
        )
    warnings = quality_warnings(new, staleness_days=0) + quality_warnings(old, staleness_days=0)

    renames: List[RenameEvent] = []
    result = {}
    for kind in ("followers", "following"):
        old_map, new_map = getattr(old, kind), getattr(new, kind)
        added_keys = set(new_map) - set(old_map)
        removed_keys = set(old_map) - set(new_map)

        new_ids = _by_id(new_map)
        renamed_from: Dict[str, str] = {}  # removed_username -> added_username
        for removed in list(removed_keys):
            user_id = old_map[removed].user_id
            if user_id and user_id in new_ids and new_ids[user_id].username in added_keys:
                added = new_ids[user_id].username
                renamed_from[removed] = added
                removed_keys.discard(removed)
                added_keys.discard(added)
                renames.append(
                    RenameEvent(
                        user_id=user_id,
                        old_username=removed,
                        new_username=added,
                        kind=kind,
                    )
                )

        result[(kind, "added")] = [new_map[k] for k in added_keys]
        result[(kind, "removed")] = [old_map[k] for k in removed_keys]
        if renamed_from:
            warnings.append(
                f"{kind}: {len(renamed_from)} аккаунт(ов) сменили ник — учтены как те же "
                "пользователи, а не как отписка/подписка."
            )

    report = DiffReport(
        username=new.username or old.username,
        new_followers=_sorted_refs(result[("followers", "added")]),
        unfollowers=_sorted_refs(result[("followers", "removed")]),
        new_following=_sorted_refs(result[("following", "added")]),
        unfollowed=_sorted_refs(result[("following", "removed")]),
        renames=renames,
        warnings=_dedupe(warnings),
        old_captured_at=old.captured_at,
        new_captured_at=new.captured_at,
        old_source=old.source,
        new_source=new.source,
    )
    if report.period_days is not None and report.period_days <= 0:
        report.warnings.append(
            "Новый снимок не «свежее» старого: возможно, сравниваете одну и ту же "
            "выгрузку (или у файлов совпадает время изменения). Тогда «нет изменений» "
            "означает именно это, а не тишину в подписках."
        )
    if report.period_days and report.period_days > staleness_days:
        report.warnings.append(
            f"Между снимками {report.period_days:.0f} дн.: часть «отписок» может быть "
            "удалёнными аккаунтами."
        )
    if report.is_empty:
        report.warnings.append(
            "Изменений нет. Убедитесь, что сравниваете разные снимки (старый файл не "
            "тот же самый, что новый)."
        )
    return report


def _dedupe(items: Sequence[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
